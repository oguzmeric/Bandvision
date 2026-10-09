import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

/**
 * İzleme (gerçek yığın): gerçek analiz sunucusu + derlenmiş panel. "Kamera" olarak uygulamanın test klibi açılır
 * (analiz sunucusu testte ANALYZER_ALLOW_FILE_SOURCES=1). Sahte API ile ayrıntılı arayüz testleri e2e/watch-ui.spec.ts'te.
 */
const CLIP = path.resolve(__dirname, "../../ios/BantSayacUITests/ui_test_clip.mp4");

async function login(page: Page) {
  await page.goto("/cameras");
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("heading", { name: "Kameralar ve kayıt cihazları" })).toBeVisible();
}

test("izleme (gerçek yığın): API ile şablon, birleşik akış gelir, tek kamera akışı gelir", async ({ page }) => {
  await login(page);
  const src = await (await page.request.post("/api/live/sources", { data: {
    kind: "camera", brand: "custom", customUrl: CLIP, name: "İzleme klibi" } })).json();
  const view = await (await page.request.post("/api/live/views", { data: {
    name: "E2E izleme", layout: "2", tiles: [{ sourceId: src.id, channelId: null }, null] } })).json();
  try {
    await page.goto("/watch");
    await page.getByRole("combobox", { name: "Şablon" }).selectOption(view.id);
    await expect.poll(async () => page.getByAltText("E2E izleme canlı görüntü")
      .evaluate((img: HTMLImageElement) => img.naturalWidth), { timeout: 30_000 }).toBeGreaterThan(0);
    await expect(page.getByTestId("watch-tile").first()).toContainText("İzleme klibi");
    await page.getByTestId("watch-tile").first().dblclick();
    await expect.poll(async () => page.getByAltText("İzleme klibi canlı görüntü")
      .evaluate((img: HTMLImageElement) => img.naturalWidth), { timeout: 30_000 }).toBeGreaterThan(0);
  } finally {
    // test düşse de şablon ve kaynak kalmasın (sonraki testler "Henüz kaynak yok" bekleyebilir)
    await page.request.delete(`/api/live/views/${view.id}`);
    await page.request.delete(`/api/live/sources/${src.id}`);
  }
});

test("izleme (gerçek yığın): arayüzden şablon oluştur, akış gelir, sil", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  await login(page);
  const src = await (await page.request.post("/api/live/sources", { data: {
    kind: "camera", brand: "custom", customUrl: CLIP, name: "Düzenleyici klibi" } })).json();
  try {
    await page.goto("/watch");
    await page.getByRole("button", { name: "Yeni şablon" }).click();
    const ed = page.getByRole("region", { name: "Şablon düzenleyici" });
    await ed.getByLabel("Şablon adı").fill("Arayüz şablonu");
    await ed.getByRole("button", { name: "Tek" }).click();
    await ed.getByTestId("edit-tile").first().click();
    await ed.getByRole("button", { name: "Düzenleyici klibi" }).click();
    await ed.getByRole("button", { name: "Kaydet" }).click();
    await expect(page.getByRole("combobox", { name: "Şablon" })).toContainText("Arayüz şablonu");
    await expect.poll(async () => page.getByAltText("Arayüz şablonu canlı görüntü")
      .evaluate((img: HTMLImageElement) => img.naturalWidth), { timeout: 30_000 }).toBeGreaterThan(0);
    await page.getByRole("button", { name: "Düzenle" }).click();
    await page.getByRole("button", { name: "Şablonu sil" }).click();
    await expect(page.getByRole("combobox", { name: "Şablon" })).not.toContainText("Arayüz şablonu");
  } finally {
    // test düşse de kaynak (ve ona bağlı şablon) kalmasın; sonraki testler "Henüz kaynak yok" bekleyebilir
    const views = await (await page.request.get("/api/live/views")).json() as Array<{ id: string; name: string }>;
    for (const v of views.filter((x) => x.name === "Arayüz şablonu")) await page.request.delete(`/api/live/views/${v.id}`);
    await page.request.delete(`/api/live/sources/${src.id}`);
  }
});
