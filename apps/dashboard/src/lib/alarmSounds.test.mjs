import test from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_SOUND, DEFAULT_VOLUME, SOUND_GROUPS, SOUNDS, parseSound, parseVolume, soundFile, soundGroup } from "./alarmSounds.mjs";

const NAMES = ["Klasik bip", "Siren", "Hızlı siren", "Çan", "Uyarı düdüğü", "Nabız", "Yükselen ton", "İkili korna",
  "Sonar", "Yumuşak gong"];

test("SOUNDS: 10 ses, benzersiz kimlik ve ad, spec sırasıyla; dosya /sounds/<id>.wav", () => {
  assert.equal(SOUNDS.length, 10);
  assert.deepEqual(SOUNDS.map((s) => s.id), Array.from({ length: 10 }, (_, i) => `alarm-${String(i + 1).padStart(2, "0")}`));
  assert.deepEqual(SOUNDS.map((s) => s.name), NAMES);
  assert.equal(new Set(SOUNDS.map((s) => s.id)).size, 10);
  assert.equal(new Set(SOUNDS.map((s) => s.name)).size, 10);
  for (const s of SOUNDS) assert.equal(s.file, `/sounds/${s.id}.wav`);
});

test("soundGroup: yangın/duman → fire, telefon → phone, diğerleri person", () => {
  assert.equal(soundGroup("fire"), "fire");
  assert.equal(soundGroup("smoke"), "fire");
  assert.equal(soundGroup("phone"), "phone");
  for (const t of ["hands_up", "lying", "test", "bilinmeyen"]) assert.equal(soundGroup(t), "person");
});

test("varsayılanlar: Siren, Hızlı siren, Klasik bip; düzey 0,8", () => {
  assert.deepEqual(DEFAULT_SOUND, { fire: "alarm-02", person: "alarm-03", phone: "alarm-01" });
  assert.equal(DEFAULT_VOLUME, 0.8);
});

test("SOUND_GROUPS: üç grup, ayar sırasıyla, Türkçe ad", () => {
  assert.deepEqual(SOUND_GROUPS.map((g) => g.id), ["fire", "person", "phone"]);
  assert.deepEqual(SOUND_GROUPS.map((g) => g.name), ["Yangın/duman", "Kişi alarmları", "Telefon kullanımı"]);
});

test("parseSound: bilinen kimlik kalır; eksik/geçersiz → grubun varsayılanı", () => {
  assert.equal(parseSound("fire", "alarm-07"), "alarm-07");
  assert.equal(parseSound("fire", null), "alarm-02");
  assert.equal(parseSound("person", ""), "alarm-03");
  assert.equal(parseSound("phone", "alarm-11"), "alarm-01");
  assert.equal(parseSound("phone", "../x"), "alarm-01");
});

test("parseVolume: 0–1 arası sayı kalır; eksik/geçersiz/aralık dışı → 0,8", () => {
  assert.equal(parseVolume("0.35"), 0.35);
  assert.equal(parseVolume("1"), 1);
  assert.equal(parseVolume("0"), 0);
  for (const raw of [null, "", "abc", "-0.1", "1.5", "NaN", "Infinity"]) assert.equal(parseVolume(raw), 0.8, String(raw));
});

test("soundFile: kimliğin dosyası; bilinmeyen kimlik → null", () => {
  assert.equal(soundFile("alarm-10"), "/sounds/alarm-10.wav");
  assert.equal(soundFile("alarm-00"), null);
});
