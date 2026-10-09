// Telefondan erişim: panel şifresi (yalnızca scrypt özeti), oturum sırrı ve paneli hangi adreste açacağımız.
// Saf mantık: hem Next (API rotası, giriş) hem başlatıcı (tools/panel_run.mjs) kullanır; `node --test` ile sınanır.
import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";
import path from "node:path";

export const MIN_PASSWORD = 8;
const SCRYPT = { N: 16384, r: 8, p: 1 };

export function hashPassword(pw) {
  const salt = randomBytes(16).toString("hex");
  return { salt, hash: scryptSync(pw, salt, 32, SCRYPT).toString("hex") };
}

export function verifyPassword(pw, salt, hash) {
  if (!salt || !hash) return false;
  const want = Buffer.from(hash, "hex");
  const got = scryptSync(String(pw), salt, 32, SCRYPT);
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
 * `PUT /api/access` kararı (saf: dosya ve ortam yok). `body`: { enabled, password? }.
 * - Açma yalnızca `enabled === true` ile; başka her değer kapalı sayılır.
 * - Şifre verilirse en az MIN_PASSWORD karakter; yalnızca scrypt özeti saklanır ve oturum sırrı yenilenir (eski oturumlar düşer).
 * - Şifre (dosyada özet ya da ortamda DASHBOARD_PASSWORD) yokken açılamaz.
 * Dönüş: { next } ya da { error, status }.
 */
export function updateAccess(cur, body, envPassword, now = Date.now() / 1000) {
  const next = { ...(cur ?? { enabled: false }), enabled: Boolean(body) && body.enabled === true, updatedAt: now };
  const pw = body ? body.password : undefined;
  if (typeof pw === "string" && pw !== "") {
    if (pw.length < MIN_PASSWORD) return { error: `Şifre en az ${MIN_PASSWORD} karakter olmalı.`, status: 422 };
    Object.assign(next, hashPassword(pw), { secret: newSecret() });
  }
  if (next.enabled && !next.hash && !envPassword) {
    return { error: "Telefondan erişim için önce panel şifresi belirleyin.", status: 422 };
  }
  return { next };
}
