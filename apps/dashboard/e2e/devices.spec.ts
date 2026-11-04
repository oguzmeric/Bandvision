import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * Cihaz ayarları sayfası. Gerçek analiz sunucusuyla: menüden açılma, işlemci satırı, seçimin kaydedilip yenilemede kalması
 * (cihaz SAYISI denenmez: geliştirme bilgisayarı gerçek ekran kartlarını listeler, CI listelemez). Ekran kartı görünümü,
 * "Şu an" satırları, hız testi ve okuma hatası SAHTE API ile (page.route): gerçek kart ve model dosyası gerekmez.
 */
async function login(page: Page, path = "/devices") {
  await page.goto(path);
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByTestId("sidebar")).toBeAttached();
  await expect(page.locator("main h1")).toBeVisible();
}

const NVIDIA = { id: "gpu-10de-28a1", kind: "gpu", name: "NVIDIA dizüstü ekran kartı", memoryMb: 5920 };
const INTEL = { id: "gpu-8086-a7a0", kind: "gpu", name: "Intel tümleşik ekran kartı", memoryMb: 128 };
const CPU = { id: "cpu", kind: "cpu", name: "İşlemci" };
/** Canlı model durumundaki cihaz: kimlik, tür, ad (not cihazda değil durumda gelir) */
const brief = ({ id, kind, name }: { id: string; kind: string; name: string }) => ({ id, kind, name });
const MISSING = "gpu-1002-73bf";
const N4 = "Ekran kartı çalışırken hata verdi (DXGI_ERROR_DEVICE_REMOVED); işlemci kullanılıyor.";

/** GET /devices gövdesi; `over` alanları değiştirir */
function body(over: Record<string, unknown> = {}) {
  return {
    gpuSupport: { available: true, reason: null },
    devices: [CPU, NVIDIA, INTEL],
    auto: NVIDIA.id,
    choices: { detector: "auto", pose: NVIDIA.id, video: MISSING },
    inUse: {
      detector: { state: "ready", device: CPU, note: N4 },
      pose: { state: "ready", device: brief(NVIDIA), note: null },
    },
    ...over,
  };
}

test.describe("gerçek analiz sunucusu", () => {
  test("menüden açılır; işlemci satırı var; seçim kaydedilir, yenilemede kalır", async ({ page }) => {
    await login(page, "/videos");
    await page.getByRole("navigation", { name: "Ana menü" }).getByRole("link", { name: "Cihaz ayarları", exact: true }).click();
    await expect(page).toHaveURL(/\/devices$/);
    await expect(page.locator("main h1")).toHaveText("Cihaz ayarları");
    await expect(page).toHaveTitle("Cihaz ayarları · BandVision");
    await expect(page.getByText("Ürün sayımı model kullanmaz, işlemcide çalışır.")).toBeVisible();

    const cpu = page.getByTestId("device-row-cpu");
    await expect(cpu).toContainText("İşlemci");
    await expect(cpu).toContainText("—");                                    // işlemcinin belleği yok
    await expect(cpu.getByRole("button", { name: "İşlemci: hız testi", exact: true })).toBeEnabled();
    const save = page.getByRole("button", { name: "Kaydet" });
    const video = page.getByTestId("use-video");
    await expect(video).toBeEnabled();                                       // ayarlar okundu
    await expect(save).toBeDisabled();                                       // değişiklik yok

    await video.selectOption("cpu");
    await expect(save).toBeEnabled();
    await save.click();
    await expect(page.getByRole("status").filter({ hasText: "Kaydedildi." })).toBeVisible();
    await expect(save).toBeDisabled();

    await page.reload();
    await expect(page.getByTestId("use-video")).toHaveValue("cpu");
    await expect(page.getByTestId("use-video").locator("option:checked")).toHaveText("İşlemci");

    // Sonraki testler etkilenmesin: "Otomatik"e geri
    await page.getByTestId("use-video").selectOption("auto");
    await page.getByRole("button", { name: "Kaydet" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Kaydedildi." })).toBeVisible();
    await page.reload();
    await expect(page.getByTestId("use-video")).toHaveValue("auto");
  });

  test("kaydedilmemiş seçimle menüden ayrılırken sorulur; vazgeçilirse sayfada kalınır", async ({ page }) => {
    await login(page);
    await expect(page.getByTestId("use-pose")).toBeEnabled();
    const before = await page.getByTestId("use-pose").inputValue();
    await page.getByTestId("use-pose").selectOption(before === "cpu" ? "auto" : "cpu");
    const nav = page.getByRole("navigation", { name: "Ana menü" });

    const asked: string[] = [];
    page.once("dialog", (d) => { asked.push(d.message()); void d.dismiss(); });
    await nav.getByRole("link", { name: "Hakkında", exact: true }).click();
    expect(asked).toEqual(["Kaydedilmedi, çıkılsın mı?"]);
    await expect(page).toHaveURL(/\/devices$/);

    page.once("dialog", (d) => { void d.accept(); });
    await nav.getByRole("link", { name: "Hakkında", exact: true }).click();
    await expect(page).toHaveURL(/\/about$/);
  });
});

test.describe("sahte API", () => {
  test("ekran kartı görünümü: seçenekler, 'Şu an' satırları, uyarı rengi, bulunamayan kart; kayıt gövdesi", async ({ page }) => {
    let put: unknown = null;
    await page.route("**/api/live/devices", async (route: Route) => {
      if (route.request().method() === "PUT") {
        put = route.request().postDataJSON();
        const choices = (put as { choices: Record<string, string> }).choices;
        await route.fulfill({ json: body({ choices }) });
        return;
      }
      await route.fulfill({ json: body() });
    });
    await login(page);

    // Cihazlar tablosu: ad, tür, bellek
    await expect(page.getByTestId(`device-row-${NVIDIA.id}`)).toContainText(NVIDIA.name);
    await expect(page.getByTestId(`device-row-${NVIDIA.id}`)).toContainText("Ekran kartı");
    await expect(page.getByTestId(`device-row-${NVIDIA.id}`)).toContainText("5920 MB");
    await expect(page.getByTestId(`device-row-${INTEL.id}`)).toContainText("128 MB");
    await expect(page.getByTestId("gpu-support")).toHaveCount(0);                      // destek var: üst satır yok

    // Seçenekler: Otomatik (kartın adı), İşlemci, her kart; kayıtlı ama listede olmayan kart en sonda
    const detector = page.getByTestId("use-detector");
    await expect(detector.locator("option")).toHaveText([`Otomatik (${NVIDIA.name})`, "İşlemci", NVIDIA.name, INTEL.name]);
    await expect(detector).toHaveValue("auto");
    await expect(page.getByTestId("use-pose")).toHaveValue(NVIDIA.id);
    const video = page.getByTestId("use-video");
    await expect(video.locator("option")).toHaveText([`Otomatik (${NVIDIA.name})`, "İşlemci", NVIDIA.name, INTEL.name,
      `Bulunamayan ekran kartı (${MISSING})`]);
    await expect(video).toHaveValue(MISSING);

    // "Şu an": işlemciye düşüş notu uyarı renginde, sağlam kart sade
    const dLine = page.getByTestId("inuse-detector");
    await expect(dLine).toHaveText(`Şu an: İşlemci — ${N4}`);
    await expect(dLine).toHaveClass(/text-nok-ink/);
    const pLine = page.getByTestId("inuse-pose");
    await expect(pLine).toHaveText(`Şu an: ${NVIDIA.name}`);
    await expect(pLine).not.toHaveClass(/text-nok-ink/);
    await expect(page.getByTestId("inuse-video")).toHaveCount(0);                      // video satırında "Şu an" yok

    // Kaydet: yalnız değişince açılır; üç anahtar da gider
    const save = page.getByRole("button", { name: "Kaydet" });
    await expect(save).toBeDisabled();
    await detector.selectOption(INTEL.id);
    await expect(save).toBeEnabled();
    await detector.selectOption("auto");                                               // eski değere dönünce yine kapalı
    await expect(save).toBeDisabled();
    await page.getByTestId("use-pose").selectOption("cpu");
    await save.click();
    await expect(page.getByRole("status").filter({ hasText: "Kaydedildi." })).toBeVisible();
    expect(put).toEqual({ choices: { detector: "auto", pose: "cpu", video: MISSING } });
    await expect(save).toBeDisabled();
  });

  test("yükleniyor ve hata satırları; ekran kartı desteği yoksa neden satırı", async ({ page }) => {
    const reason = "Ekran kartı desteği yalnız Windows'ta var";
    await page.route("**/api/live/devices", (route) => route.fulfill({
      json: body({
        gpuSupport: { available: false, reason },
        devices: [CPU], auto: "cpu", choices: { detector: "auto", pose: "auto", video: "auto" },
        inUse: {
          detector: { state: "loading", device: CPU, note: null },
          pose: { state: "error", device: null, note: "Poz modeli açılamadı: model dosyası bulunamadı." },
        },
      }),
    }));
    await login(page);
    await expect(page.getByTestId("gpu-support")).toHaveText(reason);
    await expect(page.getByTestId("device-row-cpu")).toBeVisible();
    await expect(page.getByTestId("use-detector").locator("option")).toHaveText(["Otomatik (İşlemci)", "İşlemci"]);
    await expect(page.getByTestId("inuse-detector")).toHaveText("Şu an: İşlemci (yeni cihaz yükleniyor…)");
    await expect(page.getByTestId("inuse-pose")).toHaveText("Poz modeli açılamadı: model dosyası bulunamadı.");
    await expect(page.getByTestId("inuse-pose")).toHaveClass(/text-nok-ink/);
  });

  test("hız testi: çalışırken 'Ölçülüyor…' ve öteki düğmeler kapalı; sonuç, işlemciye düşüş notu ve hata satırda", async ({ page }) => {
    await page.route("**/api/live/devices", (route) => route.fulfill({ json: body() }));
    const asked: string[] = [];
    let release: () => void = () => undefined;
    let gate = new Promise<void>((r) => { release = r; });
    let mode: "ok" | "note" | "busy" = "ok";
    await page.route("**/api/live/devices/benchmark", async (route) => {
      const { device } = route.request().postDataJSON() as { device: string };
      asked.push(device);
      await gate;
      if (mode === "busy") {
        await route.fulfill({ status: 409, json: { detail: "Başka bir hız testi sürüyor; bitince yeniden deneyin." } });
        return;
      }
      const used = mode === "note"
        ? { ...CPU, note: "Ekran kartında açılamadı (x); işlemci kullanılıyor." }
        : { id: device, kind: "gpu", name: NVIDIA.name, note: null };
      await route.fulfill({ json: { device: used, msPerFrame: 12.34, loadS: 2.04 } });
    });
    await login(page);

    const nv = page.getByTestId(`device-row-${NVIDIA.id}`);
    const cpu = page.getByTestId("device-row-cpu");
    await nv.getByRole("button", { name: `${NVIDIA.name}: hız testi`, exact: true }).click();
    await expect(nv.getByRole("button", { name: `${NVIDIA.name}: ölçülüyor`, exact: true })).toBeDisabled();
    await expect(cpu.getByRole("button", { name: "İşlemci: hız testi", exact: true })).toBeDisabled();
    await expect(page.getByTestId(`device-row-${INTEL.id}`).getByRole("button", { name: `${INTEL.name}: hız testi`, exact: true })).toBeDisabled();
    release();
    await expect(page.getByTestId(`bench-${NVIDIA.id}`)).toHaveText("12.3 ms/kare (2.0 sn açılış)");
    await expect(page.getByTestId(`bench-${NVIDIA.id}`)).not.toHaveClass(/text-nok-ink/);
    await expect(cpu.getByRole("button", { name: "İşlemci: hız testi", exact: true })).toBeEnabled();
    expect(asked).toEqual([NVIDIA.id]);

    // kart işlemciye düştü: sayı yerine not, uyarı renginde
    gate = new Promise<void>((r) => { release = r; }); release(); mode = "note";
    await page.getByTestId(`device-row-${INTEL.id}`).getByRole("button", { name: `${INTEL.name}: hız testi`, exact: true }).click();
    await expect(page.getByTestId(`bench-${INTEL.id}`)).toHaveText("Ekran kartında açılamadı (x); işlemci kullanılıyor.");
    await expect(page.getByTestId(`bench-${INTEL.id}`)).toHaveClass(/text-nok-ink/);

    // başka test sürüyor (409): hata o satırda
    mode = "busy";
    await cpu.getByRole("button", { name: "İşlemci: hız testi", exact: true }).click();
    await expect(page.getByTestId("bench-cpu")).toHaveText("Başka bir hız testi sürüyor; bitince yeniden deneyin.");
    await expect(page.getByTestId("bench-cpu")).toHaveClass(/text-nok-ink/);
    await expect(cpu.getByRole("button", { name: "İşlemci: hız testi", exact: true })).toBeEnabled();
  });

  test("okuma hatası (502): hata satırı, Kaydet kapalı; sunucu dönünce sayfa kendiliğinden toparlanır", async ({ page }) => {
    let down = true;
    await page.route("**/api/live/devices", (route) => down
      ? route.fulfill({ status: 502, json: { detail: "Analiz sunucusuna ulaşılamıyor." } })
      : route.fulfill({ json: body() }));
    await login(page);
    const error = page.getByRole("status").filter({ hasText: "Analiz sunucusuna ulaşılamıyor." });
    await expect(error).toBeVisible();
    await expect(page.getByRole("button", { name: "Kaydet" })).toBeDisabled();
    await expect(page.getByTestId("use-detector")).toBeDisabled();
    await expect(page.getByTestId("device-row-cpu")).toHaveCount(0);

    down = false;                                                      // 5 sn'lik yeniden deneme okur
    await expect(page.getByTestId("device-row-cpu")).toBeVisible({ timeout: 20_000 });
    await expect(error).toHaveCount(0);
    await expect(page.getByTestId("use-detector")).toBeEnabled();
    await expect(page.getByTestId("inuse-pose")).toHaveText(`Şu an: ${NVIDIA.name}`);
  });

  /** Canlı model durumu: "loading" eski cihazda hizmet verirken, "ready" yeni (ekran kartı) cihazda */
  const detectorIn = (phase: "loading" | "ready") => phase === "loading"
    ? { state: "loading", device: CPU, note: null }
    : { state: "ready", device: brief(NVIDIA), note: null };
  const poseIn = { state: "ready", device: brief(NVIDIA), note: null };
  const fixture = (phase: "loading" | "ready", over: Record<string, unknown> = {}) =>
    body({ choices: { detector: "auto", pose: NVIDIA.id, video: "auto" }, inUse: { detector: detectorIn(phase), pose: poseIn }, ...over });

  test("yükleme yenilemesi: 'Şu an' satırı hazır olunca güncellenir, kullanıcının seçimi ve Kaydet bozulmaz, hazır olunca istekler durur", async ({ page }) => {
    let phase: "loading" | "ready" = "loading";
    let gets = 0;
    await page.route("**/api/live/devices", (route) => { gets += 1; return route.fulfill({ json: fixture(phase) }); });
    await login(page);
    await expect(page.getByTestId("inuse-detector")).toHaveText("Şu an: İşlemci (yeni cihaz yükleniyor…)");

    await page.getByTestId("use-video").selectOption(INTEL.id);                       // kullanıcı bu sırada seçim yaptı
    phase = "ready";                                                                  // model yeni cihaza geçti
    await expect(page.getByTestId("inuse-detector")).toHaveText(`Şu an: ${NVIDIA.name}`);
    await expect(page.getByTestId("use-video")).toHaveValue(INTEL.id);                // yenileme seçimi ezmedi
    await expect(page.getByRole("button", { name: "Kaydet" })).toBeEnabled();

    const after = gets;                                                               // hazır: yenileme durmalı
    await page.waitForTimeout(5000);
    expect(gets - after).toBeLessThanOrEqual(1);
  });

  test("yenileme hatası: analiz sunucusu gidince okuma hatası görünür (sonsuza dek 'yükleniyor' demez); dönünce toparlanır", async ({ page }) => {
    let mode: "loading" | "down" | "ready" = "loading";
    await page.route("**/api/live/devices", (route) => mode === "down"
      ? route.fulfill({ status: 502, json: { detail: "Analiz sunucusuna ulaşılamıyor." } })
      : route.fulfill({ json: fixture(mode) }));
    await login(page);
    await expect(page.getByTestId("inuse-detector")).toHaveText("Şu an: İşlemci (yeni cihaz yükleniyor…)");

    mode = "down";
    const error = page.getByRole("status").filter({ hasText: "Analiz sunucusuna ulaşılamıyor." });
    await expect(error).toBeVisible();                                                // 2 sn'lik yenileme hatayı yüzeye çıkardı
    await expect(page.getByRole("button", { name: "Kaydet" })).toBeDisabled();
    await expect(page.getByTestId("use-video")).toBeDisabled();

    mode = "ready";                                                                   // 5 sn'lik yeniden deneme okur
    await expect(page.getByTestId("inuse-detector")).toHaveText(`Şu an: ${NVIDIA.name}`, { timeout: 20_000 });
    await expect(error).toHaveCount(0);
    await expect(page.getByTestId("use-video")).toBeEnabled();
  });

  test("eski yanıt atılır: kayıttan önce başlayıp sonra gelen yavaş okuma, yeni durumu eski 'yükleniyor'la ezmez", async ({ page }) => {
    let phase: "loading" | "ready" = "loading";
    let hold: Promise<void> | null = null;
    let held = false;
    await page.route("**/api/live/devices", async (route) => {
      if (route.request().method() === "PUT") {
        phase = "ready";
        const choices = (route.request().postDataJSON() as { choices: Record<string, string> }).choices;
        await route.fulfill({ json: fixture("ready", { choices }) });
        return;
      }
      const snapshot = fixture(phase);                                                // istek anındaki durum
      const gate = hold;
      if (gate) { hold = null; held = true; await gate; }
      await route.fulfill({ json: snapshot });
    });
    await login(page);
    await expect(page.getByTestId("inuse-detector")).toHaveText("Şu an: İşlemci (yeni cihaz yükleniyor…)");

    let open: () => void = () => undefined;
    hold = new Promise<void>((r) => { open = r; });
    await expect.poll(() => held, { timeout: 10_000 }).toBe(true);                    // sıradaki yenileme yolda ve bekletiliyor
    await page.getByTestId("use-video").selectOption(INTEL.id);
    await page.getByRole("button", { name: "Kaydet" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Kaydedildi." })).toBeVisible();
    await expect(page.getByTestId("inuse-detector")).toHaveText(`Şu an: ${NVIDIA.name}`);

    open();                                                                           // eski yanıt şimdi gelir
    await page.waitForTimeout(700);
    await expect(page.getByTestId("inuse-detector")).toHaveText(`Şu an: ${NVIDIA.name}`);
    await expect(page.getByTestId("use-video")).toHaveValue(INTEL.id);
  });

  test("kayıt sürerken seçimler kapalıdır, bitince açılır", async ({ page }) => {
    let open: () => void = () => undefined;
    const gate = new Promise<void>((r) => { open = r; });
    await page.route("**/api/live/devices", async (route) => {
      if (route.request().method() === "PUT") {
        await gate;
        const choices = (route.request().postDataJSON() as { choices: Record<string, string> }).choices;
        await route.fulfill({ json: fixture("ready", { choices }) });
        return;
      }
      await route.fulfill({ json: fixture("ready") });
    });
    await login(page);
    await page.getByTestId("use-pose").selectOption("cpu");
    await page.getByRole("button", { name: "Kaydet" }).click();
    for (const k of ["detector", "pose", "video"]) await expect(page.getByTestId(`use-${k}`)).toBeDisabled();
    await expect(page.getByRole("button", { name: "Kaydet" })).toBeDisabled();
    open();
    await expect(page.getByRole("status").filter({ hasText: "Kaydedildi." })).toBeVisible();
    for (const k of ["detector", "pose", "video"]) await expect(page.getByTestId(`use-${k}`)).toBeEnabled();
    await expect(page.getByTestId("use-pose")).toHaveValue("cpu");
  });

  test("aynı adlı iki ekran kartı numaralanır: seçenekler, 'Otomatik (…)', tablo adı ve hız testi düğmesinin adı", async ({ page }) => {
    const twin1 = { id: "gpu-10de-2684", kind: "gpu", name: "NVIDIA ekran kartı", memoryMb: 24000 };
    const twin2 = { ...twin1, id: "gpu-10de-2684-2" };
    await page.route("**/api/live/devices", (route) => route.fulfill({
      json: body({ devices: [CPU, twin1, twin2], auto: twin2.id, choices: { detector: "auto", pose: twin1.id, video: "auto" },
                   inUse: { detector: detectorIn("ready"), pose: { state: "idle", device: null, note: null } } }),
    }));
    await login(page);
    await expect(page.getByTestId("use-pose").locator("option")).toHaveText(
      ["Otomatik (NVIDIA ekran kartı (2))", "İşlemci", "NVIDIA ekran kartı (1)", "NVIDIA ekran kartı (2)"]);
    await expect(page.getByTestId(`device-row-${twin1.id}`)).toContainText("NVIDIA ekran kartı (1)");
    await expect(page.getByTestId(`device-row-${twin2.id}`)).toContainText("NVIDIA ekran kartı (2)");
    await expect(page.getByRole("button", { name: "NVIDIA ekran kartı (1): hız testi", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "NVIDIA ekran kartı (2): hız testi", exact: true })).toBeVisible();
    await expect(page.getByTestId("inuse-pose")).toHaveText("Şu an: kullanılmıyor");
  });
});
