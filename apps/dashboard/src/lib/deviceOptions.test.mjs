import assert from "node:assert/strict";
import test from "node:test";
import { benchText, choiceOptions, deviceLabels, inUseText } from "./deviceOptions.mjs";

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
  assert.deepEqual(inUseText({ state: "loading", device: { id: "cpu", kind: "cpu", name: "İşlemci" }, note: null }),
    { text: "Şu an: İşlemci (yeni cihaz yükleniyor…)", warn: false });
});

test("inUseText: hazır; çalışan cihazın adı", () => {
  assert.deepEqual(inUseText({ state: "ready", device: { id: NV.id, kind: "gpu", name: NV.name }, note: null }),
    { text: `Şu an: ${NV.name}`, warn: false });
});

test("inUseText: hazır ama not var (işlemciye düşüş, başarısız geçiş) → uyarı rengi ve not metni", () => {
  const n4 = "Ekran kartı çalışırken hata verdi (DXGI_ERROR_DEVICE_REMOVED); işlemci kullanılıyor.";
  assert.deepEqual(inUseText({ state: "ready", device: { id: "cpu", kind: "cpu", name: "İşlemci" }, note: n4 }),
    { text: `Şu an: İşlemci — ${n4}`, warn: true });
  const sw = "Seçilen cihaza geçilemedi: x; önceki cihazda çalışmaya devam ediyor.";
  const r = inUseText({ state: "ready", device: { id: NV.id, kind: "gpu", name: NV.name }, note: sw });
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

const TWIN1 = { id: "gpu-10de-2684", kind: "gpu", name: "NVIDIA ekran kartı", memoryMb: 24000 };
const TWIN2 = { id: "gpu-10de-2684-2", kind: "gpu", name: "NVIDIA ekran kartı", memoryMb: 24000 };
const TWIN3 = { id: "gpu-10de-2684-3", kind: "gpu", name: "NVIDIA ekran kartı", memoryMb: 24000 };

test("deviceLabels: adı benzersiz olanlar olduğu gibi; aynı adlı kartlara kimlik sonekiyle (soneksiz = 1) numara eklenir", () => {
  assert.deepEqual(deviceLabels([CPU, NV, INTEL]), { cpu: "İşlemci", [NV.id]: NV.name, [INTEL.id]: INTEL.name });
  assert.deepEqual(deviceLabels([CPU, TWIN1, TWIN2, INTEL]), {
    cpu: "İşlemci", [TWIN1.id]: "NVIDIA ekran kartı (1)", [TWIN2.id]: "NVIDIA ekran kartı (2)", [INTEL.id]: INTEL.name,
  });
  // numara listedeki sıraya değil kimliğin sonekine bağlıdır: ilk kart listede yoksa kalan 2 ve 3 kendi numarasını korur
  const labels = deviceLabels([TWIN3, TWIN2]);
  assert.equal(labels[TWIN2.id], "NVIDIA ekran kartı (2)");
  assert.equal(labels[TWIN3.id], "NVIDIA ekran kartı (3)");
});

test("choiceOptions: aynı adlı kartlar seçenekte ve 'Otomatik (…)' etiketinde numaralı", () => {
  const opts = choiceOptions([CPU, TWIN1, TWIN2], TWIN2.id, "auto");
  assert.deepEqual(opts.map((o) => o.label), ["Otomatik (NVIDIA ekran kartı (2))", "İşlemci", "NVIDIA ekran kartı (1)", "NVIDIA ekran kartı (2)"]);
});

test("deviceLabels: aynı adlı ama farklı aygıt kimlikli kartlar (sonekler çakışır) listedeki sırayla numaralanır", () => {
  const A = { id: "gpu-10de-2503", kind: "gpu", name: "NVIDIA GeForce RTX 3060", memoryMb: 12000 };
  const B = { id: "gpu-10de-2504", kind: "gpu", name: "NVIDIA GeForce RTX 3060", memoryMb: 12000 };
  assert.deepEqual(deviceLabels([CPU, A, B]), {
    cpu: "İşlemci", [A.id]: "NVIDIA GeForce RTX 3060 (1)", [B.id]: "NVIDIA GeForce RTX 3060 (2)",
  });
  // karışık grup: 2503, 2503-2 ve 2504 → sonekler 1, 2, 1 çakışır → sırayla 1, 2, 3 (etiketler yine benzersiz)
  const A2 = { ...A, id: "gpu-10de-2503-2" };
  const labels = deviceLabels([A, A2, B]);
  assert.deepEqual([labels[A.id], labels[A2.id], labels[B.id]],
    ["NVIDIA GeForce RTX 3060 (1)", "NVIDIA GeForce RTX 3060 (2)", "NVIDIA GeForce RTX 3060 (3)"]);
  // başka adlı grup kendi kuralıyla: aynı model kartlar sonekle kalır
  const both = deviceLabels([A, B, TWIN2, TWIN3]);
  assert.equal(both[TWIN2.id], "NVIDIA ekran kartı (2)");
  assert.equal(both[TWIN3.id], "NVIDIA ekran kartı (3)");
  assert.equal(new Set(Object.values(both)).size, 4);
});

test("inUseText: aynı adlı kartta 'Şu an' satırı seçeneklerle aynı numaralı etiketi kullanır", () => {
  const labels = deviceLabels([CPU, TWIN1, TWIN2]);
  const ready = { state: "ready", device: { id: TWIN2.id, kind: "gpu", name: TWIN2.name }, note: null };
  assert.deepEqual(inUseText(ready, labels), { text: "Şu an: NVIDIA ekran kartı (2)", warn: false });
  assert.deepEqual(inUseText({ ...ready, state: "loading" }, labels),
    { text: "Şu an: NVIDIA ekran kartı (2) (yeni cihaz yükleniyor…)", warn: false });
  const n4 = "Ekran kartı çalışırken hata verdi (x); işlemci kullanılıyor.";
  assert.equal(inUseText({ ...ready, note: n4 }, labels).text, `Şu an: NVIDIA ekran kartı (2) — ${n4}`);
  // listede olmayan kimlik (kart sökülmüş): sunucunun verdiği ad
  const gone = { state: "ready", device: { id: "gpu-1002-73bf", kind: "gpu", name: "AMD kart" }, note: null };
  assert.equal(inUseText(gone, labels).text, "Şu an: AMD kart");
});

test("choiceOptions: otomatik işlemciye çözülürse (yalnız tümleşik kart var) 'Otomatik (İşlemci)', kart elle seçilebilir", () => {
  assert.deepEqual(choiceOptions([CPU, INTEL], "cpu", "auto"), [
    { value: "auto", label: "Otomatik (İşlemci)" },
    { value: "cpu", label: "İşlemci" },
    { value: INTEL.id, label: INTEL.name },
  ]);
});
