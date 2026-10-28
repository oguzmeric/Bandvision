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
});
