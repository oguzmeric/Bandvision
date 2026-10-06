import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

/**
 * Canlı sayım: kamera ekle → canlı sayımı başlat → işaretli akış, sayım düğmeleri, kalibrasyon → kapat → sil.
 * "Kamera" olarak uygulamanın test klibi açılır (analiz sunucusu testte ANALYZER_ALLOW_FILE_SOURCES=1).
 */
const CLIP = path.resolve(__dirname, "../../ios/BantSayacUITests/ui_test_clip.mp4");

async function login(page: Page) {
  await page.goto("/cameras");
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("heading", { name: "Kameralar ve kayıt cihazları" })).toBeVisible();
}

/** <img> yüklendi ve gerçekten görüntü içeriyor mu (MJPEG akışında ilk kare gelince genişlik > 0). */
async function imageWidth(page: Page, alt: string): Promise<number> {
  return page.getByAltText(alt).evaluate((img: HTMLImageElement) => img.naturalWidth);
}

test("canlı sayım: kamera ekle, başlat, say, kalibrasyon, kapat", async ({ page }) => {
  page.on("dialog", (d) => d.accept());                      // "kapatılsın mı?" / "silinsin mi?" onayları
  await login(page);
  await expect(page.getByText("Henüz kaynak yok")).toBeVisible();

  // Kenar çubuğu: canlı sayım ve kameralar açık (yakında değil)
  await expect(page.getByRole("link", { name: "Canlı sayım" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Kameralar" })).toBeVisible();

  // IP kamera (özel RTSP adresi yerine test klibi)
  await page.getByRole("radio", { name: "IP kamera" }).click();
  await page.getByLabel("Kamera markası").selectOption("custom");
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect(page.getByText("RTSP adresini yaz.")).toBeVisible();     // boş adres reddedilir
  await page.getByLabel("RTSP adresi").fill(CLIP);
  await page.getByRole("textbox", { name: /^Ad/ }).fill("Test bandı");
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();

  const card = page.getByTestId("source-card").filter({ hasText: "Test bandı" });
  await expect(card).toBeVisible();
  await expect.poll(() => imageWidth(page, "Test bandı"), { timeout: 20_000 }).toBeGreaterThan(0);  // küçük resim

  // Ne sayılacağını seç → başlat → canlı sayfa
  await card.getByRole("button", { name: "Canlı sayım" }).click();
  const dialog = page.getByRole("dialog", { name: "Canlı sayımı başlat" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Kişi sayımı")).toBeVisible();
  await dialog.getByRole("button", { name: /^Yumurta/ }).click();
  await dialog.getByRole("button", { name: "Başlat", exact: true }).click();

  await expect(page).toHaveURL(/\/live\?s=/);
  await expect(page.getByTestId("live-state")).toContainText("Canlı", { timeout: 30_000 });
  await expect.poll(() => imageWidth(page, "İşaretli canlı görüntü"), { timeout: 20_000 }).toBeGreaterThan(0);
  await expect(page.getByTestId("live-count")).toHaveText("0");

  // Sayımı başlat/durdur
  const counting = page.getByRole("region", { name: "Sayım" });
  await counting.getByRole("button", { name: "Başlat", exact: true }).click();
  await expect(counting.getByRole("button", { name: "Durdur" })).toBeVisible();
  await expect(page.getByText("Sayım duruyor")).toBeHidden();
  await counting.getByRole("button", { name: "Durdur" }).click();
  await expect(page.getByText("Sayım duruyor")).toBeVisible();

  // Kalibrasyon: alan düzenleyici ham kare üstünde açılır; iptal edince akışa döner
  await counting.getByRole("button", { name: "Kalibre" }).click();
  const calib = page.getByRole("region", { name: "Kalibrasyon" });
  await expect(calib).toBeVisible();
  await calib.getByRole("button", { name: "İptal" }).click();
  await expect(page.getByRole("region", { name: "Sayım" })).toBeVisible();

  // CSV indirilebilir
  const csvHref = await page.getByRole("link", { name: "CSV indir" }).getAttribute("href");
  const csv = await page.request.get(csvHref!);
  expect(csv.status()).toBe(200);

  // Kapat → boş durum; kaynağı sil
  await page.getByRole("button", { name: "Canlı sayımı kapat" }).click();
  await expect(page.getByText("Açık canlı sayım yok")).toBeVisible();
  await page.getByRole("link", { name: "Kameralara git" }).click();
  await page.getByTestId("source-card").filter({ hasText: "Test bandı" }).getByRole("button", { name: "Sil" }).click();
  await expect(page.getByText("Henüz kaynak yok")).toBeVisible();
});
