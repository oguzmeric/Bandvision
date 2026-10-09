#!/usr/bin/env node
// Paneli erişim ayarına göre başlatır: telefondan erişim kapalıyken yalnızca bu bilgisayar (127.0.0.1, geliştirme kipi),
// açıkken (şifreyle) tüm ağ arayüzleri ve HER ZAMAN üretim kipi (`next start`): `next dev`in kendi uç noktaları
// (yeniden başlatma, dosya açma, kaynak haritası…) middleware'den önce çalıştığı için yerel ağda şifresiz erişilebilirdi.
// - Tek kopya: apps/dashboard/.local/panel.lock (PID; canlı başlatıcı zamanını yeniler). Başka başlatıcı çalışıyorsa
//   "Panel zaten çalışıyor" yazıp çıkar (0); kilidin süreci yoksa ya da kilit bayatsa devralır; çıkarken siler.
// - Üretim derlemesi kendi klasörüne (.next-lan, BV_DIST_DIR) yapılır; derleme sıfırla bitince .next-lan/.bv-build-ok
//   yazılır. İşaret yoksa (derleme hiç bitmedi ya da öldürüldü) ya da kaynaktan eskiyse önce `next build` (1-2 dk).
//   Derleme başarısız olursa ya da derlemede middleware (giriş denetimi) yoksa yerel ağa AÇILMAZ, yalnızca bu
//   bilgisayarda geliştirme kipinde başlar.
// - Durum dosyası apps/dashboard/.local/panel-state.json: {state: building|failed|listening, host, at, message};
//   panel_baslat.bat (derlenirken bekler ve yazar) ve Ayarlar okur.
// apps/dashboard/.local/access.json değişince Next'i yeniden başlatır (≈ 10 sn).
// Kullanım: node tools/panel_run.mjs [--prod] [--port 3000]
import { execFileSync, spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  BUILD_MARKER, LAUNCHER_DIST, LOCK_HEARTBEAT_MS, accessFile, buildIsStale, lockDecision, middlewareReady, panelCommand,
  panelPlan, panelStateFile,
} from "../apps/dashboard/src/lib/accessCore.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DASH = path.join(ROOT, "apps", "dashboard");
const prod = process.argv.includes("--prod");
const portArg = process.argv.indexOf("--port");
const port = portArg > 0 ? process.argv[portArg + 1] : "3000";
if (!/^\d{1,5}$/.test(port)) {
  console.error(`[panel] geçersiz port: ${port}`);
  process.exit(2);
}
const FILE = accessFile(process.env, DASH);
const LOCK = path.join(DASH, ".local", "panel.lock");
const STATE = panelStateFile(process.env, DASH);
const DIST = path.join(DASH, LAUNCHER_DIST);
const BUILDING_MSG = "Panel derleniyor (ilk açılış 1-2 dk)…";

// ---------------------------------------------------------------- tek kopya kilidi

function pidAlive(pid) {
  try { process.kill(pid, 0); return true; } catch (e) { return e.code === "EPERM"; }
}
function lockInfo() {
  try {
    const ageMs = Date.now() - fs.statSync(LOCK).mtimeMs;
    const pid = Number.parseInt(fs.readFileSync(LOCK, "utf8").trim(), 10);
    return { pid: Number.isInteger(pid) ? pid : null, ageMs };
  } catch { return null; }
}
/** Kilidi alır; başka canlı başlatıcı varsa false. `wx` (yoksa oluştur) iki başlatıcının aynı anda almasını önler. */
function acquireLock() {
  fs.mkdirSync(path.dirname(LOCK), { recursive: true });
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const fd = fs.openSync(LOCK, "wx");
      fs.writeSync(fd, String(process.pid));
      fs.closeSync(fd);
      return true;
    } catch (e) {
      if (e.code !== "EEXIST") throw e;
    }
    const info = lockInfo();
    if (!info) continue;                                 // tam o an silindi: yeniden dene
    if (lockDecision(info.pid, info.pid !== null && pidAlive(info.pid), info.ageMs) === "running") return false;
    console.log(`[panel] eski kilit (PID ${info.pid ?? "?"}) artık çalışmıyor; devralınıyor`);
    try { fs.unlinkSync(LOCK); } catch { /* başka başlatıcı az önce devraldı: sonraki tur görür */ }
  }
  return false;
}
function releaseLock() {
  try { if (lockInfo()?.pid === process.pid) fs.unlinkSync(LOCK); } catch { /* zaten yok */ }
}

if (!acquireLock()) {
  console.log("[panel] Panel zaten çalışıyor (başka bir başlatıcı açık); bu kopya çıkıyor.");
  process.exit(0);
}
// Canlı olduğumuzu bildir: PID yeniden kullanılsa da (yeniden başlatma) bayat kilit "çalışıyor" sanılmasın
setInterval(() => { try { const t = new Date(); fs.utimesSync(LOCK, t, t); } catch { /* kilit silinmiş */ } }, LOCK_HEARTBEAT_MS).unref();

// ---------------------------------------------------------------- durum dosyası

/** {state, host, at, message}: panel_baslat.bat ve Ayarlar okur. Yazılamazsa yalnızca bilgi kaybolur. */
function writeState(state, host, message = "") {
  try {
    fs.mkdirSync(path.dirname(STATE), { recursive: true });
    const tmp = `${STATE}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify({ state, host, at: Date.now() / 1000, message }));
    fs.renameSync(tmp, STATE);
  } catch { /* yalnızca bilgi amaçlı */ }
}

// ---------------------------------------------------------------- Next süreçleri

const text = () => { try { return fs.readFileSync(FILE, "utf8"); } catch { return ""; } };
const parse = (t) => { try { return t ? JSON.parse(t) : null; } catch { return null; } };
let child = null;                                      // çalışan süreç: derleme ya da Next
let restartTimer = null;
let last = text();

// Windows'ta npx bir .cmd dosyasıdır: kabukla, tek komut dizesi olarak çalışır. Bağımsız değişkenlerin hepsi bu dosyada
// sabit ya da doğrulanmış (port rakam, ana makine panelCommand'dan).
function run(args, opts) {
  return process.platform === "win32" ? spawn(`npx ${args.join(" ")}`, { ...opts, shell: true }) : spawn("npx", args, opts);
}
/** Süreç bitince (çıkış ya da başlatılamadı) bir kez `done(kod)` çağırır; bilerek durdurulduysa (child !== c) çağırmaz. */
function onEnd(c, done) {
  let ended = false;
  const end = (code) => { if (ended) return; ended = true; if (child !== c) return; child = null; done(code); };
  c.on("exit", (code) => end(code ?? 1));
  c.on("error", (err) => { console.log(`[panel] süreç başlatılamadı: ${err.message}`); end(1); });
}
/** Derlemenin middleware listesi dolu mu: değilse Next isteği giriş denetimi olmadan geçirirdi */
function middlewareInBuild() {
  try { return middlewareReady(fs.readFileSync(path.join(DIST, "server", "middleware-manifest.json"), "utf8")); } catch { return false; }
}

/** Yalnızca bu bilgisayarda, geliştirme kipinde (yerel ağ derlemesi ya da denetimi başarısız): durum "failed" kalır */
function fallbackLocal(planEnv, message) {
  writeState("failed", "127.0.0.1", message);
  launch(panelCommand({ host: "127.0.0.1" }, { prod: false }), planEnv, false);
}

function launch(cmd, planEnv, reportListening = true) {
  const lan = cmd.host === "0.0.0.0";
  if (lan && cmd.mode !== "start") {                   // son güvenlik ağı: yerel ağda geliştirme sunucusu ASLA
    console.error("[panel] iç hata: yerel ağ için geliştirme kipi istendi; başlatılmıyor");
    process.exit(3);
  }
  if (lan && !middlewareInBuild()) {
    console.log("[panel] derlemede giriş denetimi (middleware) bulunamadı; yerel ağa AÇILMIYOR, yalnızca bu bilgisayarda geliştirme kipinde başlıyor");
    return fallbackLocal(planEnv, "Derlemede giriş denetimi bulunamadı; panel yerel ağa açılmadı, yalnızca bu bilgisayarda açık.");
  }
  console.log(`[panel] ${lan ? "yerel ağa açık (şifreli)" : "yalnızca bu bilgisayar"} · port ${port} (${cmd.mode === "start" ? "üretim" : "geliştirme"} kipi)`);
  const env = { ...process.env, ...planEnv, PANEL_RUNNER: "1", PANEL_LAN: lan ? "1" : "0", PORT: port };
  if (cmd.mode === "start") env.BV_DIST_DIR = LAUNCHER_DIST;   // next start, başlatıcının derlemesini okur
  if (reportListening) writeState("listening", cmd.host, "");
  const c = run(["next", cmd.mode, "-H", cmd.host, "-p", port], { cwd: DASH, env, stdio: "inherit" });
  child = c;
  onEnd(c, (code) => {
    console.log(`[panel] Next kapandı (kod ${code}); başlatıcı da çıkıyor`);
    process.exit(code);
  });
}

function start() {
  if (child) return;                                   // aynı anda tek süreç (eski Next asılı kalmasın)
  const plan = panelPlan(parse(last), process.env);
  const cmd = panelCommand(plan, { prod });
  if (cmd.mode === "start" && buildIsStale(DASH, LAUNCHER_DIST)) {
    console.log(`[panel] ${cmd.host === "0.0.0.0" ? "yerel ağ kipi: " : ""}üretim derlemesi hazırlanıyor (1-2 dk)…`);
    writeState("building", cmd.host, BUILDING_MSG);
    try { fs.rmSync(path.join(DIST, BUILD_MARKER), { force: true }); } catch { /* yok */ }   // yarıda kalırsa işaret olmasın
    const startedAt = new Date();
    const b = run(["next", "build"], {
      cwd: DASH, env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1", BV_DIST_DIR: LAUNCHER_DIST }, stdio: "inherit",
    });
    child = b;
    onEnd(b, (code) => {
      if (code === 0) {
        try {
          const marker = path.join(DIST, BUILD_MARKER);
          fs.writeFileSync(marker, `${startedAt.toISOString()}\n`);
          fs.utimesSync(marker, startedAt, startedAt);   // derleme sürerken değişen kaynak bir sonraki açılışta yeniden derlenir
        } catch (e) { console.log(`[panel] derleme işareti yazılamadı: ${e.message}`); }
        return launch(cmd, plan.env);
      }
      // Derleme olmadan `next start` çalışmaz; yerel ağda geliştirme sunucusuna düşmek de güvenli değil: yalnızca yerel
      console.log(`[panel] üretim derlemesi başarısız (kod ${code}); yerel ağa AÇILMIYOR, yalnızca bu bilgisayarda geliştirme kipinde başlıyor`);
      fallbackLocal(plan.env, `Yerel ağ için derleme başarısız (kod ${code}); panel yalnızca bu bilgisayarda açık. Ayrıntı panel günlüğünde.`);
    });
    return;
  }
  launch(cmd, plan.env);
}
function stop() {
  const c = child;
  if (!c) return;
  child = null;
  try {
    // Yalnızca kendi başlattığımız sürecin PID'i (ve alt süreçleri); süreç adıyla sonlandırma yok
    if (process.platform === "win32") execFileSync("taskkill", ["/PID", String(c.pid), "/T", "/F"], { stdio: "ignore" });
    else c.kill("SIGTERM");
  } catch { /* zaten kapanmış */ }
}
fs.watchFile(FILE, { interval: 2000 }, () => {
  const t = text();
  if (t === last) return;
  last = t;
  console.log("[panel] erişim ayarı değişti: yeniden başlatılıyor");
  stop();
  if (restartTimer) clearTimeout(restartTimer);        // art arda değişimde tek yeniden başlatma
  restartTimer = setTimeout(() => { restartTimer = null; start(); }, 1500);
});
for (const sig of ["SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK"]) process.on(sig, () => { stop(); process.exit(0); });
process.on("exit", () => {
  stop();
  try { fs.rmSync(STATE, { force: true }); } catch { /* yok */ }   // çalışmayan panelin durumu "derleniyor" kalmasın
  releaseLock();
});
start();
