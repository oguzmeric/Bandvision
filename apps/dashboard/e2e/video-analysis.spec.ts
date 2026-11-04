import { expect, test, type Locator, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/** Uygulamanın uçtan uca test klibi (tools/make_ui_test_clip.py): sayısı bilinen yumurtalar. */
const CLIP = path.resolve(__dirname, "../../ios/BantSayacUITests/ui_test_clip.mp4");
const META = JSON.parse(fs.readFileSync(CLIP.replace(/\.mp4$/, ".json"), "utf-8")) as {
  count: number;
  emptySeconds: number;
};

/** Panel testte şifreli (playwright.config.ts): her test önce giriş yapar. */
async function login(page: Page) {
  await page.goto("/videos");
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Video ile test" })).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  await login(page);
});

test("silme reddedilirse (502 analyzer_key) metin görünür, iş kalır", async ({ page }) => {
  const text = "Analiz sunucusu erişim anahtarı uyuşmuyor — panelde ve analiz sunucusunda aynı ANALYZER_TOKEN ayarlanmalı.";
  const id = "00000000-0000-4000-8000-000000000000";
  const at = "2026-11-02T10:00:00Z";
  const job = { schema: "bantvision.analysis-job.v1", id, status: "failed", createdAt: at, updatedAt: at, expiresAt: at,
    video: { name: "a.mp4", sizeBytes: 16 }, options: {}, progress: 0, error: "Hata." };
  await page.route("**/api/jobs", (r) => r.fulfill({ json: [job] }));
  await page.route(`**/api/jobs/${id}`, (r) => r.fulfill({ status: 502, json: { detail: text, code: "analyzer_key" } }));
  await page.goto("/videos");
  const detail = page.getByTestId("job-detail");
  await expect(detail).toContainText("a.mp4");
  page.once("dialog", (d) => d.accept());
  await detail.getByRole("button", { name: "Sil" }).click();
  await expect(detail.getByRole("alert").filter({ hasText: text })).toBeVisible();
  await expect(detail.getByRole("button", { name: "Sil" })).toBeEnabled();
  await expect(page.getByTestId("job-row")).toHaveCount(1);
  await expect(page.getByRole("link", { name: "Giriş yap" })).toHaveCount(0);        // anahtar sorunu: giriş işe yaramaz
});

test("Cihaz: model kullanan bitmiş işte 'Cihaz' kutusu ve not satırı; cihaz bilgisi olmayan işte kutu yok", async ({ page }) => {
  const at = new Date().toISOString();
  const note = "Ekran kartı çalışırken hata verdi (x); işlemci kullanılıyor.";
  const done = (id: string, name: string, device?: unknown) => ({
    schema: "bantvision.analysis-job.v1", id, status: "done", createdAt: at, updatedAt: at,
    expiresAt: new Date(Date.now() + 7 * 86_400_000).toISOString(), video: { name, sizeBytes: 16 }, options: {},
    progress: 1, result: { count: 3, truth: null, errorPct: null, processingFps: 20, files: [], ...(device ? { device } : {}) },
  });
  const withDevice = done("00000000-0000-4000-8000-0000000000d1", "kisi.mp4", { kind: "gpu", name: "Test GPU", note });
  const without = done("00000000-0000-4000-8000-0000000000d2", "urun.mp4");
  await page.route("**/api/jobs", (r) => r.fulfill({ json: [withDevice, without] }));
  await page.goto("/videos");
  const detail = page.getByTestId("job-detail");
  await page.getByTestId("job-row").filter({ hasText: "kisi.mp4" }).click();
  await expect(detail.getByRole("heading", { name: "kisi.mp4" })).toBeVisible();
  const stat = detail.getByText("Cihaz", { exact: true }).locator("..");
  await expect(stat.locator("b")).toHaveText("Ekran kartı");
  await expect(stat.locator("span")).toHaveText("Test GPU");                       // kartın adı ipucu olarak
  await expect(detail.getByTestId("device-note")).toHaveText(note);

  await page.getByTestId("job-row").filter({ hasText: "urun.mp4" }).click();
  await expect(detail.getByRole("heading", { name: "urun.mp4" })).toBeVisible();
  await expect(detail.getByText("Sayım", { exact: true })).toBeVisible();          // sonuç kutuları çizildi
  await expect(detail.getByText("Cihaz", { exact: true })).toHaveCount(0);
  await expect(detail.getByTestId("device-note")).toHaveCount(0);
});

test("oturum dolunca (panelin kendi 401'i) yükleme, silme ve iş listesi 'oturum doldu' + giriş bağlantısı der; HTTP 401 yazmaz", async ({ page, context, request }) => {
  const AUTH = "Oturum süresi doldu — yeniden giriş yapın.";
  const made = await page.request.post("/api/jobs", { multipart: { file: { name: "ui_test_clip.mp4", mimeType: "video/mp4", buffer: fs.readFileSync(CLIP) } } });
  expect(made.status()).toBe(202);
  const id = ((await made.json()) as { id: string }).id;
  try {
    await page.goto("/videos");
    const detail = page.getByTestId("job-detail");
    await expect(detail).toContainText("ui_test_clip.mp4");
    await context.clearCookies();                                                     // sayfa açıkken oturum doldu
    const link = (where: Locator) => where.getByRole("link", { name: "Giriş yap" });
    const href = "/login?next=%2Fvideos";

    await page.getByTestId("file-input").setInputFiles(CLIP);
    await page.getByRole("button", { name: "Analizi başlat" }).click();
    const upload = page.getByTestId("upload-error");
    await expect(upload).toContainText(AUTH);
    await expect(link(upload)).toHaveAttribute("href", href);

    page.once("dialog", (d) => d.accept());
    await detail.getByRole("button", { name: "Sil" }).click();
    const removal = detail.getByRole("alert");
    await expect(removal).toContainText(AUTH);
    await expect(link(removal)).toHaveAttribute("href", href);

    const list = page.locator("section").filter({ has: page.getByRole("heading", { name: "Son analizler" }) }).getByRole("alert");
    await expect(list).toContainText(AUTH, { timeout: 25_000 });                      // sonraki yoklamada (≤ 15 sn)
    await expect(link(list)).toHaveAttribute("href", href);
    await expect(page.getByText(/HTTP 401/)).toHaveCount(0);

    await link(upload).click();                                                       // bağlantı çalışır: giriş yapınca /videos
    await page.getByLabel("Şifre").fill("e2e-test-sifresi");
    await page.getByRole("button", { name: "Giriş yap" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Video ile test" })).toBeVisible();
    await expect(page.getByTestId("job-detail")).toContainText("ui_test_clip.mp4");   // iş silinmemişti
  } finally {
    await request.delete(`http://127.0.0.1:8091/api/v1/jobs/${id}`);                 // sonraki testler boş liste bekler
  }
});

test("video yükle → analiz → işaretli video, sayım ve CSV; sil", async ({ page }) => {
  await page.goto("/videos");
  await expect(page.getByRole("heading", { level: 1, name: "Video ile test" })).toBeVisible();
  await expect(page.getByText("Henüz analiz yok")).toBeVisible();

  await page.getByTestId("file-input").setInputFiles(CLIP);
  await expect(page.getByText("ui_test_clip.mp4").first()).toBeVisible();
  await page.getByLabel("Ürün", { exact: true }).selectOption("egg");
  await page.getByLabel(/Doğru adet/).fill(String(META.count));
  await page.getByText("Gelişmiş: boş bant aralığı").click();
  await page.getByLabel("Boş bant başlangıcı (saniye)").fill("0");
  await page.getByLabel("Boş bant bitişi (saniye)").fill(String(META.emptySeconds - 0.3).replace(".", ","));
  await page.getByRole("button", { name: "Analizi başlat" }).click();

  // İlerleme görünür, sonra sonuç (Python referansıyla aynı sayı)
  const detail = page.getByTestId("job-detail");
  await expect(detail).toBeVisible();
  await expect(detail.getByText(`${META.count} / ${META.count}`)).toBeVisible({ timeout: 180_000 });
  await expect(detail.getByText("%100,0")).toBeVisible();

  // İşaretli video tarayıcıda oynar (H.264) ve sarılabilir
  const video = page.getByTestId("annotated-video");
  const meta = await video.evaluate(async (el: HTMLVideoElement) => {
    if (el.readyState < 1) await new Promise((r) => el.addEventListener("loadedmetadata", r, { once: true }));
    el.currentTime = 10;
    await new Promise((r) => el.addEventListener("seeked", r, { once: true }));
    return { duration: el.duration, width: el.videoWidth, time: el.currentTime };
  });
  expect(meta.width).toBe(720);
  expect(meta.duration).toBeGreaterThan(17);
  expect(meta.time).toBeCloseTo(10, 0);

  // CSV indirilebilir, sayım satırları içerir
  const href = await detail.getByRole("link", { name: "CSV indir" }).getAttribute("href");
  const csv = await page.request.get(href!);              // oturum çerezi sayfayla ortak
  expect(csv.status()).toBe(200);
  const lines = (await csv.text()).trim().split(/\r?\n/);
  expect(lines[0]).toBe("zaman_sn;iz;delta;toplam");
  expect(Number(lines[lines.length - 1].split(";")[3])).toBe(META.count);

  // Zamana göre sayım grafiği
  await expect(page.getByRole("img", { name: new RegExp(`${META.count} ürün`) })).toBeVisible();

  // Sil
  page.once("dialog", (d) => d.accept());
  await detail.getByRole("button", { name: "Sil" }).click();
  await expect(page.getByText("Henüz analiz yok")).toBeVisible();
});

test("video olmayan dosya anlaşılır hatayla reddedilir", async ({ page }) => {
  await page.goto("/videos");
  await page.getByTestId("file-input").setInputFiles({ name: "notlar.txt", mimeType: "text/plain", buffer: Buffer.from("merhaba") });
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  await expect(page.getByTestId("upload-error")).toContainText("Desteklenmeyen dosya türü");
});

test("doğru adet ve boş bant aralığı doğrulanır", async ({ page }) => {
  await page.goto("/videos");
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  await expect(page.getByTestId("upload-error")).toHaveText("Önce bir video seç.");
  await page.getByTestId("file-input").setInputFiles(CLIP);
  await page.getByText("Gelişmiş: boş bant aralığı").click();
  await page.getByLabel("Boş bant başlangıcı (saniye)").fill("5");
  await page.getByLabel("Boş bant bitişi (saniye)").fill("2");
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  await expect(page.getByTestId("upload-error")).toContainText("Boş bant aralığı");
});

test("un ve koli şerit taramayla gelir; yöntem değiştirilebilir", async ({ page }) => {
  await page.goto("/videos");
  const mode = page.getByLabel("Sayım yöntemi", { exact: true });
  await expect(mode).toHaveValue("blob");                       // yumurta: ayrık ürün
  await page.getByLabel("Ürün", { exact: true }).selectOption("box");
  await expect(mode).toHaveValue("linescan");
  await expect(page.getByText("Boş bant gerekmez")).toBeVisible();
  await page.getByLabel("Ürün", { exact: true }).selectOption("flour");
  await expect(mode).toHaveValue("linescan");
  await mode.selectOption("blob");
  await expect(mode).toHaveValue("blob");
});

// ---- Güvenlik alarmı, araç ve hayvan (sahte iş yanıtlarıyla; gerçek analiz sunucusu gerekmez) ----

/** 1×1 resim: alarm küçük resmi yerine (PNG; tarayıcı türü içeriğinden anlar, bu yüzden JPEG diye sunmak yeter) */
const PIXEL = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");
const SAFETY_ID = "00000000-0000-4000-8000-0000000005a1";
const AT = "2026-11-04T09:10:00Z";

type MockAlarm = { kind: string; trackId: number; startS: number; atS: number; endS: number | null; image: string | null };

function mockJob(id: string, over: Record<string, unknown>) {
  return {
    schema: "bantvision.analysis-job.v1", id, status: "done", createdAt: new Date().toISOString(), updatedAt: AT,
    expiresAt: new Date(Date.now() + 7 * 86_400_000).toISOString(), progress: 1,
    video: { name: "kamera.mp4", sizeBytes: 1024, seconds: 18, fps: 25, width: 720, height: 480 }, ...over,
  };
}

function safetyJob(name: string, alarms: MockAlarm[], files: string[], id = SAFETY_ID, status = "done") {
  return mockJob(id, {
    status,
    video: { name, sizeBytes: 1024, seconds: 18, fps: 25, width: 720, height: 480 },
    options: { preset: "safety", safety: { handsUp: { enabled: true, seconds: 3 }, lying: { enabled: true, seconds: 10 } } },
    result: { count: alarms.length, truth: null, errorPct: null, calibration: {}, processingFps: 14.8,
              device: { kind: "gpu", name: "Test GPU", note: null }, alarms, files },
  });
}

/** İşaretli video yerine gerçek bir H.264 klibi sunar; Range desteği olmadan tarayıcı sarmaz. `videoDelayMs`: yanıtı geciktirir */
async function serveFiles(page: Page, id: string, videoDelayMs = 0) {
  const clip = fs.readFileSync(CLIP);
  await page.route(`**/api/jobs/${id}/files/annotated.mp4`, async (r) => {
    if (videoDelayMs) await new Promise((done) => setTimeout(done, videoDelayMs));   // video henüz yüklenmedi (readyState 0)
    const m = /bytes=(\d+)-(\d*)/.exec(r.request().headers()["range"] ?? "");
    const start = m ? Number(m[1]) : 0;
    const end = m && m[2] ? Math.min(Number(m[2]), clip.length - 1) : clip.length - 1;
    return r.fulfill({
      status: m ? 206 : 200, contentType: "video/mp4", body: clip.subarray(start, end + 1),
      headers: { "accept-ranges": "bytes", ...(m ? { "content-range": `bytes ${start}-${end}/${clip.length}` } : {}) },
    });
  });
  await page.route(`**/api/jobs/${id}/files/alarm-*.jpg`, (r) => r.fulfill({ contentType: "image/jpeg", body: PIXEL }));
}

test("güvenlik işi: Alarm kutusu, alarm tablosu (saat, tür, süre, küçük resim) ve CSV bağlantısı; sayım kutuları yok", async ({ page }) => {
  const alarms: MockAlarm[] = [
    { kind: "handsUp", trackId: 3, startS: 12.4, atS: 15.4, endS: 19.0, image: "alarm-1.jpg" },
    { kind: "lying", trackId: 5, startS: 61, atS: 71, endS: 95, image: "alarm-2.jpg" },
    { kind: "lying", trackId: 7, startS: 100.2, atS: 110.2, endS: null, image: null },
  ];
  const files = ["annotated.mp4", "alarms.csv", "profile.json", "alarm-1.jpg", "alarm-2.jpg"];
  await page.route("**/api/jobs", (r) => r.fulfill({ json: [safetyJob("kuyumcu.mp4", alarms, files)] }));
  await serveFiles(page, SAFETY_ID);
  await page.goto("/videos");
  const detail = page.getByTestId("job-detail");
  await expect(detail.getByRole("heading", { name: "kuyumcu.mp4" })).toBeVisible();
  await expect(detail).toContainText("Güvenlik alarmı (poz) profili");

  // Sayım kutuları yerine Alarm / İşleme hızı / Cihaz
  const stat = detail.getByText("Alarm", { exact: true }).locator("..");
  await expect(stat.locator("b")).toHaveText("3");
  await expect(detail.getByText("İşleme hızı", { exact: true })).toBeVisible();
  await expect(detail.getByText("Cihaz", { exact: true })).toBeVisible();
  for (const gone of ["Doğruluk", "Giriş", "Çıkış", "Doğru adet", "Sayım", "Yöntem"]) {
    await expect(detail.getByText(gone, { exact: true })).toHaveCount(0);
  }

  // Tablo: başlıklar ve satırlar
  const table = detail.getByTestId("alarm-table");
  await expect(table.getByRole("columnheader")).toHaveText(["Başlangıç", "Tür", "Süre", "Resim"]);
  const rows = detail.getByTestId("alarm-row");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0).getByRole("cell")).toHaveText(["00:12", "Eller yukarı", "7 sn", ""]);
  await expect(rows.nth(0).getByRole("button", { name: "Videoda 00:12 anına git (Eller yukarı)" })).toBeVisible();
  await expect(rows.nth(1).getByRole("button", { name: "Videoda 01:01 anına git (Yerde yatan kişi)" })).toBeVisible();
  await expect(rows.nth(1).getByRole("cell")).toHaveText(["01:01", "Yerde yatan kişi", "34 sn", ""]);
  await expect(rows.nth(2).getByRole("cell")).toHaveText(["01:40", "Yerde yatan kişi", "—", "—"]);   // bitişi ve resmi yok

  // Küçük resim: işin dosya yolundan, gerçekten yüklenir; resimsiz satırda resim yok
  const thumb = rows.nth(0).locator("img");
  await expect(thumb).toHaveAttribute("src", `/api/jobs/${SAFETY_ID}/files/alarm-1.jpg`);
  await expect.poll(() => thumb.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0);
  await expect(rows.nth(1).locator("img")).toHaveAttribute("src", `/api/jobs/${SAFETY_ID}/files/alarm-2.jpg`);
  await expect(rows.nth(2).locator("img")).toHaveCount(0);

  // CSV bağlantısı yalnız files'ta listeliyse
  await expect(detail.getByRole("link", { name: "Alarm CSV indir", exact: true })).toHaveAttribute("href", `/api/jobs/${SAFETY_ID}/files/alarms.csv`);
  await expect(detail.getByRole("link", { name: "Profili indir" })).toBeVisible();
  await expect(detail.getByText("Bu videoda alarm yok.")).toHaveCount(0);
  await expect(detail.getByText("Zamana göre sayım")).toHaveCount(0);
});

test("güvenlik işi: satıra tıklamak işaretli videoyu alarmın başlangıcına sarar ve oynatır", async ({ page }) => {
  const alarms: MockAlarm[] = [
    { kind: "handsUp", trackId: 3, startS: 4.2, atS: 7.2, endS: 9, image: "alarm-1.jpg" },
    { kind: "lying", trackId: 5, startS: 11.8, atS: 21.8, endS: 17, image: null },
  ];
  await page.route("**/api/jobs", (r) => r.fulfill({ json: [safetyJob("kuyumcu.mp4", alarms, ["annotated.mp4", "alarms.csv", "alarm-1.jpg"])] }));
  await serveFiles(page, SAFETY_ID);
  await page.goto("/videos");
  const video = page.getByTestId("annotated-video");
  await expect.poll(() => video.evaluate((el: HTMLVideoElement) => el.readyState)).toBeGreaterThanOrEqual(1);

  const rows = page.getByTestId("alarm-row");
  await rows.nth(1).click();
  await expect.poll(() => video.evaluate((el: HTMLVideoElement) => el.currentTime)).toBeGreaterThanOrEqual(11.8);
  expect(await video.evaluate((el: HTMLVideoElement) => el.currentTime)).toBeLessThan(14);
  await expect.poll(() => video.evaluate((el: HTMLVideoElement) => !el.paused)).toBe(true);

  await video.evaluate((el: HTMLVideoElement) => el.pause());
  await rows.nth(0).click();                                                     // başka alarm: yine başlangıcına
  await expect.poll(() => video.evaluate((el: HTMLVideoElement) => el.currentTime)).toBeGreaterThanOrEqual(4.2);
  expect(await video.evaluate((el: HTMLVideoElement) => el.currentTime)).toBeLessThan(7);
  await expect.poll(() => video.evaluate((el: HTMLVideoElement) => !el.paused)).toBe(true);
});

test("güvenlik işi: alarm yoksa 'Bu videoda alarm yok.'; süresi dolunca resim yerine — ve satır tıklanamaz", async ({ page }) => {
  const empty = safetyJob("bos.mp4", [], ["annotated.mp4", "alarms.csv", "profile.json"], "00000000-0000-4000-8000-0000000005a2");
  const expired = safetyJob("eski.mp4", [{ kind: "handsUp", trackId: 1, startS: 3, atS: 6, endS: 8, image: null }], [],
                            "00000000-0000-4000-8000-0000000005a3", "expired");
  await page.route("**/api/jobs", (r) => r.fulfill({ json: [empty, expired] }));
  await page.goto("/videos");
  const detail = page.getByTestId("job-detail");

  await page.getByTestId("job-row").filter({ hasText: "bos.mp4" }).click();
  await expect(detail.getByRole("heading", { name: "bos.mp4" })).toBeVisible();
  await expect(detail.getByText("Bu videoda alarm yok.")).toBeVisible();
  await expect(detail.getByTestId("alarm-table")).toHaveCount(0);
  await expect(detail.getByText("Alarm", { exact: true }).locator("..").locator("b")).toHaveText("0");

  await page.getByTestId("job-row").filter({ hasText: "eski.mp4" }).click();
  await expect(detail.getByRole("heading", { name: "eski.mp4" })).toBeVisible();
  await expect(detail.getByText("Saklama süresi doldu")).toBeVisible();
  const row = detail.getByTestId("alarm-row");
  await expect(row).toHaveCount(1);                                              // liste kalır
  await expect(row.getByRole("cell")).toHaveText(["00:03", "Eller yukarı", "5 sn", "—"]);
  await expect(row.locator("img")).toHaveCount(0);
  await expect(row.getByRole("button")).toHaveCount(0);                          // video yok: sarılacak yer yok
  await expect(detail.getByRole("link", { name: "Alarm CSV indir" })).toHaveCount(0);
});

test("güvenlik işi: 120 alarm kaydırılabilir kutuda durur (sayfa uzamaz), sayı 120", async ({ page }) => {
  const alarms: MockAlarm[] = Array.from({ length: 120 }, (_, i) => ({
    kind: i % 2 ? "lying" : "handsUp", trackId: i + 1, startS: i * 0.1, atS: i * 0.1 + 3, endS: i * 0.1 + 9,
    image: i < 50 ? `alarm-${i + 1}.jpg` : null,
  }));
  const files = ["annotated.mp4", "alarms.csv", ...alarms.flatMap((a) => (a.image ? [a.image] : []))];
  await page.route("**/api/jobs", (r) => r.fulfill({ json: [safetyJob("cok.mp4", alarms, files)] }));
  await serveFiles(page, SAFETY_ID);
  await page.goto("/videos");
  const detail = page.getByTestId("job-detail");
  await expect(detail.getByTestId("alarm-row")).toHaveCount(120);
  await expect(detail.getByText("Alarm", { exact: true }).locator("..").locator("b")).toHaveText("120");
  const box = detail.getByTestId("alarm-scroll");
  const m = await box.evaluate((el) => ({ client: el.clientHeight, scroll: el.scrollHeight, overflowY: getComputedStyle(el).overflowY }));
  expect(m.overflowY).toBe("auto");
  expect(m.client).toBeLessThanOrEqual(480);
  expect(m.scroll).toBeGreaterThan(m.client * 2);
  await expect(detail.getByTestId("alarm-row").nth(119).locator("img")).toHaveCount(0);   // 51. alarmdan sonra resim yok
});

test("araç ve hayvan işleri kişi gibi Giriş / Çıkış gösterir; iş başlığında ön ayar adı", async ({ page }) => {
  const mk = (id: string, name: string, preset: string, count: number, out: number, truth: number | null) =>
    mockJob(id, { video: { name, sizeBytes: 1024, seconds: 18 }, options: { preset, ...(truth ? { truth } : {}) },
      result: { count, countOut: out, truth, errorPct: truth ? 0 : null, calibration: { countMode: "detect", direction: "down" },
                processingFps: 12, files: [] } });
  const vehicle = mk("00000000-0000-4000-8000-0000000005b1", "yol.mp4", "vehicle", 7, 4, null);
  const animal = mk("00000000-0000-4000-8000-0000000005b2", "ahir.mp4", "animal", 5, 2, 5);
  await page.route("**/api/jobs", (r) => r.fulfill({ json: [vehicle, animal] }));
  await page.goto("/videos");
  const detail = page.getByTestId("job-detail");

  await page.getByTestId("job-row").filter({ hasText: "yol.mp4" }).click();
  await expect(detail.getByRole("heading", { name: "yol.mp4" })).toBeVisible();
  await expect(detail).toContainText("Araç (giriş / çıkış) profili");
  await expect(detail.getByText("Giriş", { exact: true }).locator("..").locator("b")).toHaveText("7");
  await expect(detail.getByText("Çıkış", { exact: true }).locator("..").locator("b")).toHaveText("4");
  await expect(detail.getByText("Alarm", { exact: true })).toHaveCount(0);
  await expect(page.getByTestId("job-row").filter({ hasText: "yol.mp4" })).toContainText("7 giriş · 4 çıkış");

  await page.getByTestId("job-row").filter({ hasText: "ahir.mp4" }).click();
  await expect(detail.getByRole("heading", { name: "ahir.mp4" })).toBeVisible();
  await expect(detail).toContainText("Hayvan (giriş / çıkış) profili");
  await expect(detail.getByText("Giriş", { exact: true }).locator("..").locator("b")).toHaveText("5");
  await expect(detail.getByText("Çıkış", { exact: true }).locator("..").locator("b")).toHaveText("2");
});

/** POST /api/jobs isteklerini yakalar (liste GET'ine boş liste, POST'a 202 + sahte iş döner) */
async function captureUploads(page: Page) {
  const sent: { options: Record<string, unknown>; name: string }[] = [];
  await page.route("**/api/jobs", async (r) => {
    const req = r.request();
    if (req.method() !== "POST") return r.fulfill({ json: [] });
    const body = req.postDataBuffer()?.toString("latin1") ?? "";
    const options = JSON.parse(/name="options"\r\n\r\n([\s\S]*?)\r\n--/.exec(body)![1]) as Record<string, unknown>;
    sent.push({ options, name: /filename="([^"]*)"/.exec(body)![1] });
    return r.fulfill({ status: 202, json: mockJob("00000000-0000-4000-8000-0000000005c1", { status: "queued", progress: 0, options }) });
  });
  return sent;
}

test("yükleme formu: Güvenlik alarmı sayım alanlarını gizler, kuralları gösterir ve doğru options gönderir", async ({ page }) => {
  const sent = await captureUploads(page);
  await page.goto("/videos");
  await page.getByTestId("file-input").setInputFiles(CLIP);
  const preset = page.getByLabel("Ürün", { exact: true });
  await expect(preset.locator("option")).toContainText(["Yumurta", "Un torbası", "Koli / kutu", "Genel ürün", "Kişi (mağaza girişi)",
    "Araç (giriş / çıkış)", "Hayvan (giriş / çıkış)", "Güvenlik alarmı (poz)"]);
  await preset.selectOption("safety");

  // sayım alanları yok
  for (const label of [/Doğru adet/, /Doğru giriş/, "Giriş yönü", "Akış yönü", "Sayım yöntemi", "Kamera konumu", "Boş bant başlangıcı (saniye)"]) {
    await expect(page.getByLabel(label)).toHaveCount(0);
  }
  await expect(page.getByText("Alan ve sayım çizgisi")).toHaveCount(0);
  await expect(page.getByText("Gelişmiş: boş bant aralığı")).toHaveCount(0);
  await expect(page.getByText("Doğru adeti yazarsan")).toHaveCount(0);
  // kurallar ve yardım metni
  await expect(page.getByText("Videodaki herkese uygulanır; canlıdaki güvenlik kamerasıyla aynı kurallar ve aynı analiz.")).toBeVisible();
  const hu = page.getByLabel("Eller yukarı süresi (sn)"), ly = page.getByLabel("Yerde yatan kişi süresi (sn)");
  await expect(page.getByRole("checkbox", { name: "Eller yukarı" })).toBeChecked();
  await expect(page.getByRole("checkbox", { name: "Yerde yatan kişi" })).toBeChecked();
  await expect(hu).toHaveValue("3");
  await expect(ly).toHaveValue("10");

  // aralık dışı süre: istek gitmez, sunucudakiyle aynı metin
  await hu.fill("6");
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  await expect(page.getByTestId("upload-error")).toHaveText("Eller yukarı süresi 3–5 sn arasında bir sayı olmalı.");
  await hu.fill("4,5");
  await ly.fill("4");
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  await expect(page.getByTestId("upload-error")).toHaveText("Yerde yatma süresi 5–30 sn arasında bir sayı olmalı.");
  // iki kural da kapalı
  await page.getByRole("checkbox", { name: "Eller yukarı" }).uncheck();
  await page.getByRole("checkbox", { name: "Yerde yatan kişi" }).uncheck();
  await expect(hu).toBeDisabled();
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  await expect(page.getByTestId("upload-error")).toHaveText("En az bir kural açık olmalı.");
  expect(sent).toHaveLength(0);

  // geçerli: yatan kişi 12 sn, eller yukarı kapalı
  await page.getByRole("checkbox", { name: "Yerde yatan kişi" }).check();
  await ly.fill("12");
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0].options).toEqual({ preset: "safety", safety: { handsUp: { enabled: false }, lying: { enabled: true, seconds: 12 } } });
  expect(sent[0].name).toBe("ui_test_clip.mp4");
});

test("yükleme formu: güvenliğe geçmeden yazılan sayım değerleri güvenlik isteğine sızmaz; geri dönünce alanlar yeniden görünür", async ({ page }) => {
  const sent = await captureUploads(page);
  await page.goto("/videos");
  await page.getByTestId("file-input").setInputFiles(CLIP);
  const preset = page.getByLabel("Ürün", { exact: true });
  await page.getByLabel(/Doğru adet/).fill("9");                                  // yumurta iken yazılan değer
  await page.getByLabel("Akış yönü").selectOption("left");
  await preset.selectOption("safety");
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0].options).toEqual({ preset: "safety", safety: { handsUp: { enabled: true, seconds: 3 }, lying: { enabled: true, seconds: 10 } } });
  await preset.selectOption("egg");                                               // geri dönünce sayım alanları yeniden görünür
  await expect(page.getByLabel(/Doğru adet/)).toBeVisible();
  await expect(page.getByText("Alan ve sayım çizgisi")).toBeVisible();
});

test("yükleme formu: Araç ve Hayvan kişi formunu kullanır (giriş yönü, kamera, Doğru giriş) ve preset ile gönderir", async ({ page }) => {
  const sent = await captureUploads(page);
  await page.goto("/videos");
  const preset = page.getByLabel("Ürün", { exact: true });
  for (const [value, label] of [["vehicle", "Araç (giriş / çıkış)"], ["animal", "Hayvan (giriş / çıkış)"]] as const) {
    await page.getByTestId("file-input").setInputFiles(CLIP);
    await preset.selectOption(value);
    await expect(preset.locator("option:checked")).toHaveText(label);
    await expect(page.getByLabel("Kamera konumu")).toBeVisible();
    await expect(page.getByLabel("Giriş yönü")).toBeVisible();
    await expect(page.getByLabel(/Doğru giriş/)).toBeVisible();
    await expect(page.getByLabel("Sayım yöntemi")).toHaveCount(0);
    await expect(page.getByText("Gelişmiş: boş bant aralığı")).toHaveCount(0);
    await expect(page.getByRole("checkbox")).toHaveCount(0);                      // güvenlik kuralları burada yok
    await page.getByLabel(/Doğru giriş/).fill("8");
    await page.getByRole("button", { name: "Analizi başlat" }).click();
    await expect.poll(() => sent.length).toBe(value === "vehicle" ? 1 : 2);
    expect(sent[sent.length - 1].options).toEqual({ preset: value, truth: 8, countAnchor: "center" });
  }
});

test("dosya vekili: alarms.csv ve alarm-N.jpg analiz sunucusuna iletilir; başka adlar vekilde reddedilir", async ({ page }) => {
  const id = "00000000-0000-4000-8000-0000000005d1";          // olmayan iş: iletilen ad analiz sunucusundan "İş bulunamadı." alır
  const get = async (name: string) => {
    const res = await page.request.get(`/api/jobs/${id}/files/${name}`);
    return { status: res.status(), detail: ((await res.json()) as { detail: string }).detail };
  };
  for (const ok of ["alarms.csv", "alarm-1.jpg", "alarm-50.jpg", "counts.csv"]) {
    expect(await get(ok), ok).toEqual({ status: 404, detail: "İş bulunamadı." });
  }
  for (const bad of ["alarm-100.jpg", "alarm-1.jpg.exe", "ALARM-1.JPG", "alarm-1.jpg%20", "alarm-1.jpg.", "alarm-.jpg", "job.json"]) {
    expect(await get(bad), bad).toEqual({ status: 404, detail: "Dosya bulunamadı." });
  }
});

// ---- İnceleme turu: sarma, uzun liste notu, aşama ve ipucu metinleri, yönerge, form geçişi ----

test("güvenlik işi: video yüklenmeden (readyState 0) tıklanırsa sarma metadata gelince yapılır", async ({ page }) => {
  const alarms: MockAlarm[] = [{ kind: "lying", trackId: 5, startS: 11.8, atS: 21.8, endS: 17, image: null }];
  await page.route("**/api/jobs", (r) => r.fulfill({ json: [safetyJob("kuyumcu.mp4", alarms, ["annotated.mp4", "alarms.csv"])] }));
  await serveFiles(page, SAFETY_ID, 2500);                                       // video yanıtı geciktirilir: tıklama anında süre bilinmez
  await page.goto("/videos");
  const video = page.getByTestId("annotated-video");
  const row = page.getByTestId("alarm-row");
  await expect(row).toHaveCount(1);
  expect(await video.evaluate((el: HTMLVideoElement) => el.readyState)).toBe(0);
  await row.click();
  await expect.poll(() => video.evaluate((el: HTMLVideoElement) => el.readyState), { timeout: 20_000 }).toBeGreaterThanOrEqual(1);
  await expect.poll(() => video.evaluate((el: HTMLVideoElement) => el.currentTime), { timeout: 20_000 }).toBeGreaterThanOrEqual(11.8);
  expect(await video.evaluate((el: HTMLVideoElement) => el.currentTime)).toBeLessThan(15);
  await expect.poll(() => video.evaluate((el: HTMLVideoElement) => !el.paused)).toBe(true);
});

test("güvenlik işi: dar ekranda video görünür alanın dışındaysa satıra tıklayınca görünür alana gelir", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 360 });
  const alarms: MockAlarm[] = Array.from({ length: 12 }, (_, i) => ({
    kind: "handsUp", trackId: i + 1, startS: i + 1, atS: i + 4, endS: i + 8, image: null }));
  await page.route("**/api/jobs", (r) => r.fulfill({ json: [safetyJob("kuyumcu.mp4", alarms, ["annotated.mp4", "alarms.csv"])] }));
  await serveFiles(page, SAFETY_ID);
  await page.goto("/videos");
  const video = page.getByTestId("annotated-video");
  const row = page.getByTestId("alarm-row").nth(11);
  await row.scrollIntoViewIfNeeded();
  const inView = () => video.evaluate((el) => {
    const b = el.getBoundingClientRect();
    return b.bottom > 0 && b.top < window.innerHeight;
  });
  expect(await inView()).toBe(false);                                            // tablodayken video yukarıda kaldı
  await row.click();
  await expect.poll(inView).toBe(true);
});

test("güvenlik işi: toplam 600, liste 500 satır: 'Listede ilk 500 alarm gösteriliyor; toplam 600.' ve resim notu", async ({ page }) => {
  const alarms: MockAlarm[] = Array.from({ length: 500 }, (_, i) => ({
    kind: "handsUp", trackId: i + 1, startS: i * 0.1, atS: i * 0.1 + 3, endS: i * 0.1 + 9, image: null }));
  const job = safetyJob("cok.mp4", alarms, ["annotated.mp4", "alarms.csv"]);
  (job as unknown as { result: { count: number } }).result.count = 600;
  await page.route("**/api/jobs", (r) => r.fulfill({ json: [job] }));
  await page.goto("/videos");
  const detail = page.getByTestId("job-detail");
  await expect(detail.getByTestId("alarm-row")).toHaveCount(500);
  await expect(detail.getByText("Alarm", { exact: true }).locator("..").locator("b")).toHaveText("600");
  await expect(detail.getByText("Listede ilk 500 alarm gösteriliyor; toplam 600.")).toBeVisible();
  await expect(detail.getByText("Resimler yalnızca ilk 50 alarm için kaydedilir.")).toBeVisible();
});

test("sürmekte olan iş: güvenlikte 'Hazırlanıyor' / 'Alarm analizi', sayımda 'Kalibrasyon' / 'Sayılıyor' (ayrıntı ve liste)", async ({ page }) => {
  const running = (id: string, name: string, preset: string, stage: string) =>
    mockJob(id, { status: "running", progress: 0.3, stage, video: { name, sizeBytes: 1024 }, options: { preset } });
  const jobs = [
    running("00000000-0000-4000-8000-0000000005e1", "g1.mp4", "safety", "calibrating"),
    running("00000000-0000-4000-8000-0000000005e2", "g2.mp4", "safety", "counting"),
    running("00000000-0000-4000-8000-0000000005e3", "u1.mp4", "egg", "calibrating"),
    running("00000000-0000-4000-8000-0000000005e4", "u2.mp4", "people", "counting"),
  ];
  await page.route("**/api/jobs", (r) => r.fulfill({ json: jobs }));
  await page.goto("/videos");
  const detail = page.getByTestId("job-detail");
  const pick = (name: string) => page.getByTestId("job-row").filter({ hasText: name });
  for (const [name, longText, shortText] of [
    ["g1.mp4", "Hazırlanıyor", "Hazırlanıyor · %30"],
    ["g2.mp4", "Alarm analizi", "Alarm analizi · %30"],
    ["u1.mp4", "Kalibrasyon: arka plan, eşik ve ürün boyu öğreniliyor", "Kalibrasyon · %30"],
    ["u2.mp4", "Sayılıyor", "Sayılıyor · %30"],
  ] as const) {
    await expect(pick(name)).toContainText(shortText);
    await pick(name).click();
    await expect(detail.getByRole("heading", { name })).toBeVisible();
    await expect(detail.getByText(longText, { exact: true })).toBeVisible();
  }
});

test("başarısız iş ipucu: güvenlikte ve iki yönlü sayımda bant tavsiyesi yok; bant sayımında var", async ({ page }) => {
  const failed = (id: string, name: string, preset: string) =>
    mockJob(id, { status: "failed", progress: 0, video: { name, sizeBytes: 1024 }, options: { preset }, error: "Hata." });
  const jobs = [
    failed("00000000-0000-4000-8000-0000000005f1", "g.mp4", "safety"),
    failed("00000000-0000-4000-8000-0000000005f2", "a.mp4", "vehicle"),
    failed("00000000-0000-4000-8000-0000000005f3", "h.mp4", "animal"),
    failed("00000000-0000-4000-8000-0000000005f4", "k.mp4", "people"),
    failed("00000000-0000-4000-8000-0000000005f5", "u.mp4", "egg"),
  ];
  await page.route("**/api/jobs", (r) => r.fulfill({ json: jobs }));
  await page.goto("/videos");
  const alert = page.getByTestId("job-detail").getByRole("alert");
  for (const [name, has, hasNot] of [
    ["g.mp4", "karedeki kişiler net görünmeli", /bant/i],
    ["a.mp4", "sayılacak araçlar karede net görünmeli", /bant/i],
    ["h.mp4", "sayılacak hayvanlar karede net görünmeli", /bant/i],
    ["k.mp4", "sayılacak kişiler karede net görünmeli", /bant/i],
    ["u.mp4", "bandın tepesinden çekilmiş olmalı", /(?!)/],
  ] as const) {
    await page.getByTestId("job-row").filter({ hasText: name }).click();
    await expect(page.getByTestId("job-detail").getByRole("heading", { name })).toBeVisible();
    await expect(alert).toContainText(has);
    await expect(alert).not.toContainText(hasNot);
  }
});

test("geometri penceresi yönergesi ön ayara göre: kişi, araç, hayvan", async ({ page }) => {
  await page.route("**/api/jobs", (r) => r.fulfill({ json: [] }));
  await page.goto("/videos");
  await page.getByTestId("file-input").setInputFiles(CLIP);
  const preset = page.getByLabel("Ürün", { exact: true });
  for (const [value, text] of [
    ["people", "Çizgiyi kişilerin tamamen geçtiği yere, yürüme alanının ortasına koy"],
    ["vehicle", "Çizgiyi araçların tamamen geçtiği yere, geçiş alanının ortasına koy"],
    ["animal", "Çizgiyi hayvanların tamamen geçtiği yere, geçiş alanının ortasına koy"],
  ] as const) {
    await preset.selectOption(value);
    await page.getByRole("button", { name: "Ayarla", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText(text);
    await dialog.getByRole("button", { name: "Vazgeç" }).click();
    await expect(dialog).toHaveCount(0);
  }
});

test("yükleme formu: güvenlikte kural değiştirip araca geçince istekte safety yok", async ({ page }) => {
  const sent = await captureUploads(page);
  await page.goto("/videos");
  await page.getByTestId("file-input").setInputFiles(CLIP);
  const preset = page.getByLabel("Ürün", { exact: true });
  await preset.selectOption("safety");
  await page.getByLabel("Yerde yatan kişi süresi (sn)").fill("12");
  await page.getByRole("checkbox", { name: "Eller yukarı" }).uncheck();
  await preset.selectOption("vehicle");
  await expect(page.getByRole("checkbox")).toHaveCount(0);
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0].options).toEqual({ preset: "vehicle", countAnchor: "center" });
  expect(Object.keys(sent[0].options)).not.toContain("safety");
});
