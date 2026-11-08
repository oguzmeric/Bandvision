import assert from "node:assert/strict";
import test from "node:test";
import {
  addZone, defaultFireForm, deleteVertex, FIRE_DEFAULTS, FIRE_RULES, FIRE_WARNING, fireConfig, fireModelLine, fireOptions,
  fireRulesSummary, insertVertex, insideZone, MAX_ZONES, moveVertex, newZone, removeZone, SENSITIVITY_LABELS, translateZone,
  zonesProblem,
} from "./fireAlarms.mjs";

test("sabitler: kural aralıkları, hassasiyet adları ve uyarı metni", () => {
  assert.deepEqual(FIRE_RULES, { fire: { title: "Yangın", min: 2, max: 10, def: 3 }, smoke: { title: "Duman", min: 5, max: 30, def: 8 } });
  assert.deepEqual(SENSITIVITY_LABELS, { low: "Düşük", normal: "Normal", high: "Yüksek" });
  assert.equal(FIRE_WARNING, "Erken uyarıdır; yangın algılama ve alarm sisteminin yerine geçmez.");
});

test("fireConfig: boş/eksik blok varsayılanlara düşer (alev 3 sn, duman 8 sn, normal, bölge yok, resim kapalı)", () => {
  const def = { fire: { enabled: true, seconds: 3 }, smoke: { enabled: true, seconds: 8 }, sensitivity: "normal", ignoreZones: [], sendImage: false };
  assert.deepEqual(fireConfig(undefined), def);
  assert.deepEqual(fireConfig({}), def);
  assert.deepEqual(fireConfig(FIRE_DEFAULTS), def);
  assert.deepEqual(fireConfig({ smoke: { enabled: false }, sensitivity: "high", sendImage: true }),
    { ...def, smoke: { enabled: false, seconds: 8 }, sensitivity: "high", sendImage: true });
});

test("fireConfig: yanlış türler varsayılana düşer; bozuk köşeler atılır; bölgeler kopyalanır", () => {
  const zones = [[[0.1, 0.1], [0.5, 0.1], [0.3, 0.4]]];
  const c = fireConfig({ fire: { enabled: "evet", seconds: Number.NaN }, sensitivity: "max", sendImage: 1,
                         ignoreZones: [...zones, "x", [[0.2, 0.2], [0.3], "y", [0.4, 0.5], [0.1, 0.9]]] });
  assert.deepEqual(c.fire, { enabled: true, seconds: 3 });
  assert.equal(c.sensitivity, "normal");
  assert.equal(c.sendImage, false);
  assert.deepEqual(c.ignoreZones, [zones[0], [[0.2, 0.2], [0.4, 0.5], [0.1, 0.9]]]);
  c.ignoreZones[0][0][0] = 0.9;
  assert.equal(zones[0][0][0], 0.1);                                        // kaynak değişmez
});

test("fireModelLine: hazır / yükleniyor / kurulu değil; başka hata nedeniyle; durum yoksa null", () => {
  assert.deepEqual(fireModelLine({ model: "ready" }), { text: "Yangın/duman modeli: hazır", tone: "ok" });
  assert.deepEqual(fireModelLine({ model: "loading" }), { text: "Yangın/duman modeli: yükleniyor", tone: "muted" });
  assert.deepEqual(fireModelLine({ model: "error", modelError: "Yangın/duman modeli kurulu değil." }),
    { text: "Yangın/duman modeli: kurulu değil", tone: "warn" });
  assert.deepEqual(fireModelLine({ model: "error", modelError: null }), { text: "Yangın/duman modeli: kurulu değil", tone: "warn" });
  assert.deepEqual(fireModelLine({ model: "error", modelError: "Yangın/duman modeli yüklenemedi: dosya bozuk" }),
    { text: "Yangın/duman modeli: yüklenemedi — Yangın/duman modeli yüklenemedi: dosya bozuk", tone: "warn" });
  assert.equal(fireModelLine(null), null);
  assert.equal(fireModelLine(undefined), null);
  assert.equal(fireModelLine({}), null);                                    // eski sunucu: model alanı yok
});

const form = (fi = {}, sm = {}, sensitivity) => {
  const f = defaultFireForm();
  Object.assign(f.fire, fi);
  Object.assign(f.smoke, sm);
  if (sensitivity) f.sensitivity = sensitivity;
  return f;
};

test("fireOptions: varsayılanlar sözleşmedeki options'a çevrilir (sayım alanı yok)", () => {
  assert.deepEqual(defaultFireForm(), { fire: { enabled: true, seconds: "3" }, smoke: { enabled: true, seconds: "8" }, sensitivity: "normal" });
  assert.deepEqual(fireOptions(defaultFireForm()), {
    preset: "fire",
    fire: { fire: { enabled: true, seconds: 3 }, smoke: { enabled: true, seconds: 8 }, sensitivity: "normal" },
  });
});

test("fireOptions: virgüllü ondalık, aralık uçları, hassasiyet; kapalı kuralın süresi gönderilmez", () => {
  assert.deepEqual(fireOptions(form({ seconds: "2,5" }, { seconds: "30" }, "high")).fire,
    { fire: { enabled: true, seconds: 2.5 }, smoke: { enabled: true, seconds: 30 }, sensitivity: "high" });
  assert.deepEqual(fireOptions(form({ seconds: "10" }, { enabled: false, seconds: "99" }, "low")).fire,
    { fire: { enabled: true, seconds: 10 }, smoke: { enabled: false }, sensitivity: "low" });
});

test("fireOptions: aralık dışı ya da sayı olmayan süre sunucudakiyle aynı iletiyle reddedilir", () => {
  const fi = "Yangın süresi 2–10 sn arasında bir sayı olmalı.";
  const sm = "Duman süresi 5–30 sn arasında bir sayı olmalı.";
  for (const s of ["1", "1,9", "10,1", "", "abc", "4e0", "-3"]) assert.equal(fireOptions(form({ seconds: s })), fi, s);
  for (const s of ["4", "30,5", "x"]) assert.equal(fireOptions(form({}, { seconds: s })), sm, s);
});

test("fireOptions: iki kural da kapalıysa 'En az bir kural açık olmalı.'", () => {
  assert.equal(fireOptions(form({ enabled: false, seconds: "x" }, { enabled: false })), "En az bir kural açık olmalı.");
});

test("fireRulesSummary: kurallar ve hassasiyet tek satırda; verilmeyen alan varsayılan", () => {
  assert.equal(fireRulesSummary({ fire: { enabled: true, seconds: 2.5 }, smoke: { enabled: false }, sensitivity: "high" }),
    "Yangın 2,5 sn · Duman kapalı · Hassasiyet: Yüksek");
  assert.equal(fireRulesSummary(undefined), "Yangın 3 sn · Duman 8 sn · Hassasiyet: Normal");
  assert.equal(fireRulesSummary({ smoke: { seconds: 12 } }), "Yangın 3 sn · Duman 12 sn · Hassasiyet: Normal");
});

test("addZone: 0,2'lik kare, üst üste binmeden; en çok 8", () => {
  let zones = [];
  for (let i = 0; i < 10; i++) zones = addZone(zones);
  assert.equal(zones.length, MAX_ZONES);
  assert.deepEqual(zones[0], [[0.1, 0.15], [0.3, 0.15], [0.3, 0.35], [0.1, 0.35]]);
  assert.deepEqual(newZone(5), [[0.3, 0.6], [0.5, 0.6], [0.5, 0.8], [0.3, 0.8]]);
  assert.equal(zonesProblem(zones), null);
  const boxes = zones.map((z) => [z[0][0], z[0][1]]);
  assert.equal(new Set(boxes.map(String)).size, MAX_ZONES);                 // her bölge ayrı yerde
});

test("addZone: silinen bölgenin yuvası yeniden kullanılır, kalan bölgenin üstüne binmez", () => {
  const z0 = newZone(0), z1 = newZone(1);
  const after = addZone(removeZone([z0, z1], 0));
  assert.equal(after.length, 2);
  assert.deepEqual(after[0], z1);
  assert.notDeepEqual(after[1], z1);
  assert.deepEqual(after[1], z0);                                            // ilk boş yuva
  const moved = [newZone(0), newZone(2)];                                    // ortada boş yuva
  assert.deepEqual(addZone(moved)[2], newZone(1));
  const custom = Array.from({ length: 7 }, (_, i) => newZone(i));            // dolu yuvalar dışında köşesi taşınmış bölge
  assert.deepEqual(addZone(custom)[7], newZone(7));
});

test("removeZone / moveVertex: kırpılır ve yalnız o köşe değişir", () => {
  const zones = [newZone(0), newZone(1)];
  assert.deepEqual(removeZone(zones, 0), [zones[1]]);
  const moved = moveVertex(zones, 1, 2, [1.4, -0.2]);
  assert.deepEqual(moved[1][2], [1, 0]);
  assert.deepEqual(moved[0], zones[0]);
  assert.deepEqual(moved[1][0], zones[1][0]);
});

test("insertVertex / deleteVertex: 3–12 köşe sınırı", () => {
  let zones = [[[0.1, 0.1], [0.5, 0.1], [0.3, 0.5]]];
  assert.deepEqual(deleteVertex(zones, 0, 1), zones);                       // üçgenden az olmaz
  zones = insertVertex(zones, 0, 0, [0.3, 0.05]);
  assert.deepEqual(zones[0], [[0.1, 0.1], [0.3, 0.05], [0.5, 0.1], [0.3, 0.5]]);
  assert.deepEqual(deleteVertex(zones, 0, 1)[0], [[0.1, 0.1], [0.5, 0.1], [0.3, 0.5]]);
  for (let i = 0; i < 20; i++) zones = insertVertex(zones, 0, 0, [0.2, 0.1]);
  assert.equal(zones[0].length, 12);
  assert.equal(zonesProblem(zones), null);
});

test("translateZone: bütün bölge taşınır, kenarda durur", () => {
  const zones = [newZone(0)];
  assert.deepEqual(translateZone(zones, 0, 0.1, 0.05)[0], [[0.2, 0.2], [0.4, 0.2], [0.4, 0.4], [0.2, 0.4]]);
  assert.deepEqual(translateZone(zones, 0, -1, 2)[0], [[0, 0.8], [0.2, 0.8], [0.2, 1], [0, 1]]);
  assert.deepEqual(translateZone(zones, 3, 0.1, 0.1), zones);              // olmayan bölge
});

test("insideZone: çift-tek kuralı", () => {
  const z = newZone(0);
  assert.equal(insideZone(z, [0.2, 0.25]), true);
  assert.equal(insideZone(z, [0.05, 0.25]), false);
  assert.equal(insideZone(z, [0.2, 0.5]), false);
});

test("zonesProblem: sunucunun reddedeceği bölgeler Türkçe nedenle", () => {
  assert.equal(zonesProblem([]), null);
  assert.equal(zonesProblem("x"), "Hariç bölgeler bir liste olmalı.");
  assert.equal(zonesProblem(Array.from({ length: 9 }, (_, i) => newZone(i))), "En çok 8 hariç bölge çizilebilir.");
  assert.equal(zonesProblem([[[0, 0], [1, 1]]]), "Her hariç bölge 3–12 köşeli bir çokgen olmalı.");
  assert.equal(zonesProblem([[[0, 0], [1, 1], [1.2, 0]]]), "Hariç bölge köşeleri görüntünün içinde olmalı.");
  assert.equal(zonesProblem([[[0, 0], [1, 1], [Number.NaN, 0]]]), "Hariç bölge köşeleri görüntünün içinde olmalı.");
});
