import { expect, test } from "@playwright/test";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";

/**
 * Gerçek yığın (playwright.config.ts): analiz sunucusu 8092 anahtarı `e2e-dogru-anahtar`, şifresiz panel 3102 anahtarı
 * `e2e-yanlis-anahtar`. Panelin vekili analiz sunucusunun 401'ini aktarmaz: 502 + kod; sayfa "oturum doldu" demez.
 * Aynı panel şifresiz olduğundan başka siteden gelen API isteklerinin reddi de burada sınanır.
 */
const PANEL = "http://127.0.0.1:3102";
const ANALYZER = "http://127.0.0.1:8092";
const KEY_TEXT = "Analiz sunucusu erişim anahtarı uyuşmuyor — panelde ve analiz sunucusunda aynı ANALYZER_TOKEN ayarlanmalı.";
const CROSS_SITE = { error: "Bu istek başka bir siteden geldiği için kabul edilmedi." };
const JOB = "00000000-0000-4000-8000-000000000000";
const VIDEO = { file: { name: "a.mp4", mimeType: "video/mp4", buffer: Buffer.alloc(16) } };
/** Şifreli panel (doğru anahtar: analiz sunucusu 8091 anahtarsız) */
const PASSWORD_PANEL = "http://127.0.0.1:3100";
const CLIP = path.resolve(__dirname, "../../ios/BantSayacUITests/ui_test_clip.mp4");
const BIG = 12 * 1024 * 1024;
const BOUNDARY = "e2e-sinir";

test.use({ baseURL: PANEL });

/** Yol olduğu gibi gönderilir (URL ayrıştırıcısı düzeltmesin) */
const raw = (port: number, target: string, headers: Record<string, string> = {}, method = "GET") => new Promise<{ status: number; body: string }>((resolve, reject) => {
  const q = http.request({ host: "127.0.0.1", port, path: target, method, headers: { Host: `127.0.0.1:${port}`, ...headers } }, (res) => {
    let body = "";
    res.setEncoding("utf8");
    res.on("data", (c: string) => { body += c; });
    res.on("end", () => resolve({ status: res.statusCode ?? 0, body }));
  });
  q.on("error", reject);
  q.end();
});

/** Gerçek klip + sonda MP4 `free` kutusu: Next'in 10 MB ara katman sınırını aşar, analiz sunucusu yine video diye okur */
function paddedClip(file: string): string {
  const clip = readFileSync(CLIP);
  const pad = Buffer.alloc(BIG - clip.length);
  pad.writeUInt32BE(pad.length, 0);
  pad.write("free", 4, "latin1");
  writeFileSync(file, Buffer.concat([clip, pad]));
  return file;
}

/**
 * Ham yükleme: başlıklar ve 12 MB gövdenin yalnızca 1 MB'ı; kalanı HİÇ gönderilmez. Yanıt ancak panel gövdeyi beklemeden
 * karar verirse gelir (yanlış anahtar bütün videoyu beklemez, ret bağlantıyı koparmaz).
 */
function partialUpload(port: number, headers: Record<string, string> = {}): Promise<{ status: number; body: unknown }> {
  const part = `--${BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="a.mp4"\r\nContent-Type: video/mp4\r\n\r\n`;
  const lines = { Host: `127.0.0.1:${port}`, "Content-Type": `multipart/form-data; boundary=${BOUNDARY}`, "Content-Length": String(BIG), ...headers };
  const head = ["POST /api/jobs HTTP/1.1", ...Object.entries(lines).map(([k, v]) => `${k}: ${v}`), "", ""].join("\r\n");
  return new Promise((resolve, reject) => {
    const socket = net.connect(port, "127.0.0.1");
    const timer = setTimeout(() => { socket.destroy(); reject(new Error("yanıt gövde bitmeden gelmedi")); }, 10_000);
    let got = Buffer.alloc(0);
    socket.on("error", (e) => { clearTimeout(timer); reject(e); });
    socket.on("data", (chunk) => {
      got = Buffer.concat([got, chunk]);
      const text = got.toString("utf8");
      const m = /^HTTP\/1\.1 (\d+)[\s\S]*?\r\n\r\n([\s\S]*)$/.exec(text);
      const json = m && /(\{[\s\S]*\})/.exec(m[2]);
      if (!m || !json) return;
      clearTimeout(timer);
      socket.destroy();
      resolve({ status: Number(m[1]), body: JSON.parse(json[1]) });
    });
    socket.write(head);
    socket.write(part);
    socket.write(Buffer.alloc(1024 * 1024));
  });
}

test("erişim anahtarı uyuşmuyor: analiz sunucusu 401 verir, vekil bütün yollarda 502 + analyzer_key döner", async ({ request }) => {
  // Gerçek sunucu: yanlış anahtara 401, doğrusuna 200 (ret sunucunun kendi anahtar denetiminden)
  const url = `${ANALYZER}/api/v1/live/views`;
  expect((await request.get(url, { headers: { Authorization: "Bearer e2e-yanlis-anahtar" } })).status()).toBe(401);
  expect((await request.get(url, { headers: { Authorization: "Bearer e2e-dogru-anahtar" } })).status()).toBe(200);

  const refused = { detail: KEY_TEXT, code: "analyzer_key" };
  const calls: Array<[string, () => ReturnType<typeof request.get>]> = [
    ["GET /api/live/views", () => request.get("/api/live/views")],
    ["POST /api/live/views/drafts", () => request.post("/api/live/views/drafts", { data: { layout: "4", tiles: [null, null, null, null] } })],
    ["GET /api/jobs", () => request.get("/api/jobs")],
    ["POST /api/jobs", () => request.post("/api/jobs", { multipart: VIDEO })],
    [`GET /api/jobs/${JOB}`, () => request.get(`/api/jobs/${JOB}`)],
    [`DELETE /api/jobs/${JOB}`, () => request.delete(`/api/jobs/${JOB}`)],
    [`GET /api/jobs/${JOB}/files/counts.csv`, () => request.get(`/api/jobs/${JOB}/files/counts.csv`)],
  ];
  for (const [name, call] of calls) {
    const res = await call();
    expect(res.status(), name).toBe(502);
    expect(await res.json(), name).toEqual(refused);
  }
  // Durum şeridinin ucu vekilden geçmez: 200 ve "auth" kalır
  const system = await request.get("/api/system");
  expect(system.status()).toBe(200);
  expect(await system.json()).toEqual({ analyzer: "auth" });
});

test("erişim anahtarı uyuşmuyor: Canlı izleme metni, alarm şeridi ve durum şeridi söyler; giriş bağlantısı ve 'oturum' yazısı yok", async ({ page }) => {
  await page.goto("/watch");
  await expect(page.getByRole("heading", { name: "Canlı izleme" })).toBeVisible();
  // Durum satırı (Kameralar listesi de aynı metni kendi hata satırında yazar)
  await expect(page.getByRole("status").and(page.getByText(KEY_TEXT, { exact: true }))).toBeVisible();
  // Alarm akışı üst üste 3 hatadan sonra (≈6 sn; beklentinin 15 sn'si içinde) uyarır
  await expect(page.getByTestId("alarm-feed-warning")).toHaveText(`Alarmlar alınamıyor — ${KEY_TEXT}`);
  await expect(page.getByTestId("status-bar")).toContainText("Analiz sunucusu: yetki hatası");
  await expect(page.getByRole("link", { name: "Giriş yap" })).toHaveCount(0);
  await expect(page.getByText("Oturum süresi doldu")).toHaveCount(0);
  await expect(page.getByText("yeniden deneniyor")).toHaveCount(0);
});

test("erişim anahtarı uyuşmuyor: Video ile test iş listesinde ve yüklemede metni gösterir", async ({ page }) => {
  await page.goto("/videos");
  await expect(page.getByRole("heading", { level: 1, name: "Video ile test" })).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: KEY_TEXT })).toBeVisible();
  await page.getByTestId("file-input").setInputFiles({ name: "a.mp4", mimeType: "video/mp4", buffer: Buffer.alloc(16) });
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  await expect(page.getByTestId("upload-error")).toHaveText(KEY_TEXT);
});

test("erişim anahtarı uyuşmuyor: taslak yazımı durmaz, yeniden denenir (panelin 401'i gibi kesilmez)", async ({ page }) => {
  // Düzenleyebilmek için şablon okuma istekleri sahte; taslak isteği gerçek vekile ve gerçek analiz sunucusuna gider
  const layouts = (JSON.parse(readFileSync(path.resolve(__dirname, "../../../contracts/view-layouts.json"), "utf8")) as { layouts: object[] }).layouts;
  const view = { id: "v1", name: "Giriş katı", layout: "4", createdAt: 1, updatedAt: 1, tiles: [{ sourceId: "a", channelId: null }, null, null, null] };
  const status = { id: "v1", layout: "4", tiles: [{ sourceId: "a", channelId: null, name: "Kapı", state: "live", message: "", fps: 10, analysis: null }, null, null, null] };
  await page.route("**/api/live/view-layouts", (r) => r.fulfill({ json: layouts }));
  await page.route("**/api/live/views", (r) => r.fulfill({ json: [view] }));
  await page.route("**/api/live/views/v1/status", (r) => r.fulfill({ json: status }));
  await page.route("**/api/live/views/v1/stream**", (r) => r.fulfill({ status: 404, json: { detail: "Şablon bulunamadı." } }));
  await page.route("**/api/live/sources", (r) => r.fulfill({ json: [{ id: "a", kind: "camera", name: "Kapı", brand: "custom", hasPassword: false }] }));
  const writes: Array<{ status: number; code: unknown }> = [];
  page.on("response", async (res) => {
    if (res.request().method() !== "POST" || new URL(res.url()).pathname !== "/api/live/views/drafts") return;
    const body = (await res.json().catch(() => undefined)) as { code?: unknown } | undefined;
    writes.push({ status: res.status(), code: body?.code });
  });
  await page.goto("/watch");
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  await page.getByRole("button", { name: "Şablon editörü" }).click();
  const editor = page.getByRole("dialog", { name: "Şablon editörü" });
  await editor.getByRole("group", { name: "Düzenler:" }).getByRole("button", { name: /^1\+5:/ }).click();
  await expect(page.getByTestId("watch-tile")).toHaveCount(6);
  await expect.poll(() => writes.length, { timeout: 30_000 }).toBeGreaterThanOrEqual(3);    // 2 sn'de bir yeniden dener
  expect(writes.slice(0, 3)).toEqual(Array(3).fill({ status: 502, code: "analyzer_key" }));
  await expect(page.getByRole("alert").filter({ hasText: KEY_TEXT })).toHaveCount(0);       // sessizce: hata satırı çıkmaz
});

test("şifresiz panel, başka site: API isteği 403 (Origin, null, Sec-Fetch-Site); bu bilgisayarın isteği vekile ulaşır; sayfa açılır", async ({ request }) => {
  const refused = async (res: Awaited<ReturnType<typeof request.get>>, name: string) => {
    expect(res.status(), name).toBe(403);
    expect(await res.json(), name).toEqual(CROSS_SITE);
  };
  const proxied = async (res: Awaited<ReturnType<typeof request.get>>, name: string) => {
    expect(res.status(), name).toBe(502);
    expect(((await res.json()) as { code?: unknown }).code, name).toBe("analyzer_key");
  };
  // Çok parçalı POST ön uçuş gerektirmez: vekil sunucu tarafından, Origin'siz analiz sunucusuna gidip iş açtırırdı
  await refused(await request.post("/api/jobs", { multipart: VIDEO, headers: { Origin: "https://evil.example" } }), "POST yabancı Origin");
  await refused(await request.post("/api/jobs", { multipart: VIDEO, headers: { Origin: "null" } }), "POST Origin null");
  await refused(await request.get("/api/live/views", { headers: { "Sec-Fetch-Site": "cross-site" } }), "GET cross-site");
  await refused(await request.get("/api/system", { headers: { Origin: "https://evil.example" } }), "GET /api/system yabancı Origin");
  await refused(await request.get("/api/live/views", { headers: { Origin: "http://localhost.evil.example:3102", "Sec-Fetch-Site": "same-origin" } }), "benzer ad");

  const own = { Origin: PANEL };
  await proxied(await request.post("/api/jobs", { multipart: VIDEO, headers: own }), "POST kendi Origin");
  await proxied(await request.post("/api/jobs", { multipart: VIDEO }), "POST başlıksız");
  await proxied(await request.get("/api/live/views", { headers: own }), "GET kendi Origin");
  await proxied(await request.get("/api/live/views"), "GET başlıksız");
  await proxied(await request.get("/api/live/views", { headers: { "Sec-Fetch-Site": "same-origin" } }), "GET same-origin");

  // Sayfalar etkilenmez: başka siteden gelen bağlantı paneli açar
  const page = await request.get("/watch", { headers: { "Sec-Fetch-Site": "cross-site" } });
  expect(page.status()).toBe(200);
  expect(page.headers()["content-type"]).toContain("text/html");
});

test.describe("10 MB üstü video", () => {
  let dir = "";
  let big = "";
  test.beforeAll(() => {
    dir = mkdtempSync(path.join(os.tmpdir(), "bv-e2e-klip-"));
    big = paddedClip(path.join(dir, "uzun.mp4"));
  });
  test.afterAll(() => rmSync(dir, { recursive: true, force: true }));

  test("doğru anahtarla 12 MB yüklenir: 202, iş listede (şifreli panel)", async ({ page }) => {
    await page.goto(`${PASSWORD_PANEL}/videos`);
    await page.getByLabel("Şifre").fill("e2e-test-sifresi");
    await page.getByRole("button", { name: "Giriş yap" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Video ile test" })).toBeVisible();
    await page.getByTestId("file-input").setInputFiles(big);
    const answered = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/jobs" && r.request().method() === "POST");
    await page.getByRole("button", { name: "Analizi başlat" }).click();
    const res = await answered;
    expect(res.status()).toBe(202);
    const job = (await res.json()) as { id: string; video: { sizeBytes: number } };
    expect(job.video.sizeBytes).toBe(BIG);
    await expect(page.getByTestId("job-detail")).toContainText("uzun.mp4");
    const del = await page.request.delete(`${PASSWORD_PANEL}/api/jobs/${job.id}`);       // sonraki testler boş liste bekler
    expect(del.status()).toBe(204);
    await expect(page.getByText("Henüz analiz yok")).toBeVisible();
  });

  test("anahtar uyuşmuyorsa 12 MB'ta da 502 + analyzer_key; /videos metni gösterir", async ({ page, request }) => {
    const file = { name: "uzun.mp4", mimeType: "video/mp4", buffer: readFileSync(big) };
    const res = await request.post("/api/jobs", { multipart: { file } });
    expect(res.status()).toBe(502);
    expect(await res.json()).toEqual({ detail: KEY_TEXT, code: "analyzer_key" });
    await page.goto("/videos");
    await page.getByTestId("file-input").setInputFiles(big);
    await page.getByRole("button", { name: "Analizi başlat" }).click();
    await expect(page.getByTestId("upload-error")).toHaveText(KEY_TEXT);
  });
});

test("yükleme bitmeden karar: yanlış anahtar 502 (videoyu beklemez), ret doğru JSON ile gelir", async () => {
  expect(await partialUpload(3102)).toEqual({ status: 502, body: { detail: KEY_TEXT, code: "analyzer_key" } });
  expect(await partialUpload(3102, { Origin: "https://evil.example" })).toEqual({ status: 403, body: CROSS_SITE });
  expect(await partialUpload(3102, { Host: "evil.example" })).toEqual({ status: 403, body: { error: "Geçersiz adres." } });
  expect(await partialUpload(3100)).toEqual({ status: 401, body: { error: "Giriş gerekli." } });
});

test("/api/jobs ara katman dışında ama denetimi atlanmaz: GET ve yol biçimleri", async ({ request }) => {
  const NO_SESSION = JSON.stringify({ error: "Giriş gerekli." });
  const FOREIGN = { Origin: "https://evil.example" };
  // Tam yol: oturumsuz 401, başka site 403, yabancı ad 403
  expect(await raw(3100, "/api/jobs")).toEqual({ status: 401, body: NO_SESSION });
  expect(await raw(3102, "/api/jobs", FOREIGN)).toEqual({ status: 403, body: JSON.stringify(CROSS_SITE) });
  expect(await raw(3102, "/api/jobs", { Host: "evil.example" })).toEqual({ status: 403, body: JSON.stringify({ error: "Geçersiz adres." }) });
  expect((await raw(3102, "/api/jobs")).status).toBe(502);
  // Başka yöntemler de aynı kapıdan geçer; geçince Next'in yanıtıyla aynı (405, OPTIONS 204)
  for (const method of ["PUT", "DELETE", "PATCH", "OPTIONS"]) {
    expect(await raw(3100, "/api/jobs", {}, method), `3100 ${method}`).toEqual({ status: 401, body: NO_SESSION });
    expect(await raw(3102, "/api/jobs", FOREIGN, method), `3102 ${method}`).toEqual({ status: 403, body: JSON.stringify(CROSS_SITE) });
    expect(await raw(3102, "/api/jobs", {}, method), `3102 ${method} geçer`).toEqual({ status: method === "OPTIONS" ? 204 : 405, body: "" });
  }
  // Yol biçimleri hiçbirini atlatmaz. Sorgu ve ara katmanın gördüğü biçimler reddedilir; sondaki ve çift eğik çizgiyi Next
  // tam yola yönlendirir (308), orada yine aynı karar verilir.
  const redirected = { status: 308, body: "/api/jobs" };
  for (const [target, want] of [["/api/jobs?x=1", null], ["/api/jobs%2f", null], ["/api/./jobs", null],
    ["/api/jobs/", redirected], ["//api/jobs", redirected]] as Array<[string, typeof redirected | null]>) {
    expect(await raw(3100, target), `3100 ${target}`).toEqual(want ?? { status: 401, body: NO_SESSION });
    expect(await raw(3102, target, FOREIGN), `3102 ${target}`).toEqual(want ?? { status: 403, body: JSON.stringify(CROSS_SITE) });
  }
  expect(await request.get("/api/jobs/00000000-0000-4000-8000-000000000000", { headers: FOREIGN }).then((r) => r.status())).toBe(403);
});

test("şifreli panel, başka site: kural değişmez, girişsiz API isteği 401", async ({ request }) => {
  const res = await request.get("http://127.0.0.1:3100/api/live/views", { headers: { Origin: "https://evil.example" } });
  expect(res.status()).toBe(401);
  expect(await res.json()).toEqual({ error: "Giriş gerekli." });
});

test("/_next/data/ yolları da API kapısından geçer: başka site, yabancı ad ve oturumsuz istek reddedilir, iş silinmez", async ({ request }) => {
  // Next bu yolları ara katmanda eşler ve API işleyicilerine ulaştırır; `skipMiddlewareUrlNormalize` ile ara katman önekli
  // yolu görür. Öneklenmiş yol `/api/` sanılmayınca sayfa koluna düşer ve kapı atlanırdı. Yapı kimliği derlemeden gelir.
  const build = readFileSync(path.resolve(__dirname, "../.next/BUILD_ID"), "utf8").trim();
  const data = (p: string) => `/_next/data/${build}/api/${p}.json`;
  const KEY = { Authorization: "Bearer e2e-dogru-anahtar" };
  const made = await request.post(`${ANALYZER}/api/v1/jobs`, { headers: KEY, multipart: { file: { name: "a.mp4", mimeType: "video/mp4", buffer: readFileSync(CLIP) } } });
  expect(made.status()).toBe(202);
  const id = ((await made.json()) as { id: string }).id;
  try {
    const FOREIGN = { Origin: "https://evil.example" };
    const crossSite = JSON.stringify(CROSS_SITE);
    const paths = ["live/views", "live/sources", "jobs", `jobs/${id}`, "system", "access"];
    for (const p of paths) {
      expect(await raw(3102, data(p), FOREIGN), `3102 GET ${p} yabancı Origin`).toEqual({ status: 403, body: crossSite });
      expect(await raw(3102, data(p), { "Sec-Fetch-Site": "cross-site" }), `3102 GET ${p} cross-site`).toEqual({ status: 403, body: crossSite });
      expect(await raw(3102, data(p), { Host: "evil.example" }), `3102 GET ${p} yabancı ad`).toEqual({ status: 403, body: JSON.stringify({ error: "Geçersiz adres." }) });
      expect(await raw(3100, data(p)), `3100 GET ${p} oturumsuz`).toEqual({ status: 401, body: JSON.stringify({ error: "Giriş gerekli." }) });
    }
    expect(await raw(3102, data(`jobs/${id}`), FOREIGN, "DELETE")).toEqual({ status: 403, body: crossSite });
    expect(await raw(3100, data(`jobs/${id}`), {}, "DELETE")).toEqual({ status: 401, body: JSON.stringify({ error: "Giriş gerekli." }) });
    expect((await request.get(`${ANALYZER}/api/v1/jobs/${id}`, { headers: KEY })).status()).toBe(200);   // iş yerinde
    // Bu bilgisayarın kendi isteği kapıdan geçer (vekil yanlış anahtarla analiz sunucusuna gider: 502 + analyzer_key)
    const own = await raw(3102, data("live/views"), { Origin: PANEL });
    expect(own.status).toBe(502);
    expect(JSON.parse(own.body).code).toBe("analyzer_key");
  } finally {
    await request.delete(`${ANALYZER}/api/v1/jobs/${id}`, { headers: KEY });
  }
});
