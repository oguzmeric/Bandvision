import { expect, test } from "@playwright/test";

/** Durum şeridinin beslendiği uç nokta: analiz sunucusu açıkken işlemci yükü, çalışma süresi ve sürümler. */
test("sistem durumu: giriş yoksa 401, girişle analiz sunucusu 'up' ve ölçümler", async ({ request }) => {
  expect((await request.get("/api/system")).status()).toBe(401);
  const login = await request.post("/api/login", { data: { password: "e2e-test-sifresi" } });
  expect(login.ok()).toBeTruthy();
  const res = await request.get("/api/system");
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.analyzer).toBe("up");
  expect(typeof body.cpuPercent).toBe("number");
  expect(typeof body.uptimeS).toBe("number");
  expect(typeof body.analyzerVersion).toBe("string");
  expect(typeof body.panelVersion).toBe("string");
  expect(typeof body.analyzerCommit).toBe("string");
  expect(typeof body.panelCommit).toBe("string");
  // Ekran kartı: CI'da kart yok (null), geliştirme bilgisayarında ad ve yük (yük ölçülemezse null) gelir
  expect(body.gpuName === null || typeof body.gpuName === "string").toBe(true);
  expect(body.gpuPercent === null || (typeof body.gpuPercent === "number" && body.gpuPercent >= 0 && body.gpuPercent <= 100)).toBe(true);
});

test("durum şeridi: ekran kartı alanı '—' ya da yüzde olarak yazılır", async ({ page }) => {
  await page.goto("/videos");
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByTestId("status-bar")).toContainText(/Ekran kartı: (—|%\d+)/);
});
