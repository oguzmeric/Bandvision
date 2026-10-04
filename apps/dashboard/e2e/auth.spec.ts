import { expect, test } from "@playwright/test";

/** Tek şifreli giriş (DASHBOARD_PASSWORD; testte playwright.config.ts'de tanımlı). */

test("girişsiz sayfada giriş formu çıkar, API 401 döner", async ({ page, request }) => {
  await page.goto("/videos");
  await expect(page.getByRole("heading", { name: "BandVision" })).toBeVisible();   // aynı adreste giriş formu
  await expect(page.getByLabel("Şifre")).toBeVisible();
  const api = await request.get("/api/jobs");
  expect(api.status()).toBe(401);
});

test("yanlış şifre reddedilir; doğru şifreyle girilir ve çıkılır", async ({ page }) => {
  await page.goto("/login?next=%2Fvideos");
  await page.getByLabel("Şifre").fill("yanlis");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByTestId("login-error")).toHaveText("Şifre yanlış.");

  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page).toHaveURL(/\/videos$/);
  await expect(page.getByRole("heading", { name: "Videodan sayım ve doğruluk" })).toBeVisible();
  expect((await page.request.get("/api/jobs")).status()).toBe(200);

  await page.getByRole("button", { name: "Çıkış" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/videos");
  await expect(page.getByLabel("Şifre")).toBeVisible();
});

test("giriş sonrası yalnızca bu siteye ve aynı adrese gidilir", async ({ page }) => {
  await page.goto("/login?next=https%3A%2F%2Fornek.com");
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page).toHaveURL(/^http:\/\/127\.0\.0\.1:\d+\/videos$/);
});
