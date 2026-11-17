import { expect, test, type Locator, type Page } from "@playwright/test";

/**
 * Ortadaki alarm penceresi (kritik alarm), SAHTE API ile (page.route): varsayılan canlı görüntü (oturumun işaretli akışı),
 * alarm anının yakın planı (köşe penceresi), "Alarm kaydı"na geçiş, canlı kaynağı olmayan / akışı kırık alarm, kutusu ya da
 * resmi olmayan eski kayıt ve açık alarmlar listesi (kritikler üstte; dar ekranda ‹ ›).
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
  const calls = { polls: 0, streams: 0, acks: [] as string[] };
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
