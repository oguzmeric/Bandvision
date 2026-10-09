import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

/** Telefondan erişim (Ayarlar). e2e'de DASHBOARD_PASSWORD tanımlıdır: ortam şifresi kipi sınanır.
 * Şifre özeti kipinin girişi/planı accessCore.test.mjs ile sınanır. Ayar dosyası geçici klasördedir (playwright.config.ts). */

async function login(page: Page, next = "/settings") {
  await page.goto(next);
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
}

test("ayarlar: ortam şifresi varken telefondan erişim açılır/kapanır; şifre yanıtta yok", async ({ page }) => {
  await page.goto("/settings");
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByText("DASHBOARD_PASSWORD")).toBeVisible();
  await page.getByRole("button", { name: "Telefondan erişimi aç" }).click();
  await expect(page.getByRole("status")).toContainText("yeniden başlatın");
  const v = await (await page.request.get("/api/access")).json();
  expect(v.enabled).toBe(true);
  expect(JSON.stringify(v)).not.toContain("e2e-test-sifresi");
  await page.getByRole("button", { name: "Erişimi kapat" }).click();
  expect((await (await page.request.get("/api/access")).json()).enabled).toBe(false);
});

test("ayarlar API: kısa şifre ve şifresiz açma reddedilir; şifre dosyada düz yazılmaz", async ({ page }) => {
  await page.goto("/settings");
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  const short = await page.request.put("/api/access", { data: { enabled: false, password: "kisa" } });
  expect(short.status()).toBe(422);
  expect((await short.json()).detail).toContain("en az 8");
  const ok = await page.request.put("/api/access", { data: { enabled: false, password: "uzun-sifre-123" } });
  expect(ok.status()).toBe(200);
  expect(JSON.stringify(await ok.json())).not.toContain("uzun-sifre-123");
});

test("erişim API'si girişsiz kapalı: okuma ve yazma 401; yanıtta özet/tuz/sır alanı yok", async ({ page, request }) => {
  expect((await request.get("/api/access")).status()).toBe(401);
  expect((await request.put("/api/access", { data: { enabled: true } })).status()).toBe(401);
  await login(page);
  await expect(page.getByText("DASHBOARD_PASSWORD")).toBeVisible();
  const v = await (await page.request.get("/api/access")).json();
  expect(Object.keys(v).sort()).toEqual(["addresses", "enabled", "envPassword", "hasPassword", "lanActive", "runner"]);
  expect(v.envPassword).toBe(true);
});

test("ayar dosyası geçici klasörde; yalnızca scrypt özeti saklanır, yeni şifre oturum sırrını yeniler", async ({ page }) => {
  await login(page);
  await expect(page.getByText("DASHBOARD_PASSWORD")).toBeVisible();
  const file = process.env.BV_E2E_ACCESS_FILE;
  expect(file, "playwright.config.ts yolu ortama koymalı").toBeTruthy();
  expect(path.resolve(file!).startsWith(path.resolve(os.tmpdir()))).toBe(true);             // repodaki .local değil
  expect(path.resolve(file!)).not.toContain(`${path.sep}.local${path.sep}`);

  const first = await page.request.put("/api/access", { data: { enabled: false, password: "uzun-sifre-123" } });
  expect(first.status()).toBe(200);
  const raw1 = fs.readFileSync(file!, "utf8");
  const a = JSON.parse(raw1) as { salt: string; hash: string; secret: string; enabled: boolean };
  expect(raw1).not.toContain("uzun-sifre-123");
  expect(a.salt).toMatch(/^[0-9a-f]{32}$/);
  expect(a.hash).toMatch(/^[0-9a-f]{64}$/);
  expect(a.secret).toMatch(/^[0-9a-f]{64}$/);

  // yalnızca kapatma/açma: şifre ve sır aynı kalır
  expect((await page.request.put("/api/access", { data: { enabled: true } })).status()).toBe(200);
  const b = JSON.parse(fs.readFileSync(file!, "utf8")) as typeof a;
  expect(b.enabled).toBe(true);
  expect(b.secret).toBe(a.secret);
  expect(b.hash).toBe(a.hash);

  // yeni şifre: özet, tuz ve oturum sırrı değişir; düz şifre yine dosyada yok
  expect((await page.request.put("/api/access", { data: { enabled: false, password: "baska-sifre-456" } })).status()).toBe(200);
  const raw3 = fs.readFileSync(file!, "utf8");
  const c = JSON.parse(raw3) as typeof a;
  expect(c.secret).not.toBe(a.secret);
  expect(c.hash).not.toBe(a.hash);
  expect(c.salt).not.toBe(a.salt);
  expect(raw3).not.toContain("baska-sifre-456");
  expect(raw3).not.toContain("uzun-sifre-123");
  expect(raw3).not.toContain("e2e-test-sifresi");
});

test("kenar çubuğunda Ayarlar bağlantısı var; ayarlar sayfası açılır", async ({ page }) => {
  await login(page, "/videos");
  await page.getByRole("link", { name: "Ayarlar" }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByRole("heading", { name: "Ayarlar" })).toBeVisible();
  await expect(page.getByText("Telefondan erişim", { exact: true })).toBeVisible();
});
