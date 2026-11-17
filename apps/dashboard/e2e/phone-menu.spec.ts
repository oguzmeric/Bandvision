import { expect, test, type Page } from "@playwright/test";

/**
 * Menüdeki "Telefon kullanımı" (SAHTE API ile, page.route): telefon kuralı açık güvenlik kameralarının süzülmüş görünümü;
 * başlatma penceresi yalnız telefon kuralı açık profilleri ve "Telefon kullanımı" hazır profilini sunar; Ayarla'da kural
 * kapatılınca görüntülenen kamera listeden düşmez (taslak sunucuya anında uygulanır).
 */
async function login(page: Page) {
  await page.goto("/notifications");
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("heading", { name: "Bildirimler" })).toBeVisible();
}

/** 1x1 saydam GIF: sahte canlı akış ve kare */
const GIF = Buffer.from("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7", "base64");

type Safety = { handsUp: { enabled: boolean; seconds: number }; lying: { enabled: boolean; seconds: number };
  phone?: { enabled: boolean; seconds: number }; sendImage: boolean };

function safetyProfile(id: string, name: string, phone: boolean | null): Record<string, unknown> {
  const safety: Safety = { handsUp: { enabled: !phone, seconds: 3 }, lying: { enabled: !phone, seconds: 10 }, sendImage: false };
  if (phone !== null) safety.phone = { enabled: phone, seconds: 15 };
  return { id, name, roi: { x: 0, y: 0, width: 1, height: 1 }, linePosition: 0.5, direction: "down", diffThreshold: 30,
    expectedArea: 0, splitTouching: false, countMode: "safety", processingWidth: 640, safety };
}

function session(id: string, name: string, profile: Record<string, unknown>) {
  return {
    id, name, state: "live", message: "", fps: 5, width: 1280, height: 720, counting: false, total: 0, totalOut: 0,
    staffIn: 0, staffOut: 0, twoWay: false, ratePerMinute: 0, calibrating: null, calibrationMessage: "", sourceId: null,
    channelId: null, profileId: null, substream: null, fire: null,
    safety: { active: [], lastAlarmAt: null, model: "ready", modelError: null, healthy: true, reason: null, unhealthyFor: null,
      processingError: null, lastOkAt: null },
    profile,
  };
}

test("Telefon kullanımı (sahte API): yalnız telefon kuralı açık güvenlik kameraları; kural kapatılınca açık kamera kaybolmaz", async ({ page }) => {
  await login(page);
  const sessions = [
    session("t1", "Ofis kamerası", safetyProfile("pt", "Telefon kullanımı", true)),
    session("g1", "Kasa kamerası", safetyProfile("pg", "Kuyumcu güvenliği", false)),
    session("g2", "Eski kamera", safetyProfile("po", "Eski güvenlik", null)),           // eski profil: `phone` yok
  ];
  await page.route("**/api/live/sessions", (r) => r.request().method() === "GET" ? r.fulfill({ json: sessions }) : r.continue());
  await page.route("**/api/live/sessions/*/stream*", (r) => r.fulfill({ contentType: "image/gif", body: GIF }));
  await page.route("**/api/live/sessions/*/frame.jpg*", (r) => r.fulfill({ contentType: "image/gif", body: GIF }));
  await page.route(/\/api\/live\/alarms\?/, (r) => r.fulfill({ json: [] }));
  await page.route("**/api/live/sessions/t1/profile*", (r) => {
    sessions[0] = { ...sessions[0], profile: r.request().postDataJSON() as Record<string, unknown> };   // taslak anında uygulanır
    return r.fulfill({ json: sessions[0].profile });
  });

  const cards = page.getByTestId("session-card");
  const nav = page.getByRole("navigation", { name: "Ana menü" });
  await page.goto("/live?tur=telefon");
  await expect(page.getByRole("heading", { level: 1, name: "Telefon kullanımı", exact: true })).toBeVisible();
  await expect(page).toHaveTitle("Telefon kullanımı · BandVision");
  await expect(nav.getByRole("link", { name: "Telefon kullanımı", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(nav.locator("[aria-current]")).toHaveCount(1);
  await expect(cards).toHaveCount(1);
  await expect(cards.first()).toContainText("Ofis kamerası");

  // ?s= süzmeye uymayan güvenlik kamerası: telefon listesinin ilki seçilir
  await page.goto("/live?tur=telefon&s=g1");
  await expect(page.getByRole("tab", { selected: true })).toContainText("Ofis kamerası");

  // Güvenlik alarmı (poz): üç güvenlik kamerası birden (telefon kuralı açık olan da)
  await page.goto("/live?tur=guvenlik");
  await expect(cards).toHaveCount(3);

  // Ayarla'da telefon kuralı kapatılır: görüntülenen kamera listede ve panel açık kalır; tür değişince düşer
  await page.goto("/live?tur=telefon");
  await page.getByRole("button", { name: "Ayarla", exact: true }).click();
  const rules = page.getByRole("group", { name: "Güvenlik kuralları" });
  await rules.getByRole("checkbox", { name: "Telefon kullanımı" }).uncheck();
  await expect.poll(() => (sessions[0].profile.safety as Safety).phone?.enabled).toBe(false);
  await page.waitForTimeout(1500);                                                        // en az bir oturum yoklaması
  await expect(cards).toHaveCount(1);
  await expect(rules.getByRole("checkbox", { name: "Telefon kullanımı" })).not.toBeChecked();
  await page.goto("/live?tur=telefon");
  await expect(page.getByText("Henüz telefon kullanımı izlemesi yok.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Yeni analiz" })).toHaveAttribute("href", "/cameras?tur=telefon");
});

test("Telefon kullanımı (sahte API): başlatma penceresi yalnız telefon kuralı açık profilleri ve hazır profilini sunar", async ({ page }) => {
  await login(page);
  const source = { id: "c1", kind: "camera", name: "Ofis", brand: "hikvision", host: "127.0.0.1", port: 554, channel: 1, substream: true,
    customUrl: "", recorderBrand: "trassir", httpPort: null, rtspPort: null, username: "", hasPassword: false, createdAt: 0 };
  await page.route("**/api/live/sources", (r) => r.fulfill({ json: [source] }));
  await page.route("**/api/live/sources/c1/snapshot*", (r) => r.fulfill({ contentType: "image/gif", body: GIF }));
  await page.route("**/api/live/sessions", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/live/catalog", (r) => r.fulfill({ json: [
    { id: "belt", title: "Bant üstü ürün", subtitle: "", available: true, presets: [{ key: "egg", name: "Yumurta" }] },
    { id: "safety", title: "Güvenlik", subtitle: "", available: true,
      presets: [{ key: "jeweler", name: "Kuyumcu güvenliği" }, { key: "phone", name: "Telefon kullanımı" }] },
  ] }));
  await page.route("**/api/live/profiles", (r) => r.fulfill({ json: [
    safetyProfile("pt", "Ofis telefon", true), safetyProfile("pg", "Kasa", false), safetyProfile("po", "Eski", null),
  ] }));
  await page.goto("/cameras?tur=telefon");
  await expect(page.getByTestId("kind-filter")).toContainText("Yeni analiz: Telefon kullanımı.");
  await page.getByTestId("source-card").getByRole("button", { name: "Analiz başlat" }).click();
  const dialog = page.getByRole("dialog", { name: "Canlı sayımı başlat" });
  await expect(dialog.getByTestId("profile-row")).toHaveCount(1);
  await expect(dialog.getByTestId("profile-row")).toContainText("Ofis telefon");
  await expect(dialog.getByTestId("profile-row")).toContainText("Telefon kullanımı");                    // yalnız açık kurallar
  await expect(dialog.getByRole("button", { name: "+ Telefon kullanımı profili ekle" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "+ Kuyumcu güvenliği profili ekle" })).toHaveCount(0);
  await expect(dialog.getByText("Yumurta")).toHaveCount(0);
});
