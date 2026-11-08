// Yangın/duman: canlı ayar panelinin (FireSettings, ZonesEditor) ve video ile testin saf mantığı — kural aralıkları,
// hassasiyet adları, yükleme formunun `options`a çevrilmesi, model durumu satırı ve hariç bölge (çokgen) işlemleri.
// Saf; `node --test` ile sınanır. Aralıklar analiz sunucusuyla aynı: services/edge/bantvision/live/api.py `_check_fire`,
// analyzer/app.py `FireIn`; sözleşme contracts/product-profile.schema.json `fire`, analysis-job.schema.json `options.fire`.

import { NO_RULE_ON } from "./safetyAlarms.mjs";

/** Kural aralıkları ve varsayılanları (saniye) */
export const FIRE_RULES = {
  fire: { title: "Yangın", min: 2, max: 10, def: 3 },
  smoke: { title: "Duman", min: 5, max: 30, def: 8 },
};

/** Hassasiyet seçenekleri, sırasıyla; adlar */
export const SENSITIVITIES = ["low", "normal", "high"];
export const SENSITIVITY_LABELS = { low: "Düşük", normal: "Normal", high: "Yüksek" };

/** Sabit uyarı: ayar panelinde ve izleme panelinde her zaman görünür */
export const FIRE_WARNING = "Erken uyarıdır; yangın algılama ve alarm sisteminin yerine geçmez.";
/** Analiz sunucusunun model dosyası yokken verdiği neden (R3) */
export const FIRE_MODEL_MISSING = "Yangın/duman modeli kurulu değil.";

/** Hariç bölge sınırları: en çok 8 çokgen, çokgen başına 3–12 köşe, köşeler 0–1 */
export const MAX_ZONES = 8;
export const MIN_ZONE_POINTS = 3;
export const MAX_ZONE_POINTS = 12;

/** Canlı profilin `fire` bloğunun varsayılanları (sunucudaki FireConfig ile aynı) */
export const FIRE_DEFAULTS = Object.freeze({
  fire: Object.freeze({ enabled: true, seconds: 3 }),
  smoke: Object.freeze({ enabled: true, seconds: 8 }),
  sensitivity: "normal",
  ignoreZones: Object.freeze([]),
  sendImage: false,
});

const isNum = (v) => typeof v === "number" && Number.isFinite(v);

function rule(v, def) {
  const r = v && typeof v === "object" ? v : {};
  return {
    enabled: typeof r.enabled === "boolean" ? r.enabled : def.enabled,
    seconds: isNum(r.seconds) ? r.seconds : def.seconds,
  };
}

/**
 * Profildeki (eksik ya da eski) `fire` bloğu → tam ayar: verilmeyen ya da türü yanlış alan varsayılana düşer. Hariç
 * bölgelerin köşeleri `[x, y]` dizisi olarak kopyalanır (düzenleme kaynağı değiştirmez).
 */
export function fireConfig(v) {
  const f = v && typeof v === "object" ? v : {};
  const zones = Array.isArray(f.ignoreZones)
    ? f.ignoreZones.filter((z) => Array.isArray(z)).map((z) => z.filter((p) => Array.isArray(p) && p.length === 2 && isNum(p[0]) && isNum(p[1]))
      .map((p) => [p[0], p[1]]))
    : [];
  return {
    fire: rule(f.fire, FIRE_DEFAULTS.fire),
    smoke: rule(f.smoke, FIRE_DEFAULTS.smoke),
    sensitivity: SENSITIVITIES.includes(f.sensitivity) ? f.sensitivity : FIRE_DEFAULTS.sensitivity,
    ignoreZones: zones,
    sendImage: typeof f.sendImage === "boolean" ? f.sendImage : FIRE_DEFAULTS.sendImage,
  };
}

/**
 * Modelin durum satırı ("Yangın/duman modeli: hazır / yükleniyor / kurulu değil"); oturumun `fire` bloğundan. Blok ya
 * da model alanı yoksa (eski sunucu, başka yöntem) null. `tone`: "ok" hazır, "muted" yükleniyor, "warn" kurulu değil ya da
 * yüklenemedi (yüklenemediyse sunucunun nedeni eklenir).
 */
export function fireModelLine(status) {
  const model = status?.model;
  if (model === "ready") return { text: "Yangın/duman modeli: hazır", tone: "ok" };
  if (model === "loading") return { text: "Yangın/duman modeli: yükleniyor", tone: "muted" };
  if (model === "error") {
    const err = typeof status.modelError === "string" ? status.modelError.trim() : "";
    if (!err || err === FIRE_MODEL_MISSING || err.includes("kurulu değil")) return { text: "Yangın/duman modeli: kurulu değil", tone: "warn" };
    return { text: `Yangın/duman modeli: yüklenemedi — ${err}`, tone: "warn" };
  }
  return null;
}

// ------------------------------------------------------------------------------------------------ video ile test

const SECONDS = /^[0-9]+(?:[.,][0-9]+)?$/;

/** Yükleme formunun yangın/duman durumu: iki kural (işaret kutusu, metin olarak saniye) ve hassasiyet */
export function defaultFireForm() {
  return {
    fire: { enabled: true, seconds: String(FIRE_RULES.fire.def) },
    smoke: { enabled: true, seconds: String(FIRE_RULES.smoke.def) },
    sensitivity: "normal",
  };
}

/**
 * Formdan gönderilecek `options` (`{preset: "fire", fire: {fire, smoke, sensitivity}}`; sayım ayarı yok) ya da Türkçe
 * hata metni (analiz sunucusunun iletisiyle aynı). Kapalı kural `{enabled: false}` gider, süresi denetlenmez.
 */
export function fireOptions(form) {
  const fire = {};
  for (const [key, r] of Object.entries(FIRE_RULES)) {
    const f = form[key];
    if (!f.enabled) {
      fire[key] = { enabled: false };
      continue;
    }
    const text = String(f.seconds).trim();
    const sec = SECONDS.test(text) ? Number(text.replace(",", ".")) : Number.NaN;
    if (!(sec >= r.min && sec <= r.max)) return `${r.title} süresi ${r.min}–${r.max} sn arasında bir sayı olmalı.`;
    fire[key] = { enabled: true, seconds: sec };
  }
  if (!fire.fire.enabled && !fire.smoke.enabled) return NO_RULE_ON;
  fire.sensitivity = SENSITIVITIES.includes(form.sensitivity) ? form.sensitivity : "normal";
  return { preset: "fire", fire };
}

/** İşin kuralları tek satırda ("Yangın 3 sn · Duman kapalı · Hassasiyet: Normal"); verilmeyen alan varsayılandır */
export function fireRulesSummary(fire) {
  const parts = Object.entries(FIRE_RULES).map(([key, r]) => {
    const v = fire?.[key];
    if (v?.enabled === false) return `${r.title} kapalı`;
    return `${r.title} ${(v?.seconds ?? r.def).toLocaleString("tr-TR")} sn`;
  });
  const s = SENSITIVITIES.includes(fire?.sensitivity) ? fire.sensitivity : "normal";
  return [...parts, `Hassasiyet: ${SENSITIVITY_LABELS[s]}`].join(" · ");
}

// ------------------------------------------------------------------------------------------------ hariç bölgeler

const r4 = (v) => Math.round(v * 1e4) / 1e4;
const clamp01 = (v) => r4(Math.min(1, Math.max(0, v)));
const clampPt = (p) => [clamp01(p[0]), clamp01(p[1])];

/** `i`. yeni bölgenin başlangıç karesi (0,2 × 0,2): bölgeler üst üste binmesin diye 4 sütun × 2 satır yerleşir */
export function newZone(i) {
  const x = 0.1 + (i % 4) * 0.2, y = 0.15 + (Math.floor(i / 4) % 2) * 0.45;
  return [[x, y], [x + 0.2, y], [x + 0.2, y + 0.2], [x, y + 0.2]].map(clampPt);
}

/** Yeni bölge ekler; sınırdaysa (8) değişmez. Yeri mevcut bir bölgeyle aynı olmayan ilk boş yuva (bölge silinince
 * sıradaki yuva dolu kalabilir: yeni bölge onun tam üstüne binmesin); hepsi doluysa sıradaki yuva. */
export function addZone(zones) {
  if (zones.length >= MAX_ZONES) return zones;
  const taken = new Set(zones.map((z) => JSON.stringify(z)));
  for (let i = 0; i < MAX_ZONES; i++) {
    const zone = newZone(i);
    if (!taken.has(JSON.stringify(zone))) return [...zones, zone];
  }
  return [...zones, newZone(zones.length)];
}

export function removeZone(zones, z) {
  return zones.filter((_, i) => i !== z);
}

/** Köşeyi taşır (görüntünün içine kırpılır) */
export function moveVertex(zones, z, v, pt) {
  return zones.map((zone, i) => (i !== z ? zone : zone.map((p, k) => (k === v ? clampPt(pt) : p))));
}

/** `after` köşesinden sonra köşe ekler; bölge 12 köşedeyse değişmez */
export function insertVertex(zones, z, after, pt) {
  const zone = zones[z];
  if (!zone || zone.length >= MAX_ZONE_POINTS) return zones;
  const next = [...zone];
  next.splice(after + 1, 0, clampPt(pt));
  return zones.map((q, i) => (i === z ? next : q));
}

/** Köşeyi siler; bölge 3 köşedeyse değişmez (üçgenden az olamaz) */
export function deleteVertex(zones, z, v) {
  const zone = zones[z];
  if (!zone || zone.length <= MIN_ZONE_POINTS) return zones;
  return zones.map((q, i) => (i === z ? q.filter((_, k) => k !== v) : q));
}

/** Bölgeyi bütün olarak kaydırır (`zones0`: sürüklemenin başındaki durum); hiçbir köşe görüntüden taşmaz */
export function translateZone(zones0, z, dx, dy) {
  const zone = zones0[z];
  if (!zone) return zones0;
  const xs = zone.map((p) => p[0]), ys = zone.map((p) => p[1]);
  const mx = Math.min(Math.max(dx, -Math.min(...xs)), 1 - Math.max(...xs));
  const my = Math.min(Math.max(dy, -Math.min(...ys)), 1 - Math.max(...ys));
  return zones0.map((q, i) => (i === z ? q.map((p) => clampPt([p[0] + mx, p[1] + my])) : q));
}

/** Nokta çokgenin içinde mi (çift-tek kuralı; normalize koordinat) */
export function insideZone(zone, p) {
  let inside = false;
  for (let k = 0, j = zone.length - 1; k < zone.length; j = k++) {
    const a = zone[k], b = zone[j];
    if ((a[1] > p[1]) !== (b[1] > p[1]) && p[0] < ((b[0] - a[0]) * (p[1] - a[1])) / (b[1] - a[1]) + a[0]) inside = !inside;
  }
  return inside;
}

/** Hariç bölgeler sunucunun kabul edeceği biçimde mi: değilse Türkçe neden, uygunsa null */
export function zonesProblem(zones) {
  if (!Array.isArray(zones)) return "Hariç bölgeler bir liste olmalı.";
  if (zones.length > MAX_ZONES) return `En çok ${MAX_ZONES} hariç bölge çizilebilir.`;
  for (const z of zones) {
    if (!Array.isArray(z) || z.length < MIN_ZONE_POINTS || z.length > MAX_ZONE_POINTS) {
      return `Her hariç bölge ${MIN_ZONE_POINTS}–${MAX_ZONE_POINTS} köşeli bir çokgen olmalı.`;
    }
    for (const p of z) {
      if (!Array.isArray(p) || p.length !== 2 || !p.every((c) => isNum(c) && c >= 0 && c <= 1)) {
        return "Hariç bölge köşeleri görüntünün içinde olmalı.";
      }
    }
  }
  return null;
}
