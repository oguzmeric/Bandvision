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
