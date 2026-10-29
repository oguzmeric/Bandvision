import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

/**
 * İzleme (gerçek yığın): gerçek analiz sunucusu + derlenmiş panel. "Kamera" olarak uygulamanın test klibi açılır
 * (analiz sunucusu testte ANALYZER_ALLOW_FILE_SOURCES=1). Sahte API ile ayrıntılı arayüz testleri e2e/watch-ui.spec.ts'te.
 */
const CLIP = path.resolve(__dirname, "../../ios/BantSayacUITests/ui_test_clip.mp4");

async function login(page: Page) {
  await page.goto("/cameras");
  await page.getByLabel("Şifre").fill("e2e-test-sifresi");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("heading", { name: "Kameralar ve kayıt cihazları" })).toBeVisible();
}

test("izleme (gerçek yığın): API ile şablon, birleşik akış gelir, tek kamera akışı gelir", async ({ page }) => {
  await login(page);
  const src = await (await page.request.post("/api/live/sources", { data: {
    kind: "camera", brand: "custom", customUrl: CLIP, name: "İzleme klibi" } })).json();
  const view = await (await page.request.post("/api/live/views", { data: {
    name: "E2E izleme", layout: "2", tiles: [{ sourceId: src.id, channelId: null }, null] } })).json();
  try {
    await page.goto("/watch");
    await page.getByRole("tab", { name: "E2E izleme", exact: true }).click();
    await expect.poll(async () => page.getByAltText("E2E izleme canlı görüntü")
      .evaluate((img: HTMLImageElement) => img.naturalWidth), { timeout: 30_000 }).toBeGreaterThan(0);
    await expect(page.getByTestId("watch-tile").first()).toContainText("İzleme klibi");
    await page.getByTestId("watch-tile").first().dblclick();
    await expect.poll(async () => page.getByAltText("İzleme klibi canlı görüntü")
      .evaluate((img: HTMLImageElement) => img.naturalWidth), { timeout: 30_000 }).toBeGreaterThan(0);
  } finally {
    // test düşse de şablon ve kaynak kalmasın (sonraki testler "Henüz kaynak yok" bekleyebilir)
    await page.request.delete(`/api/live/views/${view.id}`);
    await page.request.delete(`/api/live/sources/${src.id}`);
  }
});

test("izleme (gerçek yığın): arayüzden yeni şablon, düzenlerken taslak akar, kaydet, sekme menüsünden sil", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  await login(page);
  const src = await (await page.request.post("/api/live/sources", { data: {
    kind: "camera", brand: "custom", customUrl: CLIP, name: "Düzenleyici klibi" } })).json();
  try {
    await page.goto("/watch");
    await page.getByRole("button", { name: "Yeni şablon" }).click();
    await expect(page.getByTestId("watch-tile")).toHaveCount(4);                      // 2×2
    await page.getByRole("button", { name: "Şablon editörü" }).click();
    await page.getByRole("dialog", { name: "Şablon editörü" }).getByRole("button", { name: "1", exact: true }).click();
    await expect(page.getByTestId("watch-tile")).toHaveCount(1);
    await page.keyboard.press("Escape");
    await page.getByRole("complementary", { name: "Kameralar" }).getByRole("button", { name: /^Düzenleyici klibi/ }).click();
    // kaydedilmeden canlı: ızgara analiz sunucusundaki taslağı akıtır
    const img = page.getByTestId("watch-grid").locator("img");
    await expect(img).toHaveAttribute("src", /\/api\/live\/views\/draft-[0-9a-f]{12}\/stream/, { timeout: 15_000 });
    await expect.poll(async () => img.evaluate((el: HTMLImageElement) => el.naturalWidth), { timeout: 30_000 }).toBeGreaterThan(0);
    await expect(page.getByTestId("watch-tile").first()).toContainText("Düzenleyici klibi");
    await page.getByRole("button", { name: "Kaydet", exact: true }).click();
    const saved = page.getByRole("tab", { name: "Yeni şablon", exact: true });
    await expect(saved).toHaveAttribute("aria-selected", "true");
    await expect(img).toHaveAttribute("src", /\/api\/live\/views\/(?!draft-)[^/]+\/stream/);
    await expect.poll(async () => page.getByAltText("Yeni şablon canlı görüntü")
      .evaluate((el: HTMLImageElement) => el.naturalWidth), { timeout: 30_000 }).toBeGreaterThan(0);
    const views = await (await page.request.get("/api/live/views")).json() as Array<{ name: string; layout: string; tiles: unknown[] }>;
    expect(views.find((v) => v.name === "Yeni şablon")).toMatchObject({ layout: "1", tiles: [{ sourceId: src.id, channelId: null }] });
    await saved.click({ button: "right" });
    await page.getByRole("menuitem", { name: "Sil" }).click();
    await expect(saved).toHaveCount(0);
  } finally {
    // test düşse de kaynak (ve ona bağlı şablon) kalmasın; sonraki testler "Henüz kaynak yok" bekleyebilir
    const views = await (await page.request.get("/api/live/views")).json() as Array<{ id: string; name: string }>;
    for (const v of views.filter((x) => x.name === "Yeni şablon")) await page.request.delete(`/api/live/views/${v.id}`);
    await page.request.delete(`/api/live/sources/${src.id}`);
  }
});

test("izleme (gerçek yığın): panel vekili taslak yollarını gövde ve durum koduyla aktarır (201, 200, 204, 404)", async ({ page }) => {
  await login(page);
  const src = await (await page.request.post("/api/live/sources", { data: {
    kind: "camera", brand: "custom", customUrl: CLIP, name: "Taslak klibi" } })).json();
  try {
    const tiles = [{ sourceId: src.id, channelId: null }, null];
    const created = await page.request.post("/api/live/views/drafts", { data: { layout: "2", tiles } });
    expect(created.status()).toBe(201);
    const d = await created.json() as { id: string; layout: string; name: string };
    expect(d).toMatchObject({ layout: "2", name: "Taslak", tiles });
    expect(d.id).toMatch(/^draft-[0-9a-f]{12}$/);
    const put = await page.request.put(`/api/live/views/drafts/${d.id}`, { data: { layout: "1x2", tiles: [null, tiles[0]] } });
    expect(put.status()).toBe(200);
    expect(await put.json()).toMatchObject({ id: d.id, layout: "1x2", tiles: [null, tiles[0]] });
    const st = await page.request.get(`/api/live/views/${d.id}/status`);
    expect(st.status()).toBe(200);
    expect(await st.json()).toMatchObject({ id: d.id, layout: "1x2", tiles: [null, { sourceId: src.id, name: "Taslak klibi" }] });
    const bad = await page.request.put(`/api/live/views/drafts/${d.id}`, { data: { layout: "16x9", tiles: [] } });
    expect(bad.status()).toBe(422);
    const del = await page.request.delete(`/api/live/views/drafts/${d.id}`);
    expect(del.status()).toBe(204);
    expect(await del.text()).toBe("");
    expect((await page.request.put(`/api/live/views/drafts/${d.id}`, { data: { layout: "2", tiles } })).status()).toBe(404);
    expect((await page.request.get(`/api/live/views/${d.id}/status`)).status()).toBe(404);
  } finally {
    await page.request.delete(`/api/live/sources/${src.id}`);
  }
});
