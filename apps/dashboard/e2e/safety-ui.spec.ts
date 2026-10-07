import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * Güvenlik arayüzü, SAHTE API ile (page.route): gerçek poz modeli ya da alarm gerekmez, hızlı ve deterministik.
 * Gerçek uçtan uca akış e2e/safety.spec.ts'te.
 */
async function login(page: Page) {
  await page.goto("/notifications");
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("heading", { name: "Bildirimler" })).toBeVisible();
}

/** 1x1 saydam GIF: sahte canlı akış (gerçek analiz sunucusuna istek gitmesin) */
const GIF = Buffer.from("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7", "base64");

interface Fake { state: string; message: string; model: string | undefined; lastAlarmAt: number | null }

function fakeSession(f: Fake) {
  return [{
    id: "abc123", name: "Tezgah kamerası", state: f.state, message: f.message, fps: 8, width: 1280, height: 720,
    counting: false, total: 0, totalOut: 0, staffIn: 0, staffOut: 0, twoWay: false, ratePerMinute: 0,
    calibrating: null, calibrationMessage: "", sourceId: null, channelId: null, profileId: null, substream: null,
    safety: { active: [{ type: "hands_up", trackId: 1, seconds: 1.5 }], lastAlarmAt: f.lastAlarmAt, ...(f.model ? { model: f.model } : {}) },
    profile: {
      id: "p", name: "Kuyumcu güvenliği", roi: { x: 0.1, y: 0.1, width: 0.8, height: 0.8 }, linePosition: 0.5, direction: "down",
      diffThreshold: 30, expectedArea: 0, splitTouching: false, countMode: "safety",
      safety: { handsUp: { enabled: true, seconds: 3 }, lying: { enabled: true, seconds: 10 }, sendImage: false },
    },
  }];
}

test("güvenlik paneli (sahte API): model satırı, kamera durumu, Başlat/Sıfırla yok", async ({ page }) => {
  await login(page);
  await page.clock.install();                                 // 1 sn'lik oturum yoklaması beklenmez: saat ileri sarılır
  const f: Fake = { state: "live", message: "", model: "loading", lastAlarmAt: Date.now() / 1000 - 20 };
  let polls = 0;
  await page.route("**/api/live/sessions", (route) => {
    if (route.request().method() !== "GET") return route.continue();
    polls += 1;
    return route.fulfill({ json: fakeSession(f) });
  });
  /** Değişikliği görmek için bir sonraki oturum yoklamasını tetikler (zamanlayıcı kurulana kadar ileri sarmayı yineler) */
  const nextPoll = async () => {
    const n = polls;
    await expect.poll(async () => { await page.clock.fastForward(1000); return polls; }, { intervals: [50] }).toBeGreaterThan(n);
  };
  await page.route("**/api/live/sessions/abc123/stream*", (route) => route.fulfill({ contentType: "image/gif", body: GIF }));

  // yan panel alarmları yalnızca kendi kamerasını ister (sunucu süzer)
  const asked = page.waitForRequest((r) => /\/api\/live\/alarms\?sessionId=abc123$/.test(r.url()));
  await page.goto("/live?s=abc123");
  await asked;

  const panel = page.getByRole("region", { name: "Güvenlik", exact: true });
  const card = page.getByTestId("session-card");
  await expect(panel.getByText("İzleniyor")).toBeVisible();
  await expect(panel.getByText("Eller yukarı: 1.5 sn")).toBeVisible();
  // güvenlikte sayaç ve Başlat/Sıfırla yok, "Ayarla" var
  await expect(page.getByRole("button", { name: "Başlat" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Sıfırla" })).toHaveCount(0);
  await expect(page.getByTestId("live-count")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Ayarla" })).toBeVisible();
  await expect(card).toContainText("Alarm");                    // son 5 dakikada alarm
  await expect(card).not.toContainText("duruyor");

  // model satırı: yükleniyor → yüklenemedi → hazır (hiçbir şey)
  const loading = panel.getByText("Poz modeli yükleniyor…");
  const failed = panel.getByText("Poz modeli yüklenemedi — internet bağlantısını kontrol edin; 1 dakika sonra yeniden denenir.");
  await expect(loading).toBeVisible();
  await expect(failed).toHaveCount(0);
  f.model = "error";
  await nextPoll();
  await expect(failed).toBeVisible();
  await expect(loading).toHaveCount(0);
  // hazır: model satırı hiç yok. Aynı turda kamera ölür: kart "Nöbette" demez, durumu yazar; panel başlığı kalır, nokta yeşil değildir
  f.model = "ready"; f.lastAlarmAt = null; f.state = "error"; f.message = "Bağlantı koptu";
  await nextPoll();
  await expect(card).toContainText("Hata");
  await expect(card).not.toContainText("Nöbette");
  await expect(failed).toHaveCount(0);
  await expect(loading).toHaveCount(0);
  await expect(panel.getByTestId("safety-state")).toHaveText("Kamera: Hata — Bağlantı koptu");
  await expect(panel.getByText("İzleniyor")).toBeVisible();     // başlık her durumda
  await expect(panel.locator("span.bg-ok-600")).toHaveCount(0);
  f.state = "connecting"; f.message = "";
  await nextPoll();
  await expect(card).toContainText("Bağlanıyor…");
  await expect(panel.getByTestId("safety-state")).toHaveText("Kamera: Bağlanıyor…");
  f.state = "live";
  await nextPoll();
  await expect(card).toContainText("Nöbette");
  await expect(panel.getByTestId("safety-state")).toHaveCount(0);
  await expect(panel.locator("span.bg-ok-600")).toHaveCount(1);
});

interface FakeAlarm {
  id: string; sessionId: string | null; camera: string; type: string; startedAt: number; firedAt: number;
  endedAt: number | null; acked: boolean; notify: string; image: boolean;
}

test("alarm şeridi (sahte API): akış kopunca uyarı satırı, +N alarm daha, tarih, Gördüm hatası", async ({ page }) => {
  await login(page);
  await page.clock.install();                                 // 2 sn'lik yoklama beklenmez: saat ileri sarılır
  const now = Date.now() / 1000;
  const mk = (i: number, over: Partial<FakeAlarm> = {}): FakeAlarm => ({
    id: `a${i}`, sessionId: null, camera: `Kamera ${i}`, type: "test", startedAt: now - i, firedAt: now - i,
    endedAt: null, acked: false, notify: "disabled", image: false, ...over,
  });
  // sunucudaki sıra: Kamera 3 üç günlük (tarih de görünmeli)
  const alarms = [mk(1), mk(2), mk(3, { firedAt: now - 3 * 86400 }), mk(4), mk(5)];
  let feed: "ok" | "401" | "502" = "401";
  let ackFails = true;
  let polls = 0;
  /** Sıradaki yoklama cevapları elle bırakılana kadar tutulur (bayat cevap senaryosu) */
  const gates: Array<{ body: () => FakeAlarm[]; wait: Promise<void> }> = [];
  const warning = page.getByTestId("alarm-feed-warning");
  const warnedBeforePoll: boolean[] = [];                     // n. yoklamadan önce uyarı görünüyor muydu
  await page.route(/\/api\/live\/alarms\?active=1$/, async (route: Route) => {
    polls += 1;
    if (feed === "401") {
      warnedBeforePoll.push((await warning.count()) > 0);
      return route.fulfill({ status: 401, json: { error: "Giriş gerekli." } });
    }
    if (feed === "502") return route.fulfill({ status: 502, json: { detail: "Analiz sunucusuna ulaşılamadı." } });
    const held = gates.shift();
    if (held) {
      const body = held.body();                                    // cevap istek anındaki listeyle hazırlanır
      await held.wait;
      return route.fulfill({ json: body });
    }
    return route.fulfill({ json: alarms.filter((a) => !a.acked) });
  });
  await page.route(/\/api\/live\/alarms\/[^/]+\/ack$/, (route) => {
    if (ackFails) return route.fulfill({ status: 500, json: { detail: "Sunucu hatası." } });
    const id = route.request().url().split("/").at(-2);
    const a = alarms.find((x) => x.id === id);
    if (a) a.acked = true;
    return route.fulfill({ json: a ?? {} });
  });
  /** Bir sonraki yoklamayı tetikler (zamanlayıcı kurulana kadar ileri sarmayı yineler) */
  const nextPoll = async () => {
    const n = polls;
    await expect.poll(async () => { await page.clock.fastForward(2000); return polls; }, { intervals: [50] }).toBeGreaterThan(n);
  };
  await page.goto("/notifications");

  // oturum süresi dolmuş (401): ilk yoklama sayfa açılınca; iki başarısızlıkta uyarı yok, üçüncüden sonra uyarı + giriş bağlantısı
  await expect.poll(() => polls).toBe(1);
  await nextPoll();
  await nextPoll();
  await expect(warning).toContainText("Oturum süresi doldu — alarmları görmek için yeniden giriş yapın.");
  await expect(warning.getByRole("link", { name: "Giriş yap" })).toHaveAttribute("href", "/login?next=%2Fnotifications");
  expect(warnedBeforePoll.slice(0, 3)).toEqual([false, false, false]);
  expect(polls).toBeGreaterThanOrEqual(3);
  await expect(page.getByRole("alert", { name: "Güvenlik alarmı" })).toHaveCount(0);

  // analiz sunucusu yok (502): ileti değişir
  feed = "502";
  await nextPoll();
  await expect(warning).toHaveText("Alarmlar alınamıyor — analiz sunucusuna ulaşılamıyor.");

  // akış düzelir: uyarı kalkar; 5 alarmdan 3'ü + "+2 alarm daha"; üç günlük alarmda tarih de görünür
  feed = "ok";
  await nextPoll();
  const banner = page.getByRole("alert", { name: "Güvenlik alarmı" });
  await expect(banner).toBeVisible();
  await expect(warning).toHaveCount(0);
  await expect(banner).toContainText("+2 alarm daha");
  await expect(banner.getByRole("button", { name: /^Gördüm/ })).toHaveCount(3);
  await expect(banner.getByText(/— Kamera 1 · \d{2}:\d{2}:\d{2}$/)).toBeVisible();            // bugün: yalnızca saat
  await expect(banner.getByText(/— Kamera 3 · \d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}$/)).toBeVisible();   // eski: tarih + saat

  // Gördüm sunucuda başarısız: alarm kalır, kısa hata görünür
  const ack1 = banner.getByRole("button", { name: "Gördüm: Deneme alarmı — Kamera 1" });
  await ack1.click();
  await expect(banner).toContainText("Gördüm kaydedilemedi");
  await expect(ack1).toBeVisible();

  // başarılı: alarm kapanır, sıradaki görünür, hata kalkar. Onaydan ÖNCE başlayıp SONRA dönen (bayat) yoklama
  // cevabı alarmı geri getirmez; panel hemen yeni bir yoklama yapar (o da tutulurken liste doğru kalır)
  ackFails = false;
  const hold = () => {
    let release!: () => void;
    const wait = new Promise<void>((r) => { release = r; });
    return { release, wait };
  };
  const stale = hold(), fresh = hold();
  gates.push({ body: () => alarms.filter((a) => !a.acked), wait: stale.wait },      // onaydan önceki liste
             { body: () => alarms.filter((a) => !a.acked), wait: fresh.wait });     // onaydan sonraki liste
  const before = polls;
  await nextPoll();                                                  // bu yoklama tutuluyor
  await ack1.click();
  await expect(ack1).toHaveCount(0);
  await expect(banner).toContainText("+1 alarm daha");
  await expect(banner).not.toContainText("Gördüm kaydedilemedi");
  stale.release();                                                   // bayat cevap şimdi gelir: yok sayılır
  await expect.poll(() => polls).toBeGreaterThanOrEqual(before + 2); // yenisi hemen istendi (tutuluyor)
  await expect(ack1).toHaveCount(0);                                 // bayat liste alarmı geri getirmedi
  fresh.release();
  await expect(ack1).toHaveCount(0);
  await nextPoll();                                                  // sonraki yoklamalar da getirmez
  await expect(ack1).toHaveCount(0);
});
