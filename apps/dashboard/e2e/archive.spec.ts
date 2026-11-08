import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

/**
 * Kayıttan izleme, GERÇEK yığın: analiz sunucusu + panel (playwright.config.ts). Kayıt cihazı yerine dosya kaynağı
 * (analiz sunucusu testte ANALYZER_ALLOW_FILE_SOURCES=1): arşiv gibi davranır, zaman ekseni dosya saniyesidir
 * (`at` = dosyadaki saniye; takvim 1970-01 = {1}, çizelge `day=0` tek aralık). Kamera seçici yalnız kayıt cihazlarını
 * listeler (dosya kaynağı bir "kamera"dır), bu yüzden oynatıcı derin bağlantıyla açılır; dosya kaynağı kanal istemez,
 * bağlantıdaki kanal yok sayılır. Gün başı epoch 0 olsun diye saat dilimi UTC.
 * Sahte API ile ayrıntılı arayüz testleri e2e/archive-ui.spec.ts'te.
 */
test.use({ timezoneId: "UTC" });

const CLIP = path.resolve(__dirname, "../../ios/BantSayacUITests/ui_test_clip.mp4");     // 18 sn, 30 kare/sn

async function login(page: Page) {
  await page.goto("/notifications");
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("heading", { name: "Bildirimler" })).toBeVisible();
}

interface View { id: string; state: string; at: number; speed: number; speeds: number[]; canExport: boolean }

test("kayıttan izleme (gerçek yığın, dosya kaynağı): akış, saat, çizelgeden sarma, duraklat, 2×, dışa aktarma pasif, çıkışta kapanır", async ({ page }) => {
  await login(page);
  const src = await (await page.request.post("/api/live/sources", { data: {
    kind: "camera", brand: "custom", customUrl: CLIP, name: "Arşiv klibi" } })).json() as { id: string };
  try {
    await page.goto(`/archive?source=${src.id}&channel=dosya&t=1`);
    await expect(page.getByRole("heading", { name: "Kayıttan izleme" })).toBeVisible();
    // seçici yalnız kayıt cihazlarını listeler: dosya kaynağı orada yok
    await expect(page.getByRole("button", { name: /Arşiv klibi/ })).toHaveCount(0);

    // MJPEG <img> panel vekilinden kare alır; durum "Oynatılıyor"
    const img = page.getByTestId("player-stream");
    await expect(img).toHaveAttribute("src", /^\/api\/live\/archive\/players\/[^/]+\/stream$/);
    const id = (await img.getAttribute("src"))!.split("/").at(-2)!;
    const view = async (): Promise<View> => (await page.request.get(`/api/live/archive/players/${id}`)).json() as Promise<View>;
    await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.naturalWidth), { timeout: 20_000 }).toBeGreaterThan(0);
    const status = page.getByTestId("player-status");
    await expect(status).toHaveText("Oynatılıyor", { timeout: 20_000 });
    const first = await view();
    expect(first.speeds).toEqual([1, 2, 4]);
    expect(first.canExport).toBe(false);
    // dosyanın günü: takvimde 1 Ocak 1970, çizelgede tek aralık
    await expect(page.getByTestId("timeline-range")).toHaveCount(1);

    // saat ilerler (sunucu ve sayfadaki gösterge)
    await expect.poll(async () => (await view()).at, { timeout: 10_000 }).toBeGreaterThan(first.at + 0.5);
    const clock = page.getByTestId("player-clock");
    const shown = await clock.textContent();
    await expect.poll(() => clock.textContent(), { timeout: 5_000 }).not.toBe(shown);

    // 10 sn ileri: konum ≈ +10
    const before = (await view()).at;
    await page.getByRole("button", { name: "10 saniye ileri" }).click();
    await expect.poll(async () => (await view()).at, { timeout: 10_000 }).toBeGreaterThanOrEqual(before + 9);
    await expect(status).toHaveText("Oynatılıyor", { timeout: 10_000 });
    // çizelgede günün başına tıklama: dosya 18 sn, çizelge 24 saat (1 piksel ≈ 1 dk), bu yüzden sol kenar = 0. saniye
    await page.getByTestId("timeline").evaluate((el) => {
      const r = el.getBoundingClientRect();
      el.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: r.left, clientY: r.top + r.height / 2 }));
    });
    await expect.poll(async () => (await view()).at, { timeout: 10_000 }).toBeLessThan(5);
    await expect(status).toHaveText("Oynatılıyor", { timeout: 10_000 });

    // duraklat: konum 1 sn boyunca sabit, son kare görünür kalır
    await page.getByRole("button", { name: "Duraklat" }).click();
    await expect(status).toHaveText("Duraklatıldı");
    await expect.poll(async () => (await view()).state).toBe("paused");
    const held = (await view()).at;
    await page.waitForTimeout(1000);                                         // sabitlik ölçümü (kısa, bilinçli)
    expect((await view()).at).toBe(held);
    expect(await img.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0);

    // sürdür ve 2×
    await page.getByRole("button", { name: "Sürdür" }).click();
    await expect(status).toHaveText("Oynatılıyor", { timeout: 10_000 });
    await page.getByLabel("Hız").selectOption("2");
    await expect(status).toHaveText("Oynatılıyor (2×)", { timeout: 10_000 });
    expect((await view()).speed).toBe(2);

    // dışa aktarma: dosya kaynağında yok (düğme pasif, Türkçe başlık; sunucu 501)
    const exp = page.getByRole("button", { name: "Dışa aktar…" });
    await expect(exp).toBeDisabled();
    await expect(exp).toHaveAttribute("title", "Bu kayıt cihazında dışa aktarma henüz desteklenmiyor.");
    const r = await page.request.post("/api/live/archive/export", { data: { sourceId: src.id, start: 0, end: 2 } });
    expect(r.status()).toBe(501);

    // sayfadan çıkış: oynatıcı kapanır (DELETE), durum isteği 404
    await page.goto("/notifications");
    await expect(page.getByRole("heading", { name: "Bildirimler" })).toBeVisible();
    await expect.poll(async () => (await page.request.get(`/api/live/archive/players/${id}`)).status(), { timeout: 10_000 }).toBe(404);
  } finally {
    await page.request.delete(`/api/live/sources/${src.id}`);
  }
});
