import { expect, test, type Locator, type Page } from "@playwright/test";
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

/**
 * Görüntü bu adresten çözüldü: `currentSrc` beklenen yolu içerir ve boyutu var. `src` değişince tarayıcı yenisi gelene
 * dek eskisini gösterebilir; yalnız `naturalWidth` önceki akışın karesini de sayardı.
 */
function decodedFrom(img: Locator, path: string): Promise<boolean> {
  return img.evaluate((el: HTMLImageElement, p) => el.currentSrc.includes(p) && el.naturalWidth > 0, path);
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
    await expect.poll(() => decodedFrom(page.getByAltText("E2E izleme canlı görüntü"), `/api/live/views/${view.id}/stream?`),
      { timeout: 30_000 }).toBe(true);
    await expect(page.getByTestId("watch-tile").first()).toContainText("İzleme klibi");
    await page.getByTestId("watch-tile").first().dblclick();
    await expect.poll(() => decodedFrom(page.getByAltText("İzleme klibi canlı görüntü"), `/api/live/cameras/stream?source=${src.id}&`),
      { timeout: 30_000 }).toBe(true);
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
    await page.getByRole("dialog", { name: "Şablon editörü" }).getByRole("button", { name: /^1:/ }).click();
    await expect(page.getByTestId("watch-tile")).toHaveCount(1);
    await page.keyboard.press("Escape");
    await page.getByRole("complementary", { name: "Kameralar" }).getByRole("button", { name: /^Düzenleyici klibi/ }).click();
    // kaydedilmeden canlı: ızgara analiz sunucusundaki taslağı akıtır
    const img = page.getByTestId("watch-grid").locator("img");
    await expect(img).toHaveAttribute("src", /\/api\/live\/views\/draft-[0-9a-f]{12}\/stream/, { timeout: 15_000 });
    const draftId = await page.getByTestId("watch-grid").getAttribute("data-stream");
    await expect.poll(() => decodedFrom(img, `/api/live/views/${draftId}/stream?`), { timeout: 30_000 }).toBe(true);
    await expect(page.getByTestId("watch-tile").first()).toContainText("Düzenleyici klibi");
    await page.getByRole("button", { name: "Kaydet", exact: true }).click();
    const saved = page.getByRole("tab", { name: "Yeni şablon", exact: true });
    await expect(saved).toHaveAttribute("aria-selected", "true");
    await expect(img).toHaveAttribute("src", /\/api\/live\/views\/(?!draft-)[^/]+\/stream/);
    const views = await (await page.request.get("/api/live/views")).json() as Array<{ id: string; name: string; layout: string; tiles: unknown[] }>;
    const view = views.find((v) => v.name === "Yeni şablon");
    expect(view).toMatchObject({ layout: "1", tiles: [{ sourceId: src.id, channelId: null }] });
    await expect.poll(() => decodedFrom(page.getByAltText("Yeni şablon canlı görüntü"), `/api/live/views/${view!.id}/stream?`),
      { timeout: 30_000 }).toBe(true);
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

/** Birleşik akışın bir JPEG karesi: bayt dizisi ve SOF işaretinden okunan boyut */
interface JpegFrame { jpeg: Buffer; width: number; height: number }

/** JPEG'in boyutu (SOF0–SOF15 işareti; DHT/JPG/DAC değil). Bulunamazsa hata: geçerli bir JPEG değil. */
function jpegSize(jpeg: Buffer): { width: number; height: number } {
  let i = 2;
  while (i + 9 < jpeg.length) {
    if (jpeg[i] !== 0xff) throw new Error(`JPEG işareti beklenirken ${jpeg[i]} (konum ${i})`);
    const marker = jpeg[i + 1];
    if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
      return { height: jpeg.readUInt16BE(i + 5), width: jpeg.readUInt16BE(i + 7) };
    }
    i += 2 + jpeg.readUInt16BE(i + 2);
  }
  throw new Error("JPEG'de boyut işareti (SOF) yok");
}

/**
 * Birleşik akıştan kareler (`limit` kare sonra sunucu akışı bitirir): yanıt `multipart/x-mixed-replace; boundary=frame`,
 * her parça `Content-Type: image/jpeg` + `Content-Length` ve gövdesi FFD8 ile başlayıp FFD9 ile biten bir JPEG.
 */
async function mjpegFrames(page: Page, url: string): Promise<JpegFrame[]> {
  const res = await page.request.get(url, { timeout: 60_000 });
  expect(res.status()).toBe(200);
  expect(res.headers()["content-type"]).toBe("multipart/x-mixed-replace; boundary=frame");
  const body = await res.body();
  const head = Buffer.from("--frame\r\n");
  const frames: JpegFrame[] = [];
  let i = 0;
  while (i < body.length) {
    expect(body.subarray(i, i + head.length).equals(head), `parça sınırı (konum ${i})`).toBe(true);
    const end = body.indexOf("\r\n\r\n", i);
    const headers = body.subarray(i + head.length, end).toString("latin1");
    const m = /^Content-Type: image\/jpeg\r\nContent-Length: (\d+)$/.exec(headers);
    expect(m, `parça başlıkları: ${headers}`).not.toBeNull();
    const jpeg = body.subarray(end + 4, end + 4 + Number(m![1]));
    expect(jpeg.subarray(0, 2).toString("hex")).toBe("ffd8");
    expect(jpeg.subarray(-2).toString("hex")).toBe("ffd9");
    expect(body.subarray(end + 4 + jpeg.length, end + 6 + jpeg.length).toString("latin1")).toBe("\r\n");
    frames.push({ jpeg, ...jpegSize(jpeg) });
    i = end + 6 + jpeg.length;
  }
  return frames;
}

/**
 * Karenin rows×cols eşit hücrelerinin iç bölgelerinde (kutular arası 2 px aralıktan uzak) parlaklığın ortalaması ve
 * sapması. JPEG tarayıcıda çözülür (ek paket yok).
 */
async function cellStats(page: Page, jpeg: Buffer, rows: number, cols: number): Promise<Array<{ mean: number; std: number }>> {
  return page.evaluate(async ({ b64, rows, cols }) => {
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const bmp = await createImageBitmap(new Blob([bytes], { type: "image/jpeg" }));
    const ctx = new OffscreenCanvas(bmp.width, bmp.height).getContext("2d")!;
    ctx.drawImage(bmp, 0, 0);
    const out: Array<{ mean: number; std: number }> = [];
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const x0 = Math.round((c * bmp.width) / cols) + 4;
        const y0 = Math.round((r * bmp.height) / rows) + 4;
        const x1 = Math.round(((c + 1) * bmp.width) / cols) - 4;
        const y1 = Math.round(((r + 1) * bmp.height) / rows) - 4;
        const d = ctx.getImageData(x0, y0, x1 - x0, y1 - y0).data;
        let sum = 0;
        let sq = 0;
        for (let p = 0; p < d.length; p += 4) {
          const v = (d[p] + d[p + 1] + d[p + 2]) / 3;
          sum += v;
          sq += v * v;
        }
        const n = d.length / 4;
        const mean = sum / n;
        out.push({ mean, std: Math.sqrt(Math.max(0, sq / n - mean * mean)) });
      }
    }
    return out;
  }, { b64: jpeg.toString("base64"), rows, cols });
}

/**
 * Akış istenen boyutta (640×360 → sunucu kenarları 16'nın katına indirir: 640×352) JPEG kareler verir ve son kare 5×5
 * düzendedir: ilk kutuda kamera (dikey test klibi siyah payla sığdırılır: düz değil), kalan 24 kutu boş kutunun düz koyu
 * grisi (40, 40, 40).
 */
async function expectFiveByFiveWithCameraFirst(page: Page, streamId: string) {
  const frames = await mjpegFrames(page, `/api/live/views/${streamId}/stream?w=640&h=360&limit=3`);
  expect(frames).toHaveLength(3);
  for (const f of frames) expect({ width: f.width, height: f.height }).toEqual({ width: 640, height: 352 });
  const cells = await cellStats(page, frames[frames.length - 1].jpeg, 5, 5);
  expect(cells[0].std, "ilk kutuda kamera görüntüsü").toBeGreaterThan(10);
  for (const [i, c] of cells.entries()) {
    if (i === 0) continue;
    expect(Math.abs(c.mean - 40), `kutu ${i + 1} boş (koyu gri), ortalama ${c.mean.toFixed(1)}`).toBeLessThanOrEqual(4);
    expect(c.std, `kutu ${i + 1} düz, sapma ${c.std.toFixed(1)}`).toBeLessThanOrEqual(3);
  }
}

test("izleme (gerçek yığın): 5×5 taslak JPEG kareleri akıtır, kaydedince şablon aynı 5×5 akışı verir", async ({ page }) => {
  await login(page);
  const src = await (await page.request.post("/api/live/sources", { data: {
    kind: "camera", brand: "custom", customUrl: CLIP, name: "Beşli klip" } })).json();
  try {
    await page.goto("/watch");
    await page.getByRole("button", { name: "Yeni şablon" }).click();
    await page.getByRole("button", { name: "Şablon editörü" }).click();
    await page.getByRole("dialog", { name: "Şablon editörü" }).getByRole("button", { name: /^5×5:/ }).click();
    await expect(page.getByTestId("watch-tile")).toHaveCount(25);
    await page.keyboard.press("Escape");
    await page.getByRole("complementary", { name: "Kameralar" }).getByRole("button", { name: /^Beşli klip/ }).click();

    // Kaydedilmeden: ızgara analiz sunucusundaki "5x5" taslağını akıtır
    const grid = page.getByTestId("watch-grid");
    await expect(grid).toHaveAttribute("data-stream", /^draft-[0-9a-f]{12}$/, { timeout: 15_000 });
    const draftId = (await grid.getAttribute("data-stream"))!;
    const draftStatus = async () => (await page.request.get(`/api/live/views/${draftId}/status`)).json() as
      Promise<{ id: string; layout: string; tiles: unknown[] }>;
    await expect.poll(async () => (await draftStatus()).tiles[0], { timeout: 30_000 })
      .toMatchObject({ sourceId: src.id, channelId: null, name: "Beşli klip", state: "live" });
    const st = await draftStatus();
    expect(st).toMatchObject({ id: draftId, layout: "5x5" });
    expect(st.tiles).toHaveLength(25);
    expect(st.tiles.slice(1).every((t) => t === null)).toBe(true);
    const img = grid.locator("img");
    await expect(img).toHaveAttribute("src", new RegExp(`/api/live/views/${draftId}/stream\\?`));
    await expect.poll(() => decodedFrom(img, `/api/live/views/${draftId}/stream?`), { timeout: 30_000 }).toBe(true);
    await expectFiveByFiveWithCameraFirst(page, draftId);

    // Kaydet: şablon "5x5" olarak yazılır, taslak silinir, ızgara şablonun akışına döner
    await page.getByRole("button", { name: "Kaydet", exact: true }).click();
    const saved = page.getByRole("tab", { name: "Yeni şablon", exact: true });
    await expect(saved).toHaveAttribute("aria-selected", "true");
    const views = await (await page.request.get("/api/live/views")).json() as Array<{ id: string; name: string; layout: string; tiles: unknown[] }>;
    const view = views.find((v) => v.name === "Yeni şablon");
    expect(view?.layout).toBe("5x5");
    expect(view!.tiles).toEqual([{ sourceId: src.id, channelId: null }, ...Array<null>(24).fill(null)]);
    await expect(grid).toHaveAttribute("data-stream", view!.id);
    await expect(img).toHaveAttribute("src", new RegExp(`/api/live/views/${view!.id}/stream\\?`));
    await expect.poll(async () => (await page.request.get(`/api/live/views/${draftId}/status`)).status()).toBe(404);
    await expect.poll(() => decodedFrom(img, `/api/live/views/${view!.id}/stream?`), { timeout: 30_000 }).toBe(true);
    await expectFiveByFiveWithCameraFirst(page, view!.id);
  } finally {
    // test düşse de şablon ve kaynak kalmasın; sonraki testler "Henüz kaynak yok" bekleyebilir
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
