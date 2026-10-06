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
  await page.getByRole("textbox", { name: /^Ad/ }).fill("Test kamerası");
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();

  // Düzenle → Kaydet: ad değişir, kayıt reddedilmez (eski hata: "Extra inputs are not permitted")
  await page.getByTestId("source-card").filter({ hasText: "Test kamerası" }).getByRole("button", { name: "Düzenle" }).click();
  await expect(page.getByText("Kaynağı düzenle")).toBeVisible();
  await page.getByRole("textbox", { name: /^Ad/ }).fill("Test bandı");
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect(page.getByText("Kaynağı düzenle")).toBeHidden();
  await expect(page.getByText(/Extra inputs|geçersiz/)).toHaveCount(0);

  const card = page.getByTestId("source-card").filter({ hasText: "Test bandı" });
  await expect(card).toBeVisible();
  await expect.poll(() => imageWidth(page, "Test bandı"), { timeout: 20_000 }).toBeGreaterThan(0);  // küçük resim

  // Ne sayılacağını seç → başlat → canlı sayfa
  await card.getByRole("button", { name: "Canlı sayım" }).click();
  const dialog = page.getByRole("dialog", { name: "Canlı sayımı başlat" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Kişi sayımı")).toBeVisible();

  // Profil yönetimi: aynı hazır profil "Yumurta 2" olur; yeniden adlandırılır ve silinir
  await dialog.getByRole("button", { name: "+ Yumurta profili ekle" }).click();
  await expect(dialog.getByTestId("profile-row").filter({ hasText: "Yumurta 2" })).toBeVisible();
  await dialog.getByRole("button", { name: "Yeniden adlandır: Yumurta 2" }).click();
  await dialog.getByLabel("Profil adı").fill("Hat 2 yumurta");
  await dialog.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect(dialog.getByTestId("profile-row").filter({ hasText: "Hat 2 yumurta" })).toBeVisible();
  await dialog.getByRole("button", { name: "Sil: Hat 2 yumurta" }).click();
  await expect(dialog.getByTestId("profile-row").filter({ hasText: "Hat 2 yumurta" })).toHaveCount(0);
  await expect(dialog.getByTestId("profile-row").filter({ hasText: /^Yumurta/ })).toHaveCount(1);
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

  // İkinci kamera: ilk sayım sürerken başka kamerada da canlı sayım açılır; ikisi kartlarda görünür
  await expect(page.getByTestId("session-card")).toHaveCount(1);
  await page.getByRole("link", { name: "+ Kamera ekle" }).click();
  // Sayımı süren kamera "Sayılıyor" ile işaretli (yeniden başlatılmaz, o sayıma gider)
  await expect(page.getByTestId("source-card").filter({ hasText: "Test bandı" }).getByRole("link", { name: "Sayılıyor" })).toBeVisible();
  await page.getByRole("radio", { name: "IP kamera" }).click();
  await page.getByLabel("Kamera markası").selectOption("custom");
  await page.getByLabel("RTSP adresi").fill(CLIP);
  await page.getByRole("textbox", { name: /^Ad/ }).fill("İkinci bant");
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await page.getByTestId("source-card").filter({ hasText: "İkinci bant" }).getByRole("button", { name: "Canlı sayım" }).click();
  const dialog2 = page.getByRole("dialog", { name: "Canlı sayımı başlat" });
  await dialog2.getByRole("button", { name: /^Yumurta/ }).click();
  await dialog2.getByRole("button", { name: "Başlat", exact: true }).click();
  await expect(page.getByTestId("session-card")).toHaveCount(2);
  await expect(page.getByTestId("session-card").filter({ hasText: "Test bandı" })).toBeVisible();
  await expect(page.getByTestId("live-state")).toContainText("Canlı", { timeout: 30_000 });

  // Kapat (ikisi de) → boş durum; kaynakları sil
  await page.getByRole("button", { name: "Canlı sayımı kapat" }).click();
  await expect(page.getByTestId("session-card")).toHaveCount(1);
  await page.getByRole("button", { name: "Canlı sayımı kapat" }).click();
  await expect(page.getByText("Açık canlı sayım yok")).toBeVisible();
  await page.getByRole("link", { name: "Kameralara git" }).click();
  for (const name of ["Test bandı", "İkinci bant"]) {
    await page.getByTestId("source-card").filter({ hasText: name }).getByRole("button", { name: "Sil" }).click();
    await expect(page.getByTestId("source-card").filter({ hasText: name })).toHaveCount(0);
  }
  await expect(page.getByText("Henüz kaynak yok")).toBeVisible();
});

test("kişi sayımı: personel rengi öğret, örnek görünür, sil", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  await login(page);
  await page.getByRole("radio", { name: "IP kamera" }).click();
  await page.getByLabel("Kamera markası").selectOption("custom");
  await page.getByLabel("RTSP adresi").fill(CLIP);
  await page.getByRole("textbox", { name: /^Ad/ }).fill("Giriş kamerası");
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await page.getByTestId("source-card").filter({ hasText: "Giriş kamerası" }).getByRole("button", { name: "Canlı sayım" }).click();
  const dialog = page.getByRole("dialog", { name: "Canlı sayımı başlat" });
  await dialog.getByRole("button", { name: /^Mağaza girişi/ }).click();
  await dialog.getByRole("button", { name: "Başlat", exact: true }).click();
  await expect(page.getByTestId("live-state")).toContainText("Canlı", { timeout: 30_000 });

  await page.getByRole("button", { name: "Ayarla" }).click();
  const staff = page.getByRole("group", { name: "Personel rengi" });
  await expect(staff.getByText("Kapalı — tüm geçişler sayılır.")).toBeVisible();
  await staff.getByRole("button", { name: "Personel rengini öğret" }).click();
  await expect(staff.getByText("Görüntü donduruldu: bir personelin gövdesine tıklayın.")).toBeVisible();
  // öğretirken düzenleyicinin görüntüsü yenilenmez (sunucu tıklanan kareyi örnekler)
  const editorImg = page.locator('img[src*="/frame.jpg"]');
  const frozenSrc = await editorImg.getAttribute("src");
  await page.waitForTimeout(1500);
  await expect(editorImg).toHaveAttribute("src", frozenSrc ?? "");
  await page.getByRole("button", { name: "Görüntüde personelin üstüne tıklayın" }).click({ position: { x: 200, y: 200 } });
  await expect(staff.getByTestId("staff-swatch")).toHaveCount(1);
  await staff.getByRole("button", { name: "1. personel rengini sil" }).click();
  await expect(staff.getByTestId("staff-swatch")).toHaveCount(0);
  await page.getByRole("button", { name: "İptal" }).click();
  await page.getByRole("button", { name: "Canlı sayımı kapat" }).click();
  await expect(page.getByText("Açık canlı sayım yok")).toBeVisible();
  await page.getByRole("link", { name: "Kameralara git" }).click();
  await page.getByTestId("source-card").filter({ hasText: "Giriş kamerası" }).getByRole("button", { name: "Sil" }).click();
});
