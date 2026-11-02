import { expect, test } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import http from "node:http";
import net from "node:net";
import path from "node:path";

/**
 * Yükleme sırasında istemci ayrılırsa panel bunu "analiz sunucusuna ulaşılamadı" diye günlüğe yazmaz (istemci gitti, analiz
 * sunucusu sağlam); analiz sunucusu yükleme ortasında gerçekten koparsa yine 502 verir ve günlüğe yazar. Günlük satırlarını
 * görmek için bu dosya kendi paneli (3118, şifresiz) ve sahte analiz sunucusunu (8098) başlatır; ortak sunucular kullanılmaz.
 */
const PANEL_PORT = 3118;
const FAKE_PORT = 8098;
const BOUNDARY = "e2e-sinir";
const BIG = 12 * 1024 * 1024;
const REACH = "analiz sunucusuna ulaşılamadı";

let panel: ChildProcess | undefined;
let fake: http.Server | undefined;
let log = "";
/** Sahte analiz sunucusunun yükleme ucundaki davranışı: "hang" gövdeyi okur ve yanıtlamaz, "drop" ilk parçada bağlantıyı koparır */
let mode: "hang" | "drop" = "hang";

test.beforeAll(async () => {
  fake = http.createServer((req, res) => {
    if (req.method === "GET") { res.setHeader("content-type", "application/json"); res.end("{}"); return; }
    req.on("data", () => { if (mode === "drop") req.socket.destroy(); });
    req.on("error", () => undefined);
  });
  await new Promise<void>((resolve) => fake!.listen(FAKE_PORT, "127.0.0.1", resolve));
  panel = spawn(process.execPath, [require.resolve("next/dist/bin/next"), "start", "-p", String(PANEL_PORT), "-H", "127.0.0.1"], {
    cwd: path.resolve(__dirname, ".."),
    env: { ...process.env, ANALYZER_URL: `http://127.0.0.1:${FAKE_PORT}`, DASHBOARD_PASSWORD: "", NEXT_TELEMETRY_DISABLED: "1",
           PANEL_ACCESS_FILE: path.join(process.env.TEMP ?? "/tmp", "bv-abort-access.json"), PANEL_STATE_FILE: path.join(process.env.TEMP ?? "/tmp", "bv-abort-state.json") },
  });
  panel.stdout?.on("data", (c: Buffer) => { log += c.toString("utf8"); });
  panel.stderr?.on("data", (c: Buffer) => { log += c.toString("utf8"); });
  await expect.poll(async () => (await fetch(`http://127.0.0.1:${PANEL_PORT}/login`).catch(() => null))?.status, { timeout: 60_000 }).toBe(200);
});

test.afterAll(async () => {
  panel?.kill();
  await new Promise<void>((resolve) => (fake ? fake.close(() => resolve()) : resolve()));
});

/** Başlıklar ve gövdenin 1 MB'ı gider; `leave` ise bağlantıyı keser, değilse yanıtı bekler */
function upload(leave: boolean): Promise<{ status: number; body: string } | null> {
  const head = [`POST /api/jobs HTTP/1.1`, `Host: 127.0.0.1:${PANEL_PORT}`, `Content-Type: multipart/form-data; boundary=${BOUNDARY}`,
    `Content-Length: ${BIG}`, "", ""].join("\r\n");
  const part = `--${BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="a.mp4"\r\nContent-Type: video/mp4\r\n\r\n`;
  return new Promise((resolve) => {
    const socket = net.connect(PANEL_PORT, "127.0.0.1");
    let got = "";
    socket.on("error", () => resolve(null));
    socket.on("data", (c) => {
      got += c.toString("utf8");
      const m = /^HTTP\/1\.1 (\d+)[\s\S]*?\r\n\r\n[\s\S]*?(\{[\s\S]*\})/.exec(got);     // gövde parçalı (chunked) gelebilir
      if (m) { socket.destroy(); resolve({ status: Number(m[1]), body: m[2] }); }
    });
    socket.write(head + part);
    socket.write(Buffer.alloc(1024 * 1024));
    if (leave) setTimeout(() => { socket.destroy(); resolve(null); }, 800);
  });
}

test("yükleme sürerken istemci ayrılırsa panel bunu analiz sunucusu hatası diye günlüğe yazmaz", async () => {
  mode = "hang";
  expect(await upload(true)).toBeNull();
  await new Promise((r) => setTimeout(r, 2_500));                          // fetch hatasının günlüğe düşmesi için pay
  expect(log).not.toContain(REACH);
  expect(log).not.toContain("ECONNRESET");
});

test("analiz sunucusu yükleme ortasında koparsa 502 döner ve günlüğe yazılır", async () => {
  mode = "drop";
  const res = await upload(false);
  expect(res?.status).toBe(502);
  expect(JSON.parse(res!.body).detail).toContain("Analiz sunucusuna ulaşılamadı");
  await expect.poll(() => log, { timeout: 10_000 }).toContain(REACH);
});
