import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

/**
 * Yangın/duman arayüzü, SAHTE API ile (page.route): gerçek model, kamera ya da alarm gerekmez. Ayar paneli (kurallar,
 * hassasiyet, alarm resmi, hariç bölge çizimi → kaydedilen profil), model "kurulu değil" satırı ve sabit uyarı, izlenmeyen
 * kamera uyarısı, alarm listesinin etiketleri/sayaçları ve yanlış alarm işaretinin geri alınması, video ile test ön ayarı
 * ve sonuç tablosu, Cihaz ayarlarındaki yangın/duman satırı.
 */
async function login(page: Page) {
  await page.goto("/notifications");
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("heading", { name: "Bildirimler" })).toBeVisible();
}

/** 1x1 saydam GIF: sahte canlı akış ve kare */
const GIF = Buffer.from("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7", "base64");
const MISSING = "Yangın/duman modeli kurulu değil.";

interface FireState { model: string; modelError: string | null; healthy: boolean; reason: string | null; unhealthyFor: number | null }

function fireSession(f: FireState) {
  return {
    id: "f1", name: "Mutfak kamerası", state: "live", message: "", fps: 5, width: 1280, height: 720,
    counting: false, total: 0, totalOut: 0, staffIn: 0, staffOut: 0, twoWay: false, ratePerMinute: 0,
    calibrating: null, calibrationMessage: "", sourceId: null, channelId: null, profileId: null, substream: null, safety: null,
    fire: { active: [{ type: "smoke", trackId: 1, seconds: 2.5 }], lastAlarmAt: null, processingError: null, lastOkAt: null, ...f },
    profile: {
      id: "pf", name: "Mutfak yangın", roi: { x: 0, y: 0, width: 1, height: 1 }, linePosition: 0.5, direction: "down",
      diffThreshold: 30, expectedArea: 0, splitTouching: false, countMode: "fire", processingWidth: 640,
      fire: { fire: { enabled: true, seconds: 3 }, smoke: { enabled: true, seconds: 8 }, sensitivity: "normal", ignoreZones: [], sendImage: false },
    },
  };
}

test("yangın/duman oturumu (sahte API): izleme nedeni ve uyarı; Ayarla'da model satırı, kurallar, hassasiyet, hariç bölge → kaydedilen profil", async ({ page }) => {
  await login(page);
  const f: FireState = { model: "error", modelError: MISSING, healthy: false, reason: MISSING, unhealthyFor: 120 };
  await page.route("**/api/live/sessions", (route) => route.request().method() === "GET"
    ? route.fulfill({ json: [fireSession(f)] }) : route.continue());
  await page.route("**/api/live/sessions/f1/stream*", (route) => route.fulfill({ contentType: "image/gif", body: GIF }));
  await page.route("**/api/live/sessions/f1/frame.jpg*", (route) => route.fulfill({ contentType: "image/gif", body: GIF }));
  await page.route(/\/api\/live\/alarms\?/, (route) => route.fulfill({ json: [] }));
  const puts: { save: boolean; body: Record<string, unknown> }[] = [];
  await page.route("**/api/live/sessions/f1/profile*", (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    puts.push({ save: route.request().url().includes("save=true"), body });
    return route.fulfill({ json: body });
  });

  // menüdeki "Yangın / duman" süzmesi: yalnızca yangın/duman oturumları
  await page.goto("/live?tur=yangin");
  await expect(page.locator("main h1")).toHaveText("Yangın / duman");
  const nav = page.getByRole("navigation", { name: "Ana menü" });
  await expect(nav.getByRole("link", { name: "Yangın / duman", exact: true })).toHaveAttribute("aria-current", "page");
  const panel = page.getByRole("region", { name: "Yangın / duman", exact: true });
  await expect(panel.getByText("Duman: 2.5 sn")).toBeVisible();
  await expect(panel.getByTestId("safety-reason")).toHaveText(`${MISSING} · 1 dakika sonra yeniden denenir.`);
  await expect(panel.getByTestId("fire-warning")).toHaveText("Erken uyarıdır; yangın algılama ve alarm sisteminin yerine geçmez.");
  const card = page.getByTestId("session-card");
  await expect(card.getByTestId("watch-state")).toHaveText("Sorun");
  await expect(card.getByTestId("watch-state")).toHaveAttribute("title", MISSING);
  // sayım yok: sayaç, Başlat/Sıfırla, CSV yok
  await expect(page.getByTestId("live-count")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Sıfırla" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "CSV indir" })).toHaveCount(0);
  // izlenmeyen yangın/duman kamerası şeritte (sunucu 120 sn diyor, eşik 60 sn)
  await expect(page.getByTestId("watch-warning")).toContainText(`Yangın/duman kamerası izlenmiyor: Mutfak kamerası — ${MISSING}`);

  // güvenlik süzmesinde yangın oturumu görünmez
  await page.goto("/live?tur=guvenlik");
  await expect(page.getByText("Henüz güvenlik alarmı yok.")).toBeVisible();
  await page.goto("/live?tur=yangin&s=f1");

  await page.getByRole("button", { name: "Ayarla", exact: true }).click();
  const settings = page.getByRole("region", { name: "Yangın/duman ayarları" });
  await expect(settings.getByTestId("fire-model")).toHaveText("Yangın/duman modeli: kurulu değil");
  await expect(settings.getByTestId("fire-warning")).toBeVisible();
  // model yüklenince satır güncellenir (oturum yoklamasıyla)
  Object.assign(f, { model: "loading", modelError: null, reason: "Yangın/duman modeli yükleniyor" });
  await expect(settings.getByTestId("fire-model")).toHaveText("Yangın/duman modeli: yükleniyor");
  Object.assign(f, { model: "ready", healthy: true, reason: null, unhealthyFor: null });
  await expect(settings.getByTestId("fire-model")).toHaveText("Yangın/duman modeli: hazır");
  await expect(page.getByTestId("watch-warning")).toHaveCount(0, { timeout: 15_000 });

  // kurallar: yangın 5 sn, duman kapalı; hassasiyet Yüksek; alarm resmi açık
  await settings.getByLabel("Yangın süresi").fill("5");
  await expect(settings.getByText("Yangın süresi: 5 sn")).toBeVisible();
  await settings.getByRole("checkbox", { name: "Duman", exact: true }).uncheck();
  await expect(settings.getByLabel("Duman süresi")).toBeDisabled();
  const sens = settings.getByRole("radiogroup", { name: "Hassasiyet" });
  await expect(sens.getByRole("radio")).toHaveText(["Düşük", "Normal", "Yüksek"]);
  await expect(sens.getByRole("radio", { name: "Normal" })).toHaveAttribute("aria-checked", "true");
  await sens.getByRole("radio", { name: "Yüksek" }).click();
  await expect(sens.getByRole("radio", { name: "Yüksek" })).toHaveAttribute("aria-checked", "true");
  await settings.getByRole("checkbox", { name: /Alarm resmini gönder/ }).check();
  // iki kural da kapalıysa uyarı
  await settings.getByRole("checkbox", { name: "Yangın", exact: true }).uncheck();
  await expect(settings.getByText("En az bir kural açık olmalı.")).toBeVisible();
  await settings.getByRole("checkbox", { name: "Yangın", exact: true }).check();

  // hariç bölgeler: iki bölge ekle, birini sil; kalan bölgenin köşesini görüntü üstünde sürükle
  const editor = page.getByTestId("zones-editor");
  await expect(editor).toBeVisible();
  await expect(settings.getByText("Hariç bölge yok: görüntünün tamamı izlenir.")).toBeVisible();
  await settings.getByRole("button", { name: "+ Bölge ekle" }).click();
  await settings.getByRole("button", { name: "+ Bölge ekle" }).click();
  await expect(settings.getByTestId("fire-zones").locator("li")).toHaveCount(2);
  await expect(editor.locator("[data-zone]")).toHaveCount(2);
  await settings.getByRole("button", { name: "Bölge 2 sil" }).click();
  await expect(editor.locator("[data-zone]")).toHaveCount(1);
  const box = (await editor.boundingBox())!;
  await page.mouse.move(box.x + 0.1 * box.width, box.y + 0.15 * box.height);   // 1. bölgenin ilk köşesi (0,1; 0,15)
  await page.mouse.down();
  await page.mouse.move(box.x + 0.05 * box.width, box.y + 0.08 * box.height, { steps: 4 });
  await page.mouse.up();
  // kenar ortasındaki + ile köşe ekle (taşınan köşe ile ikinci köşe arasındaki kenarın ortası)
  await page.mouse.click(box.x + 0.175 * box.width, box.y + 0.115 * box.height);
  await expect(settings.getByTestId("fire-zones")).toContainText("Bölge 1 · 5 köşe");

  await page.getByRole("button", { name: "Kaydet" }).click();
  await expect.poll(() => puts.filter((p) => p.save).length).toBe(1);
  const saved = puts.find((p) => p.save)!.body as { countMode: string; fire: Record<string, unknown> };
  expect(saved.countMode).toBe("fire");
  const { ignoreZones, ...rest } = saved.fire as { ignoreZones: number[][][] } & Record<string, unknown>;
  expect(rest).toEqual({ fire: { enabled: true, seconds: 5 }, smoke: { enabled: false, seconds: 8 }, sensitivity: "high", sendImage: true });
  expect(ignoreZones).toHaveLength(1);
  expect(ignoreZones[0]).toHaveLength(5);
  const [first, added, ...others] = ignoreZones[0];
  expect(first[0]).toBeCloseTo(0.05, 1);
  expect(first[1]).toBeCloseTo(0.08, 1);
  expect(added[1]).toBeGreaterThan(0.05);                                     // eklenen köşe üst kenarın üstünde
  expect(others).toEqual([[0.3, 0.15], [0.3, 0.35], [0.1, 0.35]]);
  for (const z of ignoreZones) for (const p of z) for (const c of p) expect(c >= 0 && c <= 1).toBe(true);
  await expect(page.getByRole("region", { name: "Yangın/duman ayarları" })).toHaveCount(0);
});

interface FakeAlarm {
  id: string; sessionId: string | null; camera: string; type: string; startedAt: number; firedAt: number;
  endedAt: number | null; acked: boolean; notify: string; image: boolean; clip: boolean; clipStartedAt: number | null;
  falseAlarm: boolean;
}

const mk = (id: string, type: string, camera: string, firedAt: number, over: Partial<FakeAlarm> = {}): FakeAlarm => ({
  id, sessionId: null, camera, type, startedAt: firedAt - 3, firedAt, endedAt: firedAt + 4, acked: true,
  notify: "disabled", image: true, clip: false, clipStartedAt: null, falseAlarm: false, ...over,
});

/** Analiz sunucusu gibi süzen sahte alarm listesi; yanlış alarm isteğinin gövdesi kaydedilir (`null`: gövdesiz) */
async function fakeAlarms(page: Page, all: FakeAlarm[]) {
  const asked: URLSearchParams[] = [];
  const falseBodies: Array<unknown> = [];
  await page.route(/\/api\/live\/alarms\?/, (route) => {
    const q = new URL(route.request().url()).searchParams;
    if (q.has("limit")) asked.push(q);
    const type = q.get("type");
    const out = all.filter((a) => (!type || a.type === type) && (q.get("active") !== "1" || !a.acked));
    return route.fulfill({ json: out.sort((x, y) => y.firedAt - x.firedAt) });
  });
  await page.route(/\/api\/live\/alarms\/[^/]+\/false-alarm$/, (route) => {
    const id = route.request().url().split("/").at(-2)!;
    const a = all.find((x) => x.id === id)!;
    const raw = route.request().postData();
    const body = raw ? (JSON.parse(raw) as { falseAlarm: boolean }) : null;
    falseBodies.push(body);
    a.falseAlarm = body ? body.falseAlarm : true;
    if (a.falseAlarm) a.acked = true;
    return route.fulfill({ json: a });
  });
  await page.route(/\/api\/live\/alarms\/[^/]+\/image\.jpg$/, (route) => route.fulfill({ contentType: "image/gif", body: GIF }));
  return { asked, falseBodies };
}

test("Alarmlar sayfası (sahte API): Yangın/Duman etiketleri, sayaçlar tür listesinden, tür süzgeci; yanlış alarm işareti geri alınır", async ({ page }) => {
  await login(page);
  const now = Date.now() / 1000;
  const all = [
    mk("f1", "fire", "Mutfak kamerası", now - 100, { falseAlarm: true }),
    mk("s1", "smoke", "Mutfak kamerası", now - 200),
    mk("s2", "smoke", "Depo", now - 300),
    mk("h1", "hands_up", "Kasa", now - 400),
  ];
  const calls = await fakeAlarms(page, all);
  await page.goto("/alarms");
  const rows = page.getByTestId("alarm-row");
  await expect(rows).toHaveCount(4);
  await expect(rows.nth(0).locator("td").nth(1)).toHaveText("Yangın");
  await expect(rows.nth(1).locator("td").nth(1)).toHaveText("Duman");
  await expect(rows.nth(0)).toContainText("Yanlış alarm");

  // sayaçlar: toplam, her tür (tür listesinin sırasıyla), yanlış alarm
  const counts = page.getByTestId("alarm-counts");
  expect(await counts.locator("b").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid"))))
    .toEqual(["count-total", "count-hands_up", "count-lying", "count-fire", "count-smoke", "count-test", "count-false"]);
  await expect(counts).toContainText("Yangın 1");
  await expect(counts).toContainText("Duman 2");
  for (const [k, n] of [["total", 4], ["hands_up", 1], ["lying", 0], ["fire", 1], ["smoke", 2], ["test", 0], ["false", 1]] as const) {
    await expect(page.getByTestId(`count-${k}`)).toHaveText(String(n));
  }

  // tür süzgeci: Yangın ve Duman seçenekleri; sunucuya gider
  const type = page.getByLabel("Tür", { exact: true });
  await expect(type.locator("option")).toHaveText(["Tüm türler", "Eller yukarı", "Yerde yatan kişi", "Yangın", "Duman", "Deneme alarmı"]);
  await type.selectOption("smoke");
  await expect(rows).toHaveCount(2);
  expect(calls.asked.at(-1)!.get("type")).toBe("smoke");
  await expect(page.getByTestId("count-smoke")).toHaveText("2");
  await expect(page.getByTestId("count-fire")).toHaveText("0");
  await type.selectOption("");
  await expect(rows).toHaveCount(4);

  // yanlış alarm olarak işaretli yangın alarmı: pencerede "Yangın" (büyük harfle çizilir), işaret geri alınır
  await rows.nth(0).click();
  const modal = page.getByRole("alertdialog", { name: "Güvenlik alarmı" });
  await expect(modal.getByTestId("alarm-title")).toHaveText("Yangın");
  await expect(modal.getByTestId("alarm-title")).toHaveCSS("text-transform", "uppercase");
  await expect(modal.getByTestId("alarm-state")).toContainText("Yanlış alarm");
  await expect(modal.getByRole("button", { name: "Yanlış alarm", exact: true })).toHaveCount(0);
  const asked: string[] = [];
  page.once("dialog", (d) => { asked.push(d.message()); return d.accept(); });
  await modal.getByRole("button", { name: "Yanlış alarm işaretini kaldır" }).click();
  await expect.poll(() => calls.falseBodies).toEqual([{ falseAlarm: false }]);
  expect(asked[0]).toContain("Yanlış alarm işareti kaldırılsın mı?");
  await expect(modal.getByRole("button", { name: "Yanlış alarm", exact: true })).toBeVisible();
  await expect(modal.getByTestId("alarm-state")).not.toContainText("Yanlış alarm");
  await expect(page.getByTestId("count-false")).toHaveText("0");
  // yeniden işaretlemek gövdesiz istektir
  page.once("dialog", (d) => d.accept());
  await modal.getByRole("button", { name: "Yanlış alarm", exact: true }).click();
  await expect.poll(() => calls.falseBodies).toEqual([{ falseAlarm: false }, null]);
  await expect(modal.getByRole("button", { name: "Yanlış alarm işaretini kaldır" })).toBeVisible();
  await expect(page.getByTestId("count-false")).toHaveText("1");
  await modal.getByRole("button", { name: "Kapat" }).click();
});

test("alarm penceresi ve şerit (sahte API): onaylanmamış duman alarmı 'Duman' başlığıyla açılır, şeritte kalır", async ({ page }) => {
  await login(page);
  const now = Date.now() / 1000;
  const all: FakeAlarm[] = [];
  await fakeAlarms(page, all);
  await page.route("**/api/live/alarms/*/ack", (route) => route.fulfill({ json: {} }));
  await page.goto("/notifications");
  all.push(mk("d1", "smoke", "Depo kamerası", now - 5, { acked: false, endedAt: null, sessionId: "f9" }));
  const modal = page.getByRole("alertdialog", { name: "Güvenlik alarmı" });
  await expect(modal.getByTestId("alarm-title")).toHaveText("Duman");
  await expect(modal.getByTestId("alarm-status")).toContainText("devam ediyor");
  await modal.getByRole("button", { name: "Küçült" }).click();
  const banner = page.getByTestId("alarm-banner");
  await expect(banner).toContainText("Duman — Depo kamerası");
  await expect(banner.getByRole("button", { name: "Gördüm: Duman — Depo kamerası" })).toBeVisible();
});

/** Uygulamanın uçtan uca test klibi (içeriği önemli değil: istek sahte) */
const CLIP = path.resolve(__dirname, "../../ios/BantSayacUITests/ui_test_clip.mp4");

test("video ile test (sahte API): Yangın / duman ön ayarı kural, hassasiyet ve uyarıyla; options gövdesi; sonuç tablosu etiketleri", async ({ page }) => {
  await login(page);
  const sent: Record<string, unknown>[] = [];
  const at = new Date().toISOString();
  const job = {
    schema: "bantvision.analysis-job.v1", id: "00000000-0000-4000-8000-0000000006f1", status: "done", createdAt: at, updatedAt: at,
    expiresAt: new Date(Date.now() + 7 * 86_400_000).toISOString(), progress: 1,
    video: { name: "mutfak.mp4", sizeBytes: 1024, seconds: 90, fps: 25, width: 1280, height: 720 },
    options: { preset: "fire", fire: { fire: { enabled: true, seconds: 3 }, smoke: { enabled: false }, sensitivity: "high" } },
    result: { count: 2, truth: null, errorPct: null, processingFps: 22, files: ["alarms.csv", "alarm-1.jpg"],
              alarms: [{ kind: "fire", trackId: 0, startS: 4, atS: 7, endS: 12, image: "alarm-1.jpg" },
                       { kind: "smoke", trackId: 1, startS: 61, atS: 69, endS: null, image: null }] },
  };
  await page.route("**/api/jobs", async (r) => {
    const req = r.request();
    if (req.method() !== "POST") return r.fulfill({ json: [job] });
    const body = req.postDataBuffer()?.toString("latin1") ?? "";
    const options = JSON.parse(/name="options"\r\n\r\n([\s\S]*?)\r\n--/.exec(body)![1]) as Record<string, unknown>;
    sent.push(options);
    return r.fulfill({ status: 202, json: { ...job, id: "00000000-0000-4000-8000-0000000006f2", status: "queued", progress: 0, result: undefined,
                                            video: { ...job.video, name: "ui_test_clip.mp4" }, options } });
  });
  await page.route("**/api/jobs/*/files/alarm-1.jpg", (r) => r.fulfill({ contentType: "image/gif", body: GIF }));
  await page.goto("/videos");
  await page.getByTestId("file-input").setInputFiles(CLIP);
  const preset = page.getByLabel("Ürün", { exact: true });
  await preset.selectOption("fire");
  await expect(preset.locator("option:checked")).toHaveText("Yangın / duman");
  // sayım alanları yok; kurallar, hassasiyet ve uyarı var
  for (const label of [/Doğru adet/, "Akış yönü", "Sayım yöntemi", "Kamera konumu", "Eller yukarı süresi (sn)"]) {
    await expect(page.getByLabel(label)).toHaveCount(0);
  }
  await expect(page.getByText("Alan ve sayım çizgisi")).toHaveCount(0);
  await expect(page.getByTestId("fire-warning")).toHaveText("Erken uyarıdır; yangın algılama ve alarm sisteminin yerine geçmez.");
  const fi = page.getByLabel("Yangın süresi (sn)"), sm = page.getByLabel("Duman süresi (sn)");
  await expect(fi).toHaveValue("3");
  await expect(sm).toHaveValue("8");
  const sens = page.getByLabel("Hassasiyet");
  await expect(sens.locator("option")).toHaveText(["Düşük", "Normal", "Yüksek"]);
  await expect(sens).toHaveValue("normal");
  // aralık dışı süre: istek gitmez
  await fi.fill("1");
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  await expect(page.getByTestId("upload-error")).toHaveText("Yangın süresi 2–10 sn arasında bir sayı olmalı.");
  await page.getByRole("checkbox", { name: "Yangın", exact: true }).uncheck();
  await page.getByRole("checkbox", { name: "Duman", exact: true }).uncheck();
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  await expect(page.getByTestId("upload-error")).toHaveText("En az bir kural açık olmalı.");
  expect(sent).toHaveLength(0);
  // geçerli: yangın 2,5 sn, duman kapalı, yüksek
  await page.getByRole("checkbox", { name: "Yangın", exact: true }).check();
  await fi.fill("2,5");
  await sens.selectOption("high");
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0]).toEqual({ preset: "fire", fire: { fire: { enabled: true, seconds: 2.5 }, smoke: { enabled: false }, sensitivity: "high" } });

  // biten iş: kurallar satırı ve Yangın/Duman satırları
  await page.getByTestId("job-row").filter({ hasText: "mutfak.mp4" }).first().click();
  const detail = page.getByTestId("job-detail");
  await expect(detail).toContainText("Yangın / duman profili");
  await expect(detail.getByTestId("alarm-rules")).toHaveText("Kurallar: Yangın 3 sn · Duman kapalı · Hassasiyet: Yüksek");
  const rows = detail.getByTestId("alarm-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0).locator("td").nth(1)).toHaveText("Yangın");
  await expect(rows.nth(1).locator("td").nth(1)).toHaveText("Duman");
  await expect(rows.nth(0).locator("img")).toHaveAttribute("alt", "Yangın, 00:04");
  await expect(detail.getByText("Alarm", { exact: true }).locator("..").locator("b")).toHaveText("2");
});

test("Cihaz ayarları (sahte API): Yangın/duman modeli satırı, 'kurulu değil' notu; kayıtta fire anahtarı gider", async ({ page }) => {
  await login(page);
  const CPU = { id: "cpu", kind: "cpu", name: "İşlemci" };
  const state = (choices: Record<string, string>) => ({
    gpuSupport: { available: false, reason: null }, devices: [CPU], auto: "cpu", choices,
    inUse: {
      detector: { state: "ready", device: CPU, note: null },
      pose: { state: "ready", device: CPU, note: null },
      fire: { state: "error", device: null, note: MISSING },
    },
  });
  let put: unknown = null;
  await page.route("**/api/live/devices", (route) => {
    if (route.request().method() === "PUT") {
      put = route.request().postDataJSON();
      return route.fulfill({ json: state((put as { choices: Record<string, string> }).choices) });
    }
    return route.fulfill({ json: state({ detector: "auto", pose: "auto", video: "auto", fire: "auto" }) });
  });
  await page.goto("/devices");
  await expect(page.getByText("Yangın/duman modeli", { exact: true })).toBeVisible();
  const fire = page.getByTestId("use-fire");
  await expect(fire).toBeEnabled();
  await expect(fire.locator("option")).toHaveText(["Otomatik (İşlemci)", "İşlemci"]);
  await expect(page.getByTestId("inuse-fire")).toHaveText(MISSING);
  await expect(page.getByTestId("inuse-fire")).toHaveClass(/text-nok-ink/);
  await fire.selectOption("cpu");
  await page.getByRole("button", { name: "Kaydet" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Kaydedildi." })).toBeVisible();
  expect(put).toEqual({ choices: { detector: "auto", pose: "auto", video: "auto", fire: "cpu" } });
});

test("Cihaz ayarları (sahte API): fire anahtarını bilmeyen eski sunucuda satır yok ve kayıtta gönderilmez", async ({ page }) => {
  await login(page);
  const CPU = { id: "cpu", kind: "cpu", name: "İşlemci" };
  let put: unknown = null;
  await page.route("**/api/live/devices", (route) => {
    let choices: Record<string, string> = { detector: "auto", pose: "auto", video: "auto" };
    if (route.request().method() === "PUT") {
      put = route.request().postDataJSON();
      choices = (put as { choices: Record<string, string> }).choices;
    }
    return route.fulfill({ json: { gpuSupport: { available: false, reason: null }, devices: [CPU], auto: "cpu", choices,
      inUse: { detector: { state: "ready", device: CPU, note: null }, pose: { state: "ready", device: CPU, note: null } } } });
  });
  await page.goto("/devices");
  await expect(page.getByTestId("use-video")).toBeEnabled();
  await expect(page.getByTestId("use-fire")).toHaveCount(0);
  await page.getByTestId("use-video").selectOption("cpu");
  await page.getByRole("button", { name: "Kaydet" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Kaydedildi." })).toBeVisible();
  expect(put).toEqual({ choices: { detector: "auto", pose: "auto", video: "cpu" } });
});

test("yeni analiz (sahte API): Yangın / duman türünde başlatma penceresi yalnız yangın/duman profillerini ve hazır ayarını sunar", async ({ page }) => {
  await login(page);
  const source = { id: "c1", kind: "camera", name: "Mutfak", brand: "hikvision", host: "127.0.0.1", port: 554, channel: 1, substream: true,
    customUrl: "", recorderBrand: "trassir", httpPort: null, rtspPort: null, username: "", hasPassword: false, createdAt: 0 };
  const profile = (id: string, name: string, countMode: string) => ({ id, name, roi: { x: 0, y: 0, width: 1, height: 1 }, linePosition: 0.5,
    direction: "down", diffThreshold: 30, expectedArea: 0, splitTouching: false, countMode });
  const catalog = [
    { id: "belt", title: "Bant üstü ürün", subtitle: "", available: true, presets: [{ key: "egg", name: "Yumurta" }] },
    { id: "safety", title: "Güvenlik", subtitle: "", available: true, presets: [{ key: "jeweler", name: "Kuyumcu güvenliği" }] },
    { id: "fire", title: "Yangın / duman", subtitle: "Alev ve duman için erken uyarı", available: true, presets: [{ key: "fire", name: "Yangın / duman" }] },
  ];
  await page.route("**/api/live/sources", (r) => r.fulfill({ json: [source] }));
  await page.route("**/api/live/sources/c1/snapshot*", (r) => r.fulfill({ contentType: "image/gif", body: GIF }));
  await page.route("**/api/live/sessions", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/live/catalog", (r) => r.fulfill({ json: catalog }));
  await page.route("**/api/live/profiles", (r) => r.fulfill({ json: [
    profile("p1", "Yumurta hattı", "blob"), profile("p2", "Kuyumcu", "safety"), profile("p3", "Mutfak yangın", "fire"),
  ] }));
  await page.goto("/cameras?tur=yangin");
  await expect(page.getByText("Yeni analiz:")).toContainText("Yangın / duman");
  await page.getByRole("button", { name: "Analiz başlat" }).click();
  const dialog = page.getByRole("dialog", { name: "Canlı sayımı başlat" });
  const rows = dialog.getByTestId("profile-row");
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("Mutfak yangın");
  await expect(rows.first()).toContainText("Alev / duman erken uyarısı");
  await expect(dialog.getByRole("button", { name: "+ Yangın / duman profili ekle" })).toBeVisible();
  await expect(dialog.getByText("Kuyumcu")).toHaveCount(0);
});
