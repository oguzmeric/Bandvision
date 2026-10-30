import { expect, test, type Locator, type Page, type Route } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

/**
 * Canlı izleme sayfası, SAHTE API ile (page.route): şablon sekmeleri, Şablon editörü, kamera listesi (sürükle-bırak,
 * dokun-seç), canlı taslak, kaydedilmemiş değişiklik bekçisi; ızgara, kutu katmanları, tek kamera, alarm, video duvarı ve
 * akış yeniden bağlanması. Gerçek akış e2e/watch.spec.ts'te.
 */
/** Gerçek düzen kataloğu (sözleşme): editörün hazır düzen düğmeleri katalog kimliklerini kullanır */
const LAYOUTS = (JSON.parse(readFileSync(path.resolve(__dirname, "../../../contracts/view-layouts.json"), "utf8")) as { layouts: object[] }).layouts;
const VIEW = { id: "v1", name: "Giriş katı", layout: "4", createdAt: 1, updatedAt: 1,
  tiles: [{ sourceId: "a", channelId: null }, { sourceId: "b", channelId: "2" }, { sourceId: "c", channelId: null }, null] };
// 1×1 siyah JPEG (akış yerine; tek parça yeterli)
const JPEG = Buffer.from("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==", "base64");

/** Kamera listesi: tek kameralar ve bir kayıt cihazı (kanalları: Giriş, Kasa) */
const SOURCES = [
  { id: "a", kind: "camera", name: "Kapı", brand: "custom", hasPassword: false },
  { id: "c", kind: "camera", name: "Arka kapı", brand: "custom", hasPassword: false },
  { id: "d", kind: "camera", name: "Depo", brand: "custom", hasPassword: false },
  { id: "b", kind: "recorder", name: "Ofis NVR", recorderBrand: "hikvision", hasPassword: true },
];
const CHANNELS = [
  { id: "1", name: "Giriş", number: 1, title: "Giriş", hasSubstream: true },
  { id: "2", name: "Kasa", number: 2, title: "Kasa", hasSubstream: true },
];
const NAMES: Record<string, string> = { "a|": "Kapı", "c|": "Arka kapı", "d|": "Depo", "b|1": "Ofis NVR · Giriş", "b|2": "Ofis NVR · Kasa" };

type Ref = { sourceId: string; channelId: string | null } | null;
type Call = { method: string; url: string; body: unknown };
/** Sahte taslak deposu (`views/drafts`): istekleri kaydeder; durum, kutulardaki kameraları canlı bildirir */
async function mockDrafts(page: Page) {
  const store = new Map<string, { layout: string; tiles: Ref[] }>();
  const calls: Call[] = [];
  let n = 0;
  await page.route("**/api/live/views/drafts", (r) => {
    const req = r.request();
    if (req.method() !== "POST") return r.fallback();
    const body = req.postDataJSON() as { layout: string; tiles: Ref[] };
    calls.push({ method: "POST", url: req.url(), body });
    const id = `draft-${++n}`;
    store.set(id, body);
    return r.fulfill({ status: 201, json: { id, name: "Taslak", createdAt: 1, updatedAt: 1, ...body } });
  });
  await page.route("**/api/live/views/drafts/*", (r) => {
    const req = r.request();
    const id = new URL(req.url()).pathname.split("/").pop()!;
    calls.push({ method: req.method(), url: req.url(), body: req.method() === "PUT" ? req.postDataJSON() : null });
    if (!store.has(id)) return r.fulfill({ status: 404, json: { detail: "Taslak bulunamadı." } });
    if (req.method() === "DELETE") { store.delete(id); return r.fulfill({ status: 204 }); }
    store.set(id, req.postDataJSON());
    return r.fulfill({ json: { id, name: "Taslak", createdAt: 1, updatedAt: 2, ...store.get(id) } });
  });
  await page.route("**/api/live/views/draft-*/status", (r) => {
    const id = r.request().url().split("/").at(-2)!;
    const d = store.get(id);
    if (!d) return r.fulfill({ status: 404, json: { detail: "Şablon bulunamadı." } });
    return r.fulfill({ json: { id, layout: d.layout, tiles: d.tiles.map((t) => t && {
      ...t, name: NAMES[`${t.sourceId}|${t.channelId ?? ""}`] ?? "Kamera", state: "live", message: "", fps: 10, analysis: null }) } });
  });
  await page.route("**/api/live/views/draft-*/stream**", (r) => r.fulfill({ body: JPEG, contentType: "image/jpeg" }));
  return { store, calls };
}

async function mock(page: Page, status: object, view: object | object[] = VIEW) {
  await page.route("**/api/live/view-layouts", (r) => r.fulfill({ json: LAYOUTS }));
  await page.route("**/api/live/views", (r) => r.fulfill({ json: Array.isArray(view) ? view : [view] }));
  await page.route("**/api/live/views/v1/status", (r) => r.fulfill({ json: status }));
  await page.route("**/api/live/views/v1/stream**", (r) => r.fulfill({ body: JPEG, contentType: "image/jpeg" }));
  await page.route("**/api/live/cameras/**", (r) => r.fulfill({ body: JPEG, contentType: "image/jpeg" }));
  await page.route("**/api/live/alarms?active=1", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/live/sessions", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/live/sources", (r) => r.fulfill({ json: SOURCES }));
  await page.route("**/api/live/sources/b/channels", (r) => r.fulfill({ json: CHANNELS }));
  return mockDrafts(page);
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
  await expect(page.getByRole("heading", { name: "Canlı izleme" })).toBeVisible();
}

test("izleme: şablon ızgarası, adlar, rozetler, hata ve alarm çerçevesi", async ({ page }) => {
  await mock(page, STATUS);
  await login(page);
  await expect(page.getByRole("tab", { name: "Giriş katı" })).toHaveAttribute("aria-selected", "true");
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
  const tabs = await page.getByRole("tablist", { name: "Şablonlar" }).boundingBox();
  expect(tabs!.y + tabs!.height).toBeLessThanOrEqual(box!.y);                                        // sekmeler ızgaranın üstünde
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
  await expect(page.getByRole("navigation", { name: "Ana menü" }).getByRole("link", { name: "Canlı izleme", exact: true })).toHaveAttribute("aria-current", "page");
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
  await expect(page.getByRole("tab", { name: "Giriş katı" })).toHaveAttribute("aria-selected", "true", { timeout: 15_000 });   // ≈5 sn sonra
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
  await expect(page.getByRole("main").getByRole("status")).toHaveCount(0);                  // canlı: yazı kalkar
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
  await tiles.nth(0).dblclick();                                       // yine de açılır (ad yedeği: kamera listesindeki ad)
  await expect(page.getByRole("heading", { name: "Kapı", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Canlı sayıma git" })).toHaveAttribute("href", "/cameras");
});

test("izleme: klavyeyle kutu seçme ve açma (Enter seçer, seçiliyken Enter/Boşluk açar); iç bağlantıdaki Enter kutuyu açmaz", async ({ page }) => {
  await mock(page, STATUS);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  await tiles.nth(0).focus();
  await expect(tiles.nth(0)).not.toHaveAttribute("data-selected", "true");      // odak seçmez
  await page.keyboard.press("Enter");
  await expect(tiles.nth(0)).toHaveAttribute("data-selected", "true");
  await expect(page.getByRole("heading", { name: "Kapı" })).toHaveCount(0);
  await page.keyboard.press("Enter");                                          // seçili kutu: tek kamera
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
    await expect(page.getByRole("heading", { name: "Canlı izleme" })).toBeHidden();
    await expect.poll(async () => grid.boundingBox()).toEqual({ x: 0, y: 0, width: 740, height: 360 });
    // tek kamerada da görüntü ekranı kaplar; geri dönülünce ızgara yine kaplar
    await page.getByTestId("watch-tile").nth(0).dblclick();
    const img = (await page.getByAltText("Kapı canlı görüntü").boundingBox())!;
    expect([img.x, img.y, img.width, img.height]).toEqual([0, 0, 740, 360]);
    await page.getByRole("button", { name: "← Izgaraya dön" }).click();
    await expect(grid).toBeVisible();
    await page.getByRole("button", { name: "Tam ekran görünümünden çık" }).click();
    await expect(page.getByRole("heading", { name: "Canlı izleme" })).toBeVisible();
    expect((await grid.boundingBox())!.y).toBeGreaterThan(0);
    await page.setViewportSize({ width: 375, height: 740 });             // dikeye dönünce kaplama hiç yok
    await expect(page.getByRole("button", { name: "Tam ekran görünümünden çık" })).toHaveCount(0);
  });
});

test("izleme: kısa masaüstü penceresi (fare) telefon yatay görünümü sayılmaz", async ({ page }) => {
  await mock(page, STATUS);
  await login(page);
  await page.setViewportSize({ width: 740, height: 360 });             // yatay ve kısa, ama işaretçi ince (fare)
  // Ortam gerçekten "yatay ve kısa, işaretçi ince" olsun ve değişiklik olayı işlensin; sonra kaplama olmadığı doğrulanır
  await expect.poll(() => page.evaluate(() => window.matchMedia("(orientation: landscape) and (max-height: 500px)").matches)).toBe(true);
  expect(await page.evaluate(() => window.matchMedia("(pointer: coarse)").matches)).toBe(false);
  await page.evaluate(() => new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done()))));
  await page.waitForTimeout(500);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  await expect(page.getByRole("heading", { name: "Canlı izleme" })).toBeVisible();   // araç çubuğu gizlenmez
  expect((await page.getByTestId("watch-grid").boundingBox())!.y).toBeGreaterThan(0);
  await expect(page.getByRole("button", { name: "Tam ekran görünümünden çık" })).toHaveCount(0);
});

test.describe("telefon (dokunmatik)", () => {
  test.use({ viewport: { width: 375, height: 740 }, hasTouch: true, isMobile: true });

  test("izleme: kutuya dokununca seçilir, yeniden dokununca tek kamera açılır; Canlı sayıma git tek kamera başlığında", async ({ page }) => {
    await mock(page, STATUS);
    await login(page);
    const tiles = page.getByTestId("watch-tile");
    await expect(tiles.nth(0)).toContainText("Kapı");
    await tiles.nth(0).tap();                                            // ilk dokunuş kutuyu seçer (kamera atamak için)
    await expect(tiles.nth(0)).toHaveAttribute("data-selected", "true");
    await expect(page.getByRole("heading", { name: "Kapı" })).toHaveCount(0);
    await tiles.nth(0).tap();                                            // seçili kutuya yeniden dokunmak tek kamerayı açar
    await expect(page.getByRole("heading", { name: "Kapı" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Canlı sayıma git" })).toHaveAttribute("href", "/live?s=s1");
    await page.getByRole("button", { name: "← Izgaraya dön" }).click();
    await page.getByTestId("watch-tile").nth(2).tap();
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
  await page.getByRole("tab", { name: "Yan yana" }).click();
  await expect(page.getByAltText("Yan yana canlı görüntü")).toBeVisible();
  await page.waitForTimeout(800);                                      // boyut durulma süresi geçsin
  expect(sizes).toHaveLength(1);                                       // eski (kareye yakın) boyutla bir istek daha gitmedi
  const [w, h] = sizes[0].split("x").map(Number);
  expect(w / h).toBeGreaterThan(3);                                    // 2×1 düzen: oran 32/9
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
  await expect(page.getByRole("main").getByRole("status")).toHaveCount(0);             // canlı: yazı kalkar
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
  await expect(page.getByRole("main").getByRole("status")).toHaveCount(0);             // canlı
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
  await expect(page.getByRole("main").getByRole("status")).toHaveCount(0);
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

/** Şablon işlemleri testleri için sahte şablon deposu: GET/POST/PUT/DELETE views (PUT, gerçek sunucu gibi `updatedAt`'i artırır) */
async function mockStore(page: Page, initial: object[]) {
  const store = [...initial] as Array<{ id: string; layout?: string; name?: string; updatedAt?: number }>;
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
      if (i < 0) return r.fulfill({ status: 404, json: { detail: "Şablon bulunamadı." } });
      store[i] = { ...store[i], ...body, updatedAt: (store[i].updatedAt ?? 0) + 1 };
      return r.fulfill({ json: store[i] });
    }
    if (req.method() === "DELETE") {
      calls.push({ method: "DELETE", url: req.url(), body: null });
      store.splice(store.findIndex((v) => v.id === id), 1);
      return r.fulfill({ status: 204 });
    }
    return r.fallback();
  });
  // Yeni (v1 dışı) şablonların durum ve akışı; v1 için mock()'un yolları geçerli kalır
  await page.route("**/api/live/views/*/status", (r) => {
    const id = r.request().url().split("/").at(-2)!;
    return id === "v1" || id.startsWith("draft-") ? r.fallback() : r.fulfill({ json: { id, layout: store.find((v) => v.id === id)?.layout ?? "4", tiles: [] } });
  });
  await page.route("**/api/live/views/*/stream**", (r) => (/\/views\/(v1|draft-[^/]+)\//.test(r.request().url())
    ? r.fallback() : r.fulfill({ body: JPEG, contentType: "image/jpeg" })));
  return { store, calls };
}

test("izleme: silinmiş kamerada (404) tek kamera akışı 30 sn'de bir boşuna yeniden açılmaz", async ({ page }) => {
  await mock(page, STATUS);
  await page.route("**/api/live/cameras/status**", (r) => r.fulfill({ status: 404, json: { detail: "Kaynak bulunamadı." } }));
  const ks = await streamKeys(page, "**/api/live/cameras/stream**");
  await page.clock.install();
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  await page.getByTestId("watch-tile").nth(0).dblclick();
  await expect(page.getByText("Kamera silinmiş.")).toBeVisible();
  const n = ks.length;
  await page.clock.runFor(95_000);                                    // 3 yeniden açma aralığı geçse de
  await page.waitForTimeout(300);
  expect(ks.length).toBe(n);
  await expect(page.getByText("Kamera silinmiş.")).toBeVisible();
});

// ---- Son düzeltme turu: başka cihazda düzenlenen şablon, gizli sekme, silinmiş kamera, sürükleyerek yer değiştirme

test("izleme: şablon başka yerde düzenlenirse (durum farklı düzen/kamera bildirir) liste yeniden alınır, katmanlar güncellenir", async ({ page }) => {
  await mock(page, STATUS);
  const cam = (sourceId: string, name: string) => ({ sourceId, channelId: null, name, state: "live", message: "", fps: 10, analysis: null });
  const V1 = { ...VIEW, layout: "2", tiles: [{ sourceId: "a", channelId: null }, { sourceId: "d", channelId: null }] };
  const S1 = { id: "v1", layout: "2", tiles: [STATUS.tiles[0], cam("d", "Depo")] };
  const V2 = { ...V1, tiles: [{ sourceId: "e", channelId: null }, { sourceId: "d", channelId: null }] };
  const S2 = { id: "v1", layout: "2", tiles: [cam("e", "Ek kamera"), cam("d", "Depo")] };
  let edited = 0;                                                    // 0: ilk hâl, 1: düzen değişti, 2: kutudaki kamera değişti
  let listed = 0;
  await page.route("**/api/live/views", (r) => { listed += 1; return r.fulfill({ json: [[VIEW, V1, V2][edited]] }); });
  await page.route("**/api/live/views/v1/status", (r) => r.fulfill({ json: [STATUS, S1, S2][edited] }));
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  await expect(tiles).toHaveCount(4);
  const before = listed;
  edited = 1;                                                        // başka bir cihazda düzen 2'liye çevrildi
  await expect(tiles).toHaveCount(2);
  await expect(tiles.nth(1)).toContainText("Depo");
  expect(listed).toBe(before + 1);                                   // bu uyuşmazlık için tek yeniden yükleme
  edited = 2;                                                        // aynı düzen, kutudaki kamera değişti
  await expect(tiles.nth(0)).toContainText("Ek kamera");
  await page.waitForTimeout(3500);                                   // eşleşince yeniden yükleme durur (≥2 yoklama turu)
  expect(listed).toBe(before + 2);
});

/** Sekmeyi gizli/görünür yapar (tarayıcı sekme değişimini taklit eder) */
async function setHidden(page: Page, hidden: boolean) {
  await page.evaluate((h) => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => h });
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => (h ? "hidden" : "visible") });
    document.dispatchEvent(new Event("visibilitychange"));
  }, hidden);
}

test("izleme: gizli sekmede akış bırakılır (görüntü kalkar), sekmeye dönünce yeni anahtarla açılır; tek kamerada da", async ({ page }) => {
  await mock(page, STATUS);
  const ks = await streamKeys(page, "**/api/live/views/v1/stream**");
  const cks = await streamKeys(page, "**/api/live/cameras/stream**");
  await login(page);
  const img = page.getByAltText("Giriş katı canlı görüntü");
  await expect(img).toBeVisible();
  await setHidden(page, true);
  await expect(img).toHaveCount(0);                                  // akış isteği düştü
  const n = ks.length;
  await setHidden(page, false);
  await expect(img).toBeVisible();
  await expect.poll(() => ks.length).toBeGreaterThan(n);
  expect(new Set(ks).size).toBe(ks.length);                          // yeni anahtar
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  await page.getByTestId("watch-tile").nth(0).dblclick();
  const one = page.getByAltText("Kapı canlı görüntü");
  await expect(one).toBeVisible();
  await setHidden(page, true);
  await expect(one).toHaveCount(0);
  const m = cks.length;
  await setHidden(page, false);
  await expect(one).toBeVisible();
  await expect.poll(() => cks.length).toBeGreaterThan(m);
});

test("izleme: silinmiş kamerada akış hatası (404) tek kamerayı tekrar tekrar yeniden açtırmaz", async ({ page }) => {
  await mock(page, STATUS);
  await page.route("**/api/live/cameras/status**", (r) => r.fulfill({ status: 404, json: { detail: "Kaynak bulunamadı." } }));
  let streams = 0;
  await page.route("**/api/live/cameras/stream**", (r) => { streams += 1; return r.fulfill({ status: 404, json: { detail: "Kaynak bulunamadı." } }); });
  await page.clock.install();
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  await page.getByTestId("watch-tile").nth(0).dblclick();
  await expect(page.getByText("Kamera silinmiş.")).toBeVisible();
  await page.clock.runFor(3_000);                                    // silinmiş bilinmeden kurulmuş tek bekleme bitsin
  await page.waitForTimeout(200);
  const n = streams;
  await page.clock.runFor(20_000);                                   // hata başına 2 sn'de bir yeniden açmaz
  await page.waitForTimeout(300);
  expect(streams).toBe(n);
});

// ---- Sekmeler, Şablon editörü, kamera listesi, canlı taslak, kaydedilmemiş değişiklik bekçisi

const UNSAVED = "Kaydedilmedi, çıkılsın mı?";
const V2 = { id: "v2", name: "Depo katı", layout: "1", createdAt: 2, updatedAt: 2, tiles: [{ sourceId: "d", channelId: null }] };
const tab = (page: Page, name: string | RegExp) => page.getByRole("tablist", { name: "Şablonlar" }).getByRole("tab", { name, exact: true });
const editor = (page: Page) => page.getByRole("dialog", { name: "Şablon editörü" });
const cameras = (page: Page) => page.getByRole("complementary", { name: "Kameralar" });
/** Listedeki kamera düğmesi (erişilebilir adı "Kapı, canlı, şablonda" gibi durum ekleri alabilir) */
const camera = (page: Page, name: string) => cameras(page).getByRole("button", { name: new RegExp(`^${name}(,|$)`) });
const gridSrc = (page: Page) => page.getByTestId("watch-grid").locator("img").first();
/** Kaydedilmemiş düzenlemenin bu tarayıcı sekmesindeki kaydı (sessionStorage `bv.watch.unsaved`) */
const stored = (page: Page) => page.evaluate(() => {
  const raw = sessionStorage.getItem("bv.watch.unsaved");
  return raw === null ? null : JSON.parse(raw) as { origin: string; name: string; layout: string; tiles: unknown[]; updatedAt: number | null };
});
const RESTORED = "Kaydedilmemiş değişiklikler geri yüklendi.";
/** Kaydet, şablon bu düzenleme başladıktan sonra başka yerde değiştirildiyse sorar */
const CHANGED = "Bu şablon başka yerde değiştirildi. Üzerine yazılsın mı?";
const puts = (calls: Call[]) => calls.filter((c) => c.method === "PUT");
type Box = { x: number; y: number; width: number; height: number };
/** İki sınır kutusu üst üste biniyor mu (yalnız kenarları değen kutular binmez) */
const overlaps = (a: Box, b: Box) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

/**
 * Şablon editöründeki hazır düzen düğmesi, görünen adıyla ("4×3"). Erişilebilir adı sütun ve satırı sözle söyler
 * ("4×3: 4 sütun, 3 satır (12 kutu)").
 */
const preset = (ed: Locator, label: string) =>
  ed.getByRole("group", { name: "Düzenler:" }).getByRole("button", { name: new RegExp(`^${label.replace(/[+]/g, "\\+")}:`) });

async function openEditor(page: Page) {
  await page.getByRole("button", { name: "Şablon editörü" }).click();
  await expect(editor(page)).toBeVisible();
  return editor(page);
}

test("sekmeler: tıklayınca geçer; '+' 2×2 'Yeni şablon' açar; seçili sekme yeniden yüklemede hatırlanır", async ({ page }) => {
  await mock(page, STATUS, [VIEW, V2]);
  await page.route("**/api/live/views/v2/status", (r) => r.fulfill({ json: { id: "v2", layout: "1", tiles: [
    { sourceId: "d", channelId: null, name: "Depo", state: "live", message: "", fps: 10, analysis: null }] } }));
  await page.route("**/api/live/views/v2/stream**", (r) => r.fulfill({ body: JPEG, contentType: "image/jpeg" }));
  await login(page);
  await expect(tab(page, "Giriş katı")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("watch-tile")).toHaveCount(4);
  await tab(page, "Depo katı").click();
  await expect(tab(page, "Depo katı")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("watch-tile")).toHaveCount(1);
  await expect(page.getByTestId("watch-tile").first()).toContainText("Depo");
  await expect(page.getByAltText("Depo katı canlı görüntü")).toHaveAttribute("src", /\/api\/live\/views\/v2\/stream/);
  // klavye: ←/→ odak gezdirir, Enter seçer
  await tab(page, "Depo katı").focus();
  await page.keyboard.press("ArrowLeft");
  await expect(tab(page, "Giriş katı")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(tab(page, "Giriş katı")).toHaveAttribute("aria-selected", "true");
  await tab(page, "Depo katı").click();
  await page.reload();
  await expect(tab(page, "Depo katı")).toHaveAttribute("aria-selected", "true");     // hatırlandı
  // "+": 2×2 boş yeni şablon, kaydedilmemiş (sekmede yıldız), sunucuya henüz yazılmadı
  await page.getByRole("button", { name: "Yeni şablon" }).click();
  const fresh = tab(page, /^Yeni şablon/);
  await expect(fresh).toHaveAttribute("aria-selected", "true");
  await expect(fresh).toContainText("*");
  await expect(page.getByTestId("watch-tile")).toHaveCount(4);
  await expect(page.locator("[data-testid=watch-tile][data-empty=true]")).toHaveCount(4);
  await expect(page.getByText("Kaydedilmemiş değişiklik var")).toBeVisible();
});

test("sekme menüsü: sağ tık Yeniden adlandır / Kopyala / Sil; Sil onay ister; klavye (Shift+F10) ve ⋯ düğmesi", async ({ page }) => {
  await mock(page, STATUS);
  const { calls, store } = await mockStore(page, [VIEW, V2]);
  await page.route("**/api/live/views/v2/status", (r) => r.fulfill({ json: { id: "v2", layout: "1", tiles: [] } }));
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  await tab(page, "Giriş katı").click({ button: "right" });
  const menu = page.getByRole("menu", { name: "Şablon işlemleri" });
  await expect(menu.getByRole("menuitem")).toHaveText(["Yeniden adlandır", "Kopyala", "Sil"]);
  await expect(menu.getByRole("menuitem", { name: "Yeniden adlandır" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(tab(page, "Giriş katı")).toBeFocused();                            // odak sekmeye döner
  // Yeniden adlandır: yalnız ad değişir (PUT kayıtlı düzen ve kutularla)
  await tab(page, "Giriş katı").press("Shift+F10");
  await menu.getByRole("menuitem", { name: "Yeniden adlandır" }).click();
  const dlg = page.getByRole("dialog", { name: "Yeniden adlandır" });
  await dlg.getByLabel("Şablon adı").fill("Zemin kat");
  await dlg.getByRole("button", { name: "Tamam" }).click();
  await expect(tab(page, "Zemin kat")).toBeVisible();
  await expect(dlg).toBeHidden();
  expect(calls.at(-1)).toMatchObject({ method: "PUT", body: { name: "Zemin kat", layout: "4", tiles: VIEW.tiles } });
  // Kopyala: "(kopya)", sonra "(kopya) 2"; kopyaya geçilir
  await tab(page, "Zemin kat").click({ button: "right" });
  await menu.getByRole("menuitem", { name: "Kopyala" }).click();
  await expect(tab(page, "Zemin kat (kopya)")).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: "Şablon işlemleri: Zemin kat (kopya)" }).click();     // ⋯ düğmesi: seçili sekme
  await expect(menu).toBeVisible();
  await page.keyboard.press("Escape");
  await tab(page, "Zemin kat").click({ button: "right" });
  await menu.getByRole("menuitem", { name: "Kopyala" }).click();
  await expect(tab(page, "Zemin kat (kopya) 2")).toHaveAttribute("aria-selected", "true");
  expect(calls.filter((c) => c.method === "POST").map((c) => (c.body as { name: string }).name)).toEqual(["Zemin kat (kopya)", "Zemin kat (kopya) 2"]);
  // Sil: onay sorulur; Vazgeç silmez, Tamam siler
  let asked = "";
  page.once("dialog", (d) => { asked = d.message(); void d.dismiss(); });
  await tab(page, "Depo katı").click({ button: "right" });
  await menu.getByRole("menuitem", { name: "Sil" }).click();
  expect(asked).toBe('"Depo katı" şablonu silinsin mi?');
  await expect(tab(page, "Depo katı")).toBeVisible();
  page.once("dialog", (d) => void d.accept());
  await tab(page, "Depo katı").click({ button: "right" });
  await menu.getByRole("menuitem", { name: "Sil" }).click();
  await expect(tab(page, "Depo katı")).toHaveCount(0);
  expect(calls.at(-1)).toMatchObject({ method: "DELETE" });
  expect(store.map((v) => v.id)).not.toContain("v2");
});

test("sekme menüsü: Kopyala 60 karakterlik adı bölmeden '… (kopya)' yapar; ad doluysa '(kopya) 2' (60 sınırı içinde)", async ({ page }) => {
  // 60 kod noktası; 52. karakter (indeks 51) bir emoji (UTF-16'da iki birim): slice(0, 52) vekil çiftini bölerdi
  const long = `${"a".repeat(51)}😀${"b".repeat(8)}`;
  expect([...long]).toHaveLength(60);
  const view = { ...VIEW, name: long };
  await mock(page, STATUS, view);
  const { calls } = await mockStore(page, [view]);
  await login(page);
  const menu = page.getByRole("menu", { name: "Şablon işlemleri" });
  for (let i = 0; i < 2; i++) {
    await tab(page, long).click({ button: "right" });
    await menu.getByRole("menuitem", { name: "Kopyala" }).click();
    await expect.poll(() => calls.length).toBe(i + 1);
  }
  expect((calls[0].body as { name: string }).name).toBe(`${"a".repeat(51)}😀 (kopya)`);       // 52 kod noktası + " (kopya)"
  const second = (calls[1].body as { name: string }).name;
  expect(second).toBe(`${"a".repeat(50)} (kopya) 2`);
  expect([...second].length).toBeLessThanOrEqual(60);
});

test("Şablon editörü: menü öğeleri ve 10 düzen düğmesi; N×M 6×8 = 48 kutu; 16×9 reddedilir; Geri al / Yinele; Kaydet", async ({ page }) => {
  await mock(page, STATUS);
  const { calls } = await mockStore(page, [VIEW]);
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  const ed = await openEditor(page);
  for (const name of ["Yeni şablon", "Geri al", "Yinele", "Kaydet", "Farklı kaydet…"]) await expect(ed.getByRole("button", { name, exact: false }).first()).toBeVisible();
  await expect(ed.getByRole("button", { name: /^Geri al/ })).toBeDisabled();                  // henüz değişiklik yok
  await expect(ed.getByRole("button", { name: "Kaydet", exact: true })).toBeDisabled();
  const layoutButtons = ed.getByRole("group", { name: "Düzenler:" }).getByRole("button");
  await expect(layoutButtons).toHaveText(["1", "2×2", "3×3", "4×4", "1+5", "1+7", "4×3", "5×5", "8×8", "N×M"]);
  await expect(preset(ed, "2×2")).toHaveAttribute("aria-pressed", "true");
  // hazır düğmelerin adı ve ipucu sütun ile satırı açıkça söyler (görünen "4×3" sütun × satır; N×M girişi satır × sütun)
  for (const [label, name] of [["1", "1: 1 sütun, 1 satır (1 kutu)"], ["2×2", "2×2: 2 sütun, 2 satır (4 kutu)"],
    ["4×3", "4×3: 4 sütun, 3 satır (12 kutu)"], ["1+5", "1+5: 1 büyük + 5 küçük kutu (3 sütun, 3 satır)"],
    ["1+7", "1+7: 1 büyük + 7 küçük kutu (4 sütun, 4 satır)"], ["8×8", "8×8: 8 sütun, 8 satır (64 kutu)"],
    ["N×M", "N×M: satır ve sütun sayısını aşağıya girin (en çok 128 kutu)"]] as const) {
    await expect(preset(ed, label)).toHaveAccessibleName(name);
    await expect(preset(ed, label)).toHaveAttribute("title", name);
  }
  await expect(ed.getByRole("spinbutton", { name: "Satır", exact: true })).toBeVisible();
  await expect(ed.getByRole("spinbutton", { name: "Sütun", exact: true })).toBeVisible();
  // hazır düzenler
  for (const [name, n] of [["3×3", 9], ["1+7", 8], ["8×8", 64], ["1", 1], ["5×5", 25]] as const) {
    await preset(ed, name).click();
    await expect(page.getByTestId("watch-tile")).toHaveCount(n);
  }
  await expect(page.getByText("kamera düzene sığmadı")).toHaveCount(0);             // "1"den 5×5'e: düşen yok, eski uyarı kalktı
  // N×M: 6×8 = 48
  await ed.getByLabel("Satır", { exact: true }).fill("6");
  await ed.getByLabel("Sütun", { exact: true }).fill("8");
  await expect(ed.getByTestId("grid-check")).toHaveText("= 6 satır × 8 sütun = 48 kutu (en çok 128)");
  await ed.getByRole("button", { name: "Uygula" }).click();
  await expect(page.getByTestId("watch-tile")).toHaveCount(48);
  await expect(preset(ed, "N×M")).toHaveAttribute("aria-pressed", "true");
  // 16×9 = 144: Türkçe ileti, hiçbir şey değişmez
  await ed.getByLabel("Satır", { exact: true }).fill("16");
  await ed.getByLabel("Sütun", { exact: true }).fill("9");
  await expect(ed.getByTestId("grid-check")).toHaveText("En çok 128 kutu (16×9 = 144).");
  await ed.getByRole("button", { name: "Uygula" }).click();
  await expect(page.getByTestId("watch-tile")).toHaveCount(48);
  await ed.getByLabel("Satır", { exact: true }).fill("17");
  await expect(ed.getByTestId("grid-check")).toHaveText("Satır ve sütun 1–16 arasında olmalı.");
  // Geri al / Yinele (menüde ve Ctrl+Z / Ctrl+Y)
  await ed.getByRole("button", { name: /^Geri al/ }).click();
  await expect(page.getByTestId("watch-tile")).toHaveCount(25);
  await page.keyboard.press("Escape");
  await expect(ed).toBeHidden();
  await page.keyboard.press("Control+z");
  await expect(page.getByTestId("watch-tile")).toHaveCount(1);
  await page.keyboard.press("Control+y");
  await expect(page.getByTestId("watch-tile")).toHaveCount(25);
  const ed2 = await openEditor(page);
  await ed2.getByRole("button", { name: /^Yinele/ }).click();
  await expect(page.getByTestId("watch-tile")).toHaveCount(48);
  await ed2.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect.poll(() => calls.length).toBe(1);
  expect(calls[0]).toMatchObject({ method: "PUT", body: { name: "Giriş katı", layout: "6x8" } });
  const tiles = (calls[0].body as { tiles: unknown[] }).tiles;
  expect(tiles).toHaveLength(48);
  expect(tiles.slice(0, 4)).toEqual([VIEW.tiles[0], null, null, null]);            // "1" düzeninde düşen kameralar geri gelmez
  await expect(page.getByText("Kaydedilmemiş değişiklik var")).toBeHidden();
});

test("kamera atama: listeden kutuya sürükle-bırak, dokun-seç (kutu sonra kamera), kutudan kutuya, sağ tık Boşalt; Kaydet", async ({ page }) => {
  await mock(page, STATUS);
  const { calls } = await mockStore(page, [VIEW]);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  await expect(camera(page, "Kasa")).toBeVisible();                                   // kayıt cihazının kanalları açık gelir
  // sürükle-bırak: Depo → boş 4. kutu
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await expect(tiles.nth(3)).toContainText("Depo");
  await expect(tiles.nth(3)).not.toHaveAttribute("data-empty", "true");
  // dokun-seç: 3. kutu, sonra Giriş kanalı (kutudaki "Arka kapı" yerine)
  await tiles.nth(2).click();
  await expect(tiles.nth(2)).toHaveAttribute("data-selected", "true");
  await camera(page, "Giriş").click();
  await expect(tiles.nth(2)).toContainText("Ofis NVR · Giriş");
  // şablondaki kamerayı başka kutuya bırakmak onu taşır (aynı kamera iki kutuda olmaz)
  await camera(page, "Kapı").dragTo(tiles.nth(1));
  await expect(tiles.nth(1)).toContainText("Kapı");
  await expect(tiles.nth(0)).toHaveAttribute("data-empty", "true");
  // kutudan kutuya sürükleme: yer değiştirir
  await tiles.nth(1).dragTo(tiles.nth(0));
  await expect(tiles.nth(0)).toContainText("Kapı");
  await expect(tiles.nth(1)).toHaveAttribute("data-empty", "true");
  // sağ tık → Boşalt
  await tiles.nth(3).click({ button: "right" });
  const menu = page.getByRole("menu", { name: "Kutu işlemleri" });
  await expect(menu.getByRole("menuitem")).toHaveText(["Tek kamera", "Boşalt"]);
  await menu.getByRole("menuitem", { name: "Boşalt" }).click();
  await expect(tiles.nth(3)).toHaveAttribute("data-empty", "true");
  // boş kutuya sağ tık menü açmaz; klavye: Shift+F10 menüyü, Delete boşaltır
  await tiles.nth(2).focus();
  await page.keyboard.press("Shift+F10");
  await expect(menu).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(tiles.nth(2)).toBeFocused();
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect.poll(() => calls.length).toBe(1);
  expect(calls[0].body).toEqual({ name: "Giriş katı", layout: "4",
    tiles: [{ sourceId: "a", channelId: null }, null, { sourceId: "b", channelId: "1" }, null] });
});

test("kamera atama: seçim yokken listeden tıklanan kamera ilk boş kutuya gider, sonra sıradaki boş kutu seçilir; hepsi doluysa söyler", async ({ page }) => {
  await mock(page, STATUS);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  await camera(page, "Depo").click();                                                // seçim yok: ilk boş kutu (4.)
  await expect(tiles.nth(3)).toContainText("Depo");
  await expect(page.locator("[data-testid=watch-tile][data-selected=true]")).toHaveCount(0);   // boş kutu kalmadı
  await camera(page, "Giriş").click();
  await expect(page.getByRole("status").filter({ hasText: "Bütün kutular dolu" })).toBeVisible();
  await tiles.nth(3).click({ button: "right" });
  await page.getByRole("menuitem", { name: "Boşalt" }).click();                    // boşaltılan kutu seçilir
  await expect(tiles.nth(3)).toHaveAttribute("data-selected", "true");
  await camera(page, "Giriş").click();
  await expect(tiles.nth(3)).toContainText("Ofis NVR · Giriş");
});

test("canlı taslak: düzenlerken ızgara taslağı akıtır (sunucuda taslak), Kaydet şablonu yazar, akış şablona döner, taslak silinir", async ({ page }) => {
  const drafts = await mock(page, STATUS);
  const { calls } = await mockStore(page, [VIEW]);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  await expect(gridSrc(page)).toHaveAttribute("src", /\/api\/live\/views\/v1\/stream/);
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await expect(gridSrc(page)).toHaveAttribute("src", /\/api\/live\/views\/draft-1\/stream/);
  expect(drafts.calls[0]).toMatchObject({ method: "POST", body: { layout: "4", tiles: [...VIEW.tiles.slice(0, 3), { sourceId: "d", channelId: null }] } });
  await expect(cameras(page).getByRole("button", { name: /^Depo, canlı, şablonda$/ })).toBeVisible();   // taslağın durumu
  expect(calls).toHaveLength(0);                                                       // şablon değişmedi
  // ikinci değişiklik aynı taslağı günceller (yeni taslak açılmaz)
  const ed = await openEditor(page);
  await preset(ed, "1+5").click();
  await expect(tiles).toHaveCount(6);
  await expect.poll(() => drafts.calls.filter((c) => c.method === "PUT").length).toBe(1);
  expect(drafts.calls.filter((c) => c.method === "POST")).toHaveLength(1);
  await expect(gridSrc(page)).toHaveAttribute("src", /\/views\/draft-1\/stream/);
  await ed.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect.poll(() => calls.length).toBe(1);
  expect(calls[0]).toMatchObject({ method: "PUT", body: { name: "Giriş katı", layout: "6" } });
  await expect(gridSrc(page)).toHaveAttribute("src", /\/api\/live\/views\/v1\/stream/);
  await expect.poll(() => drafts.calls.filter((c) => c.method === "DELETE").map((c) => c.url)).toEqual([expect.stringContaining("/views/drafts/draft-1")]);
  // geri alıp kaydedilmiş hâle dönmek de taslağı kapatır
  await page.keyboard.press("Control+z");
  await expect(tiles).toHaveCount(4);
  await expect(gridSrc(page)).toHaveAttribute("src", /\/views\/draft-2\/stream/);
  await page.keyboard.press("Control+y");
  await expect(gridSrc(page)).toHaveAttribute("src", /\/views\/v1\/stream/);
  await expect.poll(() => drafts.store.size).toBe(0);
});

test("canlı taslak: sunucuda kaybolursa (güncelleme 404, durum 404) sessizce yenisi açılır; hata gösterilmez", async ({ page }) => {
  const drafts = await mock(page, STATUS);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await expect(gridSrc(page)).toHaveAttribute("src", /\/views\/draft-1\/stream/);
  drafts.store.delete("draft-1");                                                       // 10 dk boşta kaldı
  await tiles.nth(0).click({ button: "right" });
  await page.getByRole("menuitem", { name: "Boşalt" }).click();
  await expect(gridSrc(page)).toHaveAttribute("src", /\/views\/draft-2\/stream/);
  expect(drafts.calls.filter((c) => c.method === "POST")).toHaveLength(2);
  await expect.poll(() => drafts.store.get("draft-2")?.tiles[0]).toBeNull();             // güncel içerik yazıldı
  drafts.store.delete("draft-2");                                                       // sunucu yeniden başladı: durum 404
  await expect(gridSrc(page)).toHaveAttribute("src", /\/views\/draft-3\/stream/);
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
  await expect(page.getByText("Analiz sunucusuna ulaşılamıyor")).toHaveCount(0);
});

test("canlı taslak: analiz sunucusunda çok fazla taslak açıksa (503) ileti hata yerinde görünür, yer açılınca taslak açılır ve ileti kalkar", async ({ page }) => {
  const FULL = "Çok fazla açık taslak var; biraz sonra yeniden deneyin.";
  const drafts = await mock(page, STATUS);
  let full = true;
  let refused = 0;
  await page.route("**/api/live/views/drafts", (r) => {
    if (!full || r.request().method() !== "POST") return r.fallback();
    refused += 1;
    return r.fulfill({ status: 503, json: { detail: FULL } });
  });
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await expect(page.getByRole("alert").filter({ hasText: FULL })).toBeVisible();
  await expect.poll(() => refused, { timeout: 10_000 }).toBeGreaterThanOrEqual(2);      // yeniden deniyor
  await expect(gridSrc(page)).toHaveAttribute("src", /\/views\/v1\/stream/);           // taslak yok: şablon akar
  await expect(tab(page, /^Giriş katı/)).toContainText("*");                           // düzenleme kaybolmadı
  full = false;                                                                        // yer açıldı
  await expect(gridSrc(page)).toHaveAttribute("src", /\/views\/draft-1\/stream/, { timeout: 10_000 });
  await expect(page.getByText(FULL)).toHaveCount(0);
  expect(drafts.calls.filter((c) => c.method === "POST")).toHaveLength(1);
});

test("kaydedilmemiş değişiklik: sekme değiştirmek ve menüden başka sayfaya gitmek sorar; Vazgeç düzenlemeyi korur; sayfa kapanırken de sorulur", async ({ page }) => {
  const drafts = await mock(page, STATUS, [VIEW, V2]);
  await page.route("**/api/live/views/v2/status", (r) => r.fulfill({ json: { id: "v2", layout: "1", tiles: [] } }));
  await page.route("**/api/live/views/v2/stream**", (r) => r.fulfill({ body: JPEG, contentType: "image/jpeg" }));
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  const beforeUnload = () => page.evaluate(() => {
    const e = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(e);
    return e.defaultPrevented;
  });
  expect(await beforeUnload()).toBe(false);                                            // değişiklik yok: sorulmaz
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await expect(tab(page, /^Giriş katı/)).toContainText("*");
  expect(await beforeUnload()).toBe(true);
  // sekme değiştir → sor → Vazgeç
  const messages: string[] = [];
  page.once("dialog", (d) => { messages.push(d.message()); void d.dismiss(); });
  await tab(page, "Depo katı").click();
  expect(messages).toEqual([UNSAVED]);
  await expect(tab(page, /^Giriş katı/)).toHaveAttribute("aria-selected", "true");
  await expect(tiles.nth(3)).toContainText("Depo");
  // menü bağlantısı → sor → Vazgeç: sayfada kalınır
  page.once("dialog", (d) => { messages.push(d.message()); void d.dismiss(); });
  await page.getByRole("navigation", { name: "Ana menü" }).getByRole("link", { name: "Alarmlar" }).click();
  expect(messages).toEqual([UNSAVED, UNSAVED]);
  await expect(page).toHaveURL(/\/watch$/);
  await expect(tiles.nth(3)).toContainText("Depo");
  // kutudaki "Canlı sayıma git" de sorar
  page.once("dialog", (d) => { messages.push(d.message()); void d.dismiss(); });
  await tiles.nth(0).hover();
  await tiles.nth(0).getByRole("link", { name: "Canlı sayıma git" }).click();
  expect(messages).toHaveLength(3);
  await expect(page).toHaveURL(/\/watch$/);
  // Tamam: başka sayfaya gidilir, taslak silinir
  page.once("dialog", (d) => void d.accept());
  await page.getByRole("navigation", { name: "Ana menü" }).getByRole("link", { name: "Alarmlar" }).click();
  await expect(page).toHaveURL(/\/alarms$/);
  await expect.poll(() => drafts.store.size).toBe(0);
  expect(await beforeUnload()).toBe(false);
});

test("kaydedilmemiş değişiklik: sekme değişiminde Tamam düzenlemeyi atar, yeni sekmeye geçer", async ({ page }) => {
  const drafts = await mock(page, STATUS, [VIEW, V2]);
  await page.route("**/api/live/views/v2/status", (r) => r.fulfill({ json: { id: "v2", layout: "1", tiles: [] } }));
  await page.route("**/api/live/views/v2/stream**", (r) => r.fulfill({ body: JPEG, contentType: "image/jpeg" }));
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await expect(gridSrc(page)).toHaveAttribute("src", /draft-1/);
  page.once("dialog", (d) => void d.accept());
  await tab(page, "Depo katı").click();
  await expect(tab(page, "Depo katı")).toHaveAttribute("aria-selected", "true");
  await expect(gridSrc(page)).toHaveAttribute("src", /\/views\/v2\/stream/);
  await expect.poll(() => drafts.store.size).toBe(0);
  expect(await stored(page)).toBeNull();                                              // saklanan düzenleme silindi
  await tab(page, "Giriş katı").click();                                             // dönünce kayıtlı hâl
  await expect(tiles.nth(3)).toHaveAttribute("data-empty", "true");
});

test("Farklı kaydet: düzenlenen hâl yeni ad ile yeni şablon olur, ona geçilir; asıl şablon değişmez", async ({ page }) => {
  await mock(page, STATUS);
  const { calls } = await mockStore(page, [VIEW]);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  await camera(page, "Depo").dragTo(tiles.nth(3));
  const ed = await openEditor(page);
  await ed.getByRole("button", { name: "Farklı kaydet…" }).click();
  const dlg = page.getByRole("dialog", { name: "Farklı kaydet" });
  await expect(dlg.getByLabel("Şablon adı")).toHaveValue("Giriş katı (kopya)");
  await dlg.getByLabel("Şablon adı").fill("Depo dahil");
  await dlg.getByRole("button", { name: "Tamam" }).click();
  await expect(tab(page, "Depo dahil")).toHaveAttribute("aria-selected", "true");
  expect(calls).toEqual([expect.objectContaining({ method: "POST", body: { name: "Depo dahil", layout: "4",
    tiles: [...VIEW.tiles.slice(0, 3), { sourceId: "d", channelId: null }] } })]);
  await expect(tab(page, "Giriş katı")).not.toContainText("*");
  await expect(page.getByText("Kaydedilmemiş değişiklik var")).toBeHidden();
  // yeni şablonu Kaydet ilk kez yazar (POST), sekmesi kalıcı olur
  await page.getByRole("button", { name: "Yeni şablon" }).click();
  await camera(page, "Kapı").click();
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect(tab(page, "Yeni şablon")).toHaveAttribute("aria-selected", "true");
  await expect(tab(page, "Yeni şablon")).not.toContainText("*");
  expect(calls.at(-1)).toMatchObject({ method: "POST", body: { name: "Yeni şablon", layout: "4", tiles: [{ sourceId: "a", channelId: null }, null, null, null] } });
});

for (const { count, layout, cells, note } of [
  { count: 20, layout: "4x5", cells: 20, note: null },
  { count: 130, layout: "8x16", cells: 128, note: "İlk 128 kanal alındı (toplam 130)." },
]) {
  test(`Şablon editörü: NVR'dan şablon ${count} kanallı cihazdan yeni şablonu kurar${note ? " ve 128'den fazlasını söyler" : "; 128'e kadar bilgi yok"}`, async ({ page }) => {
    await mock(page, STATUS);
    const { store } = await mockStore(page, [VIEW]);
    const tiles = Array.from({ length: cells }, (_, i) => (i < count ? { sourceId: "b", channelId: String(i + 1) } : null));
    let posted: unknown = null;
    await page.route("**/api/live/views/from-recorder", (r) => {
      posted = r.request().postDataJSON();
      const v = { id: "r1", name: "Ofis NVR", layout, tiles, createdAt: 6, updatedAt: 6, truncated: count > 128, channelCount: count };
      store.push(v);
      return r.fulfill({ json: v });
    });
    await login(page);
    const ed = await openEditor(page);
    const pick = ed.getByRole("combobox", { name: "NVR'dan şablon" });
    await expect(pick.locator("option")).toHaveText(["Kayıt cihazı seçin…", "Ofis NVR"]);     // yalnız kayıt cihazları
    await pick.selectOption("b");
    await expect(tab(page, "Ofis NVR")).toHaveAttribute("aria-selected", "true");
    expect(posted).toEqual({ sourceId: "b" });
    await expect(page.getByTestId("watch-tile")).toHaveCount(cells);
    if (note) {
      await expect(page.getByText(note)).toBeVisible();
      await tab(page, "Giriş katı").click();                                           // başka şablona geçince bilgi kalkar
      await expect(page.getByText("kanal alındı")).toHaveCount(0);
    } else {
      await expect(page.getByText("kanal alındı")).toHaveCount(0);
    }
  });
}

test("katalogdaki düğmesiz düzen ('3') kayıtlı şablonda çalışır: 3 kutu", async ({ page }) => {
  const view3 = { ...VIEW, layout: "3", tiles: VIEW.tiles.slice(0, 3) };
  await mock(page, { ...STATUS, layout: "3", tiles: STATUS.tiles.slice(0, 3) }, view3);
  await login(page);
  await expect(page.getByTestId("watch-tile")).toHaveCount(3);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  const ed = await openEditor(page);
  await expect(ed.getByRole("group", { name: "Düzenler:" }).getByRole("button", { pressed: true })).toHaveCount(0);
});

test("tek kamera: kutuya çift tık açar, görüntüye çift tık ızgaraya döner", async ({ page }) => {
  await mock(page, STATUS);
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  await page.getByTestId("watch-tile").nth(0).dblclick();
  await expect(page.getByRole("heading", { name: "Kapı" })).toBeVisible();
  await page.getByTestId("single-camera").dblclick();
  await expect(page.getByTestId("watch-tile")).toHaveCount(4);
  await expect(page.getByRole("heading", { name: "Kapı" })).toHaveCount(0);
});

test("kamera listesi: ızgaradaki kameraların durum noktası (yeşil canlı, turuncu sorunlu), ızgarada olmayan gri", async ({ page }) => {
  await mock(page, STATUS);
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  const dot = (name: string) => camera(page, name).locator("[data-state]");
  await expect(dot("Kapı")).toHaveAttribute("data-state", "live");
  await expect(dot("Kasa")).toHaveAttribute("data-state", "live");
  await expect(dot("Arka kapı")).toHaveAttribute("data-state", "problem");
  await expect(dot("Depo")).toHaveAttribute("data-state", "unknown");
  await expect(camera(page, "Arka kapı")).toHaveAccessibleName("Arka kapı, sorunlu, şablonda");
  await expect(camera(page, "Depo")).toHaveAccessibleName("Depo, bu şablonda izlenmiyor");
  await expect(dot("Depo")).toHaveAttribute("title", "bu şablonda izlenmiyor");
  await expect(page.getByTestId("camera-legend")).toHaveText(/canlı.*sorunlu.*bu şablonda izlenmiyor/);
});

test("kamera listesi: ızgarada olmayan ama analiz oturumu olan kameranın durumu oturum listesinden gelir", async ({ page }) => {
  await mock(page, STATUS);
  const session = (id: string, sourceId: string, channelId: string | null, state: string) => ({ id, name: id, state, message: "",
    fps: 8, width: 640, height: 360, counting: true, total: 0, totalOut: 0, staffIn: 0, staffOut: 0, twoWay: false,
    ratePerMinute: 0, calibrating: null, calibrationMessage: "", sourceId, channelId, profileId: null, substream: true, safety: null,
    profile: { id: "p", name: "p", roi: { x: 0, y: 0, width: 1, height: 1 }, linePosition: 0.5, direction: "down",
      diffThreshold: 30, expectedArea: 0, splitTouching: false, countMode: "blob" } });
  // "Giriş" kanalında iki oturum: biri canlı, biri yeniden bağlanıyor → en kötüsü (sorunlu) gösterilir
  await page.route("**/api/live/sessions", (r) => r.fulfill({ json: [session("s8", "d", null, "live"), session("s9", "b", "1", "reconnecting"),
    session("s10", "b", "1", "live")] }));
  await login(page);
  const dot = (name: string) => camera(page, name).locator("[data-state]");
  await expect(dot("Depo")).toHaveAttribute("data-state", "live");
  await expect(camera(page, "Depo")).toHaveAccessibleName("Depo, canlı");
  await expect(dot("Giriş")).toHaveAttribute("data-state", "problem");
});

test("klavye: ızgara tek sekme durağı, ok tuşları gezdirir, odak seçmez; Enter ile seçilen kutu listeye geçince kalır ve kamera ona gider", async ({ page }) => {
  await mock(page, STATUS);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  await expect(page.locator("[data-testid=watch-tile][tabindex='0']")).toHaveCount(1);   // 128 kutuda da tek durak
  await tiles.nth(0).focus();
  await page.keyboard.press("ArrowRight");
  await expect(tiles.nth(1)).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(tiles.nth(3)).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await expect(tiles.nth(2)).toBeFocused();
  await page.keyboard.press("Home");
  await expect(tiles.nth(0)).toBeFocused();
  await page.keyboard.press("End");
  await expect(tiles.nth(3)).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await expect(tiles.nth(2)).toBeFocused();
  await expect(page.locator("[data-testid=watch-tile][data-selected=true]")).toHaveCount(0);
  await expect(page.locator("[data-testid=watch-tile][tabindex='0']")).toHaveCount(1);
  await expect(tiles.nth(2)).toHaveAttribute("tabindex", "0");
  await page.keyboard.press("Enter");
  await expect(tiles.nth(2)).toHaveAttribute("data-selected", "true");
  // Tab ile kamera listesine geçilir: seçim değişmez
  const inList = () => page.evaluate(() => !!document.activeElement?.closest("aside[aria-label=Kameralar]"));
  for (let i = 0; i < 12 && !(await inList()); i++) await page.keyboard.press("Tab");
  expect(await inList()).toBe(true);
  await expect(tiles.nth(2)).toHaveAttribute("data-selected", "true");
  for (let i = 0; i < 12 && !(await camera(page, "Depo").evaluate((el) => el === document.activeElement)); i++) await page.keyboard.press("Tab");
  await expect(camera(page, "Depo")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(tiles.nth(2)).toContainText("Depo");                               // seçili kutuya (ilk boş kutuya değil)
  await expect(tiles.nth(3)).toHaveAttribute("data-empty", "true");
});

const fmt = (b: Box) => `${b.x.toFixed(1)},${b.y.toFixed(1)} ${b.width.toFixed(1)}×${b.height.toFixed(1)}`;
/**
 * Kutunun GÖRÜNEN katman parçaları (`data-part`: ad, rozet ya da nokta, durum metni, alarm etiketi, ⋯ ve fareyle üstüne
 * gelince ya da klavye odağında çıkan kutu düğmeleri) ikişer ikişer üst üste binmez ve hepsi kutunun içindedir (yumuşak
 * denetim: bütün ihlaller birlikte raporlanır). Ölçüm sayfada tek seferde yapılır. Görünen parçaların adlarını (sıralı)
 * döndürür.
 */
async function partsClear(tile: Locator, what: string): Promise<string[]> {
  const { box, parts } = await tile.evaluate((el) => {
    const rect = (e: Element) => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height }; };
    return {
      box: rect(el),
      parts: [...el.querySelectorAll<HTMLElement>("[data-part]")]
        .map((p) => ({ part: p.dataset.part ?? "", b: rect(p), hidden: getComputedStyle(p).visibility === "hidden" }))
        .filter((p) => p.b.width > 0 && p.b.height > 0 && !p.hidden),
    };
  });
  const seen: Array<{ part: string; b: Box }> = [];
  for (const { part, b } of parts) {
    const inside = b.x >= box.x - 0.5 && b.y >= box.y - 0.5 && b.x + b.width <= box.x + box.width + 0.5 && b.y + b.height <= box.y + box.height + 0.5;
    expect.soft(inside, `${what}: ${part} kutunun dışına taşıyor (${fmt(b)}; kutu ${fmt(box)})`).toBe(true);
    for (const o of seen) expect.soft(overlaps(o.b, b), `${what}: ${o.part} ile ${part} üst üste (${fmt(o.b)}; ${fmt(b)})`).toBe(false);
    seen.push({ part, b });
  }
  return seen.map((s) => s.part).sort();
}

const LIVE = { state: "live", message: "", fps: 10 };
const NO_LINK = { state: "error", message: "Görüntü açılamadı; yeniden deneniyor.", fps: 0 };
const NO_LINK_TEXT = "Bağlantı yok — Görüntü açılamadı; yeniden deneniyor.";
const GUARD = { mode: "safety", name: "Kuyumcu güvenliği", healthy: true, reason: null };
/** Noktanın beklenen rengi: kamera listesinin açıklamasındaki nokta ya da bilgi rozetinin beyazı */
type DotColor = "canlı" | "sorunlu" | "bağlanıyor" | "beyaz";
interface Role {
  key: string; ref: { sourceId: string; channelId: string | null };
  /** Kameranın durumdaki adı: kamera listesindeki etiketten farklı (durumun geldiği bundan anlaşılır) */
  name: string; status: object; alarm: boolean;
  /** Rozet yazısı (analiz yoksa null); `state`: kutuda görünmesi gereken durum metni (canlıda null) */
  badge: string | null; state: string | null;
  /** Noktanın rengi: kamera canlı değilken bağlantı rengi (halka), canlıyken rozetin rengi (dolu) */
  dot: DotColor;
}
/** Boyut matrisinin kutu rolleri: canlı alarm, canlı kişi sayımı, bağlantı yok, bağlanıyor, alarm ile bağlantı yok */
const ROLES: Role[] = [
  { key: "alarm", ref: { sourceId: "b", channelId: "2" }, name: "Ofis NVR · Kasa",
    status: { ...LIVE, analysis: { ...GUARD, sessionId: "s2", alarm: { id: "al2", type: "lying" } } },
    alarm: true, badge: "Nöbette", state: null, dot: "canlı" },
  { key: "canlı", ref: { sourceId: "a", channelId: null }, name: "Mağaza girişi kamerası",
    status: { ...LIVE, analysis: { mode: "detect", sessionId: "s1", name: "Mağaza girişi", entered: 120, exited: 99, alarm: null } },
    alarm: false, badge: "G 120 · Ç 99", state: null, dot: "beyaz" },
  { key: "bağlantı yok", ref: { sourceId: "c", channelId: null }, name: "Arka kapı bahçesi", status: { ...NO_LINK, analysis: null },
    alarm: false, badge: null, state: NO_LINK_TEXT, dot: "sorunlu" },
  { key: "bağlanıyor", ref: { sourceId: "d", channelId: null }, name: "Depo rampası",
    status: { state: "connecting", message: "", fps: 0, analysis: null }, alarm: false, badge: null, state: "Bağlanıyor…", dot: "bağlanıyor" },
  // alarmlı ama kamerası kopuk: nokta bağlantı rengindedir (alarm kırmızı çerçeve ve etiketle görünür)
  { key: "alarm ve bağlantı yok", ref: { sourceId: "b", channelId: "1" }, name: "Ofis NVR · Giriş",
    status: { ...NO_LINK, analysis: { ...GUARD, sessionId: "s3", alarm: { id: "al3", type: "hands_up" } } },
    alarm: true, badge: "Nöbette", state: NO_LINK_TEXT, dot: "sorunlu" },
];

function geom(id: string): { cols: number; count: number } {
  const known = (LAYOUTS as Array<{ id: string; cols: number; cells: unknown[] }>).find((l) => l.id === id);
  if (known) return { cols: known.cols, count: known.cells.length };
  const [rows, cols] = id.split("x").map(Number);
  return { cols, count: rows * cols };
}

/** Her düzen için şablonlar: roller sırayla kutulara; düzende yer kalmayan roller sonraki şablona (1×1'de rol başına bir şablon) */
function matrixViews(ids: string[]) {
  const plan: Array<{ id: string; name: string; roles: Role[] }> = [];
  const views: object[] = [];
  const statuses: Record<string, object> = {};
  for (const id of ids) {
    const { count } = geom(id);
    for (let k = 0; k * count < ROLES.length; k++) {
      const roles = ROLES.slice(k * count, (k + 1) * count);
      const vid = `m${plan.length}`;
      const name = `Düzen ${id} · ${k + 1}`;
      const tiles = Array.from({ length: count }, (_, i) => roles[i]?.ref ?? null);
      views.push({ id: vid, name, layout: id, createdAt: 1, updatedAt: 1, tiles });
      statuses[vid] = { id: vid, layout: id, tiles: tiles.map((t, i) => t && { ...t, name: roles[i].name, ...roles[i].status }) };
      plan.push({ id, name, roles });
    }
  }
  return { plan, views, statuses };
}

async function mockMatrix(page: Page, views: object[], statuses: Record<string, object>) {
  await page.route("**/api/live/view-layouts", (r) => r.fulfill({ json: LAYOUTS }));
  await page.route("**/api/live/views", (r) => r.fulfill({ json: views }));
  await page.route("**/api/live/views/*/status", (r) => r.fulfill({ json: statuses[r.request().url().split("/").at(-2)!] }));
  await page.route("**/api/live/views/*/stream**", (r) => r.fulfill({ body: JPEG, contentType: "image/jpeg" }));
  await page.route("**/api/live/alarms?active=1", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/live/sessions", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/live/sources", (r) => r.fulfill({ json: SOURCES }));
  await page.route("**/api/live/sources/b/channels", (r) => r.fulfill({ json: CHANNELS }));
}

/**
 * Tarayıcının yazı boyutu ayarı (Chrome: Ayarlar → Yazı tipi boyutu): kök yazı boyutu `px` olur; sayfa yeniden yüklenmez.
 * Chrome bu ayarla sabit genişlikli yazıyı standarttan 3 px küçük tutar (16 → 13, 20 → 17, 24 → 21)
 */
async function setBrowserFont(page: Page, px: number) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Page.setFontSizes", { fontSizes: { standard: px, fixed: px - 3 } });
}
const rootPx = (page: Page) => page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize));

/** Noktaların beklenen renkleri: kamera listesinin açıklamasındaki noktalardan (aynı renkler) ve bilgi rozetinin beyazı */
async function dotColors(page: Page): Promise<Record<DotColor, string>> {
  const legend = page.getByTestId("camera-legend");
  const of = (text: string) => legend.locator("span", { hasText: text }).first().locator("span").first()
    .evaluate((el) => getComputedStyle(el).backgroundColor);
  const white = await page.evaluate(() => {
    const s = document.createElement("span");
    s.className = "bg-white/85";
    document.body.append(s);
    const c = getComputedStyle(s).backgroundColor;
    s.remove();
    return c;
  });
  return { "canlı": await of("canlı"), "sorunlu": await of("sorunlu"), "bağlanıyor": await of("bağlanıyor"), "beyaz": white };
}

/**
 * Nokta: kamera canlı değilken bağlantı rengi HALKA (içi boş, görünür kenar), canlıyken rozetin rengi DOLU; ipucu ve ekran
 * okuyucu metni rozeti ve durumu söyler.
 */
async function dotShown(tile: Locator, r: Role, colors: Record<DotColor, string>, what: string) {
  const dot = tile.locator("[data-part=dot]");
  expect.soft(await dot.count(), `${what}: nokta`).toBe(1);
  if (!(await dot.count())) return;
  const title = (await dot.getAttribute("title")) ?? "";
  const sr = (await dot.locator(".sr-only").textContent()) ?? "";
  for (const t of [r.badge, r.state]) {
    if (!t) continue;
    expect.soft(title, `${what}: noktanın ipucu`).toContain(t);
    expect.soft(sr, `${what}: noktanın ekran okuyucu metni`).toContain(t);
  }
  const s = await dot.evaluate((el) => {
    const c = getComputedStyle(el);
    return { bg: c.backgroundColor, border: c.borderTopColor, width: parseFloat(c.borderTopWidth), style: c.borderTopStyle };
  });
  if (r.state) {
    expect.soft(s.bg, `${what}: halka (içi boş)`).toBe("rgba(0, 0, 0, 0)");
    expect.soft(s.style, `${what}: halkanın kenarı`).toBe("solid");
    expect.soft(s.width, `${what}: halkanın kenarı görünür`).toBeGreaterThan(1);
    expect.soft(s.border, `${what}: halka bağlantı renginde (${r.dot})`).toBe(colors[r.dot]);
  } else {
    expect.soft(s.width, `${what}: dolu nokta (kenarsız)`).toBe(0);
    expect.soft(s.bg, `${what}: dolu nokta rozet renginde (${r.dot})`).toBe(colors[r.dot]);
  }
}

/**
 * Kutunun durumu dokunmadan da görünür. Normal kutuda orta alan en az bir satır alıyorsa durum metni orada (tam satırlar,
 * `lines`'tan çok değil; tamamı kutunun ipucunda), almıyorsa üst şeritte addan sonra, rozetten önce nokta; küçük kutularda
 * nokta.
 */
async function statusShown(tile: Locator, r: Role, tier: string, lines: number, rem: number, colors: Record<DotColor, string>, what: string) {
  if (tier !== "full") { await dotShown(tile, r, colors, what); return; }
  const text = tile.locator("[data-part=state]");
  const dot = tile.locator("[data-part=dot]");
  if (!r.state) {
    expect.soft(await text.count(), `${what}: durum metni yok`).toBe(0);
    expect.soft(await dot.count(), `${what}: nokta yok`).toBe(0);
    return;
  }
  if (lines >= 1) {
    expect.soft(await text.count(), `${what}: durum metni`).toBe(1);
    expect.soft(await dot.count(), `${what}: durum metni varken nokta yok`).toBe(0);
    if (!(await text.count())) return;
    expect.soft(await text.textContent(), `${what}: durum metni`).toBe(r.state);
    expect.soft(await tile.getAttribute("title"), `${what}: kutunun ipucunda durum metninin tamamı`).toBe(r.state);
    const h = (await text.boundingBox())?.height ?? 0;
    const n = Math.round(h / rem);
    expect.soft(Math.abs(h - n * rem) < 0.6 && n >= 1 && n <= lines,
      `${what}: durum metni tam satır, en çok ${lines} (${h.toFixed(1)} px, satır ${rem} px)`).toBe(true);
    return;
  }
  expect.soft(await text.count(), `${what}: orta alan bir satır almıyor, durum metni yok`).toBe(0);
  await dotShown(tile, r, colors, what);
  // üst şeritte: addan sonra, rozetten önce
  const box = async (p: string) => {
    const l = tile.locator(`[data-part=${p}]`);
    return (await l.count()) ? l.first().boundingBox() : null;
  };
  const [name, d, badge] = await Promise.all(["name", "dot", "badge"].map(box));
  if (name && d) {
    expect.soft(d.x >= name.x + name.width && d.y + d.height <= name.y + name.height + 0.5, `${what}: nokta addan sonra, üst şeritte`).toBe(true);
  }
  if (d && badge) expect.soft(d.x + d.width <= badge.x, `${what}: nokta rozetten önce`).toBe(true);
}

/**
 * "idle": boşta; "hover": fareyle üstünde; "focus": kutu klavye odağında; "inner": kutunun içindeki alarm etiketi klavye
 * odağında; "selected": dokunmatikte seçili; "more": "⋯" menüsü açılıp Esc ile kapandı (odak "⋯"de, focus-visible).
 */
type TileState = "idle" | "hover" | "focus" | "inner" | "selected" | "more";
/** Görünmesi gereken parçalar: katman yoğunluğu (`data-tier`), orta alana sığan satır, cihaz, rol ve duruma göre */
function expectedParts(r: Role, tier: string, lines: number, touch: boolean, st: TileState): string[] {
  const dot = r.badge !== null || r.state !== null;
  if (tier === "tiny" || tier === "micro") return dot ? ["dot"] : [];
  const selected = st === "selected" || st === "more";
  const focused = st === "focus" || st === "inner";
  const parts: string[] = [];
  if (tier === "small") {
    parts.push(r.alarm ? "alarm" : "name");                                       // küçük alarmlı kutuda adın yerinde etiket
    if (dot) parts.push("dot");
    if (touch ? r.alarm || selected : st === "hover" || st === "more") parts.push("more");
  } else {
    parts.push("name");
    if (r.badge) parts.push("badge");
    if (r.state) parts.push(lines >= 1 ? "state" : "dot");                       // sığmazsa üst şeritte nokta
    if (r.alarm) parts.push("alarm");
    if (st === "hover" || focused) parts.push("actions");
    if (touch && (r.alarm || selected) && !focused) parts.push("more");
  }
  return parts.sort();
}

/**
 * Boyut matrisi: görünüm başına tek sayfa, düzen başına şablon(lar). Düzen başına beklenen [yoğunluk, normal kutunun orta
 * alanına sığan durum satırı] kutunun boyutundan ve kök yazı boyutundan (layoutGrid.mjs `tileTier`, `stateLines`; kameranın
 * durumundan bağımsız; ölçülen boyutlar ÖLÇÜ satırlarında). `font`: tarayıcının yazı boyutu ayarı (px); `live`: sayfa
 * açıkken değiştirilir (yeniden yüklemeden).
 */
const MATRIX: Array<{ name: string; use: { viewport: { width: number; height: number }; hasTouch?: boolean; isMobile?: boolean };
  touch: boolean; font?: number; live?: boolean; tiers: Record<string, [string, number]> }> = [
  { name: "masaüstü 1280 px", use: { viewport: { width: 1280, height: 800 } }, touch: false,
    tiers: { "1": ["full", 2], "4": ["full", 2], "16": ["full", 2], "5x5": ["full", 0], "8x8": ["small", 0], "9x9": ["small", 0],
      "8x16": ["tiny", 0] } },
  { name: "dokunmatik 390 px", use: { viewport: { width: 390, height: 800 }, hasTouch: true, isMobile: true }, touch: true,
    tiers: { "1": ["full", 2], "4": ["full", 1], "9": ["small", 0], "16": ["small", 0], "5x5": ["tiny", 0], "8x8": ["tiny", 0],
      "8x16": ["micro", 0], "1x16": ["micro", 0] } },
  { name: "dokunmatik 300 px", use: { viewport: { width: 300, height: 700 }, hasTouch: true, isMobile: true }, touch: true,
    tiers: { "4": ["full", 0] } },
  { name: "dokunmatik tablet 820 px", use: { viewport: { width: 820, height: 1180 }, hasTouch: true, isMobile: true }, touch: true,
    tiers: { "16": ["full", 0] } },
  { name: "masaüstü 1280 px, yazı boyutu 20 px", use: { viewport: { width: 1280, height: 800 } }, touch: false, font: 20,
    tiers: { "16": ["full", 0], "5x5": ["small", 0] } },
  { name: "masaüstü 1280 px, yazı boyutu sayfa açıkken 24 px", use: { viewport: { width: 1280, height: 800 } }, touch: false, font: 24,
    live: true, tiers: { "16": ["full", 1], "5x5": ["small", 0] } },
  { name: "dokunmatik 390 px, yazı boyutu 20 px", use: { viewport: { width: 390, height: 800 }, hasTouch: true, isMobile: true },
    touch: true, font: 20, tiers: { "4": ["full", 0], "9": ["small", 0] } },
  { name: "dokunmatik 390 px, yazı boyutu sayfa açıkken 24 px", use: { viewport: { width: 390, height: 800 }, hasTouch: true, isMobile: true },
    touch: true, font: 24, live: true, tiers: { "4": ["small", 0], "9": ["tiny", 0] } },
];
for (const m of MATRIX) {
  test.describe(`kutu katmanı, ${m.name}`, () => {
    test.use(m.use);
    test(`${Object.keys(m.tiers).join(", ")}: görünen parçalar (ad, rozet/nokta, durum, alarm etiketi, ⋯, kutu düğmeleri) her durumda üst üste binmez ve kutunun içindedir; durum dokunmadan görünür`, async ({ page }) => {
      const { plan, views, statuses } = matrixViews(Object.keys(m.tiers));
      await mockMatrix(page, views, statuses);
      if (m.font && !m.live) await setBrowserFont(page, m.font);
      await login(page);
      if (m.font && m.live) {
        await expect(page.getByTestId("watch-tile").first()).toBeVisible();          // önce 16 px ile çizildi
        await setBrowserFont(page, m.font);
      }
      const rem = m.font ?? 16;
      await expect.poll(() => rootPx(page)).toBe(rem);
      const colors = await dotColors(page);
      const tiles = page.getByTestId("watch-tile");
      const menu = page.getByRole("menu", { name: "Kutu işlemleri" });
      let escapes = 0;
      for (const p of plan) {
        const { cols, count } = geom(p.id);
        const [tier, lines] = m.tiers[p.id];
        await tab(page, p.name).click();
        await expect(tab(page, p.name)).toHaveAttribute("aria-selected", "true");
        await expect(tiles).toHaveCount(count);
        // durum geldi: kutunun yazısında ya da ipucunda kameranın durumdaki adı
        await expect.poll(() => tiles.nth(0).evaluate((el) => `${el.textContent} ${el.getAttribute("title")}`)).toContain(p.roles[0].name);
        const b = (await tiles.nth(0).boundingBox())!;
        console.log(`ÖLÇÜ ${m.name} ${p.name}: kutu ${b.width.toFixed(1)}×${b.height.toFixed(1)} (${(b.width / rem).toFixed(2)}×${(b.height / rem).toFixed(2)} rem)`);
        for (const [i, r] of p.roles.entries()) {
          const tile = tiles.nth(i);
          const what = `${p.name} ${r.key}`;
          const check = async (st: TileState) => expect.soft(await partsClear(tile, `${what} (${st})`), `${what} (${st}): görünen parçalar`)
            .toEqual(expectedParts(r, tier, lines, m.touch, st));
          if (!m.touch) await page.mouse.move(0, 0);
          expect.soft(await tile.getAttribute("data-tier"), `${what}: yoğunluk`).toBe(tier);
          await statusShown(tile, r, tier, lines, rem, colors, what);
          await check("idle");
          if (!m.touch) {
            await tile.hover();
            await check("hover");
            await page.mouse.move(0, 0);
          }
          // klavye odağı: ilk kutudan ok tuşlarıyla (odak görünür)
          await tiles.nth(0).focus();
          await page.keyboard.press("Home");
          for (let k = 0; k < Math.floor(i / cols); k++) await page.keyboard.press("ArrowDown");
          for (let k = 0; k < i % cols; k++) await page.keyboard.press("ArrowRight");
          await expect(tile).toBeFocused();
          expect(await tile.evaluate((el) => el.matches(":focus-visible"))).toBe(true);
          await check("focus");
          if (r.alarm && (tier === "full" || tier === "small")) {
            await page.keyboard.press("Tab");                                            // kutunun içindeki ilk öğe: alarm etiketi
            await expect(tile.getByRole("button", { name: /^Alarmı aç/ })).toBeFocused();
            await check("inner");
          }
          // klavye odağı bırakılır: dokunuş ve "⋯" denemeleri klavyesiz (odaktaki kutuda ya da alarm etiketinde "⋯" yerine
          // kutu düğmeleri çıkar; o durum yukarıda ölçüldü)
          await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
          if (m.touch && !r.alarm) {
            await tile.tap();                                                             // dokunuş seçer
            await expect(tile).toHaveAttribute("data-selected", "true");
            await check("selected");
          }
          if (expectedParts(r, tier, lines, m.touch, "more").includes("more")) {
            // "⋯" menüsü açılıp Esc ile kapanınca odak "⋯"ye döner (focus-visible): kutu düğmeleri onunla birlikte çıkmaz;
            // masaüstünde fare kutudan çıksa da "⋯" odaktayken görünür kalır (odak sayfaya düşmez)
            const more = tile.getByRole("button", { name: "Kutu işlemleri" });
            if (!m.touch) await tile.hover();
            await expect(more).toBeVisible();
            if (m.touch) await more.tap();
            else await more.click();
            await expect(menu).toBeVisible();
            await page.keyboard.press("Escape");
            await expect(menu).toHaveCount(0);
            if (!m.touch) await page.mouse.move(0, 0);
            await expect.soft(more, `${what}: Esc sonrası odak ⋯'de`).toBeFocused();
            expect.soft(await more.evaluate((el) => el.matches(":focus-visible")), `${what}: ⋯ focus-visible`).toBe(true);
            await check("more");
            escapes += 1;
          }
        }
      }
      expect(escapes).toBeGreaterThan(0);                                                 // "⋯" + Esc en az bir kutuda denendi
    });
  });
}

test.describe("kutu katmanı, en küçük kutu (dokunmatik 390 px, 8×16)", () => {
  test.use({ viewport: { width: 390, height: 800 }, hasTouch: true, isMobile: true });
  test("canlı değilken ortadaki nokta halka olarak seçilir: delik en az 3 px, nokta kutunun içinde (kök 16, 20, 24 px)", async ({ page }) => {
    const { plan, views, statuses } = matrixViews(["8x16"]);
    await mockMatrix(page, views, statuses);
    await login(page);
    await tab(page, plan[0].name).click();
    const tiles = page.getByTestId("watch-tile");
    await expect(tiles).toHaveCount(128);
    for (const px of [16, 20, 24]) {
      await setBrowserFont(page, px);
      await expect.poll(() => rootPx(page)).toBe(px);
      for (const [i, r] of plan[0].roles.entries()) {
        const tile = tiles.nth(i);
        await expect(tile).toHaveAttribute("data-tier", "micro");
        const m = await tile.evaluate((el) => {
          const d = el.querySelector<HTMLElement>("[data-part=dot]");
          if (!d) return null;
          const t = el.getBoundingClientRect();
          const b = d.getBoundingClientRect();
          const cs = getComputedStyle(d);
          const border = parseFloat(cs.borderTopWidth);
          return { inside: b.left >= t.left - 0.5 && b.top >= t.top - 0.5 && b.right <= t.right + 0.5 && b.bottom <= t.bottom + 0.5,
            hole: Math.min(b.width, b.height) - 2 * border, border, fill: cs.backgroundColor, size: b.width };
        });
        const what = `kök ${px} px, ${r.key}`;
        expect(m, what).not.toBeNull();
        expect.soft(m!.inside, `${what}: nokta kutunun içinde`).toBe(true);
        if (r.state) {                                                    // canlı değil: halka (içi boş), delik ≥ 3 px
          expect.soft(m!.border, `${what}: halka`).toBeGreaterThan(0);
          expect.soft(m!.fill, `${what}: içi boş`).toBe("rgba(0, 0, 0, 0)");
          expect.soft(m!.hole, `${what}: delik ${m!.hole.toFixed(2)} px`).toBeGreaterThanOrEqual(3);
        } else {
          expect.soft(m!.border, `${what}: canlıyken dolu nokta`).toBe(0);
        }
      }
    }
  });
});

test.describe("kutu katmanı, yoğunluk kameranın durumuna bağlı değil (masaüstü 1280 px, 5×5)", () => {
  test.use({ viewport: { width: 1280, height: 800 } });
  test("durum gelmeden, canlı, bağlantı yok, yeniden canlı: fare kutunun üstündeyken yoğunluk ve kutu düğmeleri değişmez, parçalar kutuda", async ({ page }) => {
    const tiles5 = Array.from({ length: 25 }, (_, i) => (i === 0 ? { sourceId: "a", channelId: null } : i === 1 ? { sourceId: "b", channelId: "2" } : null));
    const view = { ...VIEW, layout: "5x5", tiles: tiles5 };
    let state: object = LIVE;
    const status = () => ({ id: "v1", layout: "5x5", tiles: tiles5.map((t, i) => (!t ? null : i === 0
      ? { ...t, name: "Mağaza girişi kamerası", ...state, analysis: { mode: "detect", sessionId: "s1", name: "Mağaza girişi", entered: 3, exited: 1, alarm: null } }
      : { ...t, name: "Ofis NVR · Kasa", ...LIVE, analysis: { ...GUARD, sessionId: "s2", alarm: null } })) });
    await mock(page, {}, view);
    let release!: () => void;
    const gate = new Promise<void>((res) => { release = res; });
    await page.route("**/api/live/views/v1/status", async (r) => { await gate; await r.fulfill({ json: status() }); });
    await login(page);
    const tile = page.getByTestId("watch-tile").nth(0);
    await expect(tile).toContainText("Kapı");                                          // durum yok: kamera listesindeki ad, "Bağlanıyor…"
    await tile.hover();
    const at = async (what: string, parts: string[]) => {
      await expect(tile, what).toHaveAttribute("data-tier", "full");
      await expect(tile.locator("[data-part=actions]"), what).toBeVisible();
      expect.soft(await partsClear(tile, what), `${what}: görünen parçalar`).toEqual(parts);
    };
    await at("durum gelmeden", ["actions", "dot", "name"]);
    release();
    await expect(tile.locator("[data-part=badge]")).toHaveText("G 3 · Ç 1");
    await expect(tile.locator("[data-part=dot]")).toHaveCount(0);
    await at("canlı", ["actions", "badge", "name"]);
    state = NO_LINK;
    await expect(tile.locator("[data-part=dot]")).toHaveCount(1);
    await at("bağlantı yok", ["actions", "badge", "dot", "name"]);
    state = LIVE;
    await expect(tile.locator("[data-part=dot]")).toHaveCount(0);
    await at("yeniden canlı", ["actions", "badge", "name"]);
  });
});

test.describe("dokunmatik dar ekran (390 px)", () => {
  test.use({ viewport: { width: 390, height: 800 }, hasTouch: true, isMobile: true });

  test("dirty iken aynı adrese bağlantı (menüde Canlı izleme): gezinmez, düzenleme kalır, menü kapanır", async ({ page }) => {
    await mock(page, STATUS);
    await login(page);
    const tiles = page.getByTestId("watch-tile");
    await expect(tiles.nth(0)).toContainText("Kapı");
    await tiles.nth(3).tap();
    await camera(page, "Depo").tap();
    await expect(tiles.nth(3)).toContainText("Depo");
    await expect(gridSrc(page)).toHaveAttribute("src", /\/views\/draft-1\/stream/);
    let polls = 0;                                                                    // bu sayfanın taslak-1 durum yoklamaları
    await page.route("**/api/live/views/draft-1/status", (r) => { polls += 1; return r.fallback(); });
    const dialogs: string[] = [];
    page.on("dialog", (d) => { dialogs.push(d.message()); void d.dismiss(); });
    const length = await page.evaluate(() => history.length);
    await page.getByRole("button", { name: "Menü" }).tap();
    await page.getByRole("navigation", { name: "Ana menü" }).getByRole("link", { name: "Canlı izleme", exact: true }).tap();
    const after = polls;
    await expect(page.getByTestId("menu-backdrop")).toHaveCount(0);                  // menü kapandı
    await expect(page).toHaveURL(/\/watch$/);
    await expect(tiles.nth(3)).toContainText("Depo");
    await expect(tab(page, /^Giriş katı/)).toContainText("*");
    expect(dialogs).toEqual([]);
    expect(await page.evaluate(() => history.length)).toBe(length);
    // sayfa yeniden kurulmadı: kurulsaydı düzenleme geri yüklemeyle gelirdi (bildirim) ve yeni taslak açılırdı. Aynı
    // sayfanın taslak-1 yoklaması iki tur daha sürer (yeniden kurulan sayfa taslak-2'yi yoklardı), sonra bakılır
    await expect.poll(() => polls).toBeGreaterThanOrEqual(after + 2);
    await expect(page.getByRole("status").filter({ hasText: RESTORED })).toHaveCount(0);
    await expect(gridSrc(page)).toHaveAttribute("src", /\/views\/draft-1\/stream/);
  });

  test("kutunun içindeki düğmeye (⋯, alarm etiketi) çift dokunmak tek kamerayı açmaz", async ({ page }) => {
    await mock(page, STATUS);
    await login(page);
    const tiles = page.getByTestId("watch-tile");
    await expect(tiles.nth(1)).toHaveAttribute("data-alarm", "true");
    const single = page.getByRole("button", { name: "← Izgaraya dön" });
    // art arda iki dokunuş (ör. iki kutunun aynı yerdeki ⋯'si) tarayıcıda çift tık olur
    await tiles.nth(1).getByRole("button", { name: "Kutu işlemleri" }).dblclick();
    await expect(page.getByRole("menu", { name: "Kutu işlemleri" })).toBeVisible();
    await expect(single).toHaveCount(0);
    await page.keyboard.press("Escape");
    await tiles.nth(1).getByRole("button", { name: /^Alarmı aç/ }).dblclick();
    await expect(single).toHaveCount(0);
    await expect(tiles).toHaveCount(4);                                               // ızgara yerinde
  });

  test("seçili kutunun ⋯ menüsünden ve Şablon editöründen boşaltılır", async ({ page }) => {
    await mock(page, STATUS);
    await login(page);
    const tiles = page.getByTestId("watch-tile");
    await expect(tiles.nth(0)).toContainText("Kapı");
    await expect(tiles.nth(1)).toHaveAttribute("data-alarm", "true");
    await expect(page.getByRole("button", { name: "Kutu işlemleri" })).toHaveCount(1);   // yalnız alarmlı kutuda (seçili kutu yok)
    // Alarmlı kutuya dokunmak alarmı açar; kutu ⋯ menüsündeki "Seç" ile seçilir, sonra boşaltılır. İlk düzenlemeden ÖNCE
    // denenir: düzenleyince ızgara taslağın durumunu gösterir, sahte taslak durumunda analiz (alarm) yok
    const menu = page.getByRole("menu", { name: "Kutu işlemleri" });
    await tiles.nth(1).getByRole("button", { name: "Kutu işlemleri" }).tap();
    await expect(menu.getByRole("menuitem")).toHaveText(["Seç", "Tek kamera", "Boşalt"]);
    await menu.getByRole("menuitem", { name: "Seç" }).tap();
    await expect(tiles.nth(1)).toHaveAttribute("data-selected", "true");
    await expect(page.getByRole("alertdialog")).toHaveCount(0);                         // alarm penceresi açılmadı
    await tiles.nth(1).getByRole("button", { name: "Kutu işlemleri" }).tap();
    await expect(menu.getByRole("menuitem")).toHaveText(["Tek kamera", "Boşalt"]);
    await menu.getByRole("menuitem", { name: "Boşalt" }).tap();
    await expect(tiles.nth(1)).toHaveAttribute("data-empty", "true");
    await tiles.nth(0).tap();
    await expect(tiles.nth(0)).toHaveAttribute("data-selected", "true");
    await tiles.nth(0).getByRole("button", { name: "Kutu işlemleri" }).tap();
    await menu.getByRole("menuitem", { name: "Boşalt" }).tap();
    await expect(tiles.nth(0)).toHaveAttribute("data-empty", "true");
    await tiles.nth(2).tap();
    await expect(tiles.nth(2)).toHaveAttribute("data-selected", "true");
    await page.getByRole("button", { name: "Şablon editörü" }).tap();
    await editor(page).getByRole("button", { name: "Seçili kutuyu boşalt" }).tap();
    await expect(tiles.nth(2)).toHaveAttribute("data-empty", "true");
    await expect(editor(page).getByRole("button", { name: "Seçili kutuyu boşalt" })).toBeDisabled();
    await page.getByRole("button", { name: "Şablon editörü" }).tap();                 // kapat
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  });
});

test("kayıt yarışı: yeni şablon kaydedilirken başka sekmeye geçilip orada düzenlenirse, o düzenleme kalır ve sekme değişmez", async ({ page }) => {
  await mock(page, STATUS, [VIEW, V2]);
  await page.route("**/api/live/views/v2/status", (r) => r.fulfill({ json: { id: "v2", layout: "1", tiles: [] } }));
  await page.route("**/api/live/views/v2/stream**", (r) => r.fulfill({ body: JPEG, contentType: "image/jpeg" }));
  const created: object[] = [];
  let release!: () => void;
  const gate = new Promise<void>((res) => { release = res; });
  await page.route("**/api/live/views", async (r) => {
    if (r.request().method() !== "POST") return r.fulfill({ json: [VIEW, V2, ...created] });
    await gate;
    const v = { id: "n9", createdAt: 9, updatedAt: 9, ...(r.request().postDataJSON() as object) };
    created.push(v);
    return r.fulfill({ json: v });
  });
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  await page.getByRole("button", { name: "Yeni şablon" }).click();
  await camera(page, "Kapı").click();
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();          // istek bekliyor
  await expect(page.getByRole("button", { name: "Yeni şablon", exact: true })).toBeDisabled();   // kayıt sürerken yeni sekme açılmaz
  page.once("dialog", (d) => void d.accept());                                     // yeni sekmenin düzenlemesi: sorulur
  await tab(page, "Depo katı").click();
  await expect(tab(page, "Depo katı")).toHaveAttribute("aria-selected", "true");
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles).toHaveCount(1);
  await tiles.nth(0).click({ button: "right" });
  await page.getByRole("menuitem", { name: "Boşalt" }).click();
  await expect(tiles.nth(0)).toHaveAttribute("data-empty", "true");
  release();
  await expect(tab(page, "Yeni şablon")).toBeVisible();                             // kaydedildi, sekmesi eklendi
  await expect(page.getByText('"Yeni şablon" şablonu eklendi.')).toBeVisible();
  await expect(tab(page, /^Depo katı/)).toHaveAttribute("aria-selected", "true");   // geçilmedi
  await expect(tab(page, /^Depo katı/)).toContainText("*");
  await expect(tiles).toHaveCount(1);
  await expect(tiles.nth(0)).toHaveAttribute("data-empty", "true");                // B'nin düzenlemesi duruyor
  await expect(page.getByRole("button", { name: "Yeni şablon", exact: true })).toBeEnabled();
});

test("Kopyala ve NVR'dan şablon: kaydedilmemiş düzenlemeyi atmayı onaylayınca yeni şablona geçilir", async ({ page }) => {
  await mock(page, STATUS);
  const { store } = await mockStore(page, [VIEW]);
  await page.route("**/api/live/views/from-recorder", (r) => {
    const v = { id: "r1", name: "Ofis NVR", layout: "4", tiles: [{ sourceId: "b", channelId: "1" }, null, null, null],
      createdAt: 6, updatedAt: 6, truncated: false, channelCount: 1 };
    store.push(v);
    return r.fulfill({ json: v });
  });
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  const messages: string[] = [];
  page.on("dialog", (d) => { messages.push(d.message()); void d.accept(); });
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await tab(page, /^Giriş katı/).click({ button: "right" });
  await page.getByRole("menuitem", { name: "Kopyala" }).click();
  await expect(tab(page, "Giriş katı (kopya)")).toHaveAttribute("aria-selected", "true");
  expect(messages).toEqual([UNSAVED]);
  await expect(tab(page, "Giriş katı")).not.toContainText("*");                     // düzenleme atıldı (onaylandı)
  await camera(page, "Depo").dragTo(tiles.nth(3));                                   // kopyada düzenle, NVR'dan şablon
  const ed = await openEditor(page);
  await ed.getByRole("combobox", { name: "NVR'dan şablon" }).selectOption("b");
  await expect(tab(page, "Ofis NVR")).toHaveAttribute("aria-selected", "true");
  expect(messages).toEqual([UNSAVED, UNSAVED]);
  await expect(page.getByText("şablonu eklendi")).toHaveCount(0);
});

test("Yeniden adlandır, kaydedilmemiş düzenleme varken: ad sunucudaki güncel hâlle yazılır, buradaki düzenleme ve diğer sekmeler kalır", async ({ page }) => {
  await mock(page, STATUS, [VIEW, V2]);
  const { calls, store } = await mockStore(page, [{ ...VIEW }, { ...V2 }]);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  await camera(page, "Depo").dragTo(tiles.nth(3));
  Object.assign(store[0], { layout: "1", tiles: [{ sourceId: "a", channelId: null }] });   // başka cihazda düzenlendi
  store.splice(1, 1);                                                                // öbür şablon başka yerde silindi
  await tab(page, /^Giriş katı/).click({ button: "right" });
  await page.getByRole("menuitem", { name: "Yeniden adlandır" }).click();
  const dlg = page.getByRole("dialog", { name: "Yeniden adlandır" });
  await dlg.getByLabel("Şablon adı").fill("Zemin kat");
  await dlg.getByRole("button", { name: "Tamam" }).click();
  await expect(tab(page, /^Zemin kat/)).toContainText("*");                         // düzenleme duruyor
  await expect(tab(page, "Depo katı")).toBeVisible();                                // yalnız bu şablon güncellendi (liste olduğu gibi)
  expect(calls.at(-1)).toMatchObject({ method: "PUT", body: { name: "Zemin kat", layout: "1", tiles: [{ sourceId: "a", channelId: null }] } });
  await expect(tiles).toHaveCount(4);
  await expect(tiles.nth(3)).toContainText("Depo");
});

test("başka yerde silinen şablon, liste yenilenince fark edilirse de kaydedilmemiş düzenleme yeni sekmede kalır", async ({ page }) => {
  await mock(page, STATUS, [VIEW, V2]);
  const { store } = await mockStore(page, [VIEW, V2]);
  page.on("dialog", (d) => void d.accept());
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  await camera(page, "Depo").dragTo(tiles.nth(3));
  store.splice(store.findIndex((v) => v.id === "v1"), 1);                            // başka cihazda silindi
  await tab(page, "Depo katı").click({ button: "right" });                           // başka sekmeyi sil: liste yenilenir
  await page.getByRole("menuitem", { name: "Sil" }).click();
  await expect(page.getByText("Bu şablon başka yerde silindi; değişiklikler kaydedilmemiş yeni sekmede.")).toBeVisible();
  await expect(tab(page, /^Giriş katı/)).toHaveAttribute("aria-selected", "true");
  await expect(tab(page, /^Giriş katı/)).toContainText("*");
  await expect(tiles.nth(3)).toContainText("Depo");
  await expect(tab(page, "Depo katı")).toHaveCount(0);
});

test("Yeniden adlandır başka yerdeki düzenlemeyi geri almaz: sunucudaki güncel düzen ve kutular gider", async ({ page }) => {
  await mock(page, STATUS);
  const { calls, store } = await mockStore(page, [{ ...VIEW }]);
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  Object.assign(store[0], { layout: "1", tiles: [{ sourceId: "a", channelId: null }] });   // başka cihazda düzenlendi
  await tab(page, "Giriş katı").click({ button: "right" });
  await page.getByRole("menuitem", { name: "Yeniden adlandır" }).click();
  const dlg = page.getByRole("dialog", { name: "Yeniden adlandır" });
  await dlg.getByLabel("Şablon adı").fill("Zemin kat");
  await dlg.getByRole("button", { name: "Tamam" }).click();
  await expect(tab(page, "Zemin kat")).toBeVisible();
  expect(calls.at(-1)).toMatchObject({ method: "PUT", body: { name: "Zemin kat", layout: "1", tiles: [{ sourceId: "a", channelId: null }] } });
  await expect(page.getByTestId("watch-tile")).toHaveCount(1);                     // değişiklik yoktu: güncel hâl izlenir
});

for (const late of [false, true]) {
  test(`başka yerde silinen şablonun kaydedilmemiş düzenlemesi atılmaz (${late ? "liste alındıktan sonra silindi: PUT 404" : "Kaydet'ten hemen önceki listede yok: PUT gönderilmez"}): yeni sekmede kalır, Kaydet yeni şablon yazar`, async ({ page }) => {
    await mock(page, STATUS);
    const { calls, store } = await mockStore(page, [VIEW]);
    await login(page);
    const tiles = page.getByTestId("watch-tile");
    await expect(tiles.nth(0)).toContainText("Kapı");
    await camera(page, "Depo").dragTo(tiles.nth(3));
    if (!late) store.splice(0, 1);                                                    // başka cihazda silindi
    let put404 = 0;
    await page.route("**/api/live/views/v1", (r) => {
      if (r.request().method() !== "PUT") return r.fallback();
      put404 += 1;
      const i = store.findIndex((v) => v.id === "v1");
      if (i >= 0) store.splice(i, 1);                                                 // late: liste alındıktan hemen sonra silindi
      return r.fulfill({ status: 404, json: { detail: "Şablon bulunamadı." } });
    });
    await page.getByRole("button", { name: "Kaydet", exact: true }).click();
    await expect(page.getByText("Bu şablon başka yerde silindi; değişiklikler kaydedilmemiş yeni sekmede.")).toBeVisible();
    expect(put404).toBe(late ? 1 : 0);
    await expect(tab(page, /^Giriş katı/)).toHaveAttribute("aria-selected", "true");
    await expect(tab(page, /^Giriş katı/)).toContainText("*");
    await expect(tiles.nth(3)).toContainText("Depo");
    await page.getByRole("button", { name: "Kaydet", exact: true }).click();
    await expect.poll(() => calls.filter((c) => c.method === "POST").length).toBe(1);
    expect(calls.at(-1)).toMatchObject({ method: "POST", body: { name: "Giriş katı", layout: "4",
      tiles: [...VIEW.tiles.slice(0, 3), { sourceId: "d", channelId: null }] } });
    await expect(tab(page, "Giriş katı")).toHaveAttribute("aria-selected", "true");
  });
}

for (const early of [false, true]) {
  test(`kaydedilmemiş değişiklik: Çıkış bir kez sorar ve oturumu kapatır; taslak oturum kapanmadan silinir${early ? " (taslak daha açılmadan Çıkış: sonradan da açılmaz)" : ""}`, async ({ page }) => {
    const drafts = await mock(page, STATUS);
    await login(page);
    const tiles = page.getByTestId("watch-tile");
    await expect(tiles.nth(0)).toContainText("Kapı");
    // oturum kapatma isteği 2,5 sn sürer: sayfa ancak sonra değişir (onay bir süre sonra düşse yeniden sorulurdu)
    const order: string[] = [];
    page.on("request", (q) => { if (/\/api\/(logout|live\/views\/drafts)/.test(q.url())) order.push(`${q.method()} ${new URL(q.url()).pathname}`); });
    await page.route("**/api/logout", async (r) => { await new Promise((res) => setTimeout(res, 2500)); await r.continue(); });
    const dialogs: string[] = [];
    page.on("dialog", (d) => { dialogs.push(`${d.type()}: ${d.message()}`); void d.accept(); });
    await camera(page, "Depo").dragTo(tiles.nth(3));
    await expect.poll(() => stored(page)).not.toBeNull();
    if (!early) await expect.poll(() => drafts.store.size).toBe(1);                     // taslak açıldı
    await page.getByRole("button", { name: "Çıkış" }).click();
    await expect(page).toHaveURL(/\/login/);
    expect(dialogs).toEqual([`confirm: ${UNSAVED}`]);
    expect(await stored(page)).toBeNull();                                              // çıkışta saklanan düzenleme silindi
    // taslak, oturum çerezi silinmeden (Çıkış isteğinden önce) silindi; sayfa kapanırken girişsiz silme isteği gitmedi
    expect(drafts.store.size).toBe(0);
    expect(order.at(-1)).toBe("POST /api/logout");
    if (!early) expect(order).toEqual(["POST /api/live/views/drafts", "DELETE /api/live/views/drafts/draft-1", "POST /api/logout"]);
    else expect(order.filter((o) => o.startsWith("DELETE"))).toEqual(order.filter((o) => o === "POST /api/live/views/drafts").map(() => "DELETE /api/live/views/drafts/draft-1"));
  });
}

/** Alarmlar sayfasına gidip Canlı izlemeye döner (Geri ile dönülecek bir önceki sayfa olsun) */
async function viaAlarms(page: Page) {
  const nav = page.getByRole("navigation", { name: "Ana menü" });
  await nav.getByRole("link", { name: "Alarmlar", exact: true }).click();
  await expect(page).toHaveURL(/\/alarms$/);
  await nav.getByRole("link", { name: "Canlı izleme", exact: true }).click();
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
}

test("geri yükleme: Geri sormaz ve geçmişe kayıt eklenmez; İleri ile dönünce düzenleme geri yüklenir (taslak akar, hâlâ kaydedilmedi)", async ({ page }) => {
  const drafts = await mock(page, STATUS);
  await mockStore(page, [VIEW]);
  await login(page);
  await viaAlarms(page);
  const tiles = page.getByTestId("watch-tile");
  const dialogs: string[] = [];
  page.on("dialog", (d) => { dialogs.push(d.message()); void d.dismiss(); });
  const length = await page.evaluate(() => history.length);
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await tiles.nth(0).click({ button: "right" });
  await page.getByRole("menuitem", { name: "Boşalt" }).click();
  await expect(tab(page, /^Giriş katı/)).toContainText("*");
  expect(await page.evaluate(() => history.length)).toBe(length);                  // düzenleme geçmişe kayıt eklemez
  await expect.poll(() => stored(page)).toMatchObject({ origin: "v1", name: "Giriş katı", layout: "4",
    tiles: [null, ...VIEW.tiles.slice(1, 3), { sourceId: "d", channelId: null }], updatedAt: 1 });
  await expect(gridSrc(page)).toHaveAttribute("src", /\/views\/draft-1\/stream/);      // taslak açıldı
  await page.goBack();
  await expect(page).toHaveURL(/\/alarms$/);                                       // sorulmadan önceki sayfa
  expect(dialogs).toEqual([]);
  await page.goForward();
  await expect(page.getByRole("status").filter({ hasText: RESTORED })).toBeVisible();
  await expect(tab(page, /^Giriş katı/)).toHaveAttribute("aria-selected", "true");
  await expect(tab(page, /^Giriş katı/)).toContainText("*");
  await expect(tiles.nth(3)).toContainText("Depo");
  await expect(tiles.nth(0)).toHaveAttribute("data-empty", "true");
  await expect(gridSrc(page)).toHaveAttribute("src", /\/views\/draft-2\/stream/);      // yeni taslak açıldı
  expect(drafts.calls.filter((c) => c.method === "DELETE").map((c) => c.url)).toEqual([expect.stringContaining("/drafts/draft-1")]);
  // geri yüklenen düzenleme kayıtlı hâlin üstüne tek adımdır: Geri al kayıtlı hâle döner, kayıt silinir
  await page.keyboard.press("Control+z");
  await expect(tab(page, "Giriş katı")).not.toContainText("*");
  await expect.poll(() => stored(page)).toBeNull();
  await expect(page.getByRole("status").filter({ hasText: RESTORED })).toHaveCount(0);
  expect(dialogs).toEqual([]);
});

test("geri yükleme: sayfa yenilenince (beforeunload onaylanır) düzenleme geri gelir; 'Değişiklikleri at' atar ve kaydı siler", async ({ page }) => {
  await mock(page, STATUS);
  await mockStore(page, [VIEW]);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  page.on("dialog", (d) => void d.accept());
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await expect.poll(() => stored(page)).not.toBeNull();
  await page.reload();
  await expect(page.getByRole("status").filter({ hasText: RESTORED })).toBeVisible();
  await expect(tiles.nth(3)).toContainText("Depo");
  await expect(tab(page, /^Giriş katı/)).toContainText("*");
  await page.getByRole("button", { name: "Değişiklikleri at" }).click();
  await expect(tiles.nth(3)).toHaveAttribute("data-empty", "true");
  await expect(tab(page, "Giriş katı")).not.toContainText("*");
  await expect(tab(page, "Giriş katı")).toBeFocused();                                // düğme kalktı: odak sekmeye geçer (sayfaya düşmez)
  await expect.poll(() => stored(page)).toBeNull();
  await expect(page.getByRole("status").filter({ hasText: RESTORED })).toHaveCount(0);
});

test("geri yükleme: kaydedilmemiş yeni sekmede 'Değişiklikleri at' sekmeyi kapatır, odak açılan sekmeye geçer", async ({ page }) => {
  await mock(page, STATUS);
  await mockStore(page, [VIEW]);
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  page.on("dialog", (d) => void d.accept());
  await page.getByRole("button", { name: "Yeni şablon", exact: true }).click();
  await camera(page, "Kapı").click();
  await expect.poll(() => stored(page)).toMatchObject({ name: "Yeni şablon" });
  await page.reload();
  await expect(page.getByRole("status").filter({ hasText: RESTORED })).toBeVisible();
  await page.getByRole("button", { name: "Değişiklikleri at" }).click();
  await expect(tab(page, /^Yeni şablon/)).toHaveCount(0);
  await expect(tab(page, "Giriş katı")).toHaveAttribute("aria-selected", "true");
  await expect(tab(page, "Giriş katı")).toBeFocused();
  await expect.poll(() => stored(page)).toBeNull();
});

test("geri yükleme: kaydedilmemiş yeni şablon da geri gelir; Kaydet kaydı siler", async ({ page }) => {
  await mock(page, STATUS);
  const { calls } = await mockStore(page, [VIEW]);
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  page.on("dialog", (d) => void d.accept());
  await page.getByRole("button", { name: "Yeni şablon", exact: true }).click();
  await camera(page, "Kapı").click();
  await expect.poll(() => stored(page)).toMatchObject({ name: "Yeni şablon", layout: "4" });
  await page.reload();
  await expect(page.getByRole("status").filter({ hasText: RESTORED })).toBeVisible();
  await expect(tab(page, /^Yeni şablon/)).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect(tab(page, "Yeni şablon")).toHaveAttribute("aria-selected", "true");
  expect(calls.at(-1)).toMatchObject({ method: "POST", body: { name: "Yeni şablon", layout: "4" } });
  await expect.poll(() => stored(page)).toBeNull();
});

test("geri yükleme: şablon bu arada başka yerde silindiyse yeni sekmede, değiştirildiyse üstüne açılır ve söylenir (Kaydet sorar)", async ({ page }) => {
  await mock(page, STATUS);
  const { calls, store } = await mockStore(page, [{ ...VIEW }]);
  await login(page);
  await viaAlarms(page);
  const tiles = page.getByTestId("watch-tile");
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await expect.poll(() => stored(page)).not.toBeNull();
  await page.goBack();
  await expect(page).toHaveURL(/\/alarms$/);
  Object.assign(store[0], { updatedAt: 9 });                                         // başka yerde değiştirildi
  await page.goForward();
  await expect(page.getByRole("status").filter({ hasText: "başka yerde değiştirildi" })).toBeVisible();
  await expect(tab(page, /^Giriş katı/)).toContainText("*");
  await expect(tiles.nth(3)).toContainText("Depo");
  // geri yüklenen düzenlemenin temeli saklanan updatedAt'tir: Kaydet üzerine yazmadan sorar; Vazgeç yazmaz
  const asked: string[] = [];
  page.once("dialog", (d) => { asked.push(d.message()); void d.dismiss(); });
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect.poll(() => asked).toEqual([CHANGED]);
  await expect(page.getByRole("button", { name: "Kaydet", exact: true })).toBeEnabled();
  expect(puts(calls)).toHaveLength(0);
  expect(await stored(page)).toMatchObject({ origin: "v1", updatedAt: 1 });
  await page.goBack();
  await expect(page).toHaveURL(/\/alarms$/);
  store.splice(0, 1);                                                               // başka yerde silindi
  await page.goForward();
  await expect(page.getByRole("status").filter({ hasText: "başka yerde silindi; değişiklikler kaydedilmemiş yeni sekmede" })).toBeVisible();
  await expect(tab(page, /^Giriş katı/)).toHaveAttribute("aria-selected", "true");
  await expect(tab(page, /^Giriş katı/)).toContainText("*");
  await expect(tiles.nth(3)).toContainText("Depo");
  expect((await stored(page))?.origin).toMatch(/^yeni-/);
});

test("geri yükleme: onaylanmış bağlantıyla çıkınca kayıt silinir; bozuk kayıt yok sayılır ve silinir", async ({ page }) => {
  await mock(page, STATUS);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await expect.poll(() => stored(page)).not.toBeNull();
  page.once("dialog", (d) => void d.accept());
  await page.getByRole("navigation", { name: "Ana menü" }).getByRole("link", { name: "Alarmlar", exact: true }).click();
  await expect(page).toHaveURL(/\/alarms$/);
  expect(await stored(page)).toBeNull();
  // bozuk kayıt: sayfa çalışır, kayıt silinir, bildirim yok. İkincisi düzeni ("4") tanınan ama ayrıştırıcının reddettiği
  // kayıt (kamera kimliği sayı): ayrıştırıcı kabul etseydi geri yüklenirdi (bildirim, "*")
  for (const bad of ["{bozuk", JSON.stringify({ v: 1, origin: "v1", name: "x", layout: "4", tiles: [{ sourceId: 5 }], updatedAt: 1 })]) {
    await page.evaluate((v) => sessionStorage.setItem("bv.watch.unsaved", v), bad);
    await page.goto("/watch");
    await expect(tiles.nth(0)).toContainText("Kapı");
    await expect(tiles).toHaveCount(4);
    await expect.poll(() => page.evaluate(() => sessionStorage.getItem("bv.watch.unsaved"))).toBeNull();
    await expect(page.getByRole("status").filter({ hasText: RESTORED })).toHaveCount(0);
    await expect(tab(page, "Giriş katı")).not.toContainText("*");
    await expect(page.getByText("Kaydedilmemiş değişiklik var")).toBeHidden();
    await expect(gridSrc(page)).toHaveAttribute("src", /\/views\/v1\/stream/);          // ızgara şablonu akıtır (taslak yok)
    await tiles.nth(3).click();                                                        // ızgara kullanılabilir
    await expect(tiles.nth(3)).toHaveAttribute("data-selected", "true");
  }
});

/** Saklanan düzenleme kaydı: Giriş katı'nın 4. kutusuna Depo eklenmiş (şablonun updatedAt'i 1 iken başladı) */
const ENTRY = { v: 1, origin: "v1", name: "Giriş katı", layout: "4", tiles: [...VIEW.tiles.slice(0, 3), { sourceId: "d", channelId: null }], updatedAt: 1 };
const V3 = { id: "v3", name: "Bahçe", layout: "1", createdAt: 3, updatedAt: 3, tiles: [null] };

/**
 * Başka bir şablonu (`del`) siler; liste yenilenir. Yenilenen listenin uygulandığı görülsün diye depoda `id` şablonunun
 * adı `rename` olur ve sekmesi beklenir.
 */
async function reloadByDelete(page: Page, store: Array<{ id: string; name?: string }>, del: string, id: string, rename: string) {
  Object.assign(store.find((v) => v.id === id)!, { name: rename });
  await tab(page, del).click({ button: "right" });
  await page.getByRole("menuitem", { name: "Sil" }).click();
  await expect(tab(page, rename)).toBeVisible();
}

test("Çıkış başka sayfadan da saklanan düzenlemeyi siler (Canlı izlemeden Geri ile çıkılmış)", async ({ page }) => {
  await mock(page, STATUS);
  await login(page);
  await viaAlarms(page);
  await camera(page, "Depo").dragTo(page.getByTestId("watch-tile").nth(3));
  await expect.poll(() => stored(page)).not.toBeNull();
  await page.goBack();
  await expect(page).toHaveURL(/\/alarms$/);
  const dialogs: string[] = [];
  page.on("dialog", (d) => { dialogs.push(`${d.type()}: ${d.message()}`); void d.accept(); });
  await page.getByRole("button", { name: "Çıkış" }).click();
  await expect(page).toHaveURL(/\/login/);
  expect(dialogs).toEqual([]);                                                        // bu sayfada değişiklik yok: sorulmaz
  expect(await stored(page)).toBeNull();                                              // sonraki girişte geri yüklenmez
});

test("Çıkış, Canlı izleme açılırken (şablon listesi gelmeden) basılırsa saklanan düzenleme sonradan geri yüklenip yeniden yazılmaz", async ({ page }) => {
  await mock(page, STATUS);
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  let release!: () => void;
  const gate = new Promise<void>((res) => { release = res; });
  await page.route("**/api/live/views", async (r) => { await gate; await r.fulfill({ json: [VIEW] }); });
  // liste, oturum kapatma isteği sürerken gelir (sayfa henüz /login'e geçmedi)
  await page.route("**/api/logout", async (r) => { release(); await new Promise((res) => setTimeout(res, 1500)); await r.continue(); });
  await page.evaluate((e) => sessionStorage.setItem("bv.watch.unsaved", JSON.stringify(e)), ENTRY);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Canlı izleme" })).toBeVisible();
  await expect(page.getByTestId("watch-tile")).toHaveCount(0);                       // liste bekliyor
  const dialogs: string[] = [];
  page.on("dialog", (d) => { dialogs.push(`${d.type()}: ${d.message()}`); void d.accept(); });
  await page.getByRole("button", { name: "Çıkış" }).click();
  await expect(page).toHaveURL(/\/login/);
  expect(dialogs).toEqual([]);                                                        // geri yüklenip "kaydedilmedi" olmadı
  expect(await stored(page)).toBeNull();
});

test("Kaydet: şablon bu düzenleme başladıktan sonra başka yerde değiştirildiyse sorar; Vazgeç yazmaz ve düzenleme kalır, Tamam yazar", async ({ page }) => {
  await mock(page, STATUS);
  const { calls, store } = await mockStore(page, [{ ...VIEW }]);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await expect(tab(page, /^Giriş katı/)).toContainText("*");
  Object.assign(store[0], { updatedAt: 9 });                                         // başka yerde değiştirildi (bu sayfanın listesi eski)
  const save = page.getByRole("button", { name: "Kaydet", exact: true });
  const dialogs: string[] = [];
  page.once("dialog", (d) => { dialogs.push(d.message()); void d.dismiss(); });
  await save.click();
  await expect.poll(() => dialogs).toEqual([CHANGED]);
  await expect(save).toBeEnabled();                                                   // istek bitti, hâlâ kaydedilmedi
  expect(puts(calls)).toHaveLength(0);
  await expect(tab(page, /^Giriş katı/)).toContainText("*");
  await expect(tiles.nth(3)).toContainText("Depo");
  await expect(page.getByText("Kaydedilmemiş değişiklik var")).toBeVisible();
  await expect.poll(() => stored(page)).toMatchObject({ origin: "v1", updatedAt: 1 });
  page.once("dialog", (d) => { dialogs.push(d.message()); void d.accept(); });
  await save.click();
  await expect.poll(() => puts(calls).length).toBe(1);
  expect(dialogs).toEqual([CHANGED, CHANGED]);
  expect(puts(calls)[0].body).toEqual({ name: "Giriş katı", layout: "4", tiles: ENTRY.tiles });
  await expect(tab(page, "Giriş katı")).not.toContainText("*");
  await expect(page.getByText("Kaydedilmemiş değişiklik var")).toBeHidden();
  await expect.poll(() => stored(page)).toBeNull();
});

test("Kaydet: değişmemiş şablonda sormaz; kaydetmek ve burada yeniden adlandırmak temeli günceller; liste yenilense de temel (ve saklanan) değişmez", async ({ page }) => {
  await mock(page, STATUS, [VIEW, V2, V3]);
  const { calls, store } = await mockStore(page, [{ ...VIEW }, { ...V2 }, { ...V3 }]);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  const dialogs: string[] = [];
  page.on("dialog", (d) => { dialogs.push(d.message()); void d.accept(); });
  const save = page.getByRole("button", { name: "Kaydet", exact: true });
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await save.click();
  await expect.poll(() => puts(calls).length).toBe(1);
  await expect(tab(page, "Giriş katı")).not.toContainText("*");
  // sunucu updatedAt'i artırdı; temel kaydedilen hâlin updatedAt'i oldu: yeniden düzenleyip kaydetmek sormaz
  await tiles.nth(3).click({ button: "right" });
  await page.getByRole("menuitem", { name: "Boşalt" }).click();
  await save.click();
  await expect.poll(() => puts(calls).length).toBe(2);
  // kaydedilmemiş düzenleme varken burada yeniden adlandırmak kendi değişikliğimizdir: Kaydet yine sormaz
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await tab(page, /^Giriş katı/).click({ button: "right" });
  await page.getByRole("menuitem", { name: "Yeniden adlandır" }).click();
  const dlg = page.getByRole("dialog", { name: "Yeniden adlandır" });
  await dlg.getByLabel("Şablon adı").fill("Zemin kat");
  await dlg.getByRole("button", { name: "Tamam" }).click();
  await expect(tab(page, /^Zemin kat/)).toContainText("*");
  await save.click();
  await expect.poll(() => puts(calls).length).toBe(4);                              // ad + Kaydet
  await expect(tab(page, "Zemin kat")).not.toContainText("*");
  expect(dialogs).toEqual([]);
  // düzenleme sürerken başka yerde değişti ve liste yenilendi (başka şablon silindi): temel ve saklanan kayıt eski kalır, Kaydet sorar
  await tiles.nth(3).click({ button: "right" });
  await page.getByRole("menuitem", { name: "Boşalt" }).click();
  await expect.poll(() => stored(page)).not.toBeNull();
  const base = (await stored(page))!.updatedAt;
  Object.assign(store[0], { updatedAt: 99 });
  await reloadByDelete(page, store, "Bahçe", "v2", "Depo katı (2)");
  await expect(tab(page, /^Zemin kat/)).toContainText("*");
  expect((await stored(page))!.updatedAt).toBe(base);
  await save.click();
  await expect.poll(() => puts(calls).length).toBe(5);
  expect(dialogs).toEqual(['"Bahçe" şablonu silinsin mi?', CHANGED]);
});

/** Kaydet'in hemen önceki şablon listesi isteğini (GET views) bekletir; `release` ile bırakılır */
async function holdListGet(page: Page) {
  const h = { on: false, held: 0, release: () => undefined as void, gate: Promise.resolve() };
  await page.route("**/api/live/views", async (r) => {
    if (h.on && r.request().method() === "GET") { h.held += 1; await h.gate; }
    return r.fallback();
  });
  return {
    arm: () => { h.on = true; h.gate = new Promise<void>((res) => { h.release = () => { h.on = false; res(); }; }); },
    held: () => h.held,
    release: () => h.release(),
  };
}

test("Kaydet: denetim isteği sürerken başka sekmeye geçilirse (atma onaylandı) ne üzerine yazma sorulur ne kaydedilir", async ({ page }) => {
  await mock(page, STATUS, [VIEW, V2]);
  const { calls, store } = await mockStore(page, [{ ...VIEW }, { ...V2 }]);
  const list = await holdListGet(page);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  const dialogs: string[] = [];
  page.on("dialog", (d) => { dialogs.push(d.message()); void d.accept(); });
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await expect(tab(page, /^Giriş katı/)).toContainText("*");
  Object.assign(store[0], { updatedAt: 9 });                                         // başka yerde de değişti
  list.arm();
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect.poll(() => list.held()).toBe(1);                                     // liste isteği bekliyor
  await tab(page, "Depo katı").click();                                              // "Kaydedilmedi, çıkılsın mı?" → Tamam
  await expect(tab(page, "Depo katı")).toHaveAttribute("aria-selected", "true");
  list.release();
  await expect(page.getByRole("button", { name: "Yeni şablon", exact: true })).toBeEnabled();   // kayıt işlemi bitti
  expect(dialogs).toEqual([UNSAVED]);
  expect(puts(calls)).toHaveLength(0);
  await tab(page, "Giriş katı").click();
  await expect(tiles.nth(3)).toHaveAttribute("data-empty", "true");                  // düzenleme atıldı, şablon değişmedi
});

test("Kaydet: denetim isteği sürerken 'Değişiklikleri at' ile düzenleme atılırsa kaydedilmez", async ({ page }) => {
  await mock(page, STATUS);
  const { calls } = await mockStore(page, [{ ...VIEW }]);
  const list = await holdListGet(page);
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  const dialogs: string[] = [];
  page.on("dialog", (d) => { dialogs.push(d.message()); void d.accept(); });
  await page.evaluate((e) => sessionStorage.setItem("bv.watch.unsaved", JSON.stringify(e)), ENTRY);
  await page.reload();
  await expect(page.getByRole("status").filter({ hasText: RESTORED })).toBeVisible();
  list.arm();
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect.poll(() => list.held()).toBe(1);
  await page.getByRole("button", { name: "Değişiklikleri at" }).click();
  await expect(tab(page, "Giriş katı")).not.toContainText("*");
  list.release();
  await expect(page.getByRole("button", { name: "Yeni şablon", exact: true })).toBeEnabled();
  expect(dialogs).toEqual([]);
  expect(puts(calls)).toHaveLength(0);
  await expect(page.getByTestId("watch-tile").nth(3)).toHaveAttribute("data-empty", "true");
});

test("Kaydet: denetim isteği sürerken düzenlemeye devam edilirse Kaydet'e basıldığı andaki hâl yazılır; sonraki düzenleme (geri alma da) kaydedilmemiş kalır ve saklanır", async ({ page }) => {
  await mock(page, STATUS);
  const { calls, store } = await mockStore(page, [{ ...VIEW }]);
  const list = await holdListGet(page);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  const dialogs: string[] = [];
  page.on("dialog", (d) => { dialogs.push(d.message()); void d.accept(); });
  const save = page.getByRole("button", { name: "Kaydet", exact: true });
  const idle = () => expect(page.getByRole("button", { name: "Yeni şablon", exact: true })).toBeEnabled();   // kayıt işlemi bitti
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await expect(tab(page, /^Giriş katı/)).toContainText("*");
  list.arm();
  await save.click();
  await expect.poll(() => list.held()).toBe(1);
  await tiles.nth(0).click({ button: "right" });                                     // istek sürerken düzenleme sürer
  await page.getByRole("menuitem", { name: "Boşalt" }).click();
  await expect(tiles.nth(0)).toHaveAttribute("data-empty", "true");
  list.release();
  await expect.poll(() => puts(calls).length).toBe(1);
  expect(puts(calls)[0].body).toEqual({ name: "Giriş katı", layout: "4", tiles: ENTRY.tiles });   // Kaydet'e basıldığı andaki hâl
  await idle();
  expect(dialogs).toEqual([]);
  await expect(tab(page, /^Giriş katı/)).toContainText("*");                         // sonraki düzenleme kaydedilmedi
  await expect(page.getByText("Kaydedilmemiş değişiklik var")).toBeVisible();
  await expect(tiles.nth(0)).toHaveAttribute("data-empty", "true");
  await expect(tiles.nth(3)).toContainText("Depo");
  const later = [null, ...ENTRY.tiles.slice(1)];
  expect(store[0].updatedAt).toBe(2);
  // saklanan kayıt sonraki düzenlemeyi ve yeni temeli (PUT yanıtının updatedAt'i) taşır
  await expect.poll(() => stored(page)).toMatchObject({ origin: "v1", layout: "4", tiles: later, updatedAt: 2 });
  await save.click();                                                                 // temel güncel: sormadan yazar
  await expect.poll(() => puts(calls).length).toBe(2);
  expect(puts(calls)[1].body).toEqual({ name: "Giriş katı", layout: "4", tiles: later });
  await expect(tab(page, "Giriş katı")).not.toContainText("*");
  await expect.poll(() => stored(page)).toBeNull();
  // istek sürerken kayıtlı hâle geri alınırsa: Kaydet'e basıldığı andaki hâl yazılır, geri alınmış hâl kaydedilmemiş kalır
  await camera(page, "Kapı").dragTo(tiles.nth(0));
  await expect(tab(page, /^Giriş katı/)).toContainText("*");
  list.arm();
  await save.click();
  await expect.poll(() => list.held()).toBe(2);
  await page.keyboard.press("Control+z");
  await expect(tab(page, "Giriş katı")).not.toContainText("*");
  list.release();
  await expect.poll(() => puts(calls).length).toBe(3);
  expect(puts(calls)[2].body).toEqual({ name: "Giriş katı", layout: "4", tiles: ENTRY.tiles });
  await idle();
  await expect(tab(page, /^Giriş katı/)).toContainText("*");
  await expect(tiles.nth(0)).toHaveAttribute("data-empty", "true");
  await expect.poll(() => stored(page)).toMatchObject({ origin: "v1", tiles: later, updatedAt: 4 });
  expect(dialogs).toEqual([]);
});

test("Kaydet: denetim isteği sürerken 'Değişiklikleri at' sonrası yeniden düzenlense de kaydedilmez; yeni düzenleme kaydedilmemiş kalır", async ({ page }) => {
  await mock(page, STATUS);
  const { calls } = await mockStore(page, [{ ...VIEW }]);
  const list = await holdListGet(page);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  const dialogs: string[] = [];
  page.on("dialog", (d) => { dialogs.push(d.message()); void d.accept(); });
  await page.evaluate((e) => sessionStorage.setItem("bv.watch.unsaved", JSON.stringify(e)), ENTRY);
  await page.reload();
  await expect(page.getByRole("status").filter({ hasText: RESTORED })).toBeVisible();
  list.arm();
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect.poll(() => list.held()).toBe(1);
  await page.getByRole("button", { name: "Değişiklikleri at" }).click();
  await expect(tab(page, "Giriş katı")).not.toContainText("*");
  await tiles.nth(0).click({ button: "right" });                                     // atıldıktan sonra yeni düzenleme
  await page.getByRole("menuitem", { name: "Boşalt" }).click();
  await expect(tab(page, /^Giriş katı/)).toContainText("*");
  list.release();
  await expect(page.getByRole("button", { name: "Yeni şablon", exact: true })).toBeEnabled();
  expect(dialogs).toEqual([]);
  expect(puts(calls)).toHaveLength(0);
  await expect(tab(page, /^Giriş katı/)).toContainText("*");
  await expect(tiles.nth(0)).toHaveAttribute("data-empty", "true");
  await expect(tiles.nth(3)).toHaveAttribute("data-empty", "true");                  // atılan düzenleme geri gelmedi
  await expect.poll(() => stored(page)).toMatchObject({ origin: "v1", tiles: [null, ...VIEW.tiles.slice(1)], updatedAt: 1 });
});

test("şablon yazan işlemler tek tek: Kaydet sürerken Yeniden adlandır (sağ tık, sekme ⋯), Kopyala, Sil pasif; Kaydet sorusuz yazar, ad sonra değişir", async ({ page }) => {
  await mock(page, STATUS);
  const { calls, store } = await mockStore(page, [{ ...VIEW }]);
  const list = await holdListGet(page);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  const dialogs: string[] = [];
  page.on("dialog", (d) => { dialogs.push(d.message()); void d.accept(); });
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await expect(tab(page, /^Giriş katı/)).toContainText("*");
  list.arm();
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect.poll(() => list.held()).toBe(1);                                     // Kaydet'in denetim isteği bekliyor
  const tabMenu = page.getByRole("menu", { name: "Şablon işlemleri" });
  await tab(page, /^Giriş katı/).click({ button: "right" });
  for (const name of ["Yeniden adlandır", "Kopyala", "Sil"]) await expect(tabMenu.getByRole("menuitem", { name })).toBeDisabled();
  await page.keyboard.press("Escape");                                               // bütün öğeleri pasif menü de Esc ile kapanır
  await expect(tabMenu).toHaveCount(0);
  await page.getByRole("button", { name: /^Şablon işlemleri:/ }).click();            // sekme çubuğundaki ⋯
  await expect(tabMenu.getByRole("menuitem", { name: "Yeniden adlandır" })).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(tabMenu).toHaveCount(0);
  list.release();
  await expect.poll(() => puts(calls).length).toBe(1);
  expect(puts(calls)[0].body).toEqual({ name: "Giriş katı", layout: "4", tiles: ENTRY.tiles });
  await expect(page.getByRole("button", { name: "Yeni şablon", exact: true })).toBeEnabled();   // kayıt bitti
  await expect(tab(page, "Giriş katı")).not.toContainText("*");
  // kayıt bitince adlandırılır: sunucuda kullanıcının yaptığı (ad ve kutular)
  await tab(page, "Giriş katı").click({ button: "right" });
  await tabMenu.getByRole("menuitem", { name: "Yeniden adlandır" }).click();
  const dlg = page.getByRole("dialog", { name: "Yeniden adlandır" });
  await dlg.getByLabel("Şablon adı").fill("Zemin kat");
  await dlg.getByRole("button", { name: "Tamam" }).click();
  await expect(tab(page, "Zemin kat")).toBeVisible();
  expect(dialogs).toEqual([]);
  expect(store[0]).toMatchObject({ name: "Zemin kat", layout: "4", tiles: ENTRY.tiles });
});

test("şablon yazan işlemler tek tek: Yeniden adlandır sürerken (pencere Esc ile kapansa da) Kaydet, Farklı kaydet, Yeni şablon, NVR'dan şablon, +, Kopyala, Sil pasif; sonra Kaydet yeni adla yazar", async ({ page }) => {
  await mock(page, STATUS);
  const { calls, store } = await mockStore(page, [{ ...VIEW }]);
  let release!: () => void;
  const gate = new Promise<void>((res) => { release = res; });
  let held = 0;
  await page.route("**/api/live/views/v1", async (r) => {                            // ilk PUT (ad) bekletilir
    if (r.request().method() === "PUT" && held === 0) { held += 1; await gate; }
    await r.fallback();
  });
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  const dialogs: string[] = [];
  page.on("dialog", (d) => { dialogs.push(d.message()); void d.accept(); });
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await expect(tab(page, /^Giriş katı/)).toContainText("*");
  await tab(page, /^Giriş katı/).click({ button: "right" });
  await page.getByRole("menuitem", { name: "Yeniden adlandır" }).click();
  const dlg = page.getByRole("dialog", { name: "Yeniden adlandır" });
  await dlg.getByLabel("Şablon adı").fill("Zemin kat");
  await dlg.getByRole("button", { name: "Tamam" }).click();
  await expect.poll(() => held).toBe(1);                                             // adın PUT'u bekliyor
  await page.keyboard.press("Escape");                                               // pencere kapanır, istek sürer
  await expect(dlg).toHaveCount(0);
  const save = page.getByRole("button", { name: "Kaydet", exact: true });
  await expect(save).toBeDisabled();
  await expect(page.getByRole("button", { name: "Yeni şablon", exact: true })).toBeDisabled();   // "+"
  const ed = await openEditor(page);
  for (const name of ["Kaydet", "Farklı kaydet…", "Yeni şablon"]) await expect(ed.getByRole("button", { name, exact: true })).toBeDisabled();
  await expect(ed.getByRole("combobox", { name: "NVR'dan şablon" })).toBeDisabled();
  await page.keyboard.press("Escape");
  await tab(page, /^Giriş katı/).click({ button: "right" });
  const tabMenu = page.getByRole("menu", { name: "Şablon işlemleri" });
  for (const name of ["Yeniden adlandır", "Kopyala", "Sil"]) await expect(tabMenu.getByRole("menuitem", { name })).toBeDisabled();
  await page.keyboard.press("Escape");                                               // bütün öğeleri pasif menü de Esc ile kapanır
  await expect(tabMenu).toHaveCount(0);
  release();
  await expect(tab(page, /^Zemin kat/)).toBeVisible();
  await expect(save).toBeEnabled();
  await save.click();
  await expect.poll(() => puts(calls).length).toBe(2);
  expect(puts(calls)[0].body).toEqual({ name: "Zemin kat", layout: "4", tiles: VIEW.tiles });       // ad: sunucudaki hâlle
  expect(puts(calls)[1].body).toEqual({ name: "Zemin kat", layout: "4", tiles: ENTRY.tiles });      // Kaydet: yeni ad ve düzenleme
  await expect(tab(page, "Zemin kat")).not.toContainText("*");
  expect(dialogs).toEqual([]);                                                       // kendi ad değişikliğimiz için soru yok
  expect(store[0]).toMatchObject({ name: "Zemin kat", layout: "4", tiles: ENTRY.tiles });
});

test("geri yükleme: hiç kayıtlı şablon yokken 'Değişiklikleri at' sonrası odak '+' (Yeni şablon) düğmesine geçer", async ({ page }) => {
  await mock(page, STATUS, []);
  await mockStore(page, []);
  await login(page);
  await expect(page.locator("p", { hasText: "Henüz şablon yok" })).toBeVisible();
  page.on("dialog", (d) => void d.accept());
  await page.getByRole("button", { name: "Yeni şablon", exact: true }).click();
  await camera(page, "Kapı").click();
  await expect.poll(() => stored(page)).toMatchObject({ name: "Yeni şablon" });
  await page.reload();
  await expect(page.getByRole("status").filter({ hasText: RESTORED })).toBeVisible();
  await page.getByRole("button", { name: "Değişiklikleri at" }).click();
  await expect(page.locator("p", { hasText: "Henüz şablon yok" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Yeni şablon", exact: true })).toBeFocused();
  await expect.poll(() => stored(page)).toBeNull();
});

/** Kaydedilmemiş yeni şablonu (hiç kayıtlı şablon yokken) saklayıp sayfayı yeniler: geri yükleme bildirimi çıkar */
async function restoreNewTab(page: Page) {
  await login(page);
  await expect(page.locator("p", { hasText: "Henüz şablon yok" })).toBeVisible();
  page.on("dialog", (d) => void d.accept());
  await page.getByRole("button", { name: "Yeni şablon", exact: true }).click();
  await camera(page, "Kapı").click();
  await expect.poll(() => stored(page)).toMatchObject({ name: "Yeni şablon" });
  await page.reload();
  await expect(page.getByRole("status").filter({ hasText: RESTORED })).toBeVisible();
}

test("geri yükleme: kayıt sürerken ('+' pasif) 'Değişiklikleri at' sonrası odak Şablon editörü düğmesine geçer, sayfaya düşmez", async ({ page }) => {
  await mock(page, STATUS, []);
  const { calls } = await mockStore(page, []);
  await restoreNewTab(page);
  let release!: () => void;
  const gate = new Promise<void>((res) => { release = res; });
  await page.route("**/api/live/views", async (r) => { if (r.request().method() === "POST") await gate; await r.fallback(); });
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();          // yeni şablonun POST'u bekler
  await expect(page.getByRole("button", { name: "Yeni şablon", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Değişiklikleri at" }).click();
  const editorButton = page.getByRole("button", { name: "Şablon editörü" });
  await expect(editorButton).toBeFocused();
  release();
  await expect(page.getByRole("button", { name: "Yeni şablon", exact: true })).toBeEnabled();
  await expect(editorButton).toBeFocused();
  expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
});

test("geri yükleme: '+' ve Şablon editörü pasifken (düzen kataloğu boş) 'Değişiklikleri at' sonrası odak sekme listesine geçer", async ({ page }) => {
  await mock(page, STATUS, []);
  await mockStore(page, []);
  await login(page);
  await expect(page.locator("p", { hasText: "Henüz şablon yok" })).toBeVisible();
  // N×M düzeni katalogsuz da tanınır; katalog boşken "+" ve Şablon editörü pasif
  await page.route("**/api/live/view-layouts", (r) => r.fulfill({ json: [] }));
  await page.evaluate((e) => sessionStorage.setItem("bv.watch.unsaved", JSON.stringify(e)),
    { v: 1, origin: "yeni-1", name: "Yeni şablon", layout: "2x2", tiles: [{ sourceId: "a", channelId: null }, null, null, null], updatedAt: null });
  await page.reload();
  await expect(page.getByRole("status").filter({ hasText: RESTORED })).toBeVisible();
  await expect(page.getByRole("button", { name: "Yeni şablon", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Şablon editörü" })).toBeDisabled();
  await page.getByRole("button", { name: "Değişiklikleri at" }).click();
  await expect(page.getByRole("tablist", { name: "Şablonlar" })).toBeFocused();
  await expect.poll(() => stored(page)).toBeNull();
});

test("geri yükleme: hatırlanan sekme başka olsa ve düzenleme onun kayıtlı hâline eşit olsa da düzenleme kendi sekmesinde açılır; değişmemiş şablonda Kaydet sormaz", async ({ page }) => {
  await mock(page, STATUS, [VIEW, V2]);
  const { calls } = await mockStore(page, [{ ...VIEW }, { ...V2 }]);
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  // A'nın (Giriş katı) düzenlemesi B'nin (Depo katı) kayıtlı hâliyle aynı; hatırlanan sekme B
  const entry = { ...ENTRY, layout: V2.layout, tiles: V2.tiles };
  await page.evaluate((e) => {
    localStorage.setItem("bv.watch.last", "v2");
    sessionStorage.setItem("bv.watch.unsaved", JSON.stringify(e));
  }, entry);
  await page.reload();
  await expect(page.getByRole("status").filter({ hasText: RESTORED })).toBeVisible();
  await expect(tab(page, /^Giriş katı/)).toHaveAttribute("aria-selected", "true");
  await expect(tab(page, /^Giriş katı/)).toContainText("*");
  await expect(page.getByTestId("watch-tile")).toHaveCount(1);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Depo");
  await expect.poll(() => stored(page)).toMatchObject({ origin: "v1", layout: "1", updatedAt: 1 });
  const dialogs: string[] = [];
  page.on("dialog", (d) => { dialogs.push(d.message()); void d.dismiss(); });
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect.poll(() => puts(calls).length).toBe(1);
  expect(dialogs).toEqual([]);
  expect(puts(calls)[0].body).toEqual({ name: "Giriş katı", layout: "1", tiles: V2.tiles });
});

test("liste yenilenince açık sekme değişmez: hatırlanan sekme (başka tarayıcı sekmesinden) başka olsa da kaydedilmemiş düzenleme kalır; temizken de", async ({ page }) => {
  const V4 = { ...V3, id: "v4", name: "Otopark" };
  await mock(page, STATUS, [VIEW, V2, V3, V4]);
  const { store } = await mockStore(page, [{ ...VIEW }, { ...V2 }, { ...V3 }, { ...V4 }]);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  page.on("dialog", (d) => void d.accept());
  /** Başka bir tarayıcı sekmesi Depo katı'nı seçti (hatırlanan sekme tarayıcıda ortak) */
  const otherBrowserTab = () => page.evaluate(() => localStorage.setItem("bv.watch.last", "v2"));
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await expect.poll(() => stored(page)).not.toBeNull();
  await otherBrowserTab();
  await reloadByDelete(page, store, "Bahçe", "v2", "Depo katı (2)");
  await expect(tab(page, /^Giriş katı/)).toHaveAttribute("aria-selected", "true");
  await expect(tab(page, /^Giriş katı/)).toContainText("*");
  await expect(tiles.nth(3)).toContainText("Depo");
  expect(await stored(page)).toMatchObject({ origin: "v1" });
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect(tab(page, "Giriş katı")).not.toContainText("*");
  await otherBrowserTab();
  await reloadByDelete(page, store, "Otopark", "v2", "Depo katı (3)");
  await expect(tab(page, "Giriş katı")).toHaveAttribute("aria-selected", "true");
});

test("kamera listesi: kaynaklar alınamazsa 'Yeniden dene'; kanallar yükleniyor, boş cihaz; kapat-aç ikinci istek göndermez", async ({ page }) => {
  await mock(page, STATUS);
  let failSources = true;
  await page.route("**/api/live/sources", (r) => (failSources
    ? r.fulfill({ status: 502, json: { detail: "Analiz sunucusuna ulaşılamıyor." } })
    : r.fulfill({ json: [
      { id: "bos", kind: "recorder", name: "Boş NVR", recorderBrand: "hikvision", hasPassword: true },
      { id: "yavas", kind: "recorder", name: "Yavaş NVR", recorderBrand: "hikvision", hasPassword: true }] })));
  await page.route("**/api/live/sources/bos/channels", (r) => r.fulfill({ json: [] }));
  let release!: () => void;
  const gate = new Promise<void>((res) => { release = res; });
  let slowCalls = 0;
  await page.route("**/api/live/sources/yavas/channels", async (r) => {
    slowCalls += 1;
    await gate;
    await r.fulfill({ json: [{ id: "7", name: "Rampa", number: 7, title: "Rampa", hasSubstream: true }] });
  });
  await login(page);
  const list = cameras(page);
  await expect(list.getByRole("alert")).toContainText("Analiz sunucusuna ulaşılamıyor.");
  await expect(list.getByText("Henüz kaynak yok")).toHaveCount(0);               // alınamadı, "kaynak yok" denmez
  failSources = false;
  await list.getByRole("button", { name: "Yeniden dene" }).click();
  await expect(list.getByText("Bu kayıt cihazında kamera yok.")).toBeVisible();
  await expect(list.getByText("Kanallar yükleniyor…")).toBeVisible();
  await list.getByRole("button", { name: "Yavaş NVR" }).click();                  // kapat
  await expect(list.getByRole("button", { name: "Yavaş NVR" })).toHaveAttribute("aria-expanded", "false");
  await list.getByRole("button", { name: "Yavaş NVR" }).click();                  // istek sürerken yeniden aç
  await expect(list.getByText("Kanallar yükleniyor…")).toBeVisible();
  release();
  await expect(camera(page, "Rampa")).toBeVisible();
  expect(slowCalls).toBe(1);                                                      // ikinci istek gitmedi
});

test.describe("dar ekran (390 px)", () => {
  test.use({ viewport: { width: 390, height: 800 } });

  test("sekmeler yatay kaydırılır, sayfa taşmaz", async ({ page }) => {
    const many = Array.from({ length: 12 }, (_, i) => ({ ...VIEW, id: i ? `w${i}` : "v1", name: `Uzun adlı şablon ${i + 1}` }));
    await mock(page, STATUS, many);
    await login(page);
    await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
    const bar = page.getByTestId("watch-tabs");
    const { scroll, client } = await bar.evaluate((el) => ({ scroll: el.scrollWidth, client: el.clientWidth }));
    expect(scroll).toBeGreaterThan(client);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await expect(tab(page, "Uzun adlı şablon 1")).toBeInViewport();
    await bar.evaluate((el) => { el.scrollLeft = el.scrollWidth; });                // çubuk kendi içinde kayar
    await expect(tab(page, "Uzun adlı şablon 12")).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  });
});

// ---- Son düzeltme turu: odak, oturum düşünce giriş, sayfadan çıkarken Kaydet, istek zaman aşımı, ad penceresi

const editorButton = (page: Page) => page.getByRole("button", { name: "Şablon editörü" });
/** "+" (yeni şablon) düğmesinin DOM kimliği (TemplateTabs ADD_ID) */
const ADD_TAB_ID = "bv-tab-add";

test("odak: Şablon editörü menüsündeki işlemden sonra 'Şablon editörü' düğmesinde (Kaydet, Yeni şablon, NVR'dan şablon); Farklı kaydet penceresi kapanınca da", async ({ page }) => {
  await mock(page, STATUS);
  const { calls, store } = await mockStore(page, [VIEW]);
  await page.route("**/api/live/views/from-recorder", (r) => {
    const v = { id: "r1", name: "Ofis NVR", layout: "4", tiles: [{ sourceId: "b", channelId: "1" }, { sourceId: "b", channelId: "2" }, null, null],
      createdAt: 6, updatedAt: 6, truncated: false, channelCount: 2 };
    store.push(v);
    return r.fulfill({ json: v });
  });
  page.on("dialog", (d) => void d.accept());
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  await camera(page, "Depo").dragTo(tiles.nth(3));
  // Kaydet
  let ed = await openEditor(page);
  await ed.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect.poll(() => puts(calls).length).toBe(1);
  await expect(ed).toBeHidden();
  await expect(editorButton(page)).toBeFocused();
  // Farklı kaydet: pencere Esc ile kapanınca odak düğmeye döner; kaydedince de
  ed = await openEditor(page);
  await ed.getByRole("button", { name: "Farklı kaydet…" }).click();
  const name = page.getByRole("dialog", { name: "Farklı kaydet" });
  await expect(name).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(name).toBeHidden();
  await expect(editorButton(page)).toBeFocused();
  ed = await openEditor(page);
  await ed.getByRole("button", { name: "Farklı kaydet…" }).click();
  await name.getByRole("button", { name: "Tamam" }).click();
  await expect(name).toBeHidden();
  await expect(tab(page, "Giriş katı (kopya)")).toHaveAttribute("aria-selected", "true");
  await expect(editorButton(page)).toBeFocused();
  // Yeni şablon
  ed = await openEditor(page);
  await ed.getByRole("button", { name: "Yeni şablon" }).click();
  await expect(tab(page, /^Yeni şablon/)).toHaveAttribute("aria-selected", "true");
  await expect(editorButton(page)).toBeFocused();
  // NVR'dan şablon (kaydedilmemiş yeni şablonu atmayı onaylar)
  ed = await openEditor(page);
  await ed.getByRole("combobox", { name: "NVR'dan şablon" }).selectOption("b");
  await expect(tab(page, "Ofis NVR")).toHaveAttribute("aria-selected", "true");
  await expect(editorButton(page)).toBeFocused();
});

test("odak: menüdeki Geri al son adımda pasifleşince odak menüde kalır (sayfaya düşmez); Esc düğmeye döndürür", async ({ page }) => {
  await mock(page, STATUS);
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  const ed = await openEditor(page);
  await preset(ed, "3×3").click();
  await expect(page.getByTestId("watch-tile")).toHaveCount(9);
  const undoBtn = ed.getByRole("button", { name: /^Geri al/ });
  await undoBtn.focus();
  await page.keyboard.press("Enter");                                                // tek adım: Geri al pasifleşir
  await expect(page.getByTestId("watch-tile")).toHaveCount(4);
  await expect(undoBtn).toBeDisabled();
  await expect(ed).toBeFocused();                                                    // menünün kendisi
  expect(await page.evaluate(() => document.activeElement === document.body)).toBe(false);
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => !!document.activeElement?.closest("[role=dialog][aria-label='Şablon editörü']"))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(ed).toBeHidden();
  await expect(editorButton(page)).toBeFocused();
});

test("odak: sekme menüsünden Sil sonrası odak seçili sekmede (başka sekme silindi de, seçili sekme silindi de)", async ({ page }) => {
  await mock(page, STATUS, [VIEW, V2, V3]);
  await mockStore(page, [{ ...VIEW }, { ...V2 }, { ...V3 }]);
  await page.route("**/api/live/views/v2/status", (r) => r.fulfill({ json: { id: "v2", layout: "1", tiles: [] } }));
  page.on("dialog", (d) => void d.accept());
  await login(page);
  await expect(tab(page, "Giriş katı")).toHaveAttribute("aria-selected", "true");
  // seçili olmayan sekmeyi sil: odak seçili sekmeye
  await tab(page, "Bahçe").click({ button: "right" });
  await page.getByRole("menuitem", { name: "Sil" }).click();
  await expect(tab(page, "Bahçe")).toHaveCount(0);
  await expect(tab(page, "Giriş katı")).toBeFocused();
  // seçili sekmeyi sil: odak yeni seçili sekmeye
  await tab(page, "Giriş katı").click({ button: "right" });
  await page.getByRole("menuitem", { name: "Sil" }).click();
  await expect(tab(page, "Giriş katı")).toHaveCount(0);
  await expect(tab(page, "Depo katı")).toHaveAttribute("aria-selected", "true");
  await expect(tab(page, "Depo katı")).toBeFocused();
});

for (const where of ["ızgaranın üstündeki uyarı", "alarm şeridi"] as const) {
  test(`oturum düşünce '${where}' içindeki 'Giriş yap' sormaz ve düzenlemeyi atmaz: girişten sonra Canlı izlemede geri yüklenir`, async ({ page }) => {
    await mock(page, STATUS);
    await mockStore(page, [VIEW]);
    await login(page);
    const tiles = page.getByTestId("watch-tile");
    await expect(tiles.nth(0)).toContainText("Kapı");
    await camera(page, "Depo").dragTo(tiles.nth(3));
    await expect.poll(() => stored(page)).not.toBeNull();
    const dialogs: string[] = [];
    page.on("dialog", (d) => { dialogs.push(`${d.type()}: ${d.message()}`); void d.accept(); });
    // oturum düştü: yoklamalar 401
    await page.context().clearCookies();
    const expired = (r: Route) => r.fulfill({ status: 401, json: { error: "Giriş gerekli." } });
    await page.route("**/api/live/views/*/status", expired);
    await page.route("**/api/live/alarms?active=1", expired);
    const box = where === "alarm şeridi" ? page.getByTestId("alarm-feed-warning") : page.getByRole("status").filter({ hasText: AUTH });
    const link = box.getByRole("link", { name: "Giriş yap" });
    await expect(link).toBeVisible({ timeout: 20_000 });
    await link.click();
    await expect(page).toHaveURL(/\/login\?next=%2Fwatch/);
    expect(dialogs).toEqual([]);                                                       // ne soru ne tarayıcının kapanma sorusu
    expect(await stored(page)).toMatchObject({ origin: "v1", tiles: ENTRY.tiles });    // düzenleme saklı
    await page.unroute("**/api/live/views/*/status", expired);
    await page.unroute("**/api/live/alarms?active=1", expired);
    await page.getByLabel("Şifre").fill("e2e-test-sifresi");
    await page.getByRole("button", { name: "Giriş yap" }).click();
    await expect(page).toHaveURL(/\/watch$/);
    await expect(page.getByRole("status").filter({ hasText: RESTORED })).toBeVisible();
    await expect(tab(page, /^Giriş katı/)).toContainText("*");
    await expect(tiles.nth(3)).toContainText("Depo");
    expect(dialogs).toEqual([]);
  });
}

test("Kaydet: denetim isteği sürerken uygulama içinde Geri ile sayfadan çıkılırsa ne sorulur ne yazılır; dönünce düzenleme geri yüklenir", async ({ page }) => {
  await mock(page, STATUS);
  const { calls, store } = await mockStore(page, [{ ...VIEW }]);
  const list = await holdListGet(page);
  await login(page);
  await viaAlarms(page);
  const tiles = page.getByTestId("watch-tile");
  const dialogs: string[] = [];
  page.on("dialog", (d) => { dialogs.push(d.message()); void d.accept(); });
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await expect.poll(() => stored(page)).not.toBeNull();
  Object.assign(store[0], { updatedAt: 9 });                                         // başka yerde değişti: Kaydet sorardı
  list.arm();
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect.poll(() => list.held()).toBe(1);                                     // denetim isteği bekliyor
  await page.goBack();                                                               // uygulama içi Geri: Canlı izleme sökülür
  await expect(page).toHaveURL(/\/alarms$/);
  list.release();
  await page.waitForTimeout(500);
  expect(dialogs).toEqual([]);                                                       // başka sayfada "Üzerine yazılsın mı?" yok
  expect(puts(calls)).toHaveLength(0);
  await page.goForward();
  await expect(page.getByRole("status").filter({ hasText: RESTORED })).toBeVisible();
  await expect(tiles.nth(3)).toContainText("Depo");
  expect(puts(calls)).toHaveLength(0);
});

test("şablon isteği 15 sn'de bitmezse kesilir: işlemler serbest kalır, liste yeniden alınır, ileti çıkar, düzenleme kalır", async ({ page }) => {
  await page.clock.install();
  await mock(page, STATUS);
  const { store } = await mockStore(page, [{ ...VIEW }]);
  let gets = 0;
  await page.route("**/api/live/views", (r) => { if (r.request().method() === "GET") gets += 1; return r.fallback(); });
  const held: Route[] = [];
  await page.route("**/api/live/views/v1", (r) => { if (r.request().method() !== "PUT") return r.fallback(); held.push(r); });
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await expect(tab(page, /^Giriş katı/)).toContainText("*");
  const save = page.getByRole("button", { name: "Kaydet", exact: true });
  await save.click();
  await expect.poll(() => held.length).toBe(1);                                     // yazma isteği takıldı
  await expect(save).toBeDisabled();
  const before = gets;
  await page.clock.runFor(15_500);
  await expect(page.getByRole("alert").filter({ hasText: "İstek zaman aşımına uğradı; şablonlar yeniden yüklendi." })).toBeVisible();
  expect(gets).toBeGreaterThan(before);                                             // liste yeniden alındı
  await expect(save).toBeEnabled();                                                 // şablon işlemleri serbest
  await expect(page.locator(`#${ADD_TAB_ID}`)).toBeEnabled();
  await expect(tab(page, /^Giriş katı/)).toContainText("*");                        // düzenleme kaybolmadı
  await expect(tiles.nth(3)).toContainText("Depo");
  expect(store[0]).toMatchObject({ updatedAt: 1 });
  await held[0].fulfill({ status: 500, json: { detail: "geç" } }).catch(() => undefined);
});

test("ad penceresi: Yeniden adlandır isteği sürerken Esc ile kapatılır ve istek sonra başarısız olursa hata sayfada yazar", async ({ page }) => {
  await mock(page, STATUS);
  await mockStore(page, [{ ...VIEW }]);
  let release!: () => void;
  const gate = new Promise<void>((res) => { release = res; });
  let putCount = 0;
  await page.route("**/api/live/views/v1", async (r) => {
    if (r.request().method() !== "PUT") return r.fallback();
    putCount += 1;
    await gate;
    return r.fulfill({ status: 503, json: { detail: "Şablonlar kaydedilemedi (disk ya da dosya kilidi)." } });
  });
  await login(page);
  await expect(page.getByTestId("watch-tile").nth(0)).toContainText("Kapı");
  await tab(page, "Giriş katı").click({ button: "right" });
  await page.getByRole("menuitem", { name: "Yeniden adlandır" }).click();
  const dlg = page.getByRole("dialog", { name: "Yeniden adlandır" });
  await dlg.getByLabel("Şablon adı").fill("Zemin kat");
  await dlg.getByRole("button", { name: "Tamam" }).click();
  await expect.poll(() => putCount).toBe(1);
  await page.keyboard.press("Escape");                                               // istek sürerken pencere kapandı
  await expect(dlg).toBeHidden();
  release();
  await expect(page.getByRole("alert").filter({ hasText: "Şablonlar kaydedilemedi (disk ya da dosya kilidi)." })).toBeVisible();
  await expect(tab(page, "Giriş katı")).toBeVisible();                               // ad değişmedi
});

test("odak: araç çubuğundaki Kaydet ya da Geri al basılınca pasifleşirse odak 'Şablon editörü' düğmesine geçer (sayfaya düşmez)", async ({ page }) => {
  await mock(page, STATUS);
  const { calls } = await mockStore(page, [VIEW]);
  await login(page);
  const tiles = page.getByTestId("watch-tile");
  await expect(tiles.nth(0)).toContainText("Kapı");
  const toolbarSave = page.getByRole("button", { name: "Kaydet", exact: true });
  const toolbarUndo = page.getByRole("button", { name: "Geri al", exact: true });
  await camera(page, "Depo").dragTo(tiles.nth(3));
  await toolbarSave.focus();
  await page.keyboard.press("Enter");
  await expect.poll(() => puts(calls).length).toBe(1);
  await expect(toolbarSave).toBeDisabled();
  await expect(editorButton(page)).toBeFocused();
  // Geri al: tek adım geri alınınca pasifleşir (kaydedilmiş hâl), odak yine düğmeye
  await tiles.nth(0).click({ button: "right" });
  await page.getByRole("menuitem", { name: "Boşalt" }).click();
  await expect(toolbarUndo).toBeEnabled();
  await toolbarUndo.focus();
  await page.keyboard.press("Enter");                                               // Boşalt geri alındı
  await expect(tiles.nth(0)).toContainText("Kapı");
  await expect(toolbarUndo).toBeEnabled();                                          // kaydetmeden önceki adım da var
  await expect(toolbarUndo).toBeFocused();
  await page.keyboard.press("Enter");                                               // sürükleme geri alındı: ilk hâl
  await expect(tiles.nth(3)).toHaveAttribute("data-empty", "true");
  await expect(toolbarUndo).toBeDisabled();
  await expect(editorButton(page)).toBeFocused();
});

// ---- Son kalan düzeltmeler: eski odak izi, "NVR'dan şablon" süresi, oturum düşünce taslak yazımı

/** `hidden`: sayfa sonuna kaydırınca araç çubuğu görünümden çıkar (900×400); 1280×420'de sayfa az kayar, araç çubuğu görünür kalır */
for (const vp of [{ width: 1280, height: 420, hidden: false }, { width: 900, height: 400, hidden: true }]) {
  test(`odak: araç çubuğunda Kaydet'e odaklanıp boş yere tıklandıktan sonra Ctrl+Z ile Kaydet pasifleşirse odak sayfada kalır ve sayfa kaymaz (${vp.width}×${vp.height})`, async ({ page }) => {
    await page.setViewportSize(vp);
    await mock(page, STATUS);
    await mockStore(page, [VIEW]);
    await login(page);
    const tiles = page.getByTestId("watch-tile");
    await expect(tiles.nth(0)).toContainText("Kapı");
    const toolbarSave = page.getByRole("button", { name: "Kaydet", exact: true });
    await tiles.nth(0).click({ button: "right" });
    await page.getByRole("menuitem", { name: "Boşalt" }).click();                      // kaydedilmemiş düzenleme: Kaydet açık
    await expect(toolbarSave).toBeEnabled();
    await toolbarSave.focus();                                                         // araç çubuğunda son odaklanan düğme
    await expect(toolbarSave).toBeFocused();
    await page.getByRole("heading", { name: "Canlı izleme" }).click();                 // odaklanamayan yere tıklanır: odak sayfaya düşer
    expect(await page.evaluate(() => document.activeElement === document.body)).toBe(true);
    const scrolled = await page.evaluate(() => { window.scrollTo(0, document.documentElement.scrollHeight); return window.scrollY; });
    expect(scrolled).toBeGreaterThan(0);
    const above = await editorButton(page).evaluate((el) => el.getBoundingClientRect().bottom < 0);
    expect(above).toBe(vp.hidden);                                                     // araç çubuğu görünümün üstünde mi (odak ona geçse sayfa kayardı)
    await page.keyboard.press("Control+z");                                            // son adım geri alındı: kayıtlı hâl, Kaydet pasif
    await expect(toolbarSave).toBeDisabled();
    expect(await page.evaluate(() => document.activeElement === document.body)).toBe(true);   // odak "Şablon editörü" düğmesine atlamadı
    expect(await page.evaluate(() => window.scrollY)).toBe(scrolled);                  // sayfa kaymadı
  });
}

