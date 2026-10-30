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
  await expect(page.getByRole("heading", { level: 1, name: "Video ile test" })).toBeVisible();
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

test("giriş muafiyeti yalnızca /login ve /api/login: benzer adlı yollar giriş ister", async ({ page, request }) => {
  for (const p of ["/api/loginx", "/api/login-yok"]) {
    expect((await request.get(p)).status(), p).toBe(401);
  }
  await page.goto("/loginx");
  await expect(page.getByLabel("Şifre")).toBeVisible();                                 // 404 değil: giriş formu
  await page.goto("/login");
  await expect(page.getByLabel("Şifre")).toBeVisible();
  expect((await request.post("/api/login", { data: { password: "yanlis" } })).status()).toBe(401);   // muaf: 401 "Şifre yanlış."
});

test("girişsiz sayfa giriş formuna İÇ yeniden yazmayla gider (Next kendine vekil istek açmaz): aynı kökende, göreli hedef", async ({ request }) => {
  // Vekil (dış) yeniden yazmada hedef mutlak adres olurdu ("http://localhost:3100/login…"): Next kendine HTTP isteği açar,
  // yük altında "Failed to proxy … ECONNREFUSED" ile giriş sayfası 500 dönerdi.
  for (const [path, next] of [["/watch", "%2Fwatch"], ["/live?tur=kisi", "%2Flive%3Ftur%3Dkisi"]]) {
    const res = await request.get(path, { maxRedirects: 0 });
    expect(res.status(), path).toBe(200);
    expect(res.headers()["x-middleware-rewrite"], path).toBe(`/login?next=${next}`);
    expect(await res.text(), path).toContain("Giriş · BandVision");
  }
  const rsc = await request.get("/alarms?_rsc=abc", { headers: { RSC: "1" }, maxRedirects: 0 });   // istemci tarafı gezinme
  expect(rsc.headers()["x-middleware-rewrite"]).toMatch(/^\/login\?next=%2Falarms/);
});
