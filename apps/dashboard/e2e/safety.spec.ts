import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

const CLIP = path.resolve(__dirname, "../../ios/BantSayacUITests/ui_test_clip.mp4");

async function login(page: Page) {
  await page.goto("/notifications");
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("heading", { name: "Bildirimler" })).toBeVisible();
}

test("güvenlik: deneme alarmı şeritte görünür ve Gördüm ile kapanır; ayarlar anahtarı göstermez", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  await login(page);
  await page.getByLabel("Bot anahtarı").fill("123:E2E-GIZLI");
  await page.getByLabel("Sohbet / grup kimliği").fill("-1001");
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect(page.getByText("Anahtar kayıtlı")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("E2E-GIZLI");
  await page.getByRole("checkbox", { name: "Bildirimler açık" }).uncheck();
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();

  await page.getByRole("button", { name: "Deneme alarmı" }).click();
  const banner = page.getByRole("alert", { name: "Güvenlik alarmı" });
  await expect(banner).toContainText("Deneme alarmı", { timeout: 10_000 });
  // alarm penceresi açılır (kamerasız deneme alarmı: kayıt ve resim yok); Gördüm ile pencere ve şerit kapanır
  const modal = page.getByRole("alertdialog", { name: "Güvenlik alarmı" });
  await expect(modal.getByTestId("alarm-title")).toHaveText("DENEME ALARMI");
  await modal.getByRole("button", { name: "Gördüm", exact: true }).click();
  await expect(modal).toBeHidden();
  await expect(banner).toBeHidden();
});

test("güvenlik: kuyumcu profiliyle kamera başlar, izleniyor ve ayarlar görünür", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  await login(page);
  await page.goto("/cameras");
  await page.getByRole("radio", { name: "IP kamera" }).click();
  await page.getByLabel("Kamera markası").selectOption("custom");
  await page.getByLabel("RTSP adresi").fill(CLIP);
  await page.getByRole("textbox", { name: /^Ad/ }).fill("Tezgah kamerası");
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await page.getByTestId("source-card").filter({ hasText: "Tezgah kamerası" }).getByRole("button", { name: "Canlı sayım" }).click();
  const dialog = page.getByRole("dialog", { name: "Canlı sayımı başlat" });
  await dialog.getByRole("button", { name: "+ Kuyumcu güvenliği profili ekle" }).click();
  await dialog.getByRole("button", { name: /^Kuyumcu güvenliği/ }).click();
  await dialog.getByRole("button", { name: "Başlat", exact: true }).click();
  await expect(page.getByTestId("live-state")).toContainText("Canlı", { timeout: 30_000 });
  await expect(page.getByText("İzleniyor")).toBeVisible();

  // Deneme alarmı (yan panel): ön kayıttan olay kaydı yazılır; pencere açılır, kayıt hazır olunca video oynar
  await page.waitForTimeout(3000);                                     // ön kayıt dolsun (okuyucu, 10 kare/sn)
  const panel = page.getByRole("region", { name: "Güvenlik", exact: true });
  await panel.getByRole("button", { name: "Deneme alarmı", exact: true }).click();
  const modal = page.getByRole("alertdialog", { name: "Güvenlik alarmı" });
  await expect(modal.getByTestId("alarm-title")).toHaveText("DENEME ALARMI", { timeout: 10_000 });
  await expect(modal).toContainText("Tezgah kamerası");
  const video = modal.getByTestId("alarm-video");
  await expect(video).toBeVisible({ timeout: 20_000 });                 // sonraki yoklamada clip: true
  const src = await video.getAttribute("src");
  expect(src).toMatch(/^\/api\/live\/alarms\/[0-9a-f]{32}\/clip\.webm$/);
  // aynı adres panel vekili üzerinden: 200 video/webm; tarayıcının sarma isteği (Range) 206 ve Content-Range
  const full = await page.request.get(src!);
  expect(full.status()).toBe(200);
  expect(full.headers()["content-type"]).toBe("video/webm");
  expect(full.headers()["cache-control"]).toBe("no-store");
  const body = await full.body();
  expect([...body.subarray(0, 4)]).toEqual([0x1a, 0x45, 0xdf, 0xa3]);  // WebM (EBML) başlığı
  const part = await page.request.get(src!, { headers: { Range: "bytes=0-99" } });
  expect(part.status()).toBe(206);
  expect(part.headers()["content-range"]).toBe(`bytes 0-99/${body.length}`);
  expect(part.headers()["accept-ranges"]).toBe("bytes");
  expect((await part.body()).length).toBe(100);
  // tarayıcı kaydı vekil üzerinden çözer: süresi bilinir; zaman çizelgesinde alarm anı
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.readyState), { timeout: 15_000 }).toBeGreaterThanOrEqual(1);
  expect(await video.evaluate((v: HTMLVideoElement) => v.duration)).toBeGreaterThan(1);
  await expect(modal.getByTestId("alarm-timeline").getByRole("button", { name: /^Alarm anı · 0:0\d$/ })).toBeVisible();
  await modal.getByRole("button", { name: "Gördüm", exact: true }).click();
  await expect(modal).toBeHidden();
  await expect(page.getByRole("alert", { name: "Güvenlik alarmı" })).toBeHidden();
  await page.getByRole("button", { name: "Ayarla" }).click();
  await expect(page.getByRole("group", { name: "Güvenlik kuralları" })).toBeVisible();
  await expect(page.getByLabel("Eller yukarı süresi")).toHaveValue("3");
  await page.getByRole("button", { name: "İptal" }).click();
  await page.getByRole("button", { name: "Canlı sayımı kapat" }).click();
  await expect(page.getByText("Açık canlı sayım yok")).toBeVisible();
  await page.goto("/cameras");
  await page.getByTestId("source-card").filter({ hasText: "Tezgah kamerası" }).getByRole("button", { name: "Sil" }).click();
  await expect(page.getByTestId("source-card").filter({ hasText: "Tezgah kamerası" })).toHaveCount(0);
});
