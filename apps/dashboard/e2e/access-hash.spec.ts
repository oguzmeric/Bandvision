import { expect, test } from "@playwright/test";
import { newSecret } from "../src/lib/accessCore.mjs";
import { expectedToken, sessionToken } from "../src/lib/session";

/**
 * Telefondan erişimin ŞİFRE ÖZETİ kipi (ikinci panel, bağlantı noktası 3101; playwright.config.ts). Bu sunucuda
 * DASHBOARD_PASSWORD YOK: başlatıcının vereceği PANEL_PASSWORD_HASH/SALT/SESSION_SECRET ortamdadır. Merkezî değişmez:
 * şifre kipi açıkken şifresiz/sahte/başka kipin çerezi hiçbir sayfaya ve API'ye giremez.
 */
const PASSWORD = "ozet-kipi-test-sifresi";           // playwright.config.ts HASH_MODE_PASSWORD ile aynı
test.use({ baseURL: "http://127.0.0.1:3101" });

const cookieHeader = (value: string) => ({ cookie: `bv_session=${value}` });

test("özet kipi, girişsiz: sayfa giriş formuna yeniden yazılır; API okuma ve yazma 401", async ({ page, request }) => {
  await page.goto("/watch");
  await expect(page.getByRole("heading", { name: "BandVision" })).toBeVisible();
  await expect(page.getByLabel("Şifre")).toBeVisible();
  await expect(page.getByRole("heading", { name: "İzleme" })).toHaveCount(0);
  for (const p of ["/api/jobs", "/api/access", "/api/live/health"]) {
    expect((await request.get(p)).status(), p).toBe(401);
  }
  expect((await request.put("/api/access", { data: { enabled: true } })).status()).toBe(401);
  expect((await request.post("/api/logout")).status()).toBe(401);
});

test("özet kipi: yanlış şifre 401 ve çerez yok; sınırlar (4 KB gövde, 256 karakter) 400, kısıta sayılmaz", async ({ page, request }) => {
  const bad = await request.post("/api/login", { data: { password: "yanlis-sifre" } });
  expect(bad.status()).toBe(401);
  expect(bad.headers()["set-cookie"]).toBeUndefined();
  const empty = await request.post("/api/login", { data: { password: "" } });
  expect(empty.status()).toBe(401);

  expect((await request.post("/api/login", { data: { password: "a".repeat(257) } })).status()).toBe(400);
  expect((await request.post("/api/login", { data: { password: "a".repeat(5000) } })).status()).toBe(400);
  expect((await request.post("/api/login", { data: { password: "x", dolgu: "y".repeat(5000) } })).status()).toBe(400);
  expect((await request.post("/api/login", { data: Buffer.from("{bozuk json"), headers: { "content-type": "application/json" } })).status()).toBe(400);

  await page.goto("/login?next=%2Fwatch");
  await page.getByLabel("Şifre").fill("yine-yanlis");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByTestId("login-error")).toHaveText("Şifre yanlış.");
});

test("özet kipi: doğru şifre oturum çerezi verir ve /watch açılır; çerez HMAC, API'ler açılır, özet/sır sızmaz", async ({ page }) => {
  await page.goto("/watch");
  await page.getByLabel("Şifre").fill(PASSWORD);
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page).toHaveURL(/\/watch$/);
  await expect(page.getByRole("heading", { name: "İzleme" })).toBeVisible();

  const cookie = (await page.context().cookies()).find((c) => c.name === "bv_session");
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.value).toMatch(/^[0-9a-f]{64}$/);
  expect(cookie?.value).not.toBe(await sessionToken(PASSWORD));                  // ortam kipinin belirteci değil
  expect(cookie?.value).not.toContain(PASSWORD);

  expect((await page.request.get("/api/jobs")).status()).toBe(200);
  const acc = await page.request.get("/api/access");
  expect(acc.status()).toBe(200);
  const text = await acc.text();
  expect(Object.keys(JSON.parse(text)).sort()).toEqual(["addresses", "enabled", "envPassword", "hasPassword", "lanActive", "runner"]);
  expect(JSON.parse(text).envPassword).toBe(false);
  expect(text).not.toContain(PASSWORD);
  await expect(page.getByRole("button", { name: "Çıkış" })).toBeVisible();      // canLogout: özet kipinde de var

  await page.getByRole("button", { name: "Çıkış" }).click();                     // çıkış: çerez silinir, yeniden giriş istenir
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/watch");
  await expect(page.getByLabel("Şifre")).toBeVisible();
});

test("özet kipi: sahte çerezler ve başka kipin çerezi reddedilir (kipler arası tekrar oynatma yok)", async ({ request }) => {
  const forged: Record<string, string> = {
    "rastgele 64 onaltılık": "0".repeat(64),
    "başka sırla üretilmiş HMAC": await expectedToken({ kind: "hash", secret: newSecret(), salt: "x", hash: "y" }),
    "ortam kipi belirteci (şifrenin SHA-256'sı)": await sessionToken(PASSWORD),
    "yanlış şifrenin ortam belirteci": await sessionToken("baska-sifre-123"),
    "boş": "",
    "uzun": "a".repeat(2000),
  };
  for (const [ad, value] of Object.entries(forged)) {
    const api = await request.get("/api/jobs", { headers: cookieHeader(value) });
    expect(api.status(), ad).toBe(401);
    const put = await request.put("/api/access", { data: { enabled: false }, headers: cookieHeader(value) });
    expect(put.status(), `${ad} PUT`).toBe(401);
    const page = await request.get("/watch", { headers: cookieHeader(value) });
    const html = await page.text();
    expect(html, ad).toContain("Panele giriş");                                     // giriş formuna yeniden yazılır
    expect(html, ad).not.toContain("Çıkış");
  }
});

test("özet kipi: art arda hatalı girişte 429 (doğru şifre bile kilit sürerken reddedilir), pencere bitince giriş yeniden olur", async ({ request }) => {
  test.setTimeout(120_000);
  for (let i = 0; i < 5; i++) {
    expect((await request.post("/api/login", { data: { password: `yanlis-deneme-${i}` } })).status(), `deneme ${i + 1}`).toBe(401);
  }
  const locked = await request.post("/api/login", { data: { password: "yanlis-deneme-5" } });
  expect(locked.status()).toBe(429);
  expect((await locked.json()).error).toBe("Çok fazla hatalı deneme; biraz sonra yeniden deneyin.");
  expect(Number(locked.headers()["retry-after"])).toBeGreaterThan(0);
  const stillLocked = await request.post("/api/login", { data: { password: PASSWORD } });   // doğru şifre de kilitte reddedilir
  expect(stillLocked.status()).toBe(429);
  expect(stillLocked.headers()["set-cookie"]).toBeUndefined();

  await new Promise((r) => setTimeout(r, 10_500));                               // ilk pencere 10 sn
  const ok = await request.post("/api/login", { data: { password: PASSWORD } });
  expect(ok.status()).toBe(200);
  expect(ok.headers()["set-cookie"]).toContain("bv_session=");
});
