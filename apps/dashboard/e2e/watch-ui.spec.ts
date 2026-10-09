import { expect, test, type Page } from "@playwright/test";

/**
 * İzleme sayfası (izleme kipi), SAHTE API ile (page.route): şablon ızgarası, kutu katmanları, tek kamera, alarm,
 * video duvarı ve akış yeniden bağlanması. Gerçek akış e2e/watch.spec.ts'te.
 */
const LAYOUTS = [
  { id: "1", name: "Tek", cols: 1, rows: 1, cells: [[0, 0, 1, 1]] },
  { id: "2", name: "2'li (yan yana)", cols: 2, rows: 1, cells: [[0, 0, 1, 1], [1, 0, 1, 1]] },
  { id: "4", name: "4'lü", cols: 2, rows: 2, cells: [[0, 0, 1, 1], [1, 0, 1, 1], [0, 1, 1, 1], [1, 1, 1, 1]] },
];
const VIEW = { id: "v1", name: "Giriş katı", layout: "4", createdAt: 1, updatedAt: 1,
  tiles: [{ sourceId: "a", channelId: null }, { sourceId: "b", channelId: "2" }, { sourceId: "c", channelId: null }, null] };
// 1×1 siyah JPEG (akış yerine; tek parça yeterli)
const JPEG = Buffer.from("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==", "base64");

async function mock(page: Page, status: object, view: object | object[] = VIEW) {
  await page.route("**/api/live/view-layouts", (r) => r.fulfill({ json: LAYOUTS }));
  await page.route("**/api/live/views", (r) => r.fulfill({ json: Array.isArray(view) ? view : [view] }));
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
  await expect(tiles.nth(1).getByRole("button", { name: "Alarmı aç: ELLER YUKARI" })).toBeVisible();
  await expect(tiles.nth(2)).toContainText("Bağlantı yok — Görüntü açılamadı");
  await expect(tiles.nth(2)).not.toHaveAttribute("data-empty", "true");
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
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);   // yatay kaydırma yok
  const sel = await page.getByRole("combobox", { name: "Şablon" }).boundingBox();
  expect(sel!.y + sel!.height).toBeLessThanOrEqual(box!.y);                                          // seçici ızgaranın üstünde
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
  // alarm etiketi gerçek bir düğmedir: klavyeyle de alarm penceresi açılır
  await dlg.getByRole("button", { name: "Küçült" }).click();
  await expect(dlg).toBeHidden();
  await page.getByRole("button", { name: "Alarmı aç: ELLER YUKARI" }).focus();
  await page.keyboard.press("Enter");
  await expect(dlg).toBeVisible();
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

/** Akış isteklerinin `k` anahtarlarını toplar (yeniden bağlanma = yeni anahtar) */
async function streamKeys(page: Page, pattern: string): Promise<string[]> {
  const ks: string[] = [];
  await page.route(pattern, (r) => {
    ks.push(new URL(r.request().url()).searchParams.get("k") ?? "");
    return r.fulfill({ body: JPEG, contentType: "image/jpeg" });
  });
  return ks;
}
const fullscreen = (page: Page) => page.evaluate(() => document.fullscreenElement !== null);
const DOWN = "Analiz sunucusuna ulaşılamıyor; yeniden deneniyor…";

test("izleme: durum yoklaması koptuktan sonra düzelirse akış yeniden açılır (sunucu yeniden başladı)", async ({ page }) => {
  await mock(page, STATUS);
  let calls = 0;                                              // ilk dört durum isteği 502 (uyarı 3. ardışık hatada çıkar), sonra düzelir
  await page.route("**/api/live/views/v1/status", (r) => (++calls <= 4
    ? r.fulfill({ status: 502, json: { detail: "Analiz sunucusuna ulaşılamıyor." } }) : r.fulfill({ json: STATUS })));
  const ks = await streamKeys(page, "**/api/live/views/v1/stream**");
  await login(page);
  await expect(page.getByText(DOWN)).toBeVisible();
  await expect.poll(() => ks, { timeout: 15_000 }).toContain("1");      // yoklama düzeldi → akış baştan
  await expect(page.getByText(DOWN)).toBeHidden();
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
});

test("izleme: şablon silinirse (404) liste yeniden alınır, boş durum çıkar, akış tekrar tekrar istenmez", async ({ page }) => {
  await mock(page, STATUS);
  let listed = 0;
  await page.route("**/api/live/views", (r) => r.fulfill({ json: ++listed === 1 ? [VIEW] : [] }));
  await page.route("**/api/live/views/v1/status", (r) => r.fulfill({ status: 404, json: { detail: "Şablon bulunamadı." } }));
  let streams = 0;
  await page.route("**/api/live/views/v1/stream**", (r) => { streams += 1; return r.fulfill({ status: 404, json: { detail: "Şablon bulunamadı." } }); });
  await login(page);
  await expect(page.locator("p", { hasText: "Henüz şablon yok" })).toBeVisible();
  await expect(page.getByTestId("watch-grid")).toHaveCount(0);
  const n = streams, l = listed;
  await page.waitForTimeout(4500);                            // hata yeniden deneme döngüsünden en az 2 tur
  expect(streams).toBe(n);
  expect(listed).toBe(l);
  expect(l).toBe(2);
});

test("izleme: şablon listesi alınamazsa uyarı çıkar ve yeniden denenir; 'Henüz şablon yok' denmez", async ({ page }) => {
  await mock(page, STATUS);
  let listed = 0;
  await page.route("**/api/live/views", (r) => (++listed === 1
    ? r.fulfill({ status: 502, json: { detail: "Analiz sunucusuna ulaşılamıyor." } }) : r.fulfill({ json: [VIEW] })));
  await login(page);
  await expect(page.getByText(DOWN)).toBeVisible();
  await expect(page.locator("p", { hasText: "Henüz şablon yok" })).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "Şablon" })).toHaveValue("v1", { timeout: 15_000 });   // ≈5 sn sonra
  await expect(page.getByText(DOWN)).toBeHidden();
  await expect(page.getByTestId("watch-tile")).toHaveCount(4);
});

test("izleme: tek kamerada durum yazılır; yoklama koptuktan sonra düzelirse akış yeniden açılır", async ({ page }) => {
  await mock(page, STATUS);
  const seq = [502, 502, "connecting", "error", "live"];
  let n = 0;
  // cameras/** JPEG yolundan sonra eklendiği için durum yolu önce eşleşir
  await page.route("**/api/live/cameras/status**", (r) => {
    const s = seq[Math.min(n++, seq.length - 1)];
    if (s === 502) return r.fulfill({ status: 502, json: { detail: "Analiz sunucusuna ulaşılamıyor." } });
    return r.fulfill({ json: { name: "Kapı", state: s, message: s === "error" ? "Kamera yanıt vermiyor." : "", fps: 0, analysis: null } });
  });
  const ks = await streamKeys(page, "**/api/live/cameras/stream**");
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  await page.getByTestId("watch-tile").nth(0).dblclick();
  await expect(page.getByRole("heading", { name: "Kapı" })).toBeVisible();
  await expect(page.getByText("Bağlanıyor…")).toBeVisible();
  await expect(page.getByText("Bağlantı yok — Kamera yanıt vermiyor.")).toBeVisible();
  await expect(page.getByRole("status")).toHaveCount(0);                  // canlı: yazı kalkar
  expect(ks).toContain("1");                                              // 502'den sonra düzelince akış baştan açıldı
});

test("izleme: durum yazıları (silinmiş kamera, sınır, bağlanıyor, bağlantı yok)", async ({ page }) => {
  const view4 = { ...VIEW, tiles: [{ sourceId: "a", channelId: null }, { sourceId: "b", channelId: "2" },
    { sourceId: "c", channelId: null }, { sourceId: "d", channelId: null }] };
  const tile = (sourceId: string, channelId: string | null, name: string, state: string, message: string) =>
    ({ sourceId, channelId, name, state, message, fps: 0, analysis: null });
  await mock(page, { id: "v1", layout: "4", tiles: [
    tile("a", null, "Silinmiş kamera", "error", "Kamera silinmiş."),
    tile("b", "2", "Kasa", "error", "Sınır aşıldı (en çok 16 kamera)."),
    tile("c", null, "Depo", "connecting", ""),
    tile("d", null, "Arka kapı", "error", "Görüntü açılamadı"),
  ] }, view4);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kamera silinmiş.");
  await expect(tiles.nth(0)).not.toContainText("Bağlantı yok");
  await expect(tiles.nth(1)).toContainText("Sınır aşıldı (en çok 16 kamera).");
  await expect(tiles.nth(1)).not.toContainText("Bağlantı yok");
  await expect(tiles.nth(2)).toContainText("Bağlanıyor…");
  await expect(tiles.nth(3)).toContainText("Bağlantı yok — Görüntü açılamadı");
});

test("izleme: durum gelmeden dolu kutu 'Bağlanıyor…' der ve açılır; şablonla eşleşmeyen durum yok sayılır", async ({ page }) => {
  await mock(page, STATUS);
  let release!: () => void;
  const gate = new Promise<void>((res) => { release = res; });
  // kutu 0 için başka kamera (sourceId eşleşmiyor) bildiren bayat durum
  const stale = { ...STATUS, tiles: [{ ...(STATUS.tiles[0] as object), sourceId: "zzz", name: "Eski kamera" }, ...STATUS.tiles.slice(1)] };
  await page.route("**/api/live/views/v1/status", async (r) => { await gate; await r.fulfill({ json: stale }); });
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles).toHaveCount(4);
  await expect(tiles.nth(0)).toContainText("Bağlanıyor…");          // durum henüz yok
  await expect(tiles.nth(0)).not.toHaveAttribute("data-empty", "true");
  await expect(tiles.nth(3)).toHaveAttribute("data-empty", "true");  // boşluk şablondan bilinir
  release();
  await expect(tiles.nth(1)).toContainText("Ofis NVR · Kasa");
  await expect(tiles.nth(0)).toContainText("Bağlanıyor…");          // eşleşmeyen durum uygulanmaz
  await expect(tiles.nth(0)).not.toContainText("Eski kamera");
  await tiles.nth(0).dblclick();                                       // yine de açılır (ad yedeği: "Kamera")
  await expect(page.getByRole("heading", { name: "Kamera", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Canlı sayıma git" })).toHaveAttribute("href", "/cameras");
});

test("izleme: klavyeyle kutuyu açma (Enter, Boşluk); iç bağlantıdaki Enter kutuyu açmaz", async ({ page }) => {
  await mock(page, STATUS);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  await tiles.nth(0).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Kapı" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch-tile")).toHaveCount(4);
  await page.getByTestId("watch-tile").nth(0).focus();
  await page.keyboard.press(" ");
  await expect(page.getByRole("heading", { name: "Kapı" })).toBeVisible();
  await page.keyboard.press("Escape");
  // "Canlı sayıma git" bağlantısında Enter yalnız gezinir, kutuyu (tek kamera) açmaz
  await page.getByTestId("watch-tile").nth(0).focus();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("watch-tile").nth(0).getByRole("link", { name: "Canlı sayıma git" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/live\?s=s1/);
});

test("izleme: tek kamerada Esc üstteki alarm penceresini kapatır, tek kamerayı kapatmaz", async ({ page }) => {
  await mock(page, STATUS);
  const ALARM = { id: "al1", sessionId: "s2", camera: "Ofis NVR · Kasa", type: "hands_up", startedAt: 100, firedAt: 103,
    endedAt: null, acked: false, falseAlarm: false, notify: "disabled", image: false, clip: false, clipPending: false,
    clipFailed: false, clipStartedAt: null };
  await page.route("**/api/live/alarms?active=1", (r) => r.fulfill({ json: [ALARM] }));
  await login(page);
  const dlg = page.getByRole("alertdialog", { name: "Güvenlik alarmı" });
  await expect(dlg).toBeVisible();
  await dlg.getByRole("button", { name: "Küçült" }).click();
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  await page.getByTestId("watch-tile").nth(0).dblclick();
  await expect(page.getByRole("heading", { name: "Kapı" })).toBeVisible();
  await page.getByRole("button", { name: /^Kaydı izle/ }).click();     // alarm şeridi: pencere tek kameranın üstünde açılır
  await expect(dlg).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dlg).toBeHidden();
  await expect(page.getByRole("heading", { name: "Kapı" })).toBeVisible();   // tek kamera yerinde
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch-tile")).toHaveCount(4);
});

test("izleme: video duvarında tek kameraya geçilince tam ekran kalır; geri dönünce duvar ızgarası", async ({ page }) => {
  await mock(page, STATUS);
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  await page.getByRole("button", { name: "Tüm ekran" }).click();
  await expect(page.locator("[data-wall=true]")).toBeVisible();
  await page.getByTestId("watch-tile").nth(0).dblclick();
  await expect(page.getByRole("heading", { name: "Kapı" })).toBeVisible();
  expect(await fullscreen(page)).toBe(true);
  await expect(page.locator("[data-wall=true]")).toBeVisible();
  const vp = page.viewportSize()!;
  const img = (await page.getByAltText("Kapı canlı görüntü").boundingBox())!;
  expect(Math.round(img.width)).toBe(vp.width);                       // görüntü ekranı doldurur
  expect(Math.round(img.height)).toBe(vp.height);
  await page.getByRole("button", { name: "← Izgaraya dön" }).click();
  await expect(page.getByTestId("watch-tile")).toHaveCount(4);
  expect(await fullscreen(page)).toBe(true);                          // duvar bozulmadı
  await page.evaluate(() => document.exitFullscreen());
  await expect(page.locator("[data-wall=true]")).toHaveCount(0);
});

test.describe("telefon yan çevrilince (dokunmatik)", () => {
  test.use({ hasTouch: true, isMobile: true });

  test("izleme: telefon yan çevrilince ızgara ekranı kaplar, araç çubuğu gizlenir, × ile çıkılır", async ({ page }) => {
    await mock(page, STATUS);
    await login(page);                                                   // masaüstü boyutunda
    await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
    await page.setViewportSize({ width: 740, height: 360 });             // yatay ve kısa
    const grid = page.getByTestId("watch-grid");
    await expect(page.getByRole("heading", { name: "İzleme" })).toBeHidden();
    await expect.poll(async () => grid.boundingBox()).toEqual({ x: 0, y: 0, width: 740, height: 360 });
    // tek kamerada da görüntü ekranı kaplar; geri dönülünce ızgara yine kaplar
    await page.getByTestId("watch-tile").nth(0).dblclick();
    const img = (await page.getByAltText("Kapı canlı görüntü").boundingBox())!;
    expect([img.x, img.y, img.width, img.height]).toEqual([0, 0, 740, 360]);
    await page.getByRole("button", { name: "← Izgaraya dön" }).click();
    await expect(grid).toBeVisible();
    await page.getByRole("button", { name: "Tam ekran görünümünden çık" }).click();
    await expect(page.getByRole("heading", { name: "İzleme" })).toBeVisible();
    expect((await grid.boundingBox())!.y).toBeGreaterThan(0);
    await page.setViewportSize({ width: 375, height: 740 });             // dikeye dönünce kaplama hiç yok
    await expect(page.getByRole("button", { name: "Tam ekran görünümünden çık" })).toHaveCount(0);
  });
});

test("izleme: kısa masaüstü penceresi (fare) telefon yatay görünümü sayılmaz", async ({ page }) => {
  await mock(page, STATUS);
  await login(page);
  await page.setViewportSize({ width: 740, height: 360 });             // yatay ve kısa, ama işaretçi ince (fare)
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  await expect(page.getByRole("heading", { name: "İzleme" })).toBeVisible();   // araç çubuğu gizlenmez
  expect((await page.getByTestId("watch-grid").boundingBox())!.y).toBeGreaterThan(0);
  await expect(page.getByRole("button", { name: "Tam ekran görünümünden çık" })).toHaveCount(0);
});

test.describe("telefon (dokunmatik)", () => {
  test.use({ viewport: { width: 375, height: 740 }, hasTouch: true, isMobile: true });

  test("izleme: kutuya dokununca tek kamera açılır; Canlı sayıma git tek kamera başlığında", async ({ page }) => {
    await mock(page, STATUS);
    await login(page);
    const tiles = page.getByTestId("watch-tile");
    await expect(tiles.nth(0)).toContainText("Kapı");
    await tiles.nth(0).tap();
    await expect(page.getByRole("heading", { name: "Kapı" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Canlı sayıma git" })).toHaveAttribute("href", "/live?s=s1");
    await page.getByRole("button", { name: "← Izgaraya dön" }).click();
    await page.getByTestId("watch-tile").nth(2).tap();                  // analizi olmayan kamera → Kameralar sayfası
    await expect(page.getByRole("heading", { name: "Arka kapı" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Canlı sayıma git" })).toHaveAttribute("href", "/cameras");
  });
});

test("izleme: şablon değişince eski boyutla akış istenmez (tek istek, yeni düzenin boyutu)", async ({ page }) => {
  const view2 = { id: "v2", name: "Yan yana", layout: "2", createdAt: 2, updatedAt: 2, tiles: [{ sourceId: "a", channelId: null }, null] };
  await mock(page, STATUS, [VIEW, view2]);
  await page.route("**/api/live/views/v2/status", (r) => r.fulfill({ json: { id: "v2", layout: "2", tiles: [STATUS.tiles[0], null] } }));
  const sizes: string[] = [];
  await page.route("**/api/live/views/v2/stream**", (r) => {
    const q = new URL(r.request().url()).searchParams;
    sizes.push(`${q.get("w")}x${q.get("h")}`);
    return r.fulfill({ body: JPEG, contentType: "image/jpeg" });
  });
  await login(page);
  await expect(page.getByAltText("Giriş katı canlı görüntü")).toBeVisible();
  await page.getByRole("combobox", { name: "Şablon" }).selectOption("v2");
  await expect(page.getByAltText("Yan yana canlı görüntü")).toBeVisible();
  await page.waitForTimeout(800);                                      // boyut durulma süresi geçsin
  expect(sizes).toHaveLength(1);                                       // eski (kareye yakın) boyutla bir istek daha gitmedi
  const [w, h] = sizes[0].split("x").map(Number);
  expect(w / h).toBeGreaterThan(3);                                    // 2×1 düzen: oran 32/9
});

test("izleme: yeni şablon — düzen seç, kamera ata (tıkla + listeden), sürükleyerek yer değiştir, kaydet", async ({ page }) => {
  let saved: unknown = null;
  await mock(page, STATUS);
  await page.route("**/api/live/sources", (r) => r.fulfill({ json: [
    { id: "a", kind: "camera", name: "Kapı", brand: "custom", hasPassword: false },
    { id: "nvr", kind: "recorder", name: "Ofis NVR", recorderBrand: "hikvision", hasPassword: true },
  ] }));
  await page.route("**/api/live/sources/nvr/channels", (r) => r.fulfill({ json: [
    { id: "1", name: "Giriş", number: 1, title: "Giriş", hasSubstream: true },
    { id: "2", name: "Kasa", number: 2, title: "Kasa", hasSubstream: true },
  ] }));
  await page.route("**/api/live/sources/*/snapshot**", (r) => r.fulfill({ body: JPEG, contentType: "image/jpeg" }));
  await page.route("**/api/live/views", async (r) => {
    if (r.request().method() === "POST") {
      saved = r.request().postDataJSON();
      return r.fulfill({ json: { id: "v2", createdAt: 2, updatedAt: 2, ...(saved as object) } });
    }
    return r.fulfill({ json: [VIEW] });
  });
  await login(page);
  await page.getByRole("button", { name: "Yeni şablon" }).click();
  const ed = page.getByRole("region", { name: "Şablon düzenleyici" });
  await ed.getByLabel("Şablon adı").fill("Kasa ve giriş");
  await ed.getByRole("button", { name: "2'li (yan yana)" }).click();
  await ed.getByTestId("edit-tile").nth(0).click();                           // kutuyu seç
  await ed.getByRole("button", { name: "Kapı" }).click();                       // listeden kamera
  await ed.getByRole("button", { name: /Ofis NVR/ }).click();                   // kayıt cihazını aç
  await ed.getByTestId("edit-tile").nth(1).click();
  await ed.getByRole("button", { name: "Kasa" }).click();
  await ed.getByTestId("edit-tile").nth(0).dragTo(ed.getByTestId("edit-tile").nth(1));   // yer değiştir
  await ed.getByRole("button", { name: "Kaydet" }).click();
  expect(saved).toEqual({ name: "Kasa ve giriş", layout: "2",
    tiles: [{ sourceId: "nvr", channelId: "2" }, { sourceId: "a", channelId: null }] });
});

test("izleme: düzen küçülünce sığmayan kameralar uyarılır; aynı kamera iki kutuya konmaz", async ({ page }) => {
  await mock(page, STATUS);
  await page.route("**/api/live/sources", (r) => r.fulfill({ json: [
    { id: "a", kind: "camera", name: "Kapı", brand: "custom", hasPassword: false }] }));
  await page.route("**/api/live/sources/*/snapshot**", (r) => r.fulfill({ body: JPEG, contentType: "image/jpeg" }));
  await login(page);
  await page.getByRole("button", { name: "Düzenle" }).click();
  const ed = page.getByRole("region", { name: "Şablon düzenleyici" });
  await ed.getByRole("button", { name: "Tek" }).click();
  await expect(ed.getByRole("status")).toContainText("2 kamera düzene sığmadı");
  await ed.getByTestId("edit-tile").nth(0).click();
  await expect(ed.getByRole("button", { name: "Kapı" })).toBeDisabled();            // zaten şablonda
});

const AUTH = "Oturum süresi doldu — yeniden giriş yapın.";
const LIVE_CAM = { name: "Kapı", state: "live", message: "", fps: 10, analysis: null };

test("izleme: tek kamera bağlı değilken akış 30 sn'de bir baştan açılır; bağlanınca hemen", async ({ page }) => {
  await mock(page, STATUS);
  let cam: object = { ...LIVE_CAM, state: "error", message: "Kamera yanıt vermiyor." };
  await page.route("**/api/live/cameras/status**", (r) => r.fulfill({ json: cam }));
  const ks = await streamKeys(page, "**/api/live/cameras/stream**");
  await page.clock.install();
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  await page.getByTestId("watch-tile").nth(0).dblclick();
  await expect(page.getByText("Bağlantı yok — Kamera yanıt vermiyor.")).toBeVisible();
  const n = ks.length;
  await page.clock.runFor(31_000);                                   // sunucu akışı bitirmiş olabilir: 30 sn'de bir baştan
  await expect.poll(() => ks.length).toBeGreaterThan(n);
  cam = LIVE_CAM;                                                    // kamera döndü: bir sonraki yoklamada hemen yeni akış
  const m = ks.length;
  for (let i = 0; i < 10 && ks.length === m; i++) {
    await page.clock.runFor(1_600);
    await page.waitForTimeout(100);
  }
  expect(ks.length).toBeGreaterThan(m);
  await expect(page.getByRole("status")).toHaveCount(0);             // canlı: yazı kalkar
  const k = ks.length;
  await page.clock.runFor(61_000);                                   // canlıyken yeniden açma yok
  await page.waitForTimeout(300);
  expect(ks.length).toBe(k);
});

test("izleme: tek kamerada yoklama kopunca 'ulaşılamıyor', 401'de 'oturum doldu', 404'te 'Kamera silinmiş.' yazılır", async ({ page }) => {
  await mock(page, STATUS);
  let mode: "live" | 502 | 401 | 404 = "live";
  await page.route("**/api/live/cameras/status**", (r) => (mode === "live" ? r.fulfill({ json: LIVE_CAM })
    : r.fulfill({ status: mode, json: { detail: mode === 404 ? "Kaynak bulunamadı." : "Hata." } })));
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  await page.getByTestId("watch-tile").nth(0).dblclick();
  await expect(page.getByRole("heading", { name: "Kapı" })).toBeVisible();
  await expect(page.getByRole("status")).toHaveCount(0);             // canlı
  mode = 502;
  await expect(page.getByText(DOWN)).toBeVisible();                  // üst üste 3 hatadan sonra; eski "canlı" kalmaz
  mode = 401;
  await expect(page.getByText(AUTH)).toBeVisible();
  await expect(page.getByText(DOWN)).toBeHidden();
  await expect(page.getByRole("link", { name: "Giriş yap" })).toHaveAttribute("href", "/login?next=%2Fwatch");
  mode = 404;
  await expect(page.getByText("Kamera silinmiş.")).toBeVisible();
  await expect(page.getByText(AUTH)).toBeHidden();
  mode = "live";
  await expect(page.getByRole("status")).toHaveCount(0);
});

test("izleme: şablon yoklaması 3 ardışık hatadan sonra uyarır; 401 ile sunucu yok ayrılır; düzelince kalkar", async ({ page }) => {
  await mock(page, STATUS);
  let mode: "live" | 502 | 401 = "live";
  await page.route("**/api/live/views/v1/status", (r) => (mode === "live" ? r.fulfill({ json: STATUS })
    : r.fulfill({ status: mode, json: { detail: "Hata." } })));
  const ks = await streamKeys(page, "**/api/live/views/v1/stream**");
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  mode = 502;
  await page.waitForTimeout(1800);                                   // 1-2 hata: uyarı yok (tek aksama uyarı çıkarmaz)
  await expect(page.getByText(DOWN)).toBeHidden();
  await expect(page.getByText(DOWN)).toBeVisible();                  // 3. ardışık hata
  mode = 401;
  await expect(page.getByText(AUTH)).toBeVisible();
  await expect(page.getByText(DOWN)).toBeHidden();
  await expect(page.getByRole("link", { name: "Giriş yap" })).toHaveAttribute("href", "/login?next=%2Fwatch");
  mode = "live";
  await expect(page.getByText(AUTH)).toBeHidden();
  await expect.poll(() => ks, { timeout: 15_000 }).toContain("1");    // düzelince akış baştan
});

test("izleme: ızgara akışı sekme görünürken 15 dk'da bir baştan açılır (sessiz takılmaya karşı)", async ({ page }) => {
  await mock(page, STATUS);
  const ks = await streamKeys(page, "**/api/live/views/v1/stream**");
  await page.clock.install();
  await login(page);
  await expect(page.getByAltText("Giriş katı canlı görüntü")).toBeVisible();
  await expect.poll(() => ks.length).toBe(1);
  await page.clock.runFor(14 * 60_000);
  await page.waitForTimeout(300);
  expect(ks.length).toBe(1);                                          // henüz 15 dk dolmadı
  await page.clock.runFor(61_000);
  await expect.poll(() => ks.length).toBe(2);
  expect(new Set(ks).size).toBe(2);                                   // yeni anahtar
});

/** Düzenleyici testleri için sahte şablon deposu: GET/POST/PUT/DELETE views */
async function mockStore(page: Page, initial: object[]) {
  const store = [...initial] as Array<{ id: string }>;
  const calls: Array<{ method: string; url: string; body: unknown }> = [];
  await page.route("**/api/live/views", async (r) => {
    const req = r.request();
    if (req.method() === "POST") {
      const body = req.postDataJSON() as object;
      calls.push({ method: "POST", url: req.url(), body });
      const v = { id: `n${store.length + 1}`, createdAt: 5, updatedAt: 5, ...body };
      store.push(v);
      return r.fulfill({ json: v });
    }
    return r.fulfill({ json: store });
  });
  await page.route("**/api/live/views/*", async (r) => {
    const req = r.request();
    const id = new URL(req.url()).pathname.split("/").pop()!;
    if (req.method() === "PUT") {
      const body = req.postDataJSON() as object;
      calls.push({ method: "PUT", url: req.url(), body });
      const i = store.findIndex((v) => v.id === id);
      store[i] = { ...store[i], ...body };
      return r.fulfill({ json: store[i] });
    }
    if (req.method() === "DELETE") {
      calls.push({ method: "DELETE", url: req.url(), body: null });
      store.splice(store.findIndex((v) => v.id === id), 1);
      return r.fulfill({ status: 204 });
    }
    return r.fallback();
  });
  return { store, calls };
}

test("izleme: Kopyala şablonu '(kopya)' adıyla çoğaltır ve ona geçer; çift tık tek kopya açar", async ({ page }) => {
  await mock(page, STATUS);
  const { calls } = await mockStore(page, [VIEW]);
  await page.route("**/api/live/views/n2/status", (r) => r.fulfill({ json: { id: "n2", layout: "4", tiles: STATUS.tiles } }));
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  await page.getByRole("button", { name: "Kopyala" }).dblclick();
  const sel = page.getByRole("combobox", { name: "Şablon" });
  await expect(sel).toContainText("Giriş katı (kopya)");
  await expect(sel).toHaveValue("n2");
  expect(calls).toHaveLength(1);
  expect(calls[0].body).toEqual({ name: "Giriş katı (kopya)", layout: "4", tiles: VIEW.tiles });
});

test("izleme: Tüm kanallardan şablon yeni şablonu kurar ve 16'dan fazlaysa söyler", async ({ page }) => {
  await mock(page, STATUS);
  await page.route("**/api/live/sources", (r) => r.fulfill({ json: [
    { id: "a", kind: "camera", name: "Kapı", brand: "custom", hasPassword: false },
    { id: "nvr", kind: "recorder", name: "Ofis NVR", recorderBrand: "hikvision", hasPassword: true }] }));
  const { store } = await mockStore(page, [VIEW]);
  const tiles16 = Array.from({ length: 16 }, (_, i) => ({ sourceId: "nvr", channelId: String(i + 1) }));
  await page.route("**/api/live/views/from-recorder", (r) => {
    expect(r.request().postDataJSON()).toEqual({ sourceId: "nvr" });
    const v = { id: "r1", name: "Ofis NVR", layout: "16", tiles: tiles16, createdAt: 6, updatedAt: 6, truncated: true, channelCount: 20 };
    store.push(v);
    return r.fulfill({ json: v });
  });
  await page.route("**/api/live/views/r1/status", (r) => r.fulfill({ json: { id: "r1", layout: "16", tiles: [] } }));
  await login(page);
  const sel = page.getByRole("combobox", { name: "Şablon", exact: true });          // "Tüm kanallardan şablon" ile karışmasın
  const pick = page.getByRole("combobox", { name: "Tüm kanallardan şablon" });
  await expect(pick).toBeVisible();                                   // yalnız kayıt cihazları listelenir
  await expect(pick.locator("option")).toHaveText(["Tüm kanallardan şablon…", "Ofis NVR"]);
  await pick.selectOption("nvr");
  await expect(sel).toHaveValue("r1");
  await expect(page.getByText("İlk 16 kanal alındı (toplam 20).")).toBeVisible();
  await sel.selectOption("v1");   // başka şablona geçince bilgi kalkar
  await expect(page.getByText("İlk 16 kanal alındı")).toHaveCount(0);
});

test("izleme: şablonu düzenle (PUT), boşalt, Vazgeç; sunucu reddederse ileti gösterilir; sil", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  await mock(page, STATUS);
  await page.route("**/api/live/sources", (r) => r.fulfill({ json: [] }));
  const { calls } = await mockStore(page, [VIEW]);
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  // düzenleyici açılınca araç çubuğundaki şablon düğmeleri gizlenir; Vazgeç ızgaraya döner
  await page.getByRole("button", { name: "Düzenle" }).click();
  const ed = page.getByRole("region", { name: "Şablon düzenleyici" });
  await expect(page.getByRole("button", { name: "Yeni şablon" })).toHaveCount(0);
  await expect(page.getByTestId("watch-grid")).toHaveCount(0);
  await expect(ed.getByLabel("Şablon adı")).toHaveValue("Giriş katı");
  await expect(ed.getByTestId("edit-tile").nth(1)).toContainText("Ofis NVR · Kasa");   // adlar son durumdan
  await ed.getByRole("button", { name: "Vazgeç" }).click();
  await expect(page.getByTestId("watch-tile")).toHaveCount(4);
  // yeniden aç, ilk kutuyu boşalt, adı değiştir, kaydet → PUT
  await page.getByRole("button", { name: "Düzenle" }).click();
  await ed.getByTestId("edit-tile").nth(0).getByRole("button", { name: "Boşalt" }).click();
  await ed.getByLabel("Şablon adı").fill("Yeni ad");
  await ed.getByRole("button", { name: "Kaydet" }).click();
  await expect(page.getByRole("combobox", { name: "Şablon" })).toContainText("Yeni ad");
  expect(calls).toHaveLength(1);
  expect(calls[0].method).toBe("PUT");
  expect(calls[0].body).toEqual({ name: "Yeni ad", layout: "4",
    tiles: [null, { sourceId: "b", channelId: "2" }, { sourceId: "c", channelId: null }, null] });
  // sunucu reddederse ileti düzenleyicide kalır
  await page.route("**/api/live/views/v1", (r) => (r.request().method() === "PUT"
    ? r.fulfill({ status: 422, json: { detail: "Aynı kamera bir şablonda yalnızca bir kez yer alabilir." } }) : r.fallback()));
  await page.getByRole("button", { name: "Düzenle" }).click();
  await ed.getByRole("button", { name: "Kaydet" }).click();
  await expect(ed.getByRole("alert")).toContainText("Aynı kamera bir şablonda yalnızca bir kez yer alabilir.");
  // sil
  await ed.getByRole("button", { name: "Şablonu sil" }).click();
  await expect(page.locator("p", { hasText: "Henüz şablon yok" })).toBeVisible();
  expect(calls.at(-1)).toMatchObject({ method: "DELETE" });
});
