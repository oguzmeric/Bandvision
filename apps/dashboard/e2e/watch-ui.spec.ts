import { expect, test, type Page } from "@playwright/test";

/**
 * İzleme sayfası (izleme kipi), SAHTE API ile (page.route): şablon ızgarası, kutu katmanları, tek kamera, alarm,
 * video duvarı ve akış yeniden bağlanması. Gerçek akış e2e/watch.spec.ts'te.
 */
const LAYOUTS = [
  { id: "1", name: "Tek", cols: 1, rows: 1, cells: [[0, 0, 1, 1]] },
  { id: "4", name: "4'lü", cols: 2, rows: 2, cells: [[0, 0, 1, 1], [1, 0, 1, 1], [0, 1, 1, 1], [1, 1, 1, 1]] },
];
const VIEW = { id: "v1", name: "Giriş katı", layout: "4", createdAt: 1, updatedAt: 1,
  tiles: [{ sourceId: "a", channelId: null }, { sourceId: "b", channelId: "2" }, { sourceId: "c", channelId: null }, null] };
// 1×1 siyah JPEG (akış yerine; tek parça yeterli)
const JPEG = Buffer.from("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==", "base64");

async function mock(page: Page, status: object) {
  await page.route("**/api/live/view-layouts", (r) => r.fulfill({ json: LAYOUTS }));
  await page.route("**/api/live/views", (r) => r.fulfill({ json: [VIEW] }));
  await page.route("**/api/live/views/v1/status", (r) => r.fulfill({ json: status }));
  await page.route("**/api/live/views/v1/stream**", (r) => r.fulfill({ body: JPEG, contentType: "image/jpeg" }));
  await page.route("**/api/live/cameras/**", (r) => r.fulfill({ body: JPEG, contentType: "image/jpeg" }));
  await page.route("**/api/live/alarms?active=1", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/live/sessions", (r) => r.fulfill({ json: [] }));
}

const STATUS = { id: "v1", layout: "4", tiles: [
  { sourceId: "a", channelId: null, name: "Kapı", state: "live", message: "", fps: 10,
    analysis: { mode: "detect", sessionId: "s1", name: "Mağaza girişi", entered: 12, exited: 9, alarm: null } },
  { sourceId: "b", channelId: "2", name: "Ofis NVR · Kasa", state: "live", message: "", fps: 10,
    analysis: { mode: "safety", sessionId: "s2", name: "Kuyumcu güvenliği", healthy: true, reason: null,
                alarm: { id: "al1", type: "hands_up" } } },
  { sourceId: "c", channelId: null, name: "Arka kapı", state: "error", message: "Görüntü açılamadı; yeniden deneniyor.",
    fps: 0, analysis: null },
  null,
] };

async function login(page: Page) {
  await page.goto("/watch");
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("heading", { name: "İzleme" })).toBeVisible();
}

test("izleme: şablon ızgarası, adlar, rozetler, hata ve alarm çerçevesi", async ({ page }) => {
  await mock(page, STATUS);
  await login(page);
  await expect(page.getByRole("combobox", { name: "Şablon" })).toHaveValue("v1");
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles).toHaveCount(4);
  await expect(tiles.nth(0)).toContainText("Kapı");
  await expect(tiles.nth(0)).toContainText("G 12 · Ç 9");
  await expect(tiles.nth(1)).toContainText("ELLER YUKARI");
  await expect(tiles.nth(1)).toHaveAttribute("data-alarm", "true");
  await expect(tiles.nth(2)).toContainText("Görüntü açılamadı");
  await expect(tiles.nth(3)).toHaveAttribute("data-empty", "true");
  await expect(page.getByAltText("Giriş katı canlı görüntü")).toBeVisible();
});

test("izleme: çift tıkla tek kamera, Esc ile geri; telefon görünümü", async ({ page }) => {
  await mock(page, STATUS);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");            // durum geldi (çift tık ancak o zaman kutuyu açar)
  await tiles.nth(0).dblclick();
  await expect(page.getByRole("heading", { name: "Kapı" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Net görüntü" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch-tile")).toHaveCount(4);
  await page.setViewportSize({ width: 375, height: 740 });
  await expect(page.getByTestId("watch-grid")).toBeVisible();
  const box = await page.getByTestId("watch-grid").boundingBox();
  expect(box!.width).toBeLessThanOrEqual(375);
});

test("izleme: alarmlı kutuya tıklayınca alarm penceresi açılır", async ({ page }) => {
  await mock(page, STATUS);
  const ALARM = { id: "al1", sessionId: "s2", camera: "Ofis NVR · Kasa", type: "hands_up", startedAt: 100, firedAt: 103,
    endedAt: null, acked: false, falseAlarm: false, notify: "disabled", image: false, clip: false, clipPending: false,
    clipFailed: false, clipStartedAt: null };
  await page.route("**/api/live/alarms?active=1", (r) => r.fulfill({ json: [ALARM] }));
  await login(page);
  // yeni alarm penceresi kendiliğinden açılır: küçült, sonra kutuya tıklayıp yeniden aç
  const dlg = page.getByRole("alertdialog", { name: "Güvenlik alarmı" });
  await expect(dlg).toBeVisible();
  await dlg.getByRole("button", { name: "Küçült" }).click();
  await expect(dlg).toBeHidden();
  await page.getByTestId("watch-tile").nth(1).click();
  await expect(page.getByRole("alertdialog", { name: "Güvenlik alarmı" })).toBeVisible();
});

test("izleme: kutu düğmeleri (Tam ekran, Canlı sayıma git) ve kenar çubuğu girişi", async ({ page }) => {
  await mock(page, STATUS);
  await login(page);
  await expect(page.getByRole("navigation", { name: "Ana menü" }).getByRole("link", { name: "İzleme" })).toHaveAttribute("aria-current", "page");
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  // analizi olan kutu o oturuma, olmayan Kameralar sayfasına götürür
  await tiles.nth(0).hover();
  await expect(tiles.nth(0).getByRole("link", { name: "Canlı sayıma git" })).toHaveAttribute("href", "/live?s=s1");
  await tiles.nth(2).hover();
  await expect(tiles.nth(2).getByRole("link", { name: "Canlı sayıma git" })).toHaveAttribute("href", "/cameras");
  // "Tam ekran" kutuyu tek kamera olarak açar
  await tiles.nth(2).getByRole("button", { name: "Tam ekran" }).click();
  await expect(page.getByRole("heading", { name: "Arka kapı" })).toBeVisible();
  await page.getByRole("button", { name: "← Izgaraya dön" }).click();
  await expect(page.getByTestId("watch-tile")).toHaveCount(4);
});

test("izleme: Tüm ekran video duvarı ızgarayı oranıyla ortalar ve kapanır", async ({ page }) => {
  await mock(page, STATUS);
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  await page.getByRole("button", { name: "Tüm ekran" }).click();
  await expect(page.locator("[data-wall=true]")).toBeVisible();
  expect(await page.evaluate(() => document.fullscreenElement !== null)).toBe(true);
  const vp = page.viewportSize()!;
  const box = (await page.getByTestId("watch-grid").boundingBox())!;
  expect(box.width).toBeLessThanOrEqual(vp.width + 1);
  expect(box.height).toBeLessThanOrEqual(vp.height + 1);
  expect(box.width / box.height).toBeCloseTo(32 / 18, 1);        // 2×2 düzen: oran korunur
  await page.evaluate(() => document.exitFullscreen());
  await expect(page.locator("[data-wall=true]")).toHaveCount(0);
});

test("izleme: akış koparsa yeniden bağlanır (hata olayı, çevrimiçi, sekme görünür)", async ({ page }) => {
  await mock(page, STATUS);
  const ks: string[] = [];
  // ilk istek koparılır (img error); sonrakiler gelir. Daha sonra eklenen yol öncelik alır.
  await page.route("**/api/live/views/v1/stream**", (r) => {
    ks.push(new URL(r.request().url()).searchParams.get("k") ?? "");
    return ks.length === 1 ? r.abort() : r.fulfill({ body: JPEG, contentType: "image/jpeg" });
  });
  await login(page);
  await expect.poll(() => ks, { timeout: 15_000 }).toContain("1");          // hata → 2 sn sonra k=1
  const n = ks.length;
  await page.evaluate(() => window.dispatchEvent(new Event("online")));      // ağ geri geldi → hemen yeni k
  await expect.poll(() => ks.length).toBeGreaterThan(n);
  const m = ks.length;
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));   // sekme görünür → hemen yeni k
  await expect.poll(() => ks.length).toBeGreaterThan(m);
  expect(new Set(ks).size).toBe(ks.length);                                   // her yeniden bağlanma yeni anahtar
});
