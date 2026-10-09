// Telefondan erişim: panel şifresi (yalnızca scrypt özeti), oturum sırrı ve paneli hangi adreste açacağımız.
// Saf mantık: hem Next (API rotası, giriş) hem başlatıcı (tools/panel_run.mjs) kullanır; `node --test` ile sınanır.
import { randomBytes, scrypt, scryptSync, timingSafeEqual } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
import { hostName } from "./hostCheck.mjs";

export const MIN_PASSWORD = 8;
/** Şifre üst sınırı: scrypt'e ve karşılaştırmaya sınırsız uzunlukta girdi verilmesin */
export const MAX_PASSWORD = 256;
const SCRYPT = { N: 16384, r: 8, p: 1 };
const scryptAsync = promisify(scrypt);

export function hashPassword(pw) {
  const salt = randomBytes(16).toString("hex");
  return { salt, hash: scryptSync(pw, salt, 32, SCRYPT).toString("hex") };
}

/** Eşzamanlı sürüm (testler ve araçlar için). Giriş rotası olay döngüsünü kilitlememek için `verifyPasswordAsync` kullanır. */
export function verifyPassword(pw, salt, hash) {
  if (!salt || !hash || String(pw).length > MAX_PASSWORD) return false;
  const want = Buffer.from(hash, "hex");
  const got = scryptSync(String(pw), salt, 32, SCRYPT);
  return want.length === got.length && timingSafeEqual(want, got);
}

/** `verifyPassword` ile aynı sonuç; scrypt iş parçacığı havuzunda çalışır, olay döngüsünü bloklamaz. */
export async function verifyPasswordAsync(pw, salt, hash) {
  if (!salt || !hash || String(pw).length > MAX_PASSWORD) return false;
  const want = Buffer.from(hash, "hex");
  const got = await scryptAsync(String(pw), salt, 32, SCRYPT);
  return want.length === got.length && timingSafeEqual(want, got);
}

export function newSecret() {
  return randomBytes(32).toString("hex");
}

export function accessFile(env, cwd) {
  return env.PANEL_ACCESS_FILE || path.join(cwd, ".local", "access.json");
}

const filled = (v) => typeof v === "string" && v.length > 0;

/** Panel hangi adreste açılsın ve Next'e hangi ortam değişkenleri gitsin. Şifresiz yerel ağ ASLA açılmaz. */
export function panelPlan(access, env) {
  const envPw = filled(env.DASHBOARD_PASSWORD);
  const hashed = Boolean(access) && filled(access.salt) && filled(access.hash) && filled(access.secret);
  const lan = Boolean(access) && access.enabled === true && (envPw || hashed);
  const out = {};
  if (lan && !envPw) {
    out.PANEL_PASSWORD_HASH = access.hash;
    out.PANEL_PASSWORD_SALT = access.salt;
    out.PANEL_SESSION_SECRET = access.secret;
  }
  return { host: lan ? "0.0.0.0" : "127.0.0.1", env: out };
}

/**
 * Next'i hangi kipte açacağız. Yerel ağa açıkken (0.0.0.0) HER ZAMAN `next start`: `next dev`in kendi uç noktaları
 * (/__nextjs_restart_dev, launch-editor, source-map…) middleware'den ÖNCE çalışır, yani şifresiz erişilebilirdi.
 * Yerelde (127.0.0.1) geliştirme kipi; `prod` verilirse üretim.
 */
export function panelCommand(plan, opts = {}) {
  const lan = plan.host === "0.0.0.0";
  return { mode: lan || opts.prod === true ? "start" : "dev", host: lan ? "0.0.0.0" : "127.0.0.1" };
}

/** Başlatıcının üretim derlemesi klasörü (BV_DIST_DIR ile next.config.ts'e verilir): `npm run build`/e2e (.next) ve
 * geliştirme sunucusu (.next-dev) ile çakışmaz. */
export const LAUNCHER_DIST = ".next-lan";
/** Derleme sıfır çıkış koduyla bitince yazılan işaret (zamanı = derlemenin başladığı an). Yarıda kesilen derleme
 * BUILD_ID bıraksa da işaret bırakmaz: bir sonraki açılışta yeniden derlenir. */
export const BUILD_MARKER = ".bv-build-ok";

const BUILD_INPUT_DIRS = ["src", "public"];
const BUILD_INPUT_FILES = ["next.config.ts", "next.config.mjs", "next.config.js", "package.json", "package-lock.json",
  "tsconfig.json", "postcss.config.mjs"];

function newestMtime(p) {
  let st;
  try { st = fs.statSync(p); } catch { return 0; }
  if (!st.isDirectory()) return st.mtimeMs;
  let newest = st.mtimeMs;                                         // dosya eklenince/silinince klasör zamanı da değişir
  for (const name of fs.readdirSync(p)) newest = Math.max(newest, newestMtime(path.join(p, name)));
  return newest;
}

/**
 * Başlatıcının üretim derlemesi (`<distDir>/.bv-build-ok` + BUILD_ID) yok ya da kaynaktan eski mi? İşaret yoksa (derleme
 * hiç bitmedi ya da öldürüldü) ya da src/, public/, next.config.*, package*.json'dan biri işaretten yeniyse eski sayılır.
 */
export function buildIsStale(dashDir, distDir = LAUNCHER_DIST) {
  let built;
  try {
    built = fs.statSync(path.join(dashDir, distDir, BUILD_MARKER)).mtimeMs;
    fs.statSync(path.join(dashDir, distDir, "BUILD_ID"));
  } catch { return true; }
  return [...BUILD_INPUT_DIRS, ...BUILD_INPUT_FILES].some((rel) => newestMtime(path.join(dashDir, rel)) > built);
}

/**
 * Derlemenin middleware listesi dolu mu (`<distDir>/server/middleware-manifest.json`)? Next, liste boşsa ya da dosya
 * yoksa isteği giriş denetimi olmadan geçirir: bu durumda yerel ağa AÇILMAZ.
 */
export function middlewareReady(manifestText) {
  try {
    const m = JSON.parse(manifestText);
    const mw = m && typeof m === "object" ? m.middleware : null;
    return Boolean(mw) && typeof mw === "object" && !Array.isArray(mw) && Object.keys(mw).length > 0;
  } catch { return false; }
}

/** Tek kopya kilidi: canlı başlatıcı kilidin zamanını bu aralıkla yeniler; bundan eski kilit bayat sayılır (PID
 * yeniden kullanılmış olabilir: bilgisayar yeniden başladı, başlatıcı zorla kapatıldı). */
export const LOCK_HEARTBEAT_MS = 15_000;
export const LOCK_STALE_MS = 60_000;
/** PID'i henüz yazılmamış kilit (başka başlatıcı tam şu an oluşturuyor) bu kadar süre "çalışıyor" sayılır */
export const LOCK_FRESH_MS = 5_000;

/**
 * Kilit dosyası varken karar (saf): `existingPid` dosyadaki PID (okunamadıysa null), `alive` o süreç var mı,
 * `ageMs` kilidin son yenilenmesinden bu yana geçen süre. "running": başka başlatıcı çalışıyor (çık); "stale": devral.
 */
export function lockDecision(existingPid, alive, ageMs = 0) {
  const valid = Number.isInteger(existingPid) && existingPid > 0;
  if (!valid) return ageMs < LOCK_FRESH_MS ? "running" : "stale";
  return alive && ageMs < LOCK_STALE_MS ? "running" : "stale";
}

const PANEL_STATES = new Set(["building", "failed", "listening"]);

/** Başlatıcının durum dosyası (`{state, host, at, message}`); Ayarlar ve panel_baslat.bat okur */
export function panelStateFile(env, cwd) {
  return env.PANEL_STATE_FILE || path.join(cwd, ".local", "panel-state.json");
}

/** Durum dosyasının metninden Ayarlar'ın göstereceği kısım; bilinmeyen durum, bozuk ya da boş dosya null */
export function panelState(text) {
  try {
    const d = JSON.parse(text);
    if (!d || typeof d !== "object" || !PANEL_STATES.has(d.state)) return null;
    return { state: d.state, message: typeof d.message === "string" ? d.message.slice(0, 300) : "" };
  } catch { return null; }
}

/** Giriş isteği yalnızca `application/json` olabilir: site dışı "basit" istekler (text/plain, form) ön kontrolsüz
 * gönderilebildiği için kısıtı kilitleyebilirdi; JSON ön kontrol ister ve tarayıcı onu başka siteye vermez. */
export function isJsonContentType(value) {
  if (typeof value !== "string") return false;
  return value.split(";")[0].trim().toLowerCase() === "application/json";
}

/**
 * Giriş denemesi kısıtı (tüm istemciler için ortak: uzak adres güvenilir değil). Saf; saat dışarıdan verilir.
 * - İlk `free` hatalı deneme serbest. Sonrasında her hatada kilit penceresi başlar (baseMs, sonra ikiye katlanır, en çok maxMs).
 * - Kilit sürerken `begin()` kalan ms'yi döner (çağıran scrypt çalıştırmadan 429 verir). Başarı her şeyi sıfırlar.
 * - Eşzamanlı denemeler sınırlıdır: serbest hakkı aşan tek deneme birden çok kez aynı anda denenemez.
 * Kullanım: `const wait = t.begin(); if (wait > 0) → 429; … t.end(başarılı)`.
 */
export function createLoginThrottle({ now = Date.now, free = 5, baseMs = 10_000, maxMs = 300_000 } = {}) {
  let fails = 0, pending = 0, lockUntil = 0, windowMs = 0;
  return {
    begin() {
      const t = now();
      if (t < lockUntil) return lockUntil - t;
      const open = fails < free ? fails + pending < free : pending === 0;
      if (!open) return 1000;
      pending += 1;
      return 0;
    },
    end(ok) {
      pending = Math.max(0, pending - 1);
      if (ok) { fails = 0; lockUntil = 0; windowMs = 0; return; }
      fails += 1;
      if (fails >= free) {
        windowMs = windowMs ? Math.min(windowMs * 2, maxMs) : baseMs;
        lockUntil = now() + windowMs;
      }
    },
  };
}

/**
 * Ayarları değiştirme isteği (DNS yeniden bağlama savunması): `Host` başlığının ana makine adı yalnızca geri döngü
 * (127.0.0.1, localhost, ::1) ya da bu bilgisayarın kendi IPv4 adreslerinden biri olabilir.
 */
export function hostAllowed(hostHeader, ownIps = []) {
  const name = hostName(hostHeader);
  if (!name) return false;
  return name === "127.0.0.1" || name === "localhost" || name === "::1" || ownIps.includes(name);
}

/**
 * `PUT /api/access` kararı (saf: dosya ve ortam yok). `body`: { enabled, password? }.
 * - Açma yalnızca `enabled === true` ile; başka her değer kapalı sayılır.
 * - Şifre verilirse boşluklar kırpıldıktan sonra en az MIN_PASSWORD, en çok MAX_PASSWORD karakter; yalnızca scrypt özeti
 *   saklanır ve oturum sırrı yenilenir (eski oturumlar düşer).
 * - Kapalıdan açığa her geçişte de yeni oturum sırrı üretilir (kapalıyken çalınmış çerez geri gelmesin).
 * - Açmak için tam özet (salt+hash+secret) ya da ortamda DASHBOARD_PASSWORD gerekir.
 * Dönüş: { next } ya da { error, status }.
 */
export function updateAccess(cur, body, envPassword, now = Date.now() / 1000) {
  const was = Boolean(cur) && cur.enabled === true;
  const next = { ...(cur ?? { enabled: false }), enabled: Boolean(body) && body.enabled === true, updatedAt: now };
  const pw = body ? body.password : undefined;
  if (typeof pw === "string" && pw !== "") {
    if (pw.length > MAX_PASSWORD) return { error: `Şifre en çok ${MAX_PASSWORD} karakter olabilir.`, status: 422 };
    if (pw.trim().length < MIN_PASSWORD) {
      return { error: `Şifre en az ${MIN_PASSWORD} karakter olmalı (baştaki ve sondaki boşluklar sayılmaz).`, status: 422 };
    }
    Object.assign(next, hashPassword(pw), { secret: newSecret() });
  } else if (filled(next.salt) && filled(next.hash) && (!filled(next.secret) || (next.enabled && !was))) {
    next.secret = newSecret();
  }
  const complete = filled(next.salt) && filled(next.hash) && filled(next.secret);
  if (next.enabled && !complete && !envPassword) {
    return { error: "Telefondan erişim için önce panel şifresi belirleyin.", status: 422 };
  }
  return { next };
}
