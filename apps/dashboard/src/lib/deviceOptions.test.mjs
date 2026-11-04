import assert from "node:assert/strict";
import test from "node:test";
import { benchText, choiceOptions, inUseText } from "./deviceOptions.mjs";

const CPU = { id: "cpu", kind: "cpu", name: "İşlemci" };
const NV = { id: "gpu-10de-28a1", kind: "gpu", name: "NVIDIA GeForce RTX 4050 Laptop GPU", memoryMb: 5920 };
const INTEL = { id: "gpu-8086-a7a0", kind: "gpu", name: "Intel(R) Iris(R) Xe Graphics", memoryMb: 128 };

test("choiceOptions: Otomatik (seçilecek cihazın adı), İşlemci, sonra her ekran kartı", () => {
  assert.deepEqual(choiceOptions([CPU, NV, INTEL], NV.id, "auto"), [
    { value: "auto", label: `Otomatik (${NV.name})` },
    { value: "cpu", label: "İşlemci" },
    { value: NV.id, label: NV.name },
    { value: INTEL.id, label: INTEL.name },
  ]);
});

test("choiceOptions: otomatik işlemciye çözülüyorsa 'Otomatik (İşlemci)'; ekran kartı yoksa yalnız iki seçenek", () => {
  assert.deepEqual(choiceOptions([CPU], "cpu", "auto"), [
    { value: "auto", label: "Otomatik (İşlemci)" },
    { value: "cpu", label: "İşlemci" },
  ]);
  // cihaz listesi boş olsa da 'cpu' adı bilinir
  assert.equal(choiceOptions([], "cpu", "auto")[0].label, "Otomatik (İşlemci)");
});

test("choiceOptions: kayıtlı ama listede olmayan ekran kartı 'Bulunamayan ekran kartı (<kimlik>)' olarak eklenir", () => {
  const opts = choiceOptions([CPU, NV], NV.id, "gpu-1002-73bf");
  assert.deepEqual(opts.at(-1), { value: "gpu-1002-73bf", label: "Bulunamayan ekran kartı (gpu-1002-73bf)" });
  assert.equal(opts.length, 4);
});

test("choiceOptions: kayıtlı kart listedeyse ya da auto/cpu ise fazladan seçenek yok", () => {
  assert.equal(choiceOptions([CPU, NV], NV.id, NV.id).length, 3);
  assert.equal(choiceOptions([CPU, NV], NV.id, "cpu").length, 3);
  assert.equal(choiceOptions([CPU, NV], NV.id, "auto").length, 3);
});

test("inUseText: kullanılmıyor (idle)", () => {
  assert.deepEqual(inUseText({ state: "idle", device: null, note: null }), { text: "Şu an: kullanılmıyor", warn: false });
});

test("inUseText: yükleniyor; eski cihaz hâlâ çalışıyorsa adı da yazılır", () => {
  assert.deepEqual(inUseText({ state: "loading", device: null, note: null }), { text: "Şu an: yükleniyor…", warn: false });
  assert.deepEqual(inUseText({ state: "loading", device: { id: "cpu", kind: "cpu", name: "İşlemci", note: null }, note: null }),
    { text: "Şu an: İşlemci (yeni cihaz yükleniyor…)", warn: false });
});

test("inUseText: hazır; çalışan cihazın adı", () => {
  assert.deepEqual(inUseText({ state: "ready", device: { id: NV.id, kind: "gpu", name: NV.name, note: null }, note: null }),
    { text: `Şu an: ${NV.name}`, warn: false });
});

test("inUseText: hazır ama not var (işlemciye düşüş, başarısız geçiş) → uyarı rengi ve not metni", () => {
  const n4 = "Ekran kartı çalışırken hata verdi (DXGI_ERROR_DEVICE_REMOVED); işlemci kullanılıyor.";
  assert.deepEqual(inUseText({ state: "ready", device: { id: "cpu", kind: "cpu", name: "İşlemci", note: n4 }, note: n4 }),
    { text: `Şu an: İşlemci — ${n4}`, warn: true });
  const sw = "Seçilen cihaza geçilemedi: x; önceki cihazda çalışmaya devam ediyor.";
  const r = inUseText({ state: "ready", device: { id: NV.id, kind: "gpu", name: NV.name, note: null }, note: sw });
  assert.equal(r.warn, true);
  assert.ok(r.text.includes(NV.name) && r.text.includes(sw));
});

test("inUseText: hata → not metni, uyarı rengi; not yoksa genel ileti", () => {
  assert.deepEqual(inUseText({ state: "error", device: null, note: "Model açılamadı: x" }), { text: "Model açılamadı: x", warn: true });
  const r = inUseText({ state: "error", device: null, note: null });
  assert.equal(r.warn, true);
  assert.ok(r.text.length > 0);
});

test("benchText: '12.3 ms/kare (2.0 sn açılış)'; not varsa uyarı ve not metni", () => {
  const dev = { id: NV.id, kind: "gpu", name: NV.name, note: null };
  assert.deepEqual(benchText({ device: dev, msPerFrame: 12.3, loadS: 2 }), { text: "12.3 ms/kare (2.0 sn açılış)", warn: false });
  assert.equal(benchText({ device: dev, msPerFrame: 40, loadS: 0.54 }).text, "40.0 ms/kare (0.5 sn açılış)");
  const note = "Ekran kartında açılamadı (x); işlemci kullanılıyor.";
  assert.deepEqual(benchText({ device: { ...dev, id: "cpu", kind: "cpu", name: "İşlemci", note }, msPerFrame: 90, loadS: 1 }),
    { text: note, warn: true });
});
