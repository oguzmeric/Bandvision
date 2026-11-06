import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * İlk yüklemesi başarısız olan sayfalar 5 sn'de bir kendiliğinden yeniden dener (`useRetryWhileFailed`): anahtar ya da sunucu
 * düzelince hata satırı tıklamadan ve sayfa yenilenmeden kalkar. Sahte API: yalnızca sınanan istek reddedilir.
 */
const KEY_TEXT = "Analiz sunucusu erişim anahtarı uyuşmuyor — panelde ve analiz sunucusunda aynı ANALYZER_TOKEN ayarlanmalı.";
const REFUSED = { detail: KEY_TEXT, code: "analyzer_key" };
/** 5 sn'de bir denenir: bu süre içinde düzelmeli (eskiden 15 sn'lik yoklama ya da hiç) */
const RETRY_MS = 7_000;
const CAMERA = { id: "a", kind: "camera", name: "Kapı", brand: "custom", hasPassword: false };

async function login(page: Page, to: string) {
  await page.goto(to);
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await page.waitForURL((u) => u.pathname === to);
  await expect(page.getByRole("button", { name: "Giriş yap" })).toHaveCount(0);
}

/** `glob` isteği `refused` açıkken reddedilir, kapanınca `normal` yanıtını alır */
async function refusable(page: Page, glob: string, normal: (r: Route) => unknown, method?: string) {
  const state = { refused: true, calls: 0 };
  await page.route(glob, (r) => {
    if (method && r.request().method() !== method) return r.fallback();
    state.calls += 1;
    return state.refused ? r.fulfill({ status: 502, json: REFUSED }) : normal(r);
  });
  return state;
}

/** Sayfa yenilenmedi: işaret aynı belgede duruyor */
const markDocument = (page: Page) => page.evaluate(() => { (window as unknown as { __sameDoc: boolean }).__sameDoc = true; });
const sameDocument = (page: Page) => page.evaluate(() => (window as unknown as { __sameDoc?: boolean }).__sameDoc === true);

test("kendiliğinden düzelme: Kameralar sayfası reddedilen kaynak listesini kendisi yeniden ister, hata satırı kalkar", async ({ page }) => {
  const sources = await refusable(page, "**/api/live/sources", (r) => r.fulfill({ json: [CAMERA] }));
  await login(page, "/cameras");
  const alert = page.getByRole("alert").filter({ hasText: KEY_TEXT });
  await expect(alert).toBeVisible();
  await markDocument(page);
  sources.refused = false;
  await expect(page.getByTestId("source-card")).toContainText("Kapı", { timeout: RETRY_MS });
  await expect(alert).toHaveCount(0);
  expect(await sameDocument(page)).toBe(true);
  // Düzeldikten sonra yeniden denemez (bu sayfa yoklamaz)
  const n = sources.calls;
  await page.waitForTimeout(5_500);
  expect(sources.calls).toBe(n);
});

test("kendiliğinden düzelme: Bildirimler ilk yükleme başarısızsa yeniden dener; yazılan değerin üstüne yazmaz", async ({ page }) => {
  const notify = await refusable(page, "**/api/live/notify", (r) => r.fulfill({ json: { enabled: true, chatId: "-100", hasToken: true } }), "GET");
  await login(page, "/notifications");
  const line = page.getByRole("status").filter({ hasText: KEY_TEXT });
  await expect(line).toBeVisible();
  await page.getByLabel("Sohbet / grup kimliği").fill("-999");                 // hata dururken yazılan değer
  await markDocument(page);
  notify.refused = false;
  await expect(page.getByText("Anahtar kayıtlı")).toBeVisible({ timeout: RETRY_MS });
  await expect(line).toHaveCount(0);
  await expect(page.getByLabel("Sohbet / grup kimliği")).toHaveValue("-999");
  await expect(page.getByLabel("Bildirimler açık")).toBeChecked();             // dokunulmayan alan sunucudan gelir
  expect(await sameDocument(page)).toBe(true);
});

test("kendiliğinden düzelme: Bildirimler ilk yükleme başarısızken Kaydet kapalı; sunucu dönünce 'Deneme alarmı'na basmak formu boş bırakıp ayarı silmez", async ({ page }) => {
  const puts: unknown[] = [];
  const notify = await refusable(page, "**/api/live/notify", (r) => {
    if (r.request().method() === "PUT") { puts.push(r.request().postDataJSON()); return r.fulfill({ json: { enabled: true, chatId: "-100", hasToken: true } }); }
    return r.fulfill({ json: { enabled: true, chatId: "-100", hasToken: true } });
  });
  await page.route("**/api/live/alarms/test", (r) => r.fulfill({ json: {} }));
  await login(page, "/notifications");
  await expect(page.getByRole("status").filter({ hasText: KEY_TEXT })).toBeVisible();
  await expect(page.getByRole("button", { name: "Kaydet", exact: true })).toBeDisabled();   // ayar okunmadan kaydedilemez (boş form ayarı siler)
  notify.refused = false;                                                    // sunucu döndü, ama 5 sn'lik yeniden deneme henüz gelmedi
  await page.getByRole("button", { name: "Deneme alarmı" }).click();
  await expect(page.getByText("Deneme alarmı oluşturuldu.")).toBeVisible();
  await expect(page.getByLabel("Sohbet / grup kimliği")).toHaveValue("-100", { timeout: RETRY_MS });
  await expect(page.getByLabel("Bildirimler açık")).toBeChecked();
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect(page.getByText("Kaydedildi.")).toBeVisible();
  expect(puts).toEqual([{ enabled: true, chatId: "-100", token: null }]);    // sunucudaki değerler gider, boş değil
});

test("kendiliğinden düzelme: Bildirimler ayar okunamazken 'Deneme alarmı'nın sonucu da görünür; okuma hatası kalır", async ({ page }) => {
  await refusable(page, "**/api/live/notify", (r) => r.fulfill({ json: { enabled: true, chatId: "-100", hasToken: true } }), "GET");
  await page.route("**/api/live/alarms/test", (r) => r.fulfill({ json: {} }));
  await login(page, "/notifications");
  const loadLine = page.getByRole("status").filter({ hasText: KEY_TEXT });
  await expect(loadLine).toBeVisible();
  await page.getByRole("button", { name: "Deneme alarmı" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Deneme alarmı oluşturuldu." })).toBeVisible();
  await expect(loadLine).toBeVisible();                                       // ayar hâlâ okunamıyor: söylemeye devam eder
});

test("kendiliğinden düzelme: Bildirimler ilk yükleme başarılıysa yeniden istemez, yazılan değer kalır", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/live/notify", (r) => {
    calls += 1;
    return r.fulfill({ json: { enabled: false, chatId: "-100", hasToken: false } });
  });
  await login(page, "/notifications");
  await expect(page.getByLabel("Sohbet / grup kimliği")).toHaveValue("-100");
  await page.getByLabel("Sohbet / grup kimliği").fill("-999");
  await page.waitForTimeout(5_500);
  expect(calls).toBe(1);
  await expect(page.getByLabel("Sohbet / grup kimliği")).toHaveValue("-999");
});

test("kendiliğinden düzelme: sayfa açılırken kısa kesintide Kameralar listesi alarm yoklamasını beklemeden dolar; 'Yeniden dene' durur", async ({ page }) => {
  await page.route("**/api/live/views", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/live/alarms?active=1", (r) => r.fulfill({ json: [] }));      // alarm akışı hiç kopmaz
  const sources = await refusable(page, "**/api/live/sources", (r) => r.fulfill({ json: [CAMERA] }));
  await login(page, "/watch");
  const list = page.getByRole("complementary", { name: "Kameralar" });
  await expect(list.getByRole("alert")).toContainText(KEY_TEXT);
  await expect(list.getByRole("button", { name: "Yeniden dene" })).toBeVisible();
  await markDocument(page);
  sources.refused = false;
  await expect(list.getByRole("button", { name: /^Kapı/ })).toBeVisible({ timeout: RETRY_MS });
  await expect(list.getByRole("alert")).toHaveCount(0);
  await expect(page.getByTestId("alarm-feed-warning")).toHaveCount(0);
  expect(await sameDocument(page)).toBe(true);
});

test("kendiliğinden düzelme: Video ile test iş listesi hata varken 5 sn'de bir yeniden ister (15 sn'lik yoklamayı beklemez)", async ({ page }) => {
  const jobs = await refusable(page, "**/api/jobs", (r) => r.fulfill({ json: [] }), "GET");
  await login(page, "/videos");
  const alert = page.getByRole("alert").filter({ hasText: KEY_TEXT });
  await expect(alert).toBeVisible();
  await markDocument(page);
  jobs.refused = false;
  await expect(page.getByText("Henüz analiz yok")).toBeVisible({ timeout: RETRY_MS });
  await expect(alert).toHaveCount(0);
  expect(await sameDocument(page)).toBe(true);
});

test("kendiliğinden düzelme: Canlı sayımı başlat penceresi profil listesini yeniden ister, hata satırı kalkar", async ({ page }) => {
  await page.route("**/api/live/sources", (r) => r.fulfill({ json: [CAMERA] }));
  await page.route("**/api/live/sources/a/snapshot*", (r) => r.fulfill({ status: 404, json: { detail: "yok" } }));
  const profiles = await refusable(page, "**/api/live/profiles", (r) => r.continue(), "GET");
  await login(page, "/cameras");
  await page.getByTestId("source-card").getByRole("button", { name: "Analiz başlat" }).click();
  const dialog = page.getByRole("dialog", { name: "Canlı sayımı başlat" });
  const alert = dialog.getByRole("alert").filter({ hasText: KEY_TEXT });
  await expect(alert).toBeVisible();
  await markDocument(page);
  profiles.refused = false;
  await expect(dialog.getByText("Kişi sayımı").first()).toBeVisible({ timeout: RETRY_MS });
  await expect(alert).toHaveCount(0);
  expect(await sameDocument(page)).toBe(true);
});

test("kendiliğinden düzelme: Canlı izleme kayıt cihazlarını yeniden ister, 'NVR'dan şablon' seçicisi yenilemeden gelir", async ({ page }) => {
  const recorder = { id: "b", kind: "recorder", name: "Ofis NVR", recorderBrand: "hikvision", hasPassword: true };
  await page.route("**/api/live/views", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/live/sources/b/channels", (r) => r.fulfill({ json: [] }));
  const sources = await refusable(page, "**/api/live/sources", (r) => r.fulfill({ json: [recorder] }));
  await login(page, "/watch");
  await expect(page.getByRole("complementary", { name: "Kameralar" }).getByRole("alert")).toContainText(KEY_TEXT);
  await markDocument(page);
  sources.refused = false;
  await page.getByRole("button", { name: "Şablon editörü" }).click();
  const editor = page.getByRole("dialog", { name: "Şablon editörü" });
  await expect(editor.getByRole("combobox", { name: "NVR'dan şablon" })).toBeVisible({ timeout: RETRY_MS });
  expect(await sameDocument(page)).toBe(true);
});

test("kendiliğinden düzelme: Hakkında analiz sunucusunun sürümünü yeniden ister", async ({ page }) => {
  let state: "auth" | "up" = "auth";
  await login(page, "/about");
  await page.route("**/api/system", (r) => r.fulfill({ json: state === "auth" ? { analyzer: "auth" } : {
    analyzer: "up", cpuPercent: 1, uptimeS: 2, analyzerVersion: "1.2.3", analyzerCommit: "abc1234", panelVersion: "0.1.0", panelCommit: "def5678" } }));
  await page.reload();
  const version = page.getByTestId("about-analyzer");
  await expect(version).toHaveText("— (analiz sunucusu yetki hatası)");
  await markDocument(page);
  state = "up";
  await expect(version).toHaveText("1.2.3 (abc1234)", { timeout: RETRY_MS });
  expect(await sameDocument(page)).toBe(true);
});

test("kendiliğinden düzelme: Telefondan erişim ayarları okunamazsa söyler ve yeniden dener", async ({ page }) => {
  let broken = true;
  await login(page, "/about");
  await page.route("**/api/access", (r) => (broken && r.request().method() === "GET" ? r.abort() : r.continue()));
  await page.goto("/settings");
  const line = page.getByText("Ayarlar okunamadı.");
  await expect(line).toBeVisible();
  await markDocument(page);
  broken = false;
  await expect(page.getByRole("heading", { name: "Erişim ve şifre" })).toBeVisible({ timeout: RETRY_MS });
  await expect(line).toHaveCount(0);
  expect(await sameDocument(page)).toBe(true);
});
