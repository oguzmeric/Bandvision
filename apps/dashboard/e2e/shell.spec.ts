import { expect, test, type Page } from "@playwright/test";
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
    { label: "Bildirimler (Telegram)", href: "/notifications" },
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

test("menü: her öğe kendi sayfasını açar ve yalnızca o öğe seçili görünür", async ({ page }) => {
  await login(page);
  const nav = menu(page);
  for (const i of LINKS) {
    await nav.getByRole("link", { name: i.label, exact: true }).click();
    const url = new URL(i.href, "http://x");
    await expect.poll(() => { const u = new URL(page.url()); return u.pathname + u.search; }, { message: i.label })
      .toBe(url.pathname + url.search);
    await expect(page.locator("main h1"), i.label).toBeVisible();
    await expect(nav.getByRole("link", { name: i.label, exact: true })).toHaveAttribute("aria-current", "page");
    await expect(nav.locator("[aria-current]"), i.label).toHaveCount(1);
  }
  // süzmesiz /live (eski bağlantılar) açılır; hiçbir Analiz öğesi seçili değildir
  await page.goto("/live");
  await expect(page.locator("main h1")).toBeVisible();
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

test("menü: gruplar kapanır, açılır; durum tarayıcıda hatırlanır", async ({ page }) => {
  await login(page);
  const nav = menu(page);
  const group = nav.getByRole("button", { name: "Analizler", exact: true });
  await expect(group).toHaveAttribute("aria-expanded", "true");
  await group.click();
  await expect(group).toHaveAttribute("aria-expanded", "false");
  await expect(nav.getByRole("link", { name: "Ürün sayımı" })).toBeHidden();
  await expect(nav.getByRole("link", { name: "Canlı izleme" })).toBeVisible();          // diğer gruplar açık
  expect(await page.evaluate(() => localStorage.getItem("bv.nav.collapsed"))).toBe(JSON.stringify(["Analizler"]));
  await page.reload();
  await expect(nav.getByRole("button", { name: "Analizler", exact: true })).toHaveAttribute("aria-expanded", "false");
  await expect(nav.getByRole("link", { name: "Ürün sayımı" })).toBeHidden();
  await nav.getByRole("button", { name: "Analizler", exact: true }).click();
  await expect(nav.getByRole("link", { name: "Ürün sayımı" })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("bv.nav.collapsed"))).toBe("[]");
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
});
