#!/usr/bin/env node
// Paneli erişim ayarına göre başlatır: telefondan erişim kapalıyken yalnızca bu bilgisayar (127.0.0.1, geliştirme kipi),
// açıkken (şifreyle) tüm ağ arayüzleri ve HER ZAMAN üretim kipi (`next start`): `next dev`in kendi uç noktaları
// (yeniden başlatma, dosya açma, kaynak haritası…) middleware'den önce çalıştığı için yerel ağda şifresiz erişilebilirdi.
// Üretim derlemesi yoksa ya da kaynaktan eskiyse önce `next build` çalışır (1-2 dk); derleme başarısız olursa yerel ağa
// AÇILMAZ, yalnızca bu bilgisayarda geliştirme kipinde başlar.
// apps/dashboard/.local/access.json değişince Next'i yeniden başlatır (≈ 10 sn).
// Kullanım: node tools/panel_run.mjs [--prod] [--port 3000]
import { execFileSync, spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { accessFile, buildIsStale, panelCommand, panelPlan } from "../apps/dashboard/src/lib/accessCore.mjs";

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

function launch(cmd, planEnv) {
  const lan = cmd.host === "0.0.0.0";
  if (lan && cmd.mode !== "start") {                   // son güvenlik ağı: yerel ağda geliştirme sunucusu ASLA
    console.error("[panel] iç hata: yerel ağ için geliştirme kipi istendi; başlatılmıyor");
    process.exit(3);
  }
  console.log(`[panel] ${lan ? "yerel ağa açık (şifreli)" : "yalnızca bu bilgisayar"} · port ${port} (${cmd.mode === "start" ? "üretim" : "geliştirme"} kipi)`);
  const env = { ...process.env, ...planEnv, PANEL_RUNNER: "1", PANEL_LAN: lan ? "1" : "0", PORT: port };
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
  if (cmd.mode === "start" && buildIsStale(DASH)) {
    console.log(`[panel] ${cmd.host === "0.0.0.0" ? "yerel ağ kipi: " : ""}üretim derlemesi hazırlanıyor (1-2 dk)…`);
    const b = run(["next", "build"], { cwd: DASH, env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1" }, stdio: "inherit" });
    child = b;
    onEnd(b, (code) => {
      if (code === 0) return launch(cmd, plan.env);
      // Derleme olmadan `next start` çalışmaz; yerel ağda geliştirme sunucusuna düşmek de güvenli değil: yalnızca yerel
      console.log(`[panel] üretim derlemesi başarısız (kod ${code}); yerel ağa AÇILMIYOR, yalnızca bu bilgisayarda geliştirme kipinde başlıyor`);
      launch(panelCommand({ host: "127.0.0.1" }, { prod: false }), plan.env);
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
process.on("exit", stop);
start();
