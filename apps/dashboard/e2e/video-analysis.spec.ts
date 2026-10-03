import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/** Uygulamanın uçtan uca test klibi (tools/make_ui_test_clip.py): sayısı bilinen yumurtalar. */
const CLIP = path.resolve(__dirname, "../../ios/BantSayacUITests/ui_test_clip.mp4");
const META = JSON.parse(fs.readFileSync(CLIP.replace(/\.mp4$/, ".json"), "utf-8")) as {
  count: number;
  emptySeconds: number;
};

test("video yükle → analiz → işaretli video, sayım ve CSV; sil", async ({ page, request }) => {
  await page.goto("/videos");
  await expect(page.getByRole("heading", { name: "Videodan sayım ve doğruluk" })).toBeVisible();
  await expect(page.getByText("Henüz analiz yok")).toBeVisible();

  await page.getByTestId("file-input").setInputFiles(CLIP);
  await expect(page.getByText("ui_test_clip.mp4").first()).toBeVisible();
  await page.getByLabel("Ürün").selectOption("egg");
  await page.getByLabel(/Doğru adet/).fill(String(META.count));
  await page.getByText("Gelişmiş: boş bant aralığı").click();
  await page.getByLabel("Boş bant başlangıcı (saniye)").fill("0");
  await page.getByLabel("Boş bant bitişi (saniye)").fill(String(META.emptySeconds - 0.3).replace(".", ","));
  await page.getByRole("button", { name: "Analizi başlat" }).click();

  // İlerleme görünür, sonra sonuç (Python referansıyla aynı sayı)
  const detail = page.getByTestId("job-detail");
  await expect(detail).toBeVisible();
  await expect(detail.getByText(`${META.count} / ${META.count}`)).toBeVisible({ timeout: 180_000 });
  await expect(detail.getByText("%100,0")).toBeVisible();

  // İşaretli video tarayıcıda oynar (H.264) ve sarılabilir
  const video = page.getByTestId("annotated-video");
  const meta = await video.evaluate(async (el: HTMLVideoElement) => {
    if (el.readyState < 1) await new Promise((r) => el.addEventListener("loadedmetadata", r, { once: true }));
    el.currentTime = 10;
    await new Promise((r) => el.addEventListener("seeked", r, { once: true }));
    return { duration: el.duration, width: el.videoWidth, time: el.currentTime };
  });
  expect(meta.width).toBe(720);
  expect(meta.duration).toBeGreaterThan(17);
  expect(meta.time).toBeCloseTo(10, 0);

  // CSV indirilebilir, sayım satırları içerir
  const href = await detail.getByRole("link", { name: "CSV indir" }).getAttribute("href");
  const csv = await request.get(href!);
  expect(csv.status()).toBe(200);
  const lines = (await csv.text()).trim().split(/\r?\n/);
  expect(lines[0]).toBe("zaman_sn;iz;delta;toplam");
  expect(Number(lines[lines.length - 1].split(";")[3])).toBe(META.count);

  // Zamana göre sayım grafiği
  await expect(page.getByRole("img", { name: new RegExp(`${META.count} ürün`) })).toBeVisible();

  // Sil
  page.once("dialog", (d) => d.accept());
  await detail.getByRole("button", { name: "Sil" }).click();
  await expect(page.getByText("Henüz analiz yok")).toBeVisible();
});

test("video olmayan dosya anlaşılır hatayla reddedilir", async ({ page }) => {
  await page.goto("/videos");
  await page.getByTestId("file-input").setInputFiles({ name: "notlar.txt", mimeType: "text/plain", buffer: Buffer.from("merhaba") });
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  await expect(page.getByTestId("upload-error")).toContainText("Desteklenmeyen dosya türü");
});

test("doğru adet ve boş bant aralığı doğrulanır", async ({ page }) => {
  await page.goto("/videos");
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  await expect(page.getByTestId("upload-error")).toHaveText("Önce bir video seç.");
  await page.getByTestId("file-input").setInputFiles(CLIP);
  await page.getByText("Gelişmiş: boş bant aralığı").click();
  await page.getByLabel("Boş bant başlangıcı (saniye)").fill("5");
  await page.getByLabel("Boş bant bitişi (saniye)").fill("2");
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  await expect(page.getByTestId("upload-error")).toContainText("Boş bant aralığı");
});
