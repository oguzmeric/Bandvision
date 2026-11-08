import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * Kayıttan izleme sayfası (`/archive`), SAHTE API ile (page.route): kamera listesi (yalnız kayıt cihazları), takvim,
 * çizelge, oynatıcı durumları (`connecting → playing → paused → ended → error`), kumandalar, sınır ve hata iletileri,
 * klavye, derin bağlantı, sayfadan çıkışta DELETE ve dışa aktarma. Gerçek yığın (dosya kaynağı) Task 6'nın testinde.
 * Saat dilimi İstanbul, "bugün" 7 Kasım 2026 12:00 (yerel): gün başları sabit.
 */
test.use({ timezoneId: "Europe/Istanbul" });

// 1×1 siyah JPEG (MJPEG akışı yerine)
const JPEG = Buffer.from("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==", "base64");

const NOW = new Date("2026-11-07T12:00:00+03:00");
/** Yerel gün başı (İstanbul UTC+3) */
const day = (d: number, m = 11) => Date.UTC(2026, m - 1, d - 1, 21) / 1000;
const DAY7 = day(7);
const DAY3 = day(3);
const H = 3600;

const SOURCES = [
  { id: "a", kind: "camera", name: "Kapı", brand: "custom", hasPassword: false },
  { id: "b", kind: "recorder", name: "Ofis NVR", recorderBrand: "trassir", hasPassword: true },
  { id: "e", kind: "recorder", name: "Depo NVR", recorderBrand: "hikvision", hasPassword: true },
];
const CHANNELS: Record<string, object[]> = {
  b: [{ id: "1", name: "Giriş", number: 1, title: "Giriş", hasSubstream: true },
      { id: "2", name: "Kasa", number: 2, title: "Kasa", hasSubstream: true }],
  e: [{ id: "7", name: "Rampa", number: 7, title: "Rampa", hasSubstream: true }],
};

/** Markaya göre hızlar (sunucuyla aynı): TRASSIR cihazda 1–16×, Hikvision/Dahua gerçek zamanlı RTSP'de yalnız 1× */
const SPEEDS: Record<string, number[]> = { b: [1, 2, 4, 8, 16], e: [1] };

type State = "connecting" | "playing" | "paused" | "ended" | "error";
interface View {
  id: string; sourceId: string; channelId: string | null; name: string; state: State; message: string; at: number;
  speed: number; speeds: number[]; fps: number; canExport: boolean;
}
type Call = { method: string; path: string; query: URLSearchParams; body: Record<string, unknown> | null };

/** Sahte arşiv uçları: istekleri kaydeder; oynatıcının durumu `fake.view` değiştirilerek sürülür */
async function mockArchive(page: Page) {
  const calls: Call[] = [];
  const fake = {
    view: null as View | null,
    n: 0,
    canExport: true,
    /** POST players reddi (ör. 429) */
    createError: null as { status: number; detail: string } | null,
    /** Oynatıcı sunucudan kayboldu (yeniden başladı): GET/actions 404 */
    gone: false,
    /** Durum yoklaması bu kodla düşer (ör. 502: analiz sunucusu yok); null: normal */
    pollError: null as number | null,
    /** POST players yanıtı bu söz bitene kadar bekler (açılış uçuşta) */
    createHold: null as Promise<void> | null,
    /** Yalnız kumanda 404 (yoklamadan önce işlem kaybolan oynatıcıya çarpar) */
    actionMissing: false,
    /** MJPEG akış istekleri; `streamError` verilirse akış bu kodla düşer (`<img>` hata verir) */
    streams: 0,
    streamError: null as number | null,
    /** Dışa aktarma yanıtı: hata ya da (null) dosya; `hold` verilirse yanıt o söz bitene kadar bekler */
    exportError: null as { status: number; detail: string } | null,
    hold: null as Promise<void> | null,
  };
  const log = (r: Route) => {
    const req = r.request();
    const url = new URL(req.url());
    const call = { method: req.method(), path: url.pathname.replace("/api/live/", ""), query: url.searchParams,
                   body: req.method() === "POST" ? (req.postDataJSON() as Record<string, unknown>) : null };
    calls.push(call);
    return call;
  };
  await page.route("**/api/live/alarms?active=1", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/live/sessions", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/live/sources", (r) => r.fulfill({ json: SOURCES }));
  await page.route("**/api/live/sources/*/channels", (r) => {
    const id = new URL(r.request().url()).pathname.split("/").at(-2)!;
    return r.fulfill({ json: CHANNELS[id] ?? [] });
  });
  await page.route("**/api/live/archive/calendar**", (r) => {
    log(r);
    return r.fulfill({ json: { days: [3, 7] } });
  });
  await page.route("**/api/live/archive/timeline**", (r) => {
    const d = Number(log(r).query.get("day"));
    return r.fulfill({ json: { ranges: [[d + H, d + 2 * H], [d + 10 * H, d + 11 * H]] } });
  });
  await page.route("**/api/live/archive/players", async (r) => {
    const c = log(r);
    if (fake.createHold) await fake.createHold;
    if (fake.createError) return r.fulfill({ status: fake.createError.status, json: { detail: fake.createError.detail } });
    const b = c.body as { sourceId: string; channelId: string; at: number; speed: number };
    fake.gone = false;
    fake.actionMissing = false;
    fake.view = { id: `p${++fake.n}`, sourceId: b.sourceId, channelId: b.channelId, name: "Ofis NVR · Kasa", state: "connecting",
                  message: "", at: b.at, speed: b.speed, speeds: SPEEDS[b.sourceId] ?? [1], fps: 25,
                  canExport: fake.canExport };
    return r.fulfill({ status: 201, json: fake.view });
  });
  const missing = (r: Route) => r.fulfill({ status: 404, json: { detail: "Kayıt oynatıcısı bulunamadı." } });
  await page.route("**/api/live/archive/players/*", (r) => {
    const c = log(r);
    const id = c.path.split("/").at(-1)!;
    if (fake.gone || fake.view?.id !== id) return missing(r);
    if (c.method === "DELETE") { fake.view = null; return r.fulfill({ status: 204 }); }
    if (fake.pollError) return r.fulfill({ status: fake.pollError, json: { detail: "Analiz sunucusuna ulaşılamadı." } });
    return r.fulfill({ json: fake.view });
  });
  await page.route("**/api/live/archive/players/*/actions", (r) => {
    const c = log(r);
    const id = c.path.split("/").at(-2)!;
    const v = fake.view;
    if (fake.gone || fake.actionMissing || !v || v.id !== id) return missing(r);
    const b = c.body as { action: string; at?: number; speed?: number };
    if (b.action === "pause" && (v.state === "playing" || v.state === "connecting")) v.state = "paused";
    if (b.action === "resume" && !(v.state === "playing" || v.state === "connecting")) v.state = "connecting";
    if (b.action === "seek") { v.state = "connecting"; v.at = b.at!; }
    if (b.action === "speed") { v.speed = b.speed!; if (v.state === "playing") v.state = "connecting"; }
    v.message = "";
    return r.fulfill({ json: v });
  });
  await page.route(/\/api\/live\/archive\/players\/[^/]+\/stream(\?|$)/, (r) => {   // `?k=` anahtarlı
    fake.streams += 1;
    if (fake.streamError) return r.fulfill({ status: fake.streamError, body: "" });
    return r.fulfill({ body: JPEG, contentType: "image/jpeg" });
  });
  await page.route("**/api/live/archive/export", async (r) => {
    log(r);
    if (fake.hold) await fake.hold;
    if (fake.exportError) return r.fulfill({ status: fake.exportError.status, json: { detail: fake.exportError.detail } });
    return r.fulfill({
      body: Buffer.from("sahte-mp4"), contentType: "video/mp4",
      headers: { "Content-Disposition": "attachment; filename=\"Ofis NVR - Kasa-20261107-0059.mp4\"; filename*=UTF-8''Ofis%20NVR%20%C2%B7%20Kasa-20261107-0059.mp4" },
    });
  });
  const of = (method: string, re: RegExp) => calls.filter((c) => c.method === method && re.test(c.path));
  return { calls, fake, of };
}

async function login(page: Page, path = "/archive") {
  await page.clock.setFixedTime(NOW);
  await page.goto(path);
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("heading", { name: "Kayıttan izleme", level: 1 })).toBeVisible();
}

const status = (page: Page) => page.getByTestId("player-status");
const camera = (page: Page, label: string) => page.getByRole("list", { name: "Kayıt cihazı kameraları" }).getByRole("button", { name: label });
const dayButton = (page: Page, label: RegExp) => page.getByRole("table").getByRole("button", { name: label });
const playButton = (page: Page) => page.getByRole("group", { name: "Oynatma kumandası" }).getByRole("button", { name: /^(Oynat|Duraklat|Sürdür)$/ });

/** Kasa kamerasını seçer; çizelge yüklenir */
async function pickKasa(page: Page) {
  await camera(page, "Ofis NVR · Kasa").click();
  await expect(page.getByTestId("timeline-range")).toHaveCount(2);
}

test("kayıttan izleme: menü girişi, sayfa kabuğu, yalnız kayıt cihazı kameraları, takvim ve çizelge", async ({ page }) => {
  const m = await mockArchive(page);
  const errors: string[] = [];
  page.on("console", (msg) => { if (msg.type() === "error") errors.push(msg.text()); });
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page);
  await expect(page).toHaveTitle("Kayıttan izleme · BandVision");
  const nav = page.getByRole("navigation", { name: "Ana menü" });
  await expect(nav.getByRole("link", { name: "Kayıttan izleme", exact: true })).toHaveAttribute("aria-current", "page");
  // durum satırı aria-live bölgesi baştan vardır
  await expect(status(page)).toHaveAttribute("aria-live", "polite");
  await expect(status(page)).toHaveText("Önce bir kamera seçin.");

  const list = page.getByRole("list", { name: "Kayıt cihazı kameraları" });
  await expect(list.getByRole("button")).toHaveText(["Ofis NVR · Giriş", "Ofis NVR · Kasa", "Depo NVR · Rampa"]);
  await expect(list.getByText("Kapı")).toHaveCount(0);              // IP kamera listelenmez
  await page.getByLabel("Kamera ara").fill("kasa");
  await expect(list.getByRole("button")).toHaveText(["Ofis NVR · Kasa"]);
  await page.getByLabel("Kamera ara").fill("");

  // takvim bugünün ayında açılır; bugün çerçeveli ve seçili
  await expect(page.getByTestId("calendar-month")).toHaveText("Kasım 2026");
  await expect(dayButton(page, /^7 Kasım 2026/)).toHaveAttribute("aria-current", "date");
  await expect(dayButton(page, /^7 Kasım 2026/)).toHaveAttribute("aria-pressed", "true");

  await pickKasa(page);
  await expect(camera(page, "Ofis NVR · Kasa")).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => { const c = m.of("GET", /^archive\/calendar$/).at(-1); return c && Object.fromEntries(c.query); })
    .toEqual({ source: "b", channel: "2", year: "2026", month: "11" });
  await expect(dayButton(page, /^3 Kasım 2026, kayıt var$/)).toHaveAttribute("data-recorded", "true");
  await expect(dayButton(page, /^5 Kasım 2026$/)).not.toHaveAttribute("data-recorded", /.*/);
  await expect.poll(() => { const c = m.of("GET", /^archive\/timeline$/).at(-1); return c && Object.fromEntries(c.query); })
    .toEqual({ source: "b", channel: "2", day: String(DAY7) });
  // imleç günün ilk kaydında (01:00); saat etiketleri
  await expect(page.getByTestId("player-clock")).toHaveText("01:00:00 07.11.2026");
  await expect(page.getByRole("slider", { name: "Zaman çizelgesi" })).toHaveAttribute("aria-valuetext", "01:00:00");
  await expect(status(page)).toHaveText("Oynatmak için çizelgede bir ana tıklayın ya da Oynat'a basın.");
  await expect(page.locator("[data-testid=timeline] + div span")).toHaveText(["0", "6", "12", "18", "24"]);

  // ay gezgini: ▶ Aralık, ◀ Kasım (takvim yeniden istenir)
  await page.getByRole("button", { name: "Sonraki ay" }).click();
  await expect(page.getByTestId("calendar-month")).toHaveText("Aralık 2026");
  await expect.poll(() => m.of("GET", /^archive\/calendar$/).at(-1)?.query.get("month")).toBe("12");
  await page.getByRole("button", { name: "Önceki ay" }).click();
  await expect(page.getByTestId("calendar-month")).toHaveText("Kasım 2026");

  // başka gün: çizelge o günün gün başıyla istenir
  await dayButton(page, /^3 Kasım 2026/).click();
  await expect.poll(() => m.of("GET", /^archive\/timeline$/).at(-1)?.query.get("day")).toBe(String(DAY3));
  await expect(page.getByTestId("player-clock")).toHaveText("01:00:00 03.11.2026");

  expect(errors.filter((e) => /hydrat|did not match|Minified React error/i.test(e))).toEqual([]);

  // telefon genişliği: yatay kaydırma yok
  await page.setViewportSize({ width: 375, height: 800 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
});

test("kayıttan izleme: oynatıcı durumları connecting → playing → paused → ended → error; Sonraki kayda git; akış yerinde kalır", async ({ page }) => {
  const m = await mockArchive(page);
  await login(page);
  await pickKasa(page);
  await expect(page.getByTestId("player-stream")).toHaveCount(0);
  await playButton(page).click();
  await expect.poll(() => m.of("POST", /^archive\/players$/).map((c) => c.body))
    .toEqual([{ sourceId: "b", channelId: "2", at: DAY7 + H, speed: 1 }]);
  await expect(status(page)).toHaveText("Bağlanıyor…");
  const img = page.getByTestId("player-stream");
  await expect(img).toHaveAttribute("src", /^\/api\/live\/archive\/players\/p1\/stream\?k=\d+$/);
  await img.evaluate((el) => el.setAttribute("data-mark", "1"));       // aynı öğe mi (yeniden açılmadı mı)

  m.fake.view!.state = "playing";
  m.fake.view!.at = DAY7 + H + 75;
  await expect(status(page)).toHaveText("Oynatılıyor");
  await expect(page.getByTestId("player-clock")).toHaveText("01:01:15 07.11.2026");
  await expect(playButton(page)).toHaveText("Duraklat");

  await playButton(page).click();
  await expect(status(page)).toHaveText("Duraklatıldı");
  await expect.poll(() => m.of("POST", /actions$/).at(-1)?.body).toEqual({ action: "pause" });
  await expect(playButton(page)).toHaveText("Sürdür");

  // "Kayıt bitti": ana düğme "Sonraki kayda git" olur (Sürdür sonda açıp hemen yine bitirirdi)
  m.fake.view!.state = "ended";
  m.fake.view!.at = DAY7 + 11 * H;                                     // günün son kaydının sonu: sonraki kayıt yok
  await expect(status(page)).toHaveText("Kayıt bitti");
  await expect(playButton(page)).toHaveText("Sürdür");
  await expect(playButton(page)).toBeDisabled();
  await expect(playButton(page)).toHaveAttribute("title", "Bu günde sonraki kayıt yok.");
  const acts = m.of("POST", /actions$/).length;
  await page.getByTestId("timeline").focus();
  await page.keyboard.press(" ");                                       // Boşluk da sürdürmez
  await page.waitForTimeout(300);
  expect(m.of("POST", /actions$/).length).toBe(acts);
  m.fake.view!.at = DAY7 + 2 * H;
  await expect(page.getByRole("group", { name: "Oynatma kumandası" }).getByRole("button", { name: "Sonraki kayda git" })).toBeVisible();
  await expect(playButton(page)).toHaveCount(0);
  await page.keyboard.press(" ");                                       // Boşluk = Sonraki kayda git
  await expect.poll(() => m.of("POST", /actions$/).at(-1)?.body).toEqual({ action: "seek", at: DAY7 + 10 * H });
  m.fake.view!.state = "ended";
  m.fake.view!.at = DAY7 + 2 * H;
  await expect(status(page)).toHaveText("Kayıt bitti");
  await page.getByRole("button", { name: "Sonraki kayda git" }).click();
  await expect.poll(() => m.of("POST", /actions$/).at(-1)?.body).toEqual({ action: "seek", at: DAY7 + 10 * H });
  await expect(status(page)).toHaveText("Sarılıyor…");
  await expect(page.getByTestId("player-clock")).toHaveText("10:00:00 07.11.2026");
  await expect(img).toHaveAttribute("data-mark", "1");                 // duraklatma/sarma akışı yeniden açmaz

  m.fake.view!.state = "error";
  m.fake.view!.message = "Kayıt cihazından görüntü gelmedi.";
  await expect(status(page)).toHaveText("Kayıt cihazından görüntü gelmedi.");
  const src = await img.getAttribute("src");
  const streams = m.fake.streams;
  await playButton(page).click();                                       // Sürdür: hatadan sonra akış baştan açılır
  await expect.poll(() => m.of("POST", /actions$/).at(-1)?.body).toEqual({ action: "resume" });
  await expect(status(page)).toHaveText("Bağlanıyor…");
  await expect(img).not.toHaveAttribute("data-mark", "1");
  await expect(img).toHaveAttribute("src", /^\/api\/live\/archive\/players\/p1\/stream\?k=\d+$/);
  await expect(img).not.toHaveAttribute("src", src!);                  // yeni anahtar: tarayıcı bağlantıyı yeniden açar
  await expect.poll(() => m.fake.streams).toBeGreaterThan(streams);
  // yoklama saniyede bir
  const polls = m.of("GET", /^archive\/players\/p1$/).length;
  await expect.poll(() => m.of("GET", /^archive\/players\/p1$/).length, { timeout: 5000 }).toBeGreaterThan(polls + 1);
});

test("kayıttan izleme: çizelge tıklaması (açar, sonra seek), hız seçimi, klavye kısayolları ve '?' listesi", async ({ page }) => {
  const m = await mockArchive(page);
  await login(page);
  await pickKasa(page);
  const bar = page.getByRole("slider", { name: "Zaman çizelgesi" });
  const box = (await bar.boundingBox())!;
  // oynatıcı yokken tıklama o andan oynatıcı açar (12:00 civarı)
  await bar.click({ position: { x: box.width / 2, y: box.height / 2 } });
  await expect.poll(() => Math.abs(Number(m.of("POST", /^archive\/players$/).at(-1)?.body?.at) - (DAY7 + 12 * H))).toBeLessThan(300);
  m.fake.view!.state = "playing";
  await expect(status(page)).toHaveText("Oynatılıyor");
  // oynatıcı varken tıklama seek gönderir (06:00 civarı)
  await bar.click({ position: { x: box.width / 4, y: box.height / 2 } });
  await expect.poll(() => m.of("POST", /actions$/).at(-1)?.body?.action).toBe("seek");
  expect(Math.abs(Number(m.of("POST", /actions$/).at(-1)?.body?.at) - (DAY7 + 6 * H))).toBeLessThan(300);
  await expect(status(page)).toHaveText("Sarılıyor…");
  m.fake.view!.state = "playing";
  await expect(status(page)).toHaveText("Oynatılıyor");

  // hız
  const speed = page.getByLabel("Hız");
  await expect(speed.locator("option")).toHaveText(["1×", "2×", "4×", "8×", "16×"]);   // TRASSIR'da cihazda
  await speed.selectOption("2");
  await expect.poll(() => m.of("POST", /actions$/).at(-1)?.body).toEqual({ action: "speed", speed: 2 });
  await expect(status(page)).toHaveText("Sarılıyor…");
  m.fake.view!.state = "playing";
  await expect(status(page)).toHaveText("Oynatılıyor (2×)");
  // klavye çizelgede: → 10 sn, Shift+← 1 dk, Boşluk duraklat/sürdür
  const base = m.fake.view!.at;
  await bar.focus();
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => m.of("POST", /actions$/).at(-1)!.body).toEqual({ action: "seek", at: base + 10 });
  m.fake.view!.state = "playing";
  await page.keyboard.press("Shift+ArrowLeft");
  await expect.poll(() => m.of("POST", /actions$/).at(-1)!.body).toEqual({ action: "seek", at: base + 10 - 60 });
  m.fake.view!.state = "playing";
  await expect(status(page)).toHaveText("Oynatılıyor (2×)");
  await page.keyboard.press(" ");
  await expect.poll(() => m.of("POST", /actions$/).at(-1)!.body).toEqual({ action: "pause" });
  await expect(status(page)).toHaveText("Duraklatıldı");
  await page.keyboard.press(" ");
  await expect.poll(() => m.of("POST", /actions$/).at(-1)!.body).toEqual({ action: "resume" });

  // "?" kısayol listesi; arama kutusunda yazılan "?" listeyi açmaz
  await page.keyboard.press("?");
  const help = page.getByRole("dialog", { name: "Klavye kısayolları" });
  await expect(help).toBeVisible();
  await expect(help).toContainText("Shift + ← / →");
  await help.getByRole("button", { name: "Kapat" }).click();
  await expect(help).toHaveCount(0);
  const search = page.getByLabel("Kamera ara");
  await search.focus();
  await page.keyboard.press("?");
  await page.keyboard.press("ArrowRight");                             // yazı kutusunda ok tuşu da sarmaz
  await expect(search).toHaveValue("?");
  await expect(help).toHaveCount(0);
  const seeks = m.of("POST", /actions$/).length;
  await page.waitForTimeout(300);
  expect(m.of("POST", /actions$/).length).toBe(seeks);
  await search.fill("");
  await page.getByRole("button", { name: "Kısayollar" }).click();
  await expect(help).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(help).toHaveCount(0);
});

test("kayıttan izleme: 429 sınır iletisi; kaybolan oynatıcı (404) sonraki işlemde kısa notla yeniden açılır", async ({ page }) => {
  const m = await mockArchive(page);
  await login(page);
  await pickKasa(page);
  m.fake.createError = { status: 429, detail: "En çok 2 kayıt aynı anda izlenebilir." };
  await playButton(page).click();
  await expect(status(page)).toHaveText("En çok 2 kayıt aynı anda izlenebilir.");
  await expect(playButton(page)).toHaveText("Oynat");

  m.fake.createError = null;
  await playButton(page).click();
  await expect(status(page)).toHaveText("Bağlanıyor…");
  m.fake.view!.state = "playing";
  await expect(status(page)).toHaveText("Oynatılıyor");
  m.fake.view!.at = DAY7 + H + 300;
  await expect(page.getByTestId("player-clock")).toHaveText("01:05:00 07.11.2026");

  m.fake.gone = true;                                    // analiz sunucusu yeniden başladı
  await expect(status(page)).toContainText("Oynatıcı kapanmış");
  await expect(playButton(page)).toHaveText("Oynat");
  await page.getByRole("button", { name: "10 saniye ileri" }).click();   // oynatıcı yokken yalnız imleç
  await expect(page.getByTestId("player-clock")).toHaveText("01:05:10 07.11.2026");
  await playButton(page).click();
  await expect.poll(() => m.of("POST", /^archive\/players$/).at(-1)?.body).toEqual({ sourceId: "b", channelId: "2", at: DAY7 + H + 310, speed: 1 });
  const creates = m.of("POST", /^archive\/players$/);
  await expect(status(page)).toContainText("Oynatıcı yeniden açıldı.");
  await expect(page.getByTestId("player-stream")).toHaveAttribute("src", /^\/api\/live\/archive\/players\/p2\/stream\?k=\d+$/);

  // işlem sırasında kaybolursa (seek 404) aynı konumdan hemen yeniden açılır
  m.fake.actionMissing = true;
  await page.getByRole("button", { name: "1 dakika ileri" }).click();
  await expect.poll(() => m.of("POST", /^archive\/players$/).length).toBe(creates.length + 1);
  expect(m.of("POST", /^archive\/players$/).at(-1)!.body!.at).toBe(DAY7 + H + 370);
  await expect(status(page)).toContainText("Oynatıcı yeniden açıldı.");
  await expect(page.getByTestId("player-stream")).toHaveAttribute("src", /^\/api\/live\/archive\/players\/p3\/stream\?k=\d+$/);
});

test("kayıttan izleme: Dışa aktar — desteklenmiyorsa pasif; 30 dk sınırı; 501/409 iletileri; indirme dosya adı", async ({ page }) => {
  const m = await mockArchive(page);
  await login(page);
  const exportBtn = page.getByRole("button", { name: "Dışa aktar…" });
  await pickKasa(page);
  await expect(exportBtn).toBeDisabled();
  m.fake.canExport = false;
  await playButton(page).click();
  await expect(status(page)).toHaveText("Bağlanıyor…");
  await expect(exportBtn).toBeDisabled();
  await expect(exportBtn).toHaveAttribute("title", "Bu kayıt cihazında dışa aktarma henüz desteklenmiyor.");

  m.fake.view!.canExport = true;
  m.fake.view!.state = "paused";
  await expect(exportBtn).toBeEnabled();
  await exportBtn.click();
  const dlg = page.getByRole("dialog", { name: "Dışa aktar" });
  await expect(dlg).toBeVisible();
  const start = dlg.getByLabel("Başlangıç");
  const end = dlg.getByLabel("Bitiş");
  await expect(start).toHaveValue("2026-11-07T00:59");                   // imleç (01:00) − 1 dk
  await expect(end).toHaveValue("2026-11-07T01:01");                     // + 1 dk
  const go = dlg.getByRole("button", { name: "Dışa aktar" });
  await expect(go).toBeEnabled();
  await end.fill("2026-11-07T01:29:01");                               // 30 dk 1 sn
  await expect(dlg.getByTestId("export-message")).toHaveText("En çok 30 dakika.");
  await expect(go).toBeDisabled();
  await end.fill("2026-11-07T01:29");                                  // tam 30 dk
  await expect(go).toBeEnabled();
  await end.fill("2026-11-07T00:50");
  await expect(dlg.getByTestId("export-message")).toHaveText("Bitiş, başlangıçtan sonra olmalı.");
  await end.fill("2026-11-07T01:01");

  m.fake.exportError = { status: 501, detail: "Bu kayıt cihazı dışa aktarmayı desteklemiyor." };
  await go.click();
  await expect(dlg.getByRole("alert")).toHaveText("Bu kayıt cihazı dışa aktarmayı desteklemiyor.");
  await expect.poll(() => m.of("POST", /^archive\/export$/).at(-1)?.body)
    .toEqual({ sourceId: "b", channelId: "2", start: DAY7 + H - 60, end: DAY7 + H + 60 });
  m.fake.exportError = { status: 409, detail: "Bir dışa aktarma sürüyor." };
  await go.click();
  await expect(dlg.getByRole("alert")).toHaveText("Bir dışa aktarma sürüyor.");

  m.fake.exportError = null;
  let release: () => void = () => undefined;
  m.fake.hold = new Promise<void>((res) => { release = res; });
  const download = page.waitForEvent("download");
  await go.click();
  await expect(dlg.getByRole("button", { name: "Hazırlanıyor…" })).toBeDisabled();
  release();
  const file = await download;
  expect(file.suggestedFilename()).toBe("Ofis NVR · Kasa-20261107-0059.mp4");
  await expect(dlg).toHaveCount(0);
});

test("kayıttan izleme: derin bağlantı kamerayı ve günü seçip t'den oynatır; kamera/gün değişince ve sayfadan çıkınca DELETE", async ({ page }) => {
  const m = await mockArchive(page);
  await login(page);
  const t = DAY3 + 10 * H + 1234;
  await page.goto(`/archive?source=b&channel=2&t=${t}`);
  await expect(page.getByRole("heading", { name: "Kayıttan izleme", level: 1 })).toBeVisible();
  await expect.poll(() => m.of("POST", /^archive\/players$/).at(-1)?.body).toEqual({ sourceId: "b", channelId: "2", at: t, speed: 1 });
  await expect(camera(page, "Ofis NVR · Kasa")).toHaveAttribute("aria-pressed", "true");
  await expect(dayButton(page, /^3 Kasım 2026/)).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("player-clock")).toHaveText("10:20:34 03.11.2026");   // ilk kayıt (01:00) imleci ezmez
  await expect.poll(() => m.of("GET", /^archive\/timeline$/).at(-1)?.query.get("day")).toBe(String(DAY3));
  await expect(status(page)).toHaveText("Bağlanıyor…");

  // sayfa yenilenince derin bağlantı yine oynar (yeni oynatıcı; eskisi sayfadan çıkışta silinir)
  await page.reload();
  await expect.poll(() => m.of("POST", /^archive\/players$/).length).toBe(2);
  expect(m.of("POST", /^archive\/players$/).at(-1)!.body).toEqual({ sourceId: "b", channelId: "2", at: t, speed: 1 });
  await expect(status(page)).toHaveText("Bağlanıyor…");
  await expect(page.getByTestId("player-stream")).toHaveAttribute("src", /^\/api\/live\/archive\/players\/p2\/stream\?k=\d+$/);

  // gün değişince oynatıcı kapanır
  await dayButton(page, /^7 Kasım 2026/).click();
  await expect.poll(() => m.of("DELETE", /^archive\/players\/p2$/).length).toBe(1);
  await expect(status(page)).toHaveText("Oynatmak için çizelgede bir ana tıklayın ya da Oynat'a basın.");
  // kamera değişince de
  await playButton(page).click();
  await expect(status(page)).toHaveText("Bağlanıyor…");
  await camera(page, "Ofis NVR · Giriş").click();
  await expect.poll(() => m.of("DELETE", /^archive\/players\/p3$/).length).toBe(1);
  // sayfadan çıkış (menüden başka sayfa)
  await playButton(page).click();
  await expect(status(page)).toHaveText("Bağlanıyor…");
  await page.route("**/api/live/views", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/live/view-layouts", (r) => r.fulfill({ json: [] }));
  await page.getByRole("navigation", { name: "Ana menü" }).getByRole("link", { name: "Canlı izleme", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Canlı izleme", level: 1 })).toBeVisible();
  await expect.poll(() => m.of("DELETE", /^archive\/players\/p4$/).length).toBe(1);
});

test("kayıttan izleme: yoklama iki kez düşerse 'ulaşılamıyor' notu, düzelince kalkar; açılış sürerken tıklanan son ana sarılır", async ({ page }) => {
  const m = await mockArchive(page);
  await login(page);
  await pickKasa(page);
  const bar = page.getByRole("slider", { name: "Zaman çizelgesi" });
  const box = (await bar.boundingBox())!;
  let release: () => void = () => undefined;
  m.fake.createHold = new Promise<void>((res) => { release = res; });
  await bar.click({ position: { x: box.width / 2, y: box.height / 2 } });              // 12:00'dan açılış (uçuşta)
  await expect(status(page)).toHaveText("Bağlanıyor…");
  await bar.click({ position: { x: box.width / 4, y: box.height / 2 } });              // 06:00 (kaybolmamalı)
  release();
  m.fake.createHold = null;
  await expect.poll(() => m.of("POST", /actions$/).at(-1)?.body?.action).toBe("seek");
  expect(Math.abs(Number(m.of("POST", /actions$/).at(-1)?.body?.at) - (DAY7 + 6 * H))).toBeLessThan(300);
  expect(m.of("POST", /^archive\/players$/)).toHaveLength(1);
  m.fake.view!.state = "playing";
  await expect(status(page)).toHaveText("Oynatılıyor");

  m.fake.pollError = 502;                                       // analiz sunucusu düştü
  await expect(status(page)).toContainText("Analiz sunucusuna ulaşılamıyor; yeniden deneniyor…");
  m.fake.pollError = null;
  await expect(status(page)).toHaveText("Oynatılıyor");
});

/** Sekmeyi gizli/görünür yapar (tarayıcı sekme değişimini taklit eder; watch-ui ile aynı) */
async function setHidden(page: Page, hidden: boolean) {
  await page.evaluate((h) => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => h });
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => (h ? "hidden" : "visible") });
    document.dispatchEvent(new Event("visibilitychange"));
  }, hidden);
}

test("kayıttan izleme: gizli sekmede duraklatılır, akış ve yoklama durur; dönünce yoklama ve akış sürer, oynatma sürmez", async ({ page }) => {
  const m = await mockArchive(page);
  await login(page);
  await pickKasa(page);
  await playButton(page).click();
  m.fake.view!.state = "playing";
  await expect(status(page)).toHaveText("Oynatılıyor");
  const img = page.getByTestId("player-stream");
  await expect(img).toHaveCount(1);
  const polls = () => m.of("GET", /^archive\/players\/p1$/).length;

  await setHidden(page, true);
  await expect.poll(() => m.of("POST", /actions$/).at(-1)?.body).toEqual({ action: "pause" });
  await expect(img).toHaveCount(0);                                     // akış bırakıldı
  await page.waitForTimeout(300);
  const hiddenPolls = polls();
  await page.waitForTimeout(2500);
  expect(polls()).toBe(hiddenPolls);                                    // gizliyken yoklama yok
  expect(m.fake.view!.state).toBe("paused");

  const streams = m.fake.streams;
  await setHidden(page, false);
  await expect(img).toHaveCount(1);
  await expect.poll(() => m.fake.streams).toBeGreaterThan(streams);     // akış yeniden açıldı
  await expect.poll(polls, { timeout: 5000 }).toBeGreaterThan(hiddenPolls + 1);
  await expect(status(page)).toHaveText("Duraklatıldı");
  await expect(playButton(page)).toHaveText("Sürdür");
  expect(m.of("POST", /actions$/).map((c) => c.body?.action)).toEqual(["pause"]);   // kendiliğinden sürmedi

  // gizliyken sunucu oynatıcıyı boşta temizlediyse: dönünce 404 → not; Sürdür yenisini açar
  await setHidden(page, true);
  m.fake.gone = true;
  await page.waitForTimeout(300);
  await setHidden(page, false);
  await expect(status(page)).toContainText("Oynatıcı kapanmış");
  await playButton(page).click();
  await expect.poll(() => m.of("POST", /^archive\/players$/).length).toBe(2);
  await expect(status(page)).toContainText("Oynatıcı yeniden açıldı.");

  // akış hata verirse (bağlantı koptu) kısa süre sonra yeniden açılır
  m.fake.view!.state = "playing";
  await expect(img).toHaveAttribute("src", /^\/api\/live\/archive\/players\/p2\/stream\?k=\d+$/);
  m.fake.streamError = 500;
  const before = m.fake.streams;
  await img.evaluate((el) => { (el as HTMLImageElement).dispatchEvent(new Event("error")); });
  m.fake.streamError = null;
  await expect.poll(() => m.fake.streams, { timeout: 5000 }).toBeGreaterThan(before);
});

test("kayıttan izleme: Hikvision kaydında yalnız 1× (gerçek zamanlı RTSP)", async ({ page }) => {
  const m = await mockArchive(page);
  await login(page);
  await camera(page, "Depo NVR · Rampa").click();
  await expect(page.getByTestId("timeline-range")).toHaveCount(2);
  await playButton(page).click();
  await expect.poll(() => m.of("POST", /^archive\/players$/).at(-1)?.body?.sourceId).toBe("e");
  await expect(page.getByLabel("Hız").locator("option")).toHaveText(["1×"]);
});
