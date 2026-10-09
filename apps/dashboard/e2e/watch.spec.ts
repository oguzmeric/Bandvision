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
  await page.goto("/watch");
  await page.getByRole("combobox", { name: "Şablon" }).selectOption(view.id);
  await expect.poll(async () => page.getByAltText("E2E izleme canlı görüntü")
    .evaluate((img: HTMLImageElement) => img.naturalWidth), { timeout: 30_000 }).toBeGreaterThan(0);
  await expect(page.getByTestId("watch-tile").first()).toContainText("İzleme klibi");
  await page.getByTestId("watch-tile").first().dblclick();
  await expect.poll(async () => page.getByAltText("İzleme klibi canlı görüntü")
    .evaluate((img: HTMLImageElement) => img.naturalWidth), { timeout: 30_000 }).toBeGreaterThan(0);
  await page.request.delete(`/api/live/views/${view.id}`);
  await page.request.delete(`/api/live/sources/${src.id}`);
});
