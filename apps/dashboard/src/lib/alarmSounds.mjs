// Alarm sesleri için saf yardımcılar (DOM'suz; node --test ile sınanır). Dosyalar `tools/make_alarm_sounds.py` ile
// sentezlenir ve panelle gelir (public/sounds/alarm-01.wav … alarm-10.wav).

const NAMES = ["Klasik bip", "Siren", "Hızlı siren", "Çan", "Uyarı düdüğü", "Nabız", "Yükselen ton", "İkili korna",
  "Sonar", "Yumuşak gong"];

/** On alarm sesi, ayardaki sırayla */
export const SOUNDS = Object.freeze(NAMES.map((name, i) => {
  const id = `alarm-${String(i + 1).padStart(2, "0")}`;
  return Object.freeze({ id, name, file: `/sounds/${id}.wav` });
}));

/** Ses seçiminin grupları (Bildirimler sayfasındaki sırayla) */
export const SOUND_GROUPS = Object.freeze([
  Object.freeze({ id: "fire", name: "Yangın/duman", hint: "yangın ve duman alarmları" }),
  Object.freeze({ id: "person", name: "Kişi alarmları", hint: "eller yukarı, yerde yatan, deneme alarmı" }),
  Object.freeze({ id: "phone", name: "Telefon kullanımı", hint: "uyarı; yeni uyarıda bir kez çalar" }),
]);

/** Grupların varsayılan sesi: Siren, Hızlı siren, Klasik bip */
export const DEFAULT_SOUND = Object.freeze({ fire: "alarm-02", person: "alarm-03", phone: "alarm-01" });
export const DEFAULT_VOLUME = 0.8;
/** En düşük ses düzeyi (%10): elle değiştirilmiş çerez alarmı sessize düşürmez */
export const MIN_VOLUME = 0.1;
/** Kritik alarmın sesi pencere açıkken bu aralıkla yeniden çalar */
export const SOUND_REPEAT_MS = 3000;

/** Alarm türünün ses grubu: yangın/duman → fire, telefon → phone, diğerleri (eller yukarı, yerde yatan, deneme) person */
export function soundGroup(type) {
  if (type === "fire" || type === "smoke") return "fire";
  if (type === "phone") return "phone";
  return "person";
}

/** Kimliğin dosya yolu; bilinmeyen kimlik → null */
export function soundFile(id) {
  return SOUNDS.find((s) => s.id === id)?.file ?? null;
}

/** Saklanan seçim: bilinen kimlik kalır, eksik/geçersiz → grubun varsayılanı */
export function parseSound(group, raw) {
  return typeof raw === "string" && soundFile(raw) !== null ? raw : DEFAULT_SOUND[group];
}

/** Saklanan ses düzeyi: 0–1 arası sayı kalır (0,1'in altı 0,1'e çekilir), eksik/geçersiz/aralık dışı → varsayılan */
export function parseVolume(raw) {
  if (typeof raw !== "string" || raw.trim() === "") return DEFAULT_VOLUME;
  const v = Number(raw);
  return Number.isFinite(v) && v >= 0 && v <= 1 ? Math.max(MIN_VOLUME, v) : DEFAULT_VOLUME;
}
