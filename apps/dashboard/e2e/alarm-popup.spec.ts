import { expect, test, type Page } from "@playwright/test";

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
  const calls = { polls: 0, streams: 0 };
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
  await page.route(/\/api\/live\/alarms\/[^/]+\/image\.jpg$/, (route) => route.fulfill({ contentType: "image/gif", body: GIF }));
  await page.route(/\/api\/live\/alarms\/[^/]+\/clip\.webm$/, (route) => route.fulfill({ status: 404, json: { detail: "Olay kaydı yok." } }));
  await page.goto("/notifications");
  await expect.poll(() => calls.polls).toBeGreaterThan(0);
  return calls;
}

const modalOf = (page: Page) => page.getByRole("alertdialog", { name: "Alarm", exact: true });

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
  expect(await modal.evaluate((el) => /\p{Extended_Pictographic}/u.test(el.textContent ?? ""))).toBe(false);
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
  await fake(page, list, "404");
  list.push(alarm({ id: "h1", type: "hands_up", box: [0.1, 0.2, 0.3, 0.6] }));
  const modal = modalOf(page);
  await expect(modal.getByTestId("alarm-header")).toHaveCSS("background-color", "rgb(217, 58, 74)");
  await expect(modal.getByTestId("media-live")).toHaveAttribute("aria-pressed", "true");
  await expect(modal.getByTestId("live-error")).toHaveText("Canlı görüntü alınamıyor");
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
