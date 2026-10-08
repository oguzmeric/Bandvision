import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * Güvenlik arayüzü, SAHTE API ile (page.route): gerçek poz modeli ya da alarm gerekmez, hızlı ve deterministik.
 * İzleme sağlığı (Uyarı/Nöbette, neden), izlenmeyen kamera uyarısı, yapışkan şerit, deneme alarmı ve Bildirimler.
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

interface Fake {
  state: string; message: string; model: string | undefined; lastAlarmAt: number | null;
  /** Sunucunun izleme sağlığı (I2); verilmezse alan gönderilmez (eski sunucu) */
  healthy?: boolean; reason?: string | null; modelError?: string | null; unhealthyFor?: number | null;
  /** Kişi tanıma modeli (verilmezse alan gönderilmez) */
  detector?: string; detectorError?: string | null;
}

function fakeSession(f: Fake, id = "abc123", name = "Tezgah kamerası") {
  const health = f.healthy === undefined ? {} : { healthy: f.healthy, reason: f.reason ?? null, unhealthyFor: f.unhealthyFor ?? null };
  return {
    id, name, state: f.state, message: f.message, fps: 8, width: 1280, height: 720,
    counting: false, total: 0, totalOut: 0, staffIn: 0, staffOut: 0, twoWay: false, ratePerMinute: 0,
    calibrating: null, calibrationMessage: "", sourceId: null, channelId: null, profileId: null, substream: null,
    safety: { active: [{ type: "hands_up", trackId: 1, seconds: 1.5 }], lastAlarmAt: f.lastAlarmAt,
              ...(f.model ? { model: f.model } : {}), modelError: f.modelError ?? null,
              ...(f.detector ? { detector: f.detector, detectorError: f.detectorError ?? null } : {}), ...health },
    profile: {
      id: "p", name: "Kuyumcu güvenliği", roi: { x: 0.1, y: 0.1, width: 0.8, height: 0.8 }, linePosition: 0.5, direction: "down",
      diffThreshold: 30, expectedArea: 0, splitTouching: false, countMode: "safety",
      safety: { handsUp: { enabled: true, seconds: 3 }, lying: { enabled: true, seconds: 10 }, sendImage: false },
    },
  };
}

const MODEL_ERR = "Poz modeli yüklenemedi: internete ulaşılamadı (bağlantıyı kontrol edin)";

test("güvenlik paneli (sahte API): izleme nedeni, kart Uyarı/Nöbette, kamera durumu, Başlat/Sıfırla yok", async ({ page }) => {
  await login(page);
  await page.clock.install();                                 // 1 sn'lik oturum yoklaması beklenmez: saat ileri sarılır
  const f: Fake = { state: "live", message: "", model: "loading", lastAlarmAt: Date.now() / 1000 - 20,
                    healthy: false, reason: "Poz modeli yükleniyor" };
  let polls = 0;
  await page.route("**/api/live/sessions", (route) => {
    if (route.request().method() !== "GET") return route.continue();
    polls += 1;
    return route.fulfill({ json: [fakeSession(f)] });
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
  const reason = panel.getByTestId("safety-reason");
  await expect(panel.getByText("İzleniyor")).toBeVisible();
  await expect(panel.getByText("Eller yukarı: 1.5 sn")).toBeVisible();
  // güvenlikte sayaç ve Başlat/Sıfırla yok, "Ayarla" var
  await expect(page.getByRole("button", { name: "Başlat" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Sıfırla" })).toHaveCount(0);
  await expect(page.getByTestId("live-count")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Ayarla" })).toBeVisible();
  await expect(card).toContainText("Alarm");                    // son 5 dakikada alarm
  await expect(card).not.toContainText("duruyor");

  // model yükleniyor: panel nedeni yazar, kart "Nöbette" değil "Uyarı" (neden üstüne gelince)
  await expect(reason).toHaveText("Poz modeli yükleniyor…");
  await expect(card.getByTestId("watch-state")).toHaveText("Uyarı");
  await expect(card.getByTestId("watch-state")).toHaveAttribute("title", "Poz modeli yükleniyor");
  await expect(card).not.toContainText("Nöbette");
  // model yüklenemedi: sabit "internet" metni değil, sunucunun gerçek nedeni
  Object.assign(f, { model: "error", modelError: MODEL_ERR, reason: MODEL_ERR });
  await nextPoll();
  await expect(reason).toHaveText(`${MODEL_ERR} · 1 dakika sonra yeniden denenir.`);
  await expect(card.getByTestId("watch-state")).toHaveAttribute("title", MODEL_ERR);
  // ek, gerekçeyi üreten koşula göre: poz modeli yüklenirken tanıma modelinin hatası "yeniden denenir" eklemez
  const DET_ERR = "Kişi tanıma modeli yüklenemedi: Model indirilemedi (bağlantı hatası)";
  Object.assign(f, { model: "loading", modelError: null, detector: "error", detectorError: DET_ERR, reason: "Poz modeli yükleniyor" });
  await nextPoll();
  await expect(reason).toHaveText("Poz modeli yükleniyor…");
  // poz hazır, tanıma hatası: gerekçe tanıma hatası ve ek onun
  Object.assign(f, { model: "ready", reason: DET_ERR });
  await nextPoll();
  await expect(reason).toHaveText(`${DET_ERR} · 1 dakika sonra yeniden denenir.`);
  Object.assign(f, { detector: undefined, detectorError: undefined });
  // model hazır ama kare işlenemiyor (işleme hatası): yine uyarı
  Object.assign(f, { model: "ready", modelError: null, reason: "Görüntü işlenemiyor: bozuk kare", lastAlarmAt: null });
  await nextPoll();
  await expect(reason).toHaveText("Görüntü işlenemiyor: bozuk kare");
  await expect(card.getByTestId("watch-state")).toHaveText("Uyarı");
  await expect(card).not.toContainText("Nöbette");
  // kamera ölür: kart "Nöbette" demez, durumu yazar; panel başlığı kalır, nokta yeşil değildir
  Object.assign(f, { state: "error", message: "Bağlantı koptu", reason: "Kamera bağlantısı yok" });
  await nextPoll();
  await expect(card).toContainText("Hata");
  await expect(card).not.toContainText("Nöbette");
  await expect(reason).toHaveCount(0);
  await expect(panel.getByTestId("safety-state")).toHaveText("Kamera: Hata — Bağlantı koptu");
  await expect(panel.getByText("İzleniyor")).toBeVisible();     // başlık her durumda
  await expect(panel.locator("span.bg-ok-600")).toHaveCount(0);
  Object.assign(f, { state: "connecting", message: "", reason: "Kameraya bağlanılıyor" });
  await nextPoll();
  await expect(card).toContainText("Bağlanıyor…");
  await expect(panel.getByTestId("safety-state")).toHaveText("Kamera: Bağlanıyor…");
  // gerçekten izleniyor: "Nöbette", neden satırı yok
  Object.assign(f, { state: "live", healthy: true, reason: null });
  await nextPoll();
  await expect(card).toContainText("Nöbette");
  await expect(card.getByTestId("watch-state")).toHaveCount(0);
  await expect(panel.getByTestId("safety-state")).toHaveCount(0);
  await expect(reason).toHaveCount(0);
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

test("izlenmeyen güvenlik kamerası (sahte API): 60 sn sonra şeritte uyarı; şerit kaydırınca da görünür", async ({ page }) => {
  await login(page);
  await page.clock.install();
  const dead: Fake = { state: "reconnecting", message: "Görüntü kesildi", model: "ready", lastAlarmAt: null,
                       healthy: false, reason: "Kamera bağlantısı yok", unhealthyFor: 0 };
  // ikinci kamera: sunucuya göre 2 dakikadır izlenmiyor (panel yeni açıldı): hemen uyarılır
  const old: Fake = { state: "live", message: "", model: "error", modelError: MODEL_ERR, lastAlarmAt: null,
                      healthy: false, reason: MODEL_ERR, unhealthyFor: 120 };
  let list = [fakeSession(dead), fakeSession(old, "def456", "Kasa kamerası")];
  let polls = 0;
  await page.route("**/api/live/sessions", (route) => {
    polls += 1;
    return route.fulfill({ json: list });
  });
  await page.route(/\/api\/live\/alarms\?active=1$/, (route) => route.fulfill({ json: [] }));
  /** Saati `ms` ileri alır ve şeridin bir sonraki oturum yoklamasını (5 sn'de bir) bekler */
  const advance = async (ms: number) => {
    const n = polls;
    await page.clock.fastForward(ms);
    await expect.poll(async () => { if (polls === n) await page.clock.fastForward(1000); return polls; },
                      { intervals: [50] }).toBeGreaterThan(n);
  };
  await page.goto("/notifications");
  const warnings = page.getByTestId("watch-warning");
  await expect.poll(() => polls).toBeGreaterThan(0);
  await expect(warnings).toHaveCount(1);                                   // yalnızca 2 dakikalık olan
  await expect(warnings.first()).toContainText(`Güvenlik kamerası izlenmiyor: Kasa kamerası — ${MODEL_ERR}`);
  await expect(warnings.first().getByRole("link", { name: "Kamerayı aç" })).toHaveAttribute("href", "/live?s=def456");
  await advance(30_000);                                                    // ≈30 sn: tezgah kamerası henüz uyarı değil
  await expect(warnings).toHaveCount(1);
  await advance(32_000);                                                    // 60 sn aşıldı
  await expect(warnings).toHaveCount(2);
  await expect(page.getByText("Güvenlik kamerası izlenmiyor: Tezgah kamerası")).toBeVisible();
  await expect(page.getByTestId("alarm-banner")).toContainText("Kamera bağlantısı yok");
  // uyarı sarı (alarm kırmızısı değil) ve alarm şeridi rolü yok
  await expect(page.getByRole("alert", { name: "Güvenlik alarmı" })).toHaveCount(0);
  await expect(warnings.first()).toHaveClass(/bg-warn-50/);

  // şerit yapışkan: kısa pencerede sayfanın en altına inilince de görünür
  await page.setViewportSize({ width: 1400, height: 420 });
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(100);
  await expect(page.getByTestId("alarm-banner")).toBeInViewport();
  const top = await page.getByTestId("alarm-banner").evaluate((el) => el.getBoundingClientRect().top);
  expect(top).toBeLessThanOrEqual(1);

  // kameralar düzelince uyarılar kalkar
  list = [fakeSession({ ...dead, state: "live", healthy: true, reason: null }), fakeSession({ ...old, healthy: true, reason: null }, "def456", "Kasa kamerası")];
  await advance(6_000);
  await expect(warnings).toHaveCount(0);
  await expect(page.getByTestId("alarm-banner")).toHaveCount(0);
});

test("alarm şeridi yapışkan: canlı sayfada aşağı kaydırınca alarm görünür kalır", async ({ page }) => {
  await login(page);
  await page.setViewportSize({ width: 1400, height: 480 });
  const f: Fake = { state: "live", message: "", model: "ready", lastAlarmAt: Date.now() / 1000, healthy: true };
  await page.route("**/api/live/sessions", (route) => route.fulfill({ json: [fakeSession(f)] }));
  await page.route("**/api/live/sessions/abc123/stream*", (route) => route.fulfill({ contentType: "image/gif", body: GIF }));
  const now = Date.now() / 1000;
  await page.route(/\/api\/live\/alarms\?active=1$/, (route) => route.fulfill({ json: [{
    id: "z1", sessionId: "abc123", camera: "Tezgah kamerası", type: "hands_up", startedAt: now - 3, firedAt: now,
    endedAt: null, acked: false, notify: "disabled", image: false }] }));
  await page.goto("/live?s=abc123");
  const banner = page.getByRole("alert", { name: "Güvenlik alarmı" });
  await expect(banner).toContainText("Eller yukarı — Tezgah kamerası");
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(100);
  await expect(banner).toBeInViewport();
  await expect(banner.getByRole("button", { name: /^Gördüm/ })).toBeInViewport();
  // zemin düz: arkadaki içerik görünmez
  const bg = await page.getByTestId("alarm-banner").evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(bg).not.toBe("rgba(0, 0, 0, 0)");
});

test("güvenlik paneli: Deneme alarmı bu kameranın karesiyle oluşturulur ve Son alarmlar'da görünür", async ({ page }) => {
  await login(page);
  const f: Fake = { state: "live", message: "", model: "ready", lastAlarmAt: null, healthy: true };
  await page.route("**/api/live/sessions", (route) => route.fulfill({ json: [fakeSession(f)] }));
  await page.route("**/api/live/sessions/abc123/stream*", (route) => route.fulfill({ contentType: "image/gif", body: GIF }));
  const now = Date.now() / 1000;
  const made: unknown[] = [];
  const mine: Array<Record<string, unknown>> = [];
  await page.route("**/api/live/alarms/test", (route) => {
    made.push(route.request().postDataJSON());
    const a = { id: "t1", sessionId: "abc123", camera: "Tezgah kamerası", type: "test", startedAt: now, firedAt: now,
                endedAt: null, acked: false, notify: "disabled", image: true };
    mine.push(a);
    return route.fulfill({ json: a });
  });
  await page.route(/\/api\/live\/alarms\?sessionId=abc123$/, (route) => route.fulfill({ json: mine }));
  await page.route("**/api/live/alarms/t1/image.jpg", (route) => route.fulfill({ contentType: "image/gif", body: GIF }));
  await page.goto("/live?s=abc123");
  const panel = page.getByRole("region", { name: "Güvenlik", exact: true });
  await expect(panel.getByText("Henüz alarm yok.")).toBeVisible();
  await panel.getByRole("button", { name: "Deneme alarmı", exact: true }).click();
  await expect(panel.getByRole("status")).toHaveText("Deneme alarmı oluşturuldu.");
  expect(made).toEqual([{ sessionId: "abc123" }]);
  const item = panel.getByRole("listitem").filter({ hasText: "Deneme alarmı" });
  await expect(item).toHaveCount(1);                                        // hemen yeniden yüklendi
  await expect(item.locator("img")).toHaveAttribute("src", "/api/live/alarms/t1/image.jpg");
  await expect(panel.getByText("Henüz alarm yok.")).toHaveCount(0);
});

test("Bildirimler (sahte API): son gönderim hatası görünür; Anahtarı sil onayla anahtarı siler", async ({ page }) => {
  await login(page);
  const at = Date.now() / 1000 - 30;
  let cfg: Record<string, unknown> = { enabled: true, chatId: "-1001", hasToken: true,
                                       lastError: { text: "Bot anahtarı geçersiz.", at } };
  const puts: unknown[] = [];
  await page.route("**/api/live/notify", (route) => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      puts.push(body);
      cfg = { enabled: body.enabled, chatId: body.chatId, hasToken: body.token === "" ? false : cfg.hasToken, lastError: null };
    }
    return route.fulfill({ json: cfg });
  });
  await page.goto("/notifications");
  const lastError = page.getByTestId("notify-last-error");
  await expect(lastError).toHaveText(/^Son gönderim hatası \(\d{2}:\d{2}:\d{2}\): Bot anahtarı geçersiz\.$/);
  await page.getByLabel("Sohbet / grup kimliği").fill("-999");                  // kaydedilmemiş değişiklik gönderilmez

  const dialogs: string[] = [];
  page.once("dialog", (d) => { dialogs.push(d.message()); return d.dismiss(); });
  await page.getByRole("button", { name: "Anahtarı sil" }).click();
  await expect.poll(() => dialogs.length).toBe(1);
  expect(dialogs[0]).toContain("silinsin mi");
  expect(puts).toEqual([]);                                                   // vazgeçildi: istek yok
  await expect(page.getByText("Anahtar kayıtlı")).toBeVisible();

  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Anahtarı sil" }).click();
  await expect(page.getByText("Anahtar silindi.")).toBeVisible();
  expect(puts).toEqual([{ enabled: true, chatId: "-1001", token: "" }]);
  await expect(page.getByText("Anahtar kayıtlı")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Anahtarı sil" })).toHaveCount(0);
  await expect(lastError).toHaveCount(0);
});
