#!/usr/bin/env node
// Paneli erişim ayarına göre başlatır: telefondan erişim kapalıyken yalnızca bu bilgisayar (127.0.0.1), açıkken (şifreyle)
// tüm ağ arayüzleri. apps/dashboard/.local/access.json değişince Next'i yeniden başlatır (≈ 10 sn).
// Kullanım: node tools/panel_run.mjs [--prod] [--port 3000]
import { execFileSync, spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { accessFile, panelPlan } from "../apps/dashboard/src/lib/accessCore.mjs";

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
let child = null;
let restartTimer = null;
let last = text();

function start() {
  if (child) return;                                  // aynı anda tek Next (eski süreç asılı kalmasın)
  const plan = panelPlan(parse(last), process.env);
  console.log(`[panel] ${plan.host === "0.0.0.0" ? "yerel ağa açık (şifreli)" : "yalnızca bu bilgisayar"} · port ${port}`);
  const args = ["next", prod ? "start" : "dev", "-H", plan.host, "-p", port];
  const opts = { cwd: DASH, env: { ...process.env, ...plan.env, PANEL_RUNNER: "1", PORT: port }, stdio: "inherit" };
  // Windows'ta npx bir .cmd dosyasıdır: kabukla çalışır. Bağımsız değişkenlerin hepsi bu dosyada sabit ya da doğrulanmış.
  const c = process.platform === "win32" ? spawn(`npx ${args.join(" ")}`, { ...opts, shell: true }) : spawn("npx", args, opts);
  child = c;
  c.on("exit", (code) => {
    if (child !== c) return;                          // bilerek durdurduk (yeniden başlatma)
    child = null;
    console.log(`[panel] Next kapandı (kod ${code ?? "?"}); başlatıcı da çıkıyor`);
    process.exit(code ?? 1);
  });
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
  if (restartTimer) clearTimeout(restartTimer);       // art arda değişimde tek yeniden başlatma
  restartTimer = setTimeout(() => { restartTimer = null; start(); }, 1500);
});
for (const sig of ["SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK"]) process.on(sig, () => { stop(); process.exit(0); });
process.on("exit", stop);
start();
