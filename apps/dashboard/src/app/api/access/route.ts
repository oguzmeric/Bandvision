import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { NextResponse, type NextRequest } from "next/server";
import { accessFile, hostAllowed, panelState, panelStateFile, updateAccess, type Access } from "@/lib/accessCore.mjs";

// Bu uç nokta middleware'in arkasındadır: şifre kipi açıkken giriş ister. Şifre kipi kapalıyken panel yalnızca
// bu bilgisayarda (127.0.0.1) açıldığı için uç nokta da yalnızca yerelden erişilebilir. Yanıtlara şifre ya da özeti girmez.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function file(): string { return accessFile(process.env, process.cwd()); }
function read(): Access | null {
  try { return JSON.parse(fs.readFileSync(file(), "utf8")) as Access; } catch { return null; }
}
/** Başlatıcının durum dosyası (tools/panel_run.mjs yazar): derleme sürüyor ya da başarısız oldu mu */
function buildState() {
  try { return panelState(fs.readFileSync(panelStateFile(process.env, process.cwd()), "utf8")); } catch { return null; }
}
/** Sanal bağdaştırıcılar (VMware, WSL, VPN…) ve 169.254.x.x sona atılır: QR gerçek ağı göstersin. */
const SANAL = /vmware|virtual|vethernet|wsl|hyper-v|docker|vpn|tailscale|zerotier|bluetooth|loopback/i;
/** Bu bilgisayarın IPv4 adresleri (geri döngü hariç); gerçek ağlar önce (kararlı sıralama) */
function ownAddresses(): string[] {
  const list = Object.entries(os.networkInterfaces()).flatMap(([name, infos]) =>
    (infos ?? []).filter((i) => i.family === "IPv4" && !i.internal)
      .map((i) => ({ address: i.address, sanal: SANAL.test(name) || i.address.startsWith("169.254.") })));
  list.sort((x, y) => Number(x.sanal) - Number(y.sanal));
  return list.map((i) => i.address);
}
function addresses(): string[] {
  const port = process.env.PORT || "3000";
  return ownAddresses().map((a) => `http://${a}:${port}`);
}
function view(a: Access | null) {
  const build = buildState();
  return {
    enabled: Boolean(a?.enabled), hasPassword: Boolean(a?.hash), envPassword: Boolean(process.env.DASHBOARD_PASSWORD),
    /** Bu çalışan panel şu an yerel ağa açık mı: yalnızca başlatıcı 0.0.0.0'a bağlarken PANEL_LAN=1 verir */
    lanActive: process.env.PANEL_LAN === "1",
    runner: process.env.PANEL_RUNNER === "1", addresses: addresses(),
    /** Başlatıcının son durumu: "building" (derleniyor), "failed" (yerel ağ derlemesi/denetimi başarısız), "listening" */
    buildState: build?.state ?? null, buildMessage: build?.message ?? null,
  };
}

export async function GET() {
  return NextResponse.json(view(read()));
}

/** {enabled, password?}: şifre verilirse en az 8, en çok 256 karakter; açmak için şifre (ya da DASHBOARD_PASSWORD) gerekir.
 * Karar `updateAccess`'te (saf, birim testli); burada yalnızca dosya yazılır. DNS yeniden bağlama savunması: `Host`
 * yalnızca geri döngü ya da bu bilgisayarın kendi adresi olabilir. */
export async function PUT(req: NextRequest) {
  if (!hostAllowed(req.headers.get("host"), ownAddresses())) {
    return NextResponse.json({ detail: "Geçersiz adres." }, { status: 403 });
  }
  let body: { enabled?: unknown; password?: unknown } | null;
  try { body = (await req.json()) as typeof body; } catch { return NextResponse.json({ detail: "Geçersiz istek." }, { status: 400 }); }
  if (!body || typeof body !== "object") return NextResponse.json({ detail: "Geçersiz istek." }, { status: 400 });
  const r = updateAccess(read(), body, Boolean(process.env.DASHBOARD_PASSWORD));
  if ("error" in r) return NextResponse.json({ detail: r.error }, { status: r.status });
  fs.mkdirSync(path.dirname(file()), { recursive: true });
  fs.writeFileSync(file(), JSON.stringify(r.next), { encoding: "utf8", mode: 0o600 });
  return NextResponse.json(view(r.next));
}
