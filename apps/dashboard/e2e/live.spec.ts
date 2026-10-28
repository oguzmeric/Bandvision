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

  // Kenar çubuğu: canlı sayım (Analizler: ürün/kişi/güvenlik) ve kameralar açık (yakında değil)
  const nav = page.getByRole("navigation", { name: "Ana menü" });
  for (const name of ["Ürün sayımı", "Kişi sayımı", "Güvenlik alarmı (poz)", "Kameralar ve kayıt cihazları"]) {
    await expect(nav.getByRole("link", { name, exact: true })).toBeVisible();
  }

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

  await page.getByRole("button", { name: "Ayarla", exact: true }).click();
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

/** Sahte oturum: yalnızca süzme için gereken alanlar (sayım yöntemi `countMode`) */
function fakeSession(id: string, name: string, countMode: string | undefined) {
  return {
    id, name, state: "live", message: "", fps: 8, width: 1280, height: 720, counting: true, total: 0, totalOut: 0,
    staffIn: 0, staffOut: 0, twoWay: countMode === "detect", ratePerMinute: 0, calibrating: null, calibrationMessage: "",
    sourceId: null, channelId: null, profileId: null, substream: null,
    profile: { id: `p-${id}`, name: `Profil ${name}`, roi: { x: 0.1, y: 0.1, width: 0.8, height: 0.8 }, linePosition: 0.5,
               direction: "down", diffThreshold: 30, expectedArea: 0, splitTouching: false, ...(countMode ? { countMode } : {}) },
  };
}

test("analiz süzmesi (sahte API): ?tur= oturumları ve başlatma profillerini türe göre süzer", async ({ page }) => {
  await login(page);
  const GIF = Buffer.from("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7", "base64");
  const sessions = [
    fakeSession("u1", "Bant A", undefined),                  // sayım yöntemi yok = ürün (blob)
    fakeSession("u2", "Bant B", "linescan"),
    fakeSession("k1", "Giriş kapısı", "detect"),
    fakeSession("g1", "Kuyumcu", "safety"),
  ];
  const profile = (id: string, name: string, countMode: string) => ({ ...fakeSession(id, name, countMode).profile, id, name });
  await page.route("**/api/live/sessions", (route) =>
    route.request().method() === "GET" ? route.fulfill({ json: sessions }) : route.continue());
  await page.route("**/api/live/sessions/*/stream*", (route) => route.fulfill({ contentType: "image/gif", body: GIF }));
  await page.route("**/api/live/alarms*", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/live/sources", (route) => route.fulfill({ json: [{
    id: "src1", kind: "camera", name: "Kapı kamerası", brand: "custom", host: "", port: 554, channel: 1, substream: false, customUrl: "x",
    recorderBrand: "trassir", httpPort: null, rtspPort: null, username: "", hasPassword: false, createdAt: 1,
  }] }));
  await page.route("**/api/live/sources/*/snapshot*", (route) => route.fulfill({ contentType: "image/gif", body: GIF }));
  await page.route("**/api/live/profiles", (route) => route.fulfill({ json: [
    profile("pb", "Yumurta", "blob"), profile("pk", "Mağaza girişi", "detect"), profile("pg", "Kuyumcu güvenliği", "safety"),
  ] }));
  await page.route("**/api/live/catalog", (route) => route.fulfill({ json: [
    { id: "belt", title: "Bant ürünleri", subtitle: "", available: true, presets: [] },
    { id: "people", title: "Kişi sayımı", subtitle: "", available: true, presets: [] },
    { id: "safety", title: "Güvenlik alarmı", subtitle: "", available: true, presets: [] },
  ] }));

  const cards = page.getByTestId("session-card");
  const nav = page.getByRole("navigation", { name: "Ana menü" });

  // kişi: yalnızca detect oturumları, başlık "Kişi sayımı", menüde o öğe seçili
  await page.goto("/live?tur=kisi");
  await expect(page.getByRole("heading", { level: 1, name: "Kişi sayımı" })).toBeVisible();
  await expect(cards).toHaveCount(1);
  await expect(cards.first()).toContainText("Giriş kapısı");
  await expect(nav.getByRole("link", { name: "Kişi sayımı", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(nav.getByRole("link", { name: "Ürün sayımı", exact: true })).not.toHaveAttribute("aria-current", "page");

  // ürün: blob (sayım yöntemi yok) ve linescan birlikte; ?s= süzmeye uymuyorsa ilk uygun oturum seçilir
  await page.goto("/live?tur=urun&s=k1");
  await expect(page.getByRole("heading", { level: 1, name: "Ürün sayımı" })).toBeVisible();
  await expect(cards).toHaveCount(2);
  await expect(page.getByRole("tab", { selected: true })).toContainText("Bant A");

  // güvenlik
  await page.goto("/live?tur=guvenlik");
  await expect(page.getByRole("heading", { level: 1, name: "Güvenlik alarmı" })).toBeVisible();
  await expect(cards).toHaveCount(1);
  await expect(cards.first()).toContainText("Kuyumcu");

  // süzmesiz ve geçersiz tur: tüm oturumlar, hiçbir menü öğesi seçili değil
  for (const url of ["/live", "/live?tur=bilinmeyen"]) {
    await page.goto(url);
    await expect(page.getByRole("heading", { level: 1, name: "Canlı sayım" })).toBeVisible();
    await expect(cards).toHaveCount(4);
    await expect(nav.locator("[aria-current]")).toHaveCount(0);
  }

  // "Yeni analiz" → kamera seç → başlatma penceresinde yalnızca kişi sayımı profilleri
  await page.goto("/live?tur=kisi");
  await page.getByRole("link", { name: "+ Yeni analiz" }).click();
  await expect(page).toHaveURL(/\/cameras\?tur=kisi$/);
  await page.getByTestId("source-card").getByRole("button", { name: "Canlı sayım" }).click();
  const dialog = page.getByRole("dialog", { name: "Canlı sayımı başlat" });
  await expect(dialog.getByTestId("profile-row")).toHaveCount(1);
  await expect(dialog.getByTestId("profile-row")).toContainText("Mağaza girişi");
  await expect(dialog.getByText("Yumurta")).toHaveCount(0);
  await dialog.getByRole("button", { name: "Vazgeç" }).click();

  // süzmesiz kameralar sayfasında tüm profiller sunulur
  await page.goto("/cameras");
  await page.getByTestId("source-card").getByRole("button", { name: "Canlı sayım" }).click();
  await expect(page.getByRole("dialog", { name: "Canlı sayımı başlat" }).getByTestId("profile-row")).toHaveCount(3);
});

test("analiz süzmesi (sahte API): türde oturum yoksa boş durum Yeni analiz bağlantısı verir", async ({ page }) => {
  await login(page);
  await page.route("**/api/live/sessions", (route) =>
    route.request().method() === "GET" ? route.fulfill({ json: [fakeSession("u1", "Bant A", "blob")] }) : route.continue());
  await page.goto("/live?tur=kisi");
  await expect(page.getByText("Henüz kişi sayımı yok.")).toBeVisible();
  await expect(page.getByText("Kameralar sayfasından ya da “Yeni analiz” ile başlat.")).toBeVisible();
  await expect(page.getByTestId("session-card")).toHaveCount(0);
  await page.getByRole("link", { name: "Yeni analiz" }).click();
  await expect(page).toHaveURL(/\/cameras\?tur=kisi$/);
});
