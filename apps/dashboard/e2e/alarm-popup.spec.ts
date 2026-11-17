import { expect, test, type Locator, type Page } from "@playwright/test";

/**
 * Ortadaki alarm penceresi (kritik alarm), SAHTE API ile (page.route): varsayılan canlı görüntü (oturumun işaretli akışı),
 * alarm anının yakın planı (köşe penceresi), "Alarm kaydı"na geçiş, canlı kaynağı olmayan / akışı kırık alarm, kutusu ya da
 * resmi olmayan eski kayıt ve açık alarmlar listesi (kritikler üstte; dar ekranda ‹ ›). Uyarı (telefon kullanımı): sağ altta
 * köşe kartları (modal değil); üstte ince alarm çubuğu (sayaçlar, "Alarmları göster"); kritik alarmda yanıp sönen ekran kenarı.
 */
async function login(page: Page) {
  await page.goto("/notifications");
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("heading", { name: "Bildirimler" })).toBeVisible();
}

/** 1x1 saydam GIF: sahte canlı akış ve olay resmi (gerçek analiz sunucusuna istek gitmesin) */
const GIF = Buffer.from("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7", "base64");
/** 4:3'e yakın (704×576) olay resmi: bazı kameraların alt akışı */
const SVG_704x576 = '<svg xmlns="http://www.w3.org/2000/svg" width="704" height="576"><rect width="704" height="576" fill="#456"/></svg>';

interface FakeAlarm {
  id: string; sessionId: string | null; camera: string; type: string; startedAt: number; firedAt: number;
  endedAt: number | null; acked: boolean; notify: string; image: boolean;
  clip?: boolean; clipStartedAt?: number | null; clipPending?: boolean; clipFailed?: boolean;
  sourceId?: string | null; channelId?: string | null; box?: [number, number, number, number] | null;
  /** Alarmın analiz alanının adı (alan yoksa null; eski kayıtta yok) */
  area?: string | null;
}

/** Canlı güvenlik oturumu (alarmın oturumu hâlâ açık: pencere oturumun işaretli akışını gösterir) */
function fakeSession(id = "abc123", name = "Tezgah kamerası") {
  return {
    id, name, state: "live", message: "", fps: 8, width: 1280, height: 720,
    counting: false, total: 0, totalOut: 0, staffIn: 0, staffOut: 0, twoWay: false, ratePerMinute: 0,
    calibrating: null, calibrationMessage: "", sourceId: null, channelId: null, profileId: null, substream: null,
    safety: { active: [], lastAlarmAt: null, healthy: true, reason: null, unhealthyFor: null },
    profile: {
      id: "p", name: "Kuyumcu güvenliği", roi: { x: 0.1, y: 0.1, width: 0.8, height: 0.8 }, linePosition: 0.5, direction: "down",
      diffThreshold: 30, expectedArea: 0, splitTouching: false, countMode: "safety",
      safety: { handsUp: { enabled: true, seconds: 3 }, lying: { enabled: true, seconds: 10 }, sendImage: false },
    },
  };
}

/**
 * Sahte alarm akışı + canlı oturum. `stream`: oturum akışının cevabı ("ok" GIF, "404" hata). Liste sayfa açıldıktan SONRA
 * doldurulmalı (login'den kalan sayfanın yoklaması alarmları "gösterildi" saymasın).
 */
async function fake(page: Page, list: FakeAlarm[], stream: "ok" | "404" = "ok") {
  /** `ackFails`: test açarsa "Gördüm" isteği 500 döner (alarm açık kalır) */
  const calls = { polls: 0, streams: 0, acks: [] as string[], ackFails: false };
  await page.route("**/api/live/sessions", (route) =>
    route.request().method() === "GET" ? route.fulfill({ json: [fakeSession()] }) : route.continue());
  await page.route("**/api/live/sessions/abc123/stream*", (route) => {
    calls.streams += 1;
    return stream === "ok" ? route.fulfill({ contentType: "image/gif", body: GIF })
      : route.fulfill({ status: 404, json: { detail: "Oturum bulunamadı." } });
  });
  await page.route(/\/api\/live\/alarms\?active=1$/, (route) => {
    calls.polls += 1;
    return route.fulfill({ json: list.filter((a) => !a.acked) });
  });
  await page.route(/\/api\/live\/alarms\/[^/]+\/ack$/, (route) => {
    if (calls.ackFails) return route.fulfill({ status: 500, json: { detail: "Sunucu hatası." } });
    const id = route.request().url().split("/").at(-2)!;
    const a = list.find((x) => x.id === id);
    if (!a) return route.fulfill({ status: 404, json: { detail: "Alarm bulunamadı." } });
    a.acked = true;
    calls.acks.push(id);
    return route.fulfill({ json: a });
  });
  await page.route(/\/api\/live\/alarms\/[^/]+\/image\.jpg$/, (route) => route.fulfill({ contentType: "image/gif", body: GIF }));
  await page.route(/\/api\/live\/alarms\/[^/]+\/clip\.webm$/, (route) => route.fulfill({ status: 404, json: { detail: "Olay kaydı yok." } }));
  await page.goto("/notifications");
  await expect.poll(() => calls.polls).toBeGreaterThan(0);
  return calls;
}

const modalOf = (page: Page) => page.getByRole("alertdialog", { name: "Alarm", exact: true });

/** Pencerenin metninde emoji var mı (başlık, bilgi satırı, liste satırları, açıklamalar dahil) */
const hasEmoji = (modal: Locator) => modal.evaluate((el) => /\p{Extended_Pictographic}/u.test(el.textContent ?? ""));

/**
 * Öğenin yazı rengiyle görünen zemini arasındaki kontrast oranı (WCAG). Zemin, öğeden yukarı doğru yarı saydam katmanlar
 * beyaz üstüne 1×1 tuvalde boyanarak bulunur (Tailwind v4 renkleri oklab/color-mix olarak gelir; tuval hepsini çözer).
 */
const contrastOf = (loc: Locator) => loc.evaluate((node) => {
  const layers: string[] = [];
  for (let el: Element | null = node; el; el = el.parentElement) layers.push(getComputedStyle(el).backgroundColor);
  const ctx = document.createElement("canvas").getContext("2d", { willReadFrequently: true })!;
  ctx.canvas.width = ctx.canvas.height = 1;
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, 1, 1);
  for (const c of layers.reverse()) { ctx.fillStyle = c; ctx.fillRect(0, 0, 1, 1); }
  const bg = [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3);
  ctx.fillStyle = getComputedStyle(node).color;
  ctx.fillRect(0, 0, 1, 1);
  const fg = [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3);
  const lum = (rgb: number[]) => {
    const [r, g, b] = rgb.map((v) => { const x = v / 255; return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const [hi, lo] = [lum(fg), lum(bg)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
});

function alarm(over: Partial<FakeAlarm> & Pick<FakeAlarm, "id" | "type">): FakeAlarm {
  const now = Date.now() / 1000;
  return { sessionId: "abc123", camera: "Tezgah kamerası", startedAt: now - 8, firedAt: now - 5, endedAt: null, acked: false,
           notify: "disabled", image: true, clip: false, clipStartedAt: null, clipPending: true, ...over };
}

test("critical alarm opens centre window on live view with alarm-moment inset", async ({ page }) => {
  await login(page);
  const list: FakeAlarm[] = [];
  const calls = await fake(page, list);
  list.push(alarm({ id: "f1", type: "fire", camera: "Mutfak kamerası", box: [0.6, 0.5, 0.8, 0.9], notify: "sent" }));
  const modal = modalOf(page);
  await expect(modal).toBeVisible();
  await expect(modal).toHaveAttribute("data-severity", "critical");
  await expect(modal).toHaveAttribute("data-kind", "fire");
  await expect(modal.getByTestId("alarm-title")).toHaveText("Yangın");
  // yangın başlığı turuncu (--color-fire-600)
  await expect(modal.getByTestId("alarm-header")).toHaveCSS("background-color", "rgb(226, 83, 31)");
  // emoji yok: başlıkta türün çizgi simgesi; ikinci satır "<kamera> · <tarih-saat>"
  await expect(modal.getByTestId("alarm-header").locator('svg[data-icon="fire"]')).toBeVisible();
  await expect(modal.getByTestId("alarm-header")).toContainText(/Mutfak kamerası · \d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}/);
  expect(await hasEmoji(modal)).toBe(false);
  // bilgi satırı: kamera, saat, geçen süre (canlı sayaç), bildirim
  await expect(modal.getByTestId("alarm-time")).toHaveText(/^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}$/);
  await expect(modal.getByTestId("alarm-ago")).toHaveText(/^\d+ sn önce$/);
  await expect(modal).toContainText("Telegram'a gitti");
  await expect(modal).toContainText("Mutfak kamerası");

  // varsayılan canlı: oturumun işaretli akışı
  await expect(modal.getByTestId("media-live")).toHaveAttribute("aria-pressed", "true");
  await expect(modal.getByTestId("media-clip")).toHaveAttribute("aria-pressed", "false");
  await expect(modal.getByTestId("alarm-live")).toHaveAttribute("src", /\/api\/live\/sessions\/abc123\/stream/);
  await expect.poll(() => calls.streams).toBeGreaterThan(0);
  await expect(modal.getByTestId("live-error")).toHaveCount(0);
  // kutu sağ yarıda: köşe penceresi solda; resim kutuya yakınlaştırılmış
  const inset = modal.getByTestId("alarm-inset");
  await expect(inset).toHaveAttribute("data-side", "left");
  await expect(inset).toContainText("Alarm anı ·");
  await expect(inset.locator("img")).toHaveAttribute("src", "/api/live/alarms/f1/image.jpg");
  // kutunun uzun kenarı (0,4) köşe penceresinin %62,5'i olur: ölçek 1 / (1,6 × 0,4) ≈ 1,56
  expect(parseFloat(await inset.locator("img").evaluate((el: HTMLImageElement) => el.style.width))).toBeCloseTo(156.25, 0);
  // Gördüm odakta
  await expect(modal.getByRole("button", { name: "Gördüm", exact: true })).toBeFocused();

  // köşe penceresine tıklayınca "Alarm kaydı"
  await inset.click();
  await expect(modal.getByTestId("media-clip")).toHaveAttribute("aria-pressed", "true");
  await expect(modal.getByTestId("media-live")).toHaveAttribute("aria-pressed", "false");
  await expect(modal.getByTestId("clip-caption").or(modal.getByTestId("alarm-video"))).toBeVisible();
  await expect(modal.getByTestId("alarm-live")).toHaveCount(0);               // kayıtta canlı akış bırakılır
  await expect(modal.getByTestId("alarm-inset")).toHaveCount(0);
  // geri canlıya
  await modal.getByTestId("media-live").click();
  await expect(modal.getByTestId("alarm-live")).toBeVisible();
});

test("alarm without live source opens on clip and disables live", async ({ page }) => {
  await login(page);
  const list: FakeAlarm[] = [];
  await fake(page, list);
  list.push(alarm({ id: "t1", type: "test", camera: "Kasa", sessionId: null, sourceId: null, image: false, clipPending: false }));
  const modal = modalOf(page);
  await expect(modal.getByTestId("alarm-title")).toHaveText("DENEME ALARMI");
  await expect(modal).toHaveAttribute("data-kind", "test");
  await expect(modal.getByTestId("alarm-header")).toHaveCSS("background-color", "rgb(74, 95, 125)");
  await expect(modal.getByTestId("media-clip")).toHaveAttribute("aria-pressed", "true");
  await expect(modal.getByTestId("media-live")).toBeDisabled();
  await expect(modal.getByTestId("media-live")).toHaveAttribute("title", "Canlı görüntü yok");
  await expect(modal.getByTestId("clip-caption")).toHaveText("Bu alarmın kaydı yok.");
  await expect(page.getByTestId("alarm-live")).toHaveCount(0);
  await expect(modal.locator("img")).toHaveCount(0);                          // kırık resim yok
  await expect(modal.getByTestId("alarm-inset")).toHaveCount(0);
});

test("broken live stream shows error and clip still works", async ({ page }) => {
  await login(page);
  const list: FakeAlarm[] = [];
  const calls = await fake(page, list, "404");
  list.push(alarm({ id: "h1", type: "hands_up", box: [0.1, 0.2, 0.3, 0.6] }));
  const modal = modalOf(page);
  await expect(modal.getByTestId("alarm-header")).toHaveCSS("background-color", "rgb(217, 58, 74)");
  await expect(modal.getByTestId("media-live")).toHaveAttribute("aria-pressed", "true");
  await expect(modal.getByTestId("live-error")).toHaveText("Canlı görüntü alınamıyor");
  // kırık resim (tarayıcının simgesi, alt yazısı) yazının arkasında görünmez; akış kendiliğinden yeniden denenir (≈2 sn)
  await expect(modal.getByTestId("alarm-live")).toBeHidden();
  await expect.poll(() => calls.streams, { timeout: 10_000 }).toBeGreaterThan(1);
  await expect(modal.getByTestId("live-error")).toBeVisible();
  await expect(modal.getByTestId("alarm-inset")).toHaveAttribute("data-side", "right");   // kutu sol yarıda
  await modal.getByTestId("media-clip").click();
  await expect(modal.getByTestId("media-clip")).toHaveAttribute("aria-pressed", "true");
  await expect(modal.getByTestId("clip-caption")).toHaveText("Kayıt hazırlanıyor…");
  await expect(modal.getByAltText("Olay resmi")).toHaveAttribute("src", "/api/live/alarms/h1/image.jpg");
  await expect(modal.getByTestId("live-error")).toHaveCount(0);
});

test("old record without box shows whole image; no image no inset", async ({ page }) => {
  await login(page);
  const list: FakeAlarm[] = [];
  await fake(page, list);
  const now = Date.now() / 1000;
  // o1'in olay resmi 704×576 (4:3'e yakın alt akış): köşe penceresi resmin kendi oranında, gerilmez
  await page.route(/\/api\/live\/alarms\/o1\/image\.jpg$/, (route) => route.fulfill({ contentType: "image/svg+xml", body: SVG_704x576 }));
  list.push(
    alarm({ id: "o1", type: "lying", firedAt: now - 5 }),                         // eski kayıt: box alanı yok
    alarm({ id: "o2", type: "hands_up", firedAt: now - 30, image: false, box: [0.6, 0.5, 0.8, 0.9] }),
  );
  const modal = modalOf(page);
  await expect(modal.getByTestId("alarm-title")).toHaveText("YERDE YATAN KİŞİ");
  await expect(modal.getByTestId("media-live")).toHaveAttribute("aria-pressed", "true");
  const inset = modal.getByTestId("alarm-inset");
  await expect(inset).toBeVisible();
  await expect(inset).toHaveAttribute("data-side", "right");
  expect(await inset.locator("img").evaluate((el: HTMLImageElement) => el.style.width)).toBe("");   // resmin tamamı
  await expect.poll(async () => {
    const b = (await modal.getByTestId("inset-frame").boundingBox())!;
    return b.width / b.height;
  }).toBeCloseTo(704 / 576, 1);
  await modal.getByTestId("queue-item").nth(1).click();
  await expect(modal.getByTestId("alarm-title")).toHaveText("ELLER YUKARI");
  await expect(modal.getByTestId("alarm-live")).toBeVisible();
  await expect(modal.getByTestId("alarm-inset")).toHaveCount(0);               // resim yok: köşe penceresi yok
});

test("queue lists critical first and selects on click", async ({ page }) => {
  await login(page);
  const list: FakeAlarm[] = [];
  await fake(page, list);
  const now = Date.now() / 1000;
  list.push(
    alarm({ id: "p1", type: "phone", camera: "Kasa", firedAt: now - 2 }),
    alarm({ id: "f1", type: "fire", camera: "Mutfak", firedAt: now - 10 }),
    alarm({ id: "l1", type: "lying", camera: "Depo", firedAt: now - 20 }),
  );
  const modal = modalOf(page);
  await expect(modal).toBeVisible();
  const queue = modal.getByTestId("alarm-queue");
  const items = queue.getByTestId("queue-item");
  await expect(items).toHaveCount(3);
  await expect(items.nth(0)).toContainText("Yangın");
  await expect(items.nth(0)).toContainText("Mutfak");
  await expect(items.nth(1)).toContainText("Yerde yatan kişi");
  await expect(items.nth(2)).toContainText("Telefon kullanımı");
  await expect(items.nth(2)).toContainText(/\d+ sn önce/);
  // geniş ekranda ‹ › yok (liste var)
  await expect(modal.getByTestId("alarm-counter")).toBeHidden();
  await items.nth(1).click();
  await expect(modal.getByTestId("alarm-title")).toHaveText("YERDE YATAN KİŞİ");
  await expect(items.nth(1)).toHaveAttribute("aria-current", "true");
  await expect(items.nth(0)).not.toHaveAttribute("aria-current", "true");
  // emoji yok: liste satırları, başlık ve görüntü alanı (canlı ve kayıt açıklaması) dahil
  expect(await hasEmoji(modal)).toBe(false);
  await modal.getByTestId("media-clip").click();
  await expect(modal.getByTestId("clip-caption")).toBeVisible();
  expect(await hasEmoji(modal)).toBe(false);
  await modal.getByTestId("media-live").click();
  // liste satırları canlı değil: yalnız gösterilen alarm canlı akar
  await expect(modal.getByTestId("alarm-live")).toHaveCount(1);
  await expect(queue.locator("img")).toHaveCount(3);
  for (const src of await queue.locator("img").evaluateAll((els) => els.map((e) => e.getAttribute("src")))) {
    expect(src).toMatch(/^\/api\/live\/alarms\/[a-z0-9]+\/image\.jpg$/);
  }
  // dar ekranda liste gizlenir, ‹ › geri gelir (aynı sıra)
  await page.setViewportSize({ width: 700, height: 900 });
  await expect(queue).toBeHidden();
  await expect(modal.getByTestId("alarm-counter")).toHaveText("2 / 3");
  await modal.getByRole("button", { name: "Sonraki alarm" }).click();
  await expect(modal.getByTestId("alarm-title")).toHaveText("TELEFON KULLANIMI");
  await expect(modal).toHaveAttribute("data-severity", "warning");
  await expect(modal.getByTestId("alarm-header")).toHaveCSS("background-color", "rgb(216, 154, 30)");
});

test("Gördüm moves to the alarm at the same place in the sorted list, not the server order", async ({ page }) => {
  await login(page);
  const list: FakeAlarm[] = [];
  const calls = await fake(page, list);
  const now = Date.now() / 1000;
  // sunucu sırası (yeniden eskiye): telefon, yangın, yerde yatan; pencerenin sırası: yangın, yerde yatan, telefon
  list.push(
    alarm({ id: "p1", type: "phone", camera: "Kasa", firedAt: now - 2 }),
    alarm({ id: "f1", type: "fire", camera: "Mutfak", firedAt: now - 10 }),
    alarm({ id: "l1", type: "lying", camera: "Depo", firedAt: now - 20 }),
  );
  const modal = modalOf(page);
  const items = modal.getByTestId("queue-item");
  await expect(items).toHaveCount(3);
  await items.nth(0).click();
  await expect(modal.getByTestId("alarm-title")).toHaveText("Yangın");
  await modal.getByRole("button", { name: "Gördüm", exact: true }).click();
  await expect.poll(() => calls.acks).toEqual(["f1"]);
  // aynı yerdeki (ilk) alarm artık yerde yatan kişi (sunucu sırasında ilk olan telefon değil)
  await expect(modal.getByTestId("alarm-title")).toHaveText("YERDE YATAN KİŞİ");
  await expect(items).toHaveCount(2);
  await expect(items.nth(0)).toHaveAttribute("aria-current", "true");
  await expect(modal.getByRole("button", { name: "Gördüm", exact: true })).toBeFocused();
  await page.setViewportSize({ width: 700, height: 900 });
  await expect(modal.getByTestId("alarm-counter")).toHaveText("1 / 2");
});

test("browse mode opens on clip; Canlı is enabled while the alarm's session is live", async ({ page }) => {
  await login(page);
  const now = Date.now() / 1000;
  const history = [
    { ...alarm({ id: "h1", type: "hands_up", firedAt: now - 120 }), acked: true, endedAt: now - 110, clipPending: false },
  ];
  await page.route("**/api/live/sessions", (route) =>
    route.request().method() === "GET" ? route.fulfill({ json: [fakeSession()] }) : route.continue());
  let streams = 0;
  await page.route("**/api/live/sessions/abc123/stream*", (route) => { streams += 1; return route.fulfill({ contentType: "image/gif", body: GIF }); });
  // Alarmlar sayfası geçmişi ister; onaylanmamış alarm yok (etkin pencere açılmaz)
  await page.route(/\/api\/live\/alarms\?/, (route) =>
    route.fulfill({ json: new URL(route.request().url()).searchParams.get("active") === "1" ? [] : history }));
  await page.route(/\/api\/live\/alarms\/[^/]+\/image\.jpg$/, (route) => route.fulfill({ contentType: "image/gif", body: GIF }));
  // oturum listesi (alarm merkezinin yoklaması) gelmeden satıra tıklanmasın: "Canlı" o listeye bakar
  const sessionsSeen = page.waitForResponse((r) => /\/api\/live\/sessions$/.test(r.url()));
  await page.goto("/alarms");
  await sessionsSeen;
  await page.getByTestId("alarm-row").first().click();
  const modal = modalOf(page);
  await expect(modal.getByTestId("alarm-state")).toContainText("Onaylandı");
  await expect(modal.getByTestId("media-clip")).toHaveAttribute("aria-pressed", "true");     // geçmiş alarm: kayıtta açılır
  await expect(modal.getByTestId("alarm-live")).toHaveCount(0);
  expect(streams).toBe(0);
  await expect(modal.getByTestId("media-live")).toBeEnabled();
  await modal.getByTestId("media-live").click();
  await expect(modal.getByTestId("media-live")).toHaveAttribute("aria-pressed", "true");
  await expect(modal.getByTestId("alarm-live")).toBeVisible();
  await expect(modal.getByTestId("alarm-live")).toHaveAttribute("src", /\/api\/live\/sessions\/abc123\/stream/);
  await expect(modal.getByTestId("alarm-queue")).toHaveCount(0);                          // göz atmada liste yok
});

test("header small text keeps at least 4.5:1 contrast on every alarm colour", async ({ page }) => {
  await login(page);
  const list: FakeAlarm[] = [];
  await fake(page, list);
  const now = Date.now() / 1000;
  list.push(
    alarm({ id: "c1", type: "fire", camera: "Mutfak", firedAt: now - 5, endedAt: now - 1 }),        // Süre çipi
    alarm({ id: "c2", type: "hands_up", camera: "Kasa", firedAt: now - 10 }),                      // devam ediyor
    alarm({ id: "c3", type: "test", camera: "Deneme", firedAt: now - 15, sessionId: null }),
    alarm({ id: "c4", type: "phone", camera: "Depo", firedAt: now - 20, endedAt: now - 3 }),         // sarıda Süre çipi
  );
  const modal = modalOf(page);
  const items = modal.getByTestId("queue-item");
  await expect(items).toHaveCount(4);
  const kinds = ["fire", "hands_up", "test", "phone"];
  for (const [i, kind] of kinds.entries()) {
    await items.nth(i).click();
    await expect(modal).toHaveAttribute("data-kind", kind);
    expect(await contrastOf(modal.getByTestId("alarm-subtitle")), `${kind} ikinci satır`).toBeGreaterThanOrEqual(4.5);
    // büyük kalın başlık (>= 18,66 px kalın) için 3:1 yeter; yangın turuncusunda beyaz 3,8:1 (ölçüm başlık rengini görüyor)
    const title = await contrastOf(modal.getByTestId("alarm-title"));
    expect(title, `${kind} başlık`).toBeGreaterThanOrEqual(3);
    if (kind === "fire") expect(title).toBeLessThan(4.5);
    const status = modal.getByTestId("alarm-status");
    if (await status.count()) expect(await contrastOf(status), `${kind} durum çipi`).toBeGreaterThanOrEqual(4.5);
  }
  // dar ekranda başlıktaki sayaç da (ilk alarmdan başlayıp ‹ › ile)
  await items.nth(0).click();
  await page.setViewportSize({ width: 700, height: 900 });
  for (const [i, kind] of kinds.entries()) {
    await expect(modal).toHaveAttribute("data-kind", kind);
    await expect(modal.getByTestId("alarm-counter")).toHaveText(`${i + 1} / 4`);
    expect(await contrastOf(modal.getByTestId("alarm-counter")), `${kind} sayaç`).toBeGreaterThanOrEqual(4.5);
    if (i < kinds.length - 1) await modal.getByRole("button", { name: "Sonraki alarm" }).click();
  }
});

// ------------------------------------------------------------------ köşe kartları (uyarı), alarm çubuğu, ekran kenarı

const toastsOf = (page: Page) => page.getByTestId("alarm-toasts");
/** Ekran okuyucunun duyuru bölgesinde okuyacağı yazı: aria-hidden alt ağaçlar hariç */
const spokenText = (loc: Locator) => loc.evaluate((root) => {
  const walk = (n: Node): string => {
    if (n.nodeType === Node.TEXT_NODE) return n.textContent ?? "";
    if (n instanceof Element && n.getAttribute("aria-hidden") === "true") return "";
    return [...n.childNodes].map(walk).join("");
  };
  return walk(root);
});
/** Sekme başlığı yanıp sönerken alarm hâlini bekler (her saniye sayfa başlığıyla değişir) */
const alarmTitle = async (page: Page, text: string) => {
  await expect.poll(() => page.title(), { intervals: [100] }).toBe(text);
  return page.title();
};

test("phone alarm shows corner card without modal", async ({ page }) => {
  await login(page);
  const list: FakeAlarm[] = [];
  const calls = await fake(page, list);
  list.push(alarm({ id: "p1", type: "phone", camera: "Kasa", box: [0.1, 0.2, 0.3, 0.6] }));
  const toasts = toastsOf(page);
  const toast = toasts.getByTestId("alarm-toast");
  await expect(toast).toHaveCount(1);
  await expect(toast).toBeVisible();
  await expect(toasts).toHaveAttribute("aria-live", "assertive");
  await expect(toast).not.toHaveAttribute("data-compact", "true");
  await expect(toast).toHaveAttribute("data-kind", "phone");
  await expect(toast.getByTestId("toast-title")).toHaveText("Telefon kullanımı");
  await expect(toast.locator('svg[data-icon="phone"]')).toBeVisible();
  await expect(toast.getByTestId("toast-meta")).toContainText(/Kasa · \d{2}:\d{2}:\d{2} · \d+ sn önce/);
  // tam kart: canlı görüntü (oturumun işaretli akışı) ve alarm anı köşe penceresi
  await expect(toast.getByTestId("media-live")).toHaveAttribute("aria-pressed", "true");
  await expect(toast.getByTestId("alarm-live")).toHaveAttribute("src", /\/api\/live\/sessions\/abc123\/stream/);
  await expect(toast.getByTestId("alarm-inset")).toHaveAttribute("data-side", "right");
  await expect(toast.getByRole("link", { name: "Kamerayı aç" })).toHaveAttribute("href", "/live?s=abc123");
  await expect(toast.getByRole("button", { name: "Yanlış alarm" })).toBeVisible();
  // modal değil, ekran kenarı yok (yalnız kritikte); çubukta "1 uyarı", kritik sayacı yok
  await expect(modalOf(page)).toHaveCount(0);
  await expect(page.getByTestId("alarm-edge")).toHaveCount(0);
  await expect(page.getByTestId("alarm-count-warning")).toHaveText("1 uyarı");
  await expect(page.getByTestId("alarm-count-critical")).toHaveCount(0);
  await expect(page.getByTestId("alarm-banner")).toContainText("Son: Telefon kullanımı — Kasa");
  // kart odak çalmaz; sayfa kullanılmaya devam eder
  expect(await toast.evaluate((el) => el.contains(document.activeElement))).toBe(false);
  await page.getByRole("heading", { name: "Bildirimler" }).click();
  // emoji yok (kartta ve sekme başlığında); küçük yazılar ≥4,5:1
  expect(await hasEmoji(toasts)).toBe(false);
  const title = await alarmTitle(page, "ALARM — Kasa");
  expect(/\p{Extended_Pictographic}/u.test(title)).toBe(false);
  expect(await contrastOf(toast.getByTestId("toast-title")), "kart başlığı").toBeGreaterThanOrEqual(4.5);
  expect(await contrastOf(toast.getByTestId("toast-meta")), "kart bilgi satırı").toBeGreaterThanOrEqual(4.5);

  await toast.getByRole("button", { name: "Gördüm", exact: true }).click();
  await expect.poll(() => calls.acks).toEqual(["p1"]);
  await expect(toast).toHaveCount(0);
  await expect(page.getByTestId("alarm-banner")).toHaveCount(0);
});

test("corner card region is not re-announced by the ticking time; a new warning is", async ({ page }) => {
  await login(page);
  const list: FakeAlarm[] = [];
  await fake(page, list);
  const now = Date.now() / 1000;
  list.push(alarm({ id: "p1", type: "phone", camera: "Kasa", firedAt: now - 3, clipPending: false }));
  const toasts = toastsOf(page);
  await expect(toasts.getByTestId("alarm-toast")).toHaveCount(1);
  await expect(toasts.getByTestId("alarm-live")).toBeVisible();
  const ago = toasts.getByTestId("toast-ago");
  await expect(ago).toHaveAttribute("aria-hidden", "true");
  const before = await spokenText(toasts);
  const agoBefore = await ago.textContent();
  expect(before).toContain("Kasa");
  expect(before).not.toMatch(/sn önce/);                                   // geçen süre okunmaz, saat okunur
  expect(before).toMatch(/\d{2}:\d{2}:\d{2}/);
  await page.waitForTimeout(2200);                                         // kart boşta: görünen süre ilerler
  await expect.poll(() => ago.textContent()).not.toBe(agoBefore);
  expect(await spokenText(toasts)).toBe(before);                          // okunan yazı değişmedi
  // yeni uyarı yine duyurulur (bölgeye okunan yazıyla eklenir)
  list.push(alarm({ id: "p2", type: "phone", camera: "Depo", firedAt: now - 30 }));
  await expect(toasts.getByTestId("alarm-toast")).toHaveCount(2);
  const after = await spokenText(toasts);
  expect(after).toContain("Depo");
  expect(after).toContain("Telefon kullanımı");
});

test("critical arrives while card shown opens window and hides cards", async ({ page }) => {
  await login(page);
  const list: FakeAlarm[] = [];
  await fake(page, list);
  const now = Date.now() / 1000;
  list.push(alarm({ id: "p1", type: "phone", camera: "Kasa", firedAt: now - 10 }));
  const toasts = toastsOf(page);
  await expect(toasts.getByTestId("alarm-toast")).toHaveCount(1);
  list.push(alarm({ id: "s1", type: "smoke", camera: "Depo", firedAt: now - 1 }));
  const modal = modalOf(page);
  await expect(modal).toBeVisible();
  await expect(modal).toHaveAttribute("data-kind", "smoke");                 // en yeni kritikte açılır
  await expect(toasts.getByTestId("alarm-toast")).toHaveCount(0);           // pencere açıkken kart çizilmez
  // ince çubuk: iki sayaç ve son alarm
  await expect(page.getByTestId("alarm-count-critical")).toHaveText("1 kritik alarm");
  await expect(page.getByTestId("alarm-count-warning")).toHaveText("1 uyarı");
  await expect(page.getByTestId("alarm-banner")).toContainText("Son: Duman — Depo");
  await modal.getByRole("button", { name: "Küçült" }).click();
  // çubuktaki sayaçların yazısı ≥4,5:1 (kırmızı yazı açık zeminde, sarı çipte koyu yazı)
  expect(await contrastOf(page.getByTestId("alarm-count-critical")), "kritik sayacı").toBeGreaterThanOrEqual(4.5);
  expect(await contrastOf(page.getByTestId("alarm-count-warning")), "uyarı sayacı").toBeGreaterThanOrEqual(4.5);
  await expect(modal).toHaveCount(0);
  await expect(toasts.getByTestId("alarm-toast")).toHaveCount(1);
  await expect(toasts.getByTestId("alarm-toast")).toContainText("Kasa");
  // onaylanmamış kritik: ekranın kenarı yanıp söner; tıklanamaz (altındaki sayfa kullanılır)
  const edge = page.getByTestId("alarm-edge");
  await expect(edge).toBeVisible();
  await expect(edge).toHaveCSS("pointer-events", "none");
  await expect(edge).toHaveCSS("position", "fixed");
  expect(await edge.evaluate((el) => getComputedStyle(el).animationName)).not.toBe("none");
  // hareket azaltma tercihinde yanıp sönmez, sabit kalır
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect.poll(() => edge.evaluate((el) => getComputedStyle(el).animationName)).toBe("none");
  await expect(edge).toBeVisible();
  // "Alarmları göster": pencere pencerenin sırasındaki ilk alarmda (kritik) açılır
  await page.getByRole("button", { name: "Alarmları göster" }).click();
  await expect(modal).toHaveAttribute("data-kind", "smoke");
  await expect(modal.getByTestId("queue-item").nth(0)).toHaveAttribute("aria-current", "true");
});

test("minimized window plus new warning shows card only", async ({ page }) => {
  await login(page);
  const list: FakeAlarm[] = [];
  const calls = await fake(page, list);
  const now = Date.now() / 1000;
  list.push(alarm({ id: "f1", type: "fire", camera: "Mutfak", firedAt: now - 10 }));
  const modal = modalOf(page);
  await expect(modal).toBeVisible();
  await modal.getByRole("button", { name: "Küçült" }).click();
  await expect(modal).toHaveCount(0);
  list.push(alarm({ id: "p1", type: "phone", camera: "Kasa", firedAt: now - 1 }));
  await expect(toastsOf(page).getByTestId("alarm-toast")).toHaveCount(1);
  await expect(page.getByTestId("alarm-count-warning")).toHaveText("1 uyarı");
  await expect(page.getByTestId("alarm-count-critical")).toHaveText("1 kritik alarm");
  // sonraki yoklamalarda da pencere kapalı kalır (yalnız uyarı geldi)
  const n = calls.polls;
  await expect.poll(() => calls.polls, { timeout: 10_000 }).toBeGreaterThan(n + 1);
  await expect(modal).toHaveCount(0);
  await expect(page.getByTestId("alarm-edge")).toBeVisible();
});

test("card hide keeps alarm in bar", async ({ page }) => {
  await login(page);
  const list: FakeAlarm[] = [];
  const calls = await fake(page, list);
  list.push(alarm({ id: "p1", type: "phone", camera: "Kasa" }));
  const toast = toastsOf(page).getByTestId("alarm-toast");
  await expect(toast).toHaveCount(1);
  await toast.getByRole("button", { name: "Gizle: Telefon kullanımı — Kasa" }).click();
  await expect(toast).toHaveCount(0);
  expect(calls.acks).toEqual([]);                                           // × onay değildir
  await expect(page.getByTestId("alarm-count-warning")).toHaveText("1 uyarı");
  // sonraki yoklamalar gizlenen kartı geri getirmez
  const n = calls.polls;
  await expect.poll(() => calls.polls, { timeout: 10_000 }).toBeGreaterThan(n + 1);
  await expect(toast).toHaveCount(0);
  // sayfa yenilense de bu sekmede gizli kalır (pencere de açılmaz: alarm bu sekmede gösterildi)
  await page.reload();
  await expect(page.getByTestId("alarm-count-warning")).toHaveText("1 uyarı");
  const m = calls.polls;
  await expect.poll(() => calls.polls, { timeout: 10_000 }).toBeGreaterThan(m + 1);
  await expect(toast).toHaveCount(0);
  await expect(modalOf(page)).toHaveCount(0);
  await page.getByRole("button", { name: "Alarmları göster" }).click();
  const modal = modalOf(page);
  await expect(modal).toBeVisible();
  await expect(modal).toHaveAttribute("data-kind", "phone");
  await modal.getByRole("button", { name: "Küçült" }).click();
  await expect(modal).toHaveCount(0);
  await expect(toast).toHaveCount(0);                                       // gizli kalır
});

test("ack failure on card shows error", async ({ page }) => {
  await login(page);
  const list: FakeAlarm[] = [];
  const calls = await fake(page, list);
  calls.ackFails = true;
  list.push(alarm({ id: "p1", type: "phone", camera: "Kasa" }));
  const toast = toastsOf(page).getByTestId("alarm-toast");
  await toast.getByRole("button", { name: "Gördüm", exact: true }).click();
  await expect(toast.getByTestId("toast-error")).toHaveText("Gördüm kaydedilemedi; alarm açık kalıyor. Tekrar deneyin.");
  await expect(toast).toHaveCount(1);
  await expect(page.getByTestId("alarm-count-warning")).toHaveText("1 uyarı");
  // pencere açılıp küçültülünce eski hata kartta yeniden çıkmaz
  await page.getByRole("button", { name: "Alarmları göster" }).click();
  await expect(modalOf(page)).toBeVisible();
  await modalOf(page).getByRole("button", { name: "Küçült" }).click();
  await expect(toast).toHaveCount(1);
  await expect(toast.getByTestId("toast-error")).toHaveCount(0);
  // ikinci deneme başarılı: kart kapanır
  calls.ackFails = false;
  await toast.getByRole("button", { name: "Gördüm", exact: true }).click();
  await expect.poll(() => calls.acks).toEqual(["p1"]);
  await expect(toast).toHaveCount(0);
});

test("three warnings show two cards and more", async ({ page }) => {
  await login(page);
  const list: FakeAlarm[] = [];
  const calls = await fake(page, list);
  const now = Date.now() / 1000;
  list.push(
    alarm({ id: "p1", type: "phone", camera: "Kasa", firedAt: now - 2 }),
    alarm({ id: "p2", type: "phone", camera: "Depo", firedAt: now - 10 }),
    alarm({ id: "p3", type: "phone", camera: "Kapı", firedAt: now - 20 }),
  );
  const toasts = toastsOf(page);
  const items = toasts.getByTestId("alarm-toast");
  await expect(items).toHaveCount(2);
  await expect(items.nth(0)).toContainText("Kasa");                         // en yeni tam kart
  await expect(items.nth(0)).not.toHaveAttribute("data-compact", "true");
  await expect(items.nth(1)).toHaveAttribute("data-compact", "true");
  await expect(items.nth(1)).toContainText("Depo");
  // küçük kart canlı değil: olay resmi küçüğü (yalnız tam kart canlı akar)
  await expect(items.nth(1).getByTestId("alarm-live")).toHaveCount(0);
  await expect(items.nth(1).locator("img")).toHaveAttribute("src", "/api/live/alarms/p2/image.jpg");
  await expect(page.getByTestId("alarm-live")).toHaveCount(1);
  await expect(items.nth(1).getByRole("button", { name: "Gördüm", exact: true })).toBeVisible();
  await expect(items.nth(1).getByRole("button", { name: "Yanlış alarm" })).toBeVisible();
  await expect(items.nth(1).getByRole("button", { name: "Gizle: Telefon kullanımı — Depo" })).toBeVisible();
  await expect(page.getByTestId("alarm-count-warning")).toHaveText("3 uyarı");
  const more = toasts.getByTestId("toast-more");
  await expect(more).toHaveText("+1 uyarı daha");
  await more.click();
  const modal = modalOf(page);
  await expect(modal).toBeVisible();
  await expect(modal.getByTestId("alarm-subtitle")).toContainText("Kapı");  // gösterilmeyen ilk uyarıda açılır
  await expect(modal.getByTestId("queue-item").nth(2)).toHaveAttribute("aria-current", "true");
  await expect(items).toHaveCount(0);
  await modal.getByRole("button", { name: "Küçült" }).click();
  // küçük karttaki Gördüm: kalan iki uyarı iki kartta, "+N" yok
  await items.nth(1).getByRole("button", { name: "Gördüm", exact: true }).click();
  await expect.poll(() => calls.acks).toEqual(["p2"]);
  await expect(items).toHaveCount(2);
  await expect(items.nth(1)).toContainText("Kapı");
  await expect(more).toHaveCount(0);
});

test("alarm in a named area shows Alan in the window info row and on the corner card; no area no row", async ({ page }) => {
  await login(page);
  const list: FakeAlarm[] = [];
  const calls = await fake(page, list);
  const now = Date.now() / 1000;
  // uyarı (telefon) alanlı: köşe kartının bilgi satırında kameranın yanında "Alan: <ad>"
  list.push(alarm({ id: "p1", type: "phone", camera: "Kasa", firedAt: now - 4, area: "Masa 3" }));
  const toast = toastsOf(page).getByTestId("alarm-toast");
  await expect(toast).toHaveCount(1);
  await expect(toast.getByTestId("toast-meta")).toContainText(/^Kasa · Alan: Masa 3 · \d{2}:\d{2}:\d{2}/);
  await toast.getByRole("button", { name: "Gördüm", exact: true }).click();
  await expect.poll(() => calls.acks).toEqual(["p1"]);
  // alansız uyarı (area: null): satırda "Alan" yok
  list.push(alarm({ id: "p2", type: "phone", camera: "Kasa", firedAt: now - 3, area: null }));
  await expect(toast).toHaveCount(1);
  await expect(toast.getByTestId("toast-meta")).toContainText(/^Kasa · \d{2}:\d{2}:\d{2}/);
  await expect(toast.getByTestId("toast-meta")).not.toContainText("Alan");
  // küçük kartta da: ikinci uyarı alanlı gelir, ilk (en yeni) tam kart olur
  list.push(alarm({ id: "p3", type: "phone", camera: "Depo", firedAt: now - 1, area: "Kapı önü" }));
  await expect(toast).toHaveCount(2);
  await expect(toast.first().getByTestId("toast-meta")).toContainText("Depo · Alan: Kapı önü ·");
  await expect(toast.nth(1)).not.toContainText("Alan");
  await toast.first().getByRole("button", { name: "Gördüm", exact: true }).click();
  await expect.poll(() => calls.acks).toEqual(["p1", "p3"]);
  await expect(toast).toHaveCount(1);
  await toast.first().getByRole("button", { name: "Gördüm", exact: true }).click();
  await expect.poll(() => calls.acks).toEqual(["p1", "p3", "p2"]);

  // kritik alarm alanlı: pencerenin bilgi satırında "Alan" başlığı altında "Masa 3" (satırın öteki öğeleri gibi)
  list.push(alarm({ id: "h1", type: "hands_up", camera: "Tezgah kamerası", firedAt: now - 2, area: "Masa 3" }));
  const modal = modalOf(page);
  await expect(modal).toBeVisible();
  const area = modal.getByTestId("alarm-area");
  await expect(area).toHaveText("Masa 3");
  await expect(area).toHaveAttribute("title", "Masa 3");
  await expect(modal.getByRole("term").filter({ hasText: /^Alan$/ })).toBeVisible();
  // alansız kritik alarm: satır yok
  list.push(alarm({ id: "h2", type: "lying", camera: "Tezgah kamerası", firedAt: now - 1, area: null }));
  await expect(modal.getByTestId("queue-item")).toHaveCount(2);
  await modal.getByTestId("queue-item").filter({ hasText: "Yerde yatan kişi" }).click();
  await expect(modal).toHaveAttribute("data-kind", "lying");
  await expect(modal.getByTestId("alarm-area")).toHaveCount(0);
  await expect(modal).not.toContainText("Alan:");
});
