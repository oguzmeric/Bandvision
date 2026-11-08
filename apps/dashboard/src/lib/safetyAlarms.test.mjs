import assert from "node:assert/strict";
import test from "node:test";
import { ALARM_LABELS, alarmCounts, alarmRows, defaultSafetyForm, formatClock, rulesSummary, safetyOptions } from "./safetyAlarms.mjs";

const form = (hu = {}, ly = {}) => {
  const f = defaultSafetyForm();
  Object.assign(f.handsUp, hu);
  Object.assign(f.lying, ly);
  return f;
};

test("defaultSafetyForm: iki kural açık; eller yukarı 3 sn, yerde yatma 10 sn", () => {
  assert.deepEqual(defaultSafetyForm(), {
    handsUp: { enabled: true, seconds: "3" },
    lying: { enabled: true, seconds: "10" },
  });
});

test("safetyOptions: varsayılanlar sözleşmedeki options'a çevrilir (sayım alanı yok)", () => {
  assert.deepEqual(safetyOptions(defaultSafetyForm()), {
    preset: "safety",
    safety: { handsUp: { enabled: true, seconds: 3 }, lying: { enabled: true, seconds: 10 } },
  });
});

test("safetyOptions: virgüllü ondalık kabul edilir; aralık uçları geçerli", () => {
  assert.deepEqual(safetyOptions(form({ seconds: "4,5" }, { seconds: "30" })).safety,
    { handsUp: { enabled: true, seconds: 4.5 }, lying: { enabled: true, seconds: 30 } });
  assert.deepEqual(safetyOptions(form({ seconds: "5" }, { seconds: "5" })).safety,
    { handsUp: { enabled: true, seconds: 5 }, lying: { enabled: true, seconds: 5 } });
});

test("safetyOptions: kapalı kuralın süresi gönderilmez ve denetlenmez", () => {
  const o = safetyOptions(form({ enabled: false, seconds: "99" }));
  assert.deepEqual(o.safety, { handsUp: { enabled: false }, lying: { enabled: true, seconds: 10 } });
});

test("safetyOptions: aralık dışı süre sunucudakiyle aynı Türkçe iletiyle reddedilir", () => {
  const hu = "Eller yukarı süresi 3–5 sn arasında bir sayı olmalı.";
  const ly = "Yerde yatma süresi 5–30 sn arasında bir sayı olmalı.";
  for (const s of ["2", "2,9", "5,1", "6", "0", "-3"]) assert.equal(safetyOptions(form({ seconds: s })), hu, s);
  for (const s of ["4", "4,9", "30,1", "31", "0"]) assert.equal(safetyOptions(form({}, { seconds: s })), ly, s);
});

test("safetyOptions: boş, sayı olmayan ve bilimsel yazım reddedilir", () => {
  const hu = "Eller yukarı süresi 3–5 sn arasında bir sayı olmalı.";
  for (const s of ["", " ", "abc", "3 sn", "NaN", "Infinity", "4e0", "3.", ".5"]) {
    assert.equal(safetyOptions(form({ seconds: s })), hu, JSON.stringify(s));
  }
});

test("safetyOptions: iki kural da kapalıysa 'En az bir kural açık olmalı.'", () => {
  assert.equal(safetyOptions(form({ enabled: false }, { enabled: false })), "En az bir kural açık olmalı.");
  assert.equal(safetyOptions(form({ enabled: false, seconds: "x" }, { enabled: false, seconds: "x" })),
    "En az bir kural açık olmalı.");                                  // kapalı kuralın süresi hata vermez
});

test("formatClock: mm:ss, aşağı yuvarlar; 1 saatten uzun videoda dakika büyür", () => {
  assert.equal(formatClock(0), "00:00");
  assert.equal(formatClock(12.4), "00:12");
  assert.equal(formatClock(59.99), "00:59");
  assert.equal(formatClock(61), "01:01");
  assert.equal(formatClock(600), "10:00");
  assert.equal(formatClock(3725.5), "62:05");
});

test("formatClock: negatif 00:00, sayı olmayan —", () => {
  assert.equal(formatClock(-3), "00:00");
  assert.equal(formatClock(Number.NaN), "—");
  assert.equal(formatClock(Number.POSITIVE_INFINITY), "—");
  assert.equal(formatClock(undefined), "—");
});

const alarm = (over = {}) => ({ kind: "handsUp", trackId: 3, startS: 12.4, atS: 15.4, endS: 19, image: "alarm-1.jpg", ...over });

test("ALARM_LABELS: tür adları (güvenlik ve yangın/duman)", () => {
  assert.deepEqual(ALARM_LABELS, { handsUp: "Eller yukarı", lying: "Yerde yatan kişi", fire: "Yangın", smoke: "Duman" });
});

test("alarmRows: yangın/duman işinin alarmları Yangın / Duman adıyla", () => {
  const rows = alarmRows({ alarms: [alarm({ kind: "fire", trackId: 0 }), alarm({ kind: "smoke", trackId: 1, image: null })], files: ["alarm-1.jpg"] });
  assert.deepEqual(rows.map((r) => [r.kind, r.label, r.image]), [["fire", "Yangın", "alarm-1.jpg"], ["smoke", "Duman", null]]);
});

test("alarmRows: tür adı, saat, süre ve resim", () => {
  const rows = alarmRows({ alarms: [alarm(), alarm({ kind: "lying", trackId: 5, startS: 61, atS: 71, endS: 95, image: "alarm-2.jpg" })],
                           files: ["annotated.mp4", "alarms.csv", "alarm-1.jpg", "alarm-2.jpg"] });
  assert.equal(rows.length, 2);
  assert.deepEqual(rows[0], { key: 0, kind: "handsUp", label: "Eller yukarı", startS: 12.4, clock: "00:12", duration: "7 sn", image: "alarm-1.jpg" });
  assert.deepEqual(rows[1], { key: 1, kind: "lying", label: "Yerde yatan kişi", startS: 61, clock: "01:01", duration: "34 sn", image: "alarm-2.jpg" });
});

test("alarmRows: süre — endS null ise '—'; yuvarlanır; negatif fark 0 sn", () => {
  const files = ["alarm-1.jpg"];
  const d = (over) => alarmRows({ alarms: [alarm(over)], files })[0].duration;
  assert.equal(d({ endS: null }), "—");
  assert.equal(d({ startS: 10, endS: 16.6 }), "7 sn");
  assert.equal(d({ startS: 10, endS: 16.4 }), "6 sn");
  assert.equal(d({ startS: 10, endS: 10 }), "0 sn");
  assert.equal(d({ startS: 10, endS: 9 }), "0 sn");
});

test("alarmRows: resim null ya da files'ta yoksa null (süresi dolan iş: files boş); başka ad asla kullanılmaz", () => {
  const one = (image, files) => alarmRows({ alarms: [alarm({ image })], files })[0].image;
  assert.equal(one(null, ["alarm-1.jpg"]), null);
  assert.equal(one("alarm-1.jpg", []), null);
  assert.equal(one("alarm-1.jpg", ["alarm-2.jpg"]), null);
  assert.equal(one("alarm-1.jpg", ["annotated.mp4", "alarm-1.jpg"]), "alarm-1.jpg");
  assert.equal(one("../x.jpg", ["../x.jpg"]), null);              // sözleşme dışı ad
  assert.equal(one("alarm-1.jpg.exe", ["alarm-1.jpg.exe"]), null);
});

test("alarmRows: alarm listesi yok ya da boş", () => {
  assert.deepEqual(alarmRows({ files: [] }), []);
  assert.deepEqual(alarmRows({ alarms: [], files: [] }), []);
  assert.deepEqual(alarmRows(undefined), []);
});

test("alarmRows: bilinmeyen tür ham haliyle gösterilir (çökmez)", () => {
  assert.equal(alarmRows({ alarms: [alarm({ kind: "flood" })], files: [] })[0].label, "flood");
});

test("rulesSummary: iş seçeneklerindeki kurallar; verilmeyen kural varsayılanla, kapalı kural 'kapalı'", () => {
  assert.equal(rulesSummary({ handsUp: { enabled: true, seconds: 4.5 }, lying: { enabled: false } }),
    "Eller yukarı 4,5 sn · Yerde yatan kişi kapalı");
  assert.equal(rulesSummary({}), "Eller yukarı 3 sn · Yerde yatan kişi 10 sn");
  assert.equal(rulesSummary(undefined), "Eller yukarı 3 sn · Yerde yatan kişi 10 sn");
  assert.equal(rulesSummary({ handsUp: { seconds: 5 } }), "Eller yukarı 5 sn · Yerde yatan kişi 10 sn");
});

const TYPES = ["hands_up", "lying", "fire", "smoke", "test"];

test("alarmCounts: toplam, tür listesindeki her tür (sıfır dahil) ve yanlış alarm", () => {
  const c = alarmCounts([
    { type: "fire" }, { type: "fire", falseAlarm: true }, { type: "smoke" }, { type: "hands_up" }, { type: "test" },
  ], TYPES);
  assert.deepEqual(c, { total: 5, hands_up: 1, lying: 0, fire: 2, smoke: 1, test: 1, false: 1 });
  assert.deepEqual(Object.keys(c), ["total", ...TYPES, "false"]);                  // sayaçların sırası tür listesinden
});

test("alarmCounts: boş liste sıfırlar; listede olmayan tür yalnız toplama girer", () => {
  assert.deepEqual(alarmCounts([], TYPES), { total: 0, hands_up: 0, lying: 0, fire: 0, smoke: 0, test: 0, false: 0 });
  assert.deepEqual(alarmCounts([{ type: "flood" }, { type: "total" }], ["fire"]), { total: 2, fire: 0, false: 0 });
});
