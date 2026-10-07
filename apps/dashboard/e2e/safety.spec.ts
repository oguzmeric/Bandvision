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
  await banner.getByRole("button", { name: "Gördüm" }).click();
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
  await page.getByRole("button", { name: "Ayarla" }).click();
  await expect(page.getByRole("group", { name: "Güvenlik kuralları" })).toBeVisible();
  await expect(page.getByLabel("Eller yukarı süresi")).toHaveValue("3");
  await page.getByRole("button", { name: "İptal" }).click();
  await page.getByRole("button", { name: "Canlı sayımı kapat" }).click();
  await page.goto("/cameras");
  await page.getByTestId("source-card").filter({ hasText: "Tezgah kamerası" }).getByRole("button", { name: "Sil" }).click();
});
