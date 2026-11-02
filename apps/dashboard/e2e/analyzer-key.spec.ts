import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
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

test.use({ baseURL: PANEL });

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
    writes.push({ status: res.status(), code: ((await res.json()) as { code?: unknown }).code });
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

test("şifreli panel, başka site: kural değişmez, girişsiz API isteği 401", async ({ request }) => {
  const res = await request.get("http://127.0.0.1:3100/api/live/views", { headers: { Origin: "https://evil.example" } });
  expect(res.status()).toBe(401);
  expect(await res.json()).toEqual({ error: "Giriş gerekli." });
});
