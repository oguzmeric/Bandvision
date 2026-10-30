import { expect, test, type Locator, type Page } from "@playwright/test";
import pkg from "../package.json";

/**
 * Panel kabuğu: soldaki yazılı, gruplu menü (spec "Menü grupları"), alttaki durum şeridi ve Hakkında sayfası.
 * Menü beklentisi uygulamadan (src/lib/nav.ts) okunmaz, burada elle yazılır: menü tasarımdan saparsa test kırılır.
 */
type Item = { label: string; href: string | null };
const GROUPS: { title: string; items: Item[] }[] = [
  { title: "İzleme", items: [
    { label: "Canlı izleme", href: "/watch" },
    { label: "Alarmlar", href: "/alarms" },
  ] },
  { title: "Analizler", items: [
    { label: "Ürün sayımı", href: "/live?tur=urun" },
    { label: "Kişi sayımı", href: "/live?tur=kisi" },
    { label: "Güvenlik alarmı (poz)", href: "/live?tur=guvenlik" },
    { label: "Yangın ve duman", href: null },
    { label: "Kalite kontrol", href: null },
    { label: "Video ile test", href: "/videos" },
    { label: "Raporlar", href: null },
  ] },
  { title: "Donanım", items: [
    { label: "Kameralar ve kayıt cihazları", href: "/cameras" },
    { label: "Cihaz ayarları", href: null },
  ] },
  { title: "Sistem", items: [
    { label: "Bildirimler", href: "/notifications" },
    { label: "Telefondan erişim", href: "/settings" },
    { label: "Lisans", href: null },
    { label: "Hakkında", href: "/about" },
  ] },
];
const LINKS = GROUPS.flatMap((g) => g.items).filter((i): i is { label: string; href: string } => i.href !== null);
const SOON = GROUPS.flatMap((g) => g.items).filter((i) => i.href === null);

async function login(page: Page, path = "/videos") {
  await page.goto(path);
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByTestId("sidebar")).toBeAttached();          // giriş formu gitti, panel kabuğu geldi
  await expect(page.locator("main h1")).toBeVisible();
}

const menu = (page: Page) => page.getByRole("navigation", { name: "Ana menü" });
const strip = (page: Page) => page.getByTestId("status-bar");

test("menü: gruplar ve öğeler tasarımdaki sırada", async ({ page }) => {
  await login(page);
  const nav = menu(page);
  const groups = await nav.locator("[data-nav-group]").evaluateAll((els) => els.map((g) => ({
    title: g.querySelector("button[aria-expanded]")?.textContent?.trim(),
    items: [...g.querySelectorAll("li")].map((li) => li.querySelector("a, button")?.getAttribute("data-label")),
  })));
  expect(groups).toEqual(GROUPS.map((g) => ({ title: g.title, items: g.items.map((i) => i.label) })));
  for (const i of LINKS) await expect(nav.getByRole("link", { name: i.label, exact: true })).toHaveAttribute("href", i.href);
});

test("menü: her öğe kendi sayfasını açar, yalnızca o öğe seçili görünür; menüdeki ad = sayfa başlığı = sekme adı", async ({ page }) => {
  await login(page);
  const nav = menu(page);
  for (const i of LINKS) {
    await nav.getByRole("link", { name: i.label, exact: true }).click();
    const url = new URL(i.href, "http://x");
    await expect.poll(() => { const u = new URL(page.url()); return u.pathname + u.search; }, { message: i.label })
      .toBe(url.pathname + url.search);
    await expect(page.locator("main h1"), i.label).toHaveText(i.label);
    await expect(page, i.label).toHaveTitle(`${i.label} · BandVision`);
    await expect(nav.getByRole("link", { name: i.label, exact: true })).toHaveAttribute("aria-current", "page");
    await expect(nav.locator("[aria-current]"), i.label).toHaveCount(1);
  }
  // süzmesiz /live (eski bağlantılar) açılır; hiçbir Analiz öğesi seçili değildir
  await page.goto("/live");
  await expect(page.locator("main h1")).toHaveText("Canlı sayım");
  await expect(page).toHaveTitle("Canlı sayım · BandVision");
  await expect(nav.locator("[aria-current]")).toHaveCount(0);
});

test("menü: gri öğeler tıklanınca 'yakında' der, sayfa değişmez", async ({ page }) => {
  await login(page, "/alarms");
  const nav = menu(page);
  const live = page.getByTestId("nav-status");
  await expect(live).toHaveCount(1);                                   // tek duyuru bölgesi, baştan var ve boş
  await expect(live).toHaveAttribute("role", "status");
  await expect(live).toHaveText("");
  for (const i of SOON) {
    const item = nav.locator(`button[data-label="${i.label}"]`);
    await expect(item).toHaveAttribute("data-soon", "");
    await expect(item).toHaveAccessibleDescription("yakında");        // ekran okuyucu tıklamadan da duyar
    await expect(item).not.toContainText("yakında");
    await item.click();
    await expect(item).toContainText("yakında");
    await expect(live).toHaveText(`${i.label}: yakında`);
    await expect(page).toHaveURL(/\/alarms$/);
    await expect(nav.locator("a", { hasText: i.label })).toHaveCount(0);   // bağlantı değil
  }
});

/** Kapalı menü grupları (bu tarayıcıda, çerezde) */
const NAV_COOKIE = "bv_nav_collapsed";
async function collapsedCookie(page: Page): Promise<unknown> {
  const c = (await page.context().cookies()).find((x) => x.name === NAV_COOKIE);
  return c ? JSON.parse(decodeURIComponent(c.value)) : null;
}
async function setCollapsed(page: Page, titles: string[]) {
  await page.context().addCookies([{ name: NAV_COOKIE, value: encodeURIComponent(JSON.stringify(titles)), url: page.url() }]);
}

test("menü: gruplar kapanır, açılır; durum tarayıcıda hatırlanır", async ({ page }) => {
  await login(page);
  const nav = menu(page);
  const group = nav.getByRole("button", { name: "Analizler", exact: true });
  await expect(group).toHaveAttribute("aria-expanded", "true");
  await group.click();
  await expect(group).toHaveAttribute("aria-expanded", "false");
  await expect(nav.getByRole("link", { name: "Ürün sayımı" })).toBeHidden();
  await expect(nav.getByRole("link", { name: "Canlı izleme" })).toBeVisible();          // diğer gruplar açık
  expect(await collapsedCookie(page)).toEqual(["Analizler"]);
  await page.reload();
  await expect(nav.getByRole("button", { name: "Analizler", exact: true })).toHaveAttribute("aria-expanded", "false");
  await expect(nav.getByRole("link", { name: "Ürün sayımı" })).toBeHidden();
  await nav.getByRole("button", { name: "Analizler", exact: true }).click();
  await expect(nav.getByRole("link", { name: "Ürün sayımı" })).toBeVisible();
  expect(await collapsedCookie(page)).toEqual([]);
});

test("menü: kapalı grup sayfa açılırken hiç açık görünmez (sunucu kapalı çizer); hidrasyon uyarısı yok", async ({ page }) => {
  await login(page, "/about");
  await setCollapsed(page, ["İzleme"]);
  // sunucunun gönderdiği HTML'de liste zaten gizli
  const html = await (await page.request.get("/about")).text();
  expect(html).toMatch(/<ul id="bv-nav-0" hidden=""/);
  // tarayıcıda her karede bak: İzleme listesi ilk boyamadan itibaren hiç görünmez
  await page.addInitScript(() => {
    const w = window as unknown as { __navSeen: string[] };
    w.__navSeen = [];
    const look = () => {
      const ul = document.getElementById("bv-nav-0");
      if (ul) w.__navSeen.push(ul.getClientRects().length > 0 && getComputedStyle(ul).display !== "none" ? "açık" : "kapalı");
      if (w.__navSeen.length < 120) requestAnimationFrame(look);
    };
    requestAnimationFrame(look);
  });
  const errors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") errors.push(m.text()); });
  await page.reload();
  const nav = menu(page);
  await expect(nav.getByRole("button", { name: "İzleme", exact: true })).toHaveAttribute("aria-expanded", "false");
  await expect.poll(() => page.evaluate(() => (window as unknown as { __navSeen: string[] }).__navSeen.length)).toBeGreaterThan(30);
  const seen = await page.evaluate(() => (window as unknown as { __navSeen: string[] }).__navSeen);
  expect(seen).not.toContain("açık");
  expect(errors.filter((e) => /hydrat|did not match/i.test(e))).toEqual([]);
});

test("menü: önceki sürümün kaydı (localStorage) bir kez çereze taşınır", async ({ page }) => {
  await login(page, "/about");
  await page.context().clearCookies({ name: NAV_COOKIE });
  await page.evaluate(() => localStorage.setItem("bv.nav.collapsed", JSON.stringify(["Donanım"])));
  await page.reload();
  const nav = menu(page);
  await expect(nav.getByRole("button", { name: "Donanım", exact: true })).toHaveAttribute("aria-expanded", "false");
  await expect.poll(() => collapsedCookie(page)).toEqual(["Donanım"]);
  expect(await page.evaluate(() => localStorage.getItem("bv.nav.collapsed"))).toBeNull();
});

test("menü: Çıkış alt kısımda, BandVision logosu üstte", async ({ page }) => {
  await login(page);
  const aside = page.getByTestId("sidebar");
  await expect(aside.getByRole("link", { name: "BandVision ana sayfa" })).toBeVisible();
  const logout = aside.getByRole("button", { name: "Çıkış" });
  await expect(logout).toBeVisible();
  const lb = (await logout.boundingBox())!, nb = (await menu(page).boundingBox())!;
  expect(lb.y).toBeGreaterThanOrEqual(nb.y + nb.height);
});

test("durum şeridi: analiz sunucusu çalışıyor, işlemci yükü; kapanınca 'kapalı' ve '—'", async ({ page }) => {
  await login(page);
  await expect(strip(page)).toContainText("Analiz sunucusu: çalışıyor");
  await expect(strip(page)).toContainText(/İşlemci %\d+/);
  await expect(strip(page)).toContainText("Ekran kartı: —");
  await expect(strip(page)).not.toContainText("Lisans");
  // 5 sn'lik yoklama: sunucu sonradan kapanınca şerit kendiliğinden değişir
  await page.route("**/api/system", (r) => r.fulfill({ json: { analyzer: "down" } }));
  await expect(strip(page)).toContainText("Analiz sunucusu: kapalı", { timeout: 12_000 });
  await expect(strip(page)).toContainText("İşlemci —");
  await expect(strip(page)).toContainText("Ekran kartı: —");
  await expect(strip(page)).not.toContainText("%");
});

test("durum şeridi: çalışan ama işlemci yükünü bilmeyen analiz sunucusu (psutil'siz ya da eski) 'çalışıyor' ve '—'", async ({ page }) => {
  await page.route("**/api/system", (r) => r.fulfill({ json: { analyzer: "up", cpuPercent: null, uptimeS: null,
    analyzerVersion: "?", analyzerCommit: "?", panelVersion: pkg.version, panelCommit: "abc1234" } }));
  await login(page);
  await expect(strip(page)).toContainText("Analiz sunucusu: çalışıyor");
  await expect(strip(page)).toContainText("İşlemci —");
  await expect(strip(page)).not.toContainText("%");
});

test("durum şeridi: açılışta kapalı ya da yetki hatası", async ({ page }) => {
  await page.route("**/api/system", (r) => r.fulfill({ json: { analyzer: "down" } }));
  await login(page);
  await expect(strip(page)).toContainText("Analiz sunucusu: kapalı");
  await expect(strip(page)).toContainText("İşlemci —");
  await page.unroute("**/api/system");
  await page.route("**/api/system", (r) => r.fulfill({ json: { analyzer: "auth" } }));
  await page.reload();
  await expect(strip(page)).toContainText("Analiz sunucusu: yetki hatası");
  await expect(strip(page)).toContainText("İşlemci —");
  await expect(strip(page)).toContainText("Ekran kartı: —");
});

test("durum şeridi alt kenarda kalır (uzun sayfa kaydırılınca da)", async ({ page }) => {
  await login(page, "/alarms");
  const vh = page.viewportSize()!.height;
  const box = async () => (await strip(page).boundingBox())!;
  expect(Math.round((await box()).y + (await box()).height)).toBe(vh);
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  expect(Math.round((await box()).y + (await box()).height)).toBe(vh);
});

test("Hakkında: panel ve analiz sunucusu sürümü + git özeti", async ({ page }) => {
  await login(page);
  const sys = await (await page.request.get("/api/system")).json();
  expect(sys.analyzer).toBe("up");
  await menu(page).getByRole("link", { name: "Hakkında", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Hakkında", level: 1 })).toBeVisible();
  await expect(page.getByTestId("about-panel")).toHaveText(`${pkg.version} (${sys.panelCommit})`);
  await expect(page.getByTestId("about-analyzer")).toHaveText(`${sys.analyzerVersion} (${sys.analyzerCommit})`);
  await expect(page).toHaveTitle(/Hakkında · BandVision/);
});

test("Hakkında: analiz sunucusu kapalıyken panel sürümü yine görünür, analiz '—'", async ({ page }) => {
  await login(page);
  await page.route("**/api/system", (r) => r.fulfill({ json: { analyzer: "down" } }));
  await page.goto("/about");
  await expect(page.getByTestId("about-panel")).toContainText(pkg.version);
  await expect(page.getByTestId("about-analyzer")).toHaveText("— (analiz sunucusu kapalı)");
});

test.describe("telefon (390×844)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("menü 'Menü' düğmesinin arkasında; içeriğin üstünde açılır, gezinince kapanır; yatay taşma yok", async ({ page }) => {
    await login(page, "/about");
    const nav = menu(page);
    const button = page.getByRole("button", { name: "Menü" });
    await expect(button).toBeVisible();
    await expect(button).toHaveAttribute("aria-expanded", "false");
    await expect(nav).toBeHidden();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

    await button.click();
    await expect(nav).toBeVisible();
    await expect(button).toHaveAttribute("aria-expanded", "true");
    // odak menünün ilk öğesinde; arkadaki içerik etkisiz, sayfa kaydırılamaz
    await expect(nav.getByRole("link", { name: "Canlı izleme", exact: true })).toBeFocused();
    await expect(page.getByTestId("sidebar")).toHaveAttribute("aria-modal", "true");
    await expect(page.locator("[data-panel-content]")).toHaveAttribute("inert", "");
    expect(await page.evaluate(() => document.documentElement.style.overflow)).toBe("hidden");
    // içeriğin üstünde: menünün ortasındaki nokta menüye ait (altındaki sayfa başlığı değil)
    const nb = (await nav.boundingBox())!;
    expect(await page.evaluate(([x, y]) => !!document.elementFromPoint(x, y)?.closest("nav[aria-label='Ana menü']"),
      [nb.x + nb.width / 2, nb.y + 20])).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

    await nav.getByRole("link", { name: "Alarmlar", exact: true }).click();
    await expect(page).toHaveURL(/\/alarms$/);
    await expect(nav).toBeHidden();
    await expect(page.getByRole("heading", { name: "Alarmlar", level: 1 })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

    // Escape ve dış tıklama da kapatır
    await button.click();
    await expect(nav).toBeVisible();
    await expect.poll(() => page.evaluate(() => !!document.activeElement?.closest("nav[aria-label='Ana menü']"))).toBe(true);
    await page.keyboard.press("Escape");
    await expect(nav).toBeHidden();
    await expect(button).toBeFocused();                                  // odak Menü düğmesine döner
    await expect(page.locator("[data-panel-content]")).not.toHaveAttribute("inert", "");
    expect(await page.evaluate(() => document.documentElement.style.overflow)).toBe("");
    await button.click();
    await page.getByTestId("menu-backdrop").click({ position: { x: 370, y: 400 } });
    await expect(nav).toBeHidden();
    await expect(button).toBeFocused();
    // Geri ile gezinme de çekmeceyi kapatır
    await button.click();
    await expect(nav).toBeVisible();
    await page.goBack();
    await expect(page).toHaveURL(/\/about$/);
    await expect(nav).toBeHidden();
    await expect(strip(page)).toContainText("Analiz sunucusu:");
  });

  test("ilk grup kapalıyken menü açılınca odak çekmecenin içinde (görünür ilk öğe)", async ({ page }) => {
    await login(page, "/about");
    await setCollapsed(page, ["İzleme"]);
    await page.reload();
    await page.getByRole("button", { name: "Menü" }).click();
    const nav = menu(page);
    await expect(nav).toBeVisible();
    await expect(nav.getByRole("button", { name: "İzleme", exact: true })).toHaveAttribute("aria-expanded", "false");
    await expect(nav.getByRole("link", { name: "Ürün sayımı", exact: true })).toBeFocused();   // Analizler'in ilk öğesi
    expect(await page.evaluate(() => !!document.activeElement?.closest("[data-testid='sidebar']"))).toBe(true);
    // tüm gruplar kapalıyken: ilk grup başlığı
    await setCollapsed(page, ["İzleme", "Analizler", "Donanım", "Sistem"]);
    await page.reload();
    await page.getByRole("button", { name: "Menü" }).click();
    await expect(nav.getByRole("button", { name: "İzleme", exact: true })).toBeFocused();
  });

  // Canlı izleme (/watch) 390 px görünümü kendi testinde (e2e/watch-ui.spec.ts: sekmeler yatay kayar, sayfa taşmaz)
  const PAGES: { path: string; ready: (page: Page) => Locator }[] = [
    { path: "/live", ready: (p) => p.locator("main h1") },
    { path: "/live?tur=kisi", ready: (p) => p.getByRole("heading", { level: 1, name: "Kişi sayımı" }) },
    { path: "/cameras", ready: (p) => p.getByRole("heading", { name: "Kaynaklar" }) },
    { path: "/alarms", ready: (p) => p.getByTestId("alarm-counts") },
    { path: "/notifications", ready: (p) => p.getByRole("button", { name: "Deneme mesajı gönder" }) },
    { path: "/settings", ready: (p) => p.getByRole("heading", { level: 1, name: "Telefondan erişim" }) },
    { path: "/videos", ready: (p) => p.getByRole("button", { name: "Analizi başlat" }) },
    { path: "/about", ready: (p) => p.getByTestId("about-analyzer").filter({ hasNotText: "Yükleniyor" }) },
  ];

  test("panel sayfalarında yatay taşma yok (390 px)", async ({ page }) => {
    await login(page, "/about");
    for (const { path, ready } of PAGES) {
      await page.goto(path);
      await expect(ready(page), path).toBeVisible();
      // yükleniyor iskeletleri gitti: ölçülen, verisi gelmiş sayfa
      await expect(page.locator("main div.animate-pulse:not(.absolute)"), path).toHaveCount(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth), path).toBeLessThanOrEqual(390);
    }
  });

  const width = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth);

  test("canlı sayım (sahte API): seçili oturum, sayaçlar ve ayar paneli 390 px'e sığar", async ({ page }) => {
    await login(page, "/about");
    const GIF = Buffer.from("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7", "base64");
    const session = (id: string, name: string, countMode: string) => ({
      id, name, state: "live", message: "", fps: 8, width: 1280, height: 720, counting: true, total: 12345, totalOut: 678,
      staffIn: 0, staffOut: 0, twoWay: countMode === "detect", ratePerMinute: 42, calibrating: null,
      calibrationMessage: "Sarı alanı ve turuncu çizgiyi ayarla, sonra boş bandı öğret; uzun bir ileti de taşmamalı.",
      sourceId: null, channelId: null, profileId: null, substream: true,
      profile: { id: `p-${id}`, name: `Profil ${name}`, roi: { x: 0.1, y: 0.1, width: 0.8, height: 0.8 }, linePosition: 0.5,
                 direction: "down", diffThreshold: 30, expectedArea: 0, splitTouching: false, countMode },
    });
    const sessions = [session("u1", "Uzun adlı bant kamerası numara bir", "blob"), session("k1", "Giriş kapısı", "detect")];
    await page.route("**/api/live/sessions", (r) => r.request().method() === "GET" ? r.fulfill({ json: sessions }) : r.continue());
    await page.route("**/api/live/sessions/*/stream*", (r) => r.fulfill({ contentType: "image/gif", body: GIF }));
    await page.route("**/api/live/sessions/*/frame.jpg*", (r) => r.fulfill({ contentType: "image/gif", body: GIF }));
    // ayar taslağı sunucuya gitmez (sahte oturum)
    await page.route("**/api/live/sessions/*/profile*", (r) => r.fulfill({ json: {} }));
    await page.route("**/api/live/sessions/*/actions", (r) => r.fulfill({ json: {} }));
    await page.route("**/api/live/alarms*", (r) => r.fulfill({ json: [] }));

    for (const [id, button, panel] of [["u1", "Kalibre", "Kalibrasyon"], ["k1", "Ayarla", "Kalibrasyon"]] as const) {
      await page.goto(`/live?s=${id}`);
      await expect(page.getByRole("region", { name: "Sayım" })).toBeVisible();
      await expect(page.getByTestId(id === "u1" ? "live-count" : "live-in")).toBeVisible();
      expect(await width(page), `${id} sayaçlar`).toBeLessThanOrEqual(390);
      await page.getByRole("button", { name: button, exact: true }).click();
      await expect(page.getByRole("region", { name: panel })).toBeVisible();
      expect(await width(page), `${id} ayar paneli`).toBeLessThanOrEqual(390);
    }
  });

  test("video ile test (sahte API): bitmiş analiz seçiliyken 390 px'e sığar", async ({ page }) => {
    await login(page, "/about");
    const now = new Date().toISOString();
    const job = {
      schema: "bantvision.analysis-job.v1", id: "j1", status: "done", createdAt: now, updatedAt: now,
      expiresAt: new Date(Date.now() + 7 * 86_400_000).toISOString(),
      video: { name: "cok_uzun_adli_bant_videosu_yumurta_hatti_2026_10_28_vardiya_1.mp4", sizeBytes: 123_456_789,
               seconds: 95, fps: 30, width: 1920, height: 1080 },
      options: { preset: "egg" }, progress: 1,
      result: { count: 120, truth: 118, errorPct: 1.69, processingFps: 87,
                calibration: { countMode: "blob", direction: "down", background: "boş bant (0–1,5 sn)", threshold: 30,
                               expectedArea: 0.0123, notes: ["Bant başta doluydu; arka plan boş bant aralığından öğrenildi."] },
                files: ["annotated.mp4", "counts.csv", "profile.json"] },
    };
    await page.route("**/api/jobs", (r) => r.fulfill({ json: [job] }));
    await page.route("**/api/jobs/j1/files/counts.csv", (r) =>
      r.fulfill({ contentType: "text/csv", body: "zaman_sn;iz;delta;toplam\n1;1;1;1\n50;2;1;60\n95;3;1;120\n" }));
    await page.route("**/api/jobs/j1/files/annotated.mp4", (r) => r.fulfill({ status: 404 }));
    await page.goto("/videos");
    const detail = page.getByTestId("job-detail");
    await expect(detail.getByRole("heading", { name: job.video.name })).toBeVisible();
    await expect(detail.getByRole("img", { name: /120/ })).toBeVisible();                     // sayım grafiği yüklendi
    await expect(page.locator("main div.animate-pulse:not(.absolute)")).toHaveCount(0);
    expect(await width(page)).toBeLessThanOrEqual(390);
  });

  test("'yakında' duyurusu ve açıklaması açık çekmecenin (kipli kutunun) içinde", async ({ page }) => {
    await login(page, "/about");
    await page.getByRole("button", { name: "Menü" }).click();
    const dialog = page.getByRole("dialog", { name: "Menü" });
    await expect(dialog).toHaveAttribute("aria-modal", "true");
    const live = dialog.getByTestId("nav-status");
    await expect(live).toHaveAttribute("role", "status");
    await expect(live).toHaveText("");
    const item = dialog.locator('button[data-label="Lisans"]');
    await expect(item).toHaveAccessibleDescription("yakında");
    await expect(dialog.locator("#bv-soon-desc")).toHaveCount(1);
    await item.click();
    await expect(live).toHaveText("Lisans: yakında");
  });
});
