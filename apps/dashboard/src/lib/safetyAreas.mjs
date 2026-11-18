// Güvenlik (poz) ve telefon kameralarının "Analiz alanları": Ayarla panelinin (SafetyAreas, ZonesEditor) saf mantığı —
// sınırlar, profildeki `safety.areas`ın okunması, yeni alanın adı ve yeri, ad/kural değişikliği, boş listenin profilden
// düşmesi. Saf; `node --test` ile sınanır. Sözleşme: contracts/product-profile.schema.json `safety.areas` (en çok 16 alan;
// ad 1–40 karakter, kırpılmış; 3–12 köşe, 0–1; kurallar `handsUp`/`lying`/`phone`ın boş olmayan alt kümesi; boşsa yazılmaz).

export const MAX_AREAS = 16;
export const AREA_NAME_MAX = 40;
/** Alanda seçilebilen kurallar, sırasıyla; adları Ayarla panelindeki kural adlarıyla aynı */
export const AREA_RULES = ["handsUp", "lying", "phone"];
export const AREA_RULE_LABELS = { handsUp: "Eller yukarı", lying: "Yerde yatan kişi", phone: "Telefon kullanımı" };
export const AREAS_HELP = "Boş bırakırsanız bütün görüntü izlenir.";

/** Profilde kuralın `enabled`ı yoksa (eski profil) varsayılanı: eller yukarı ve yerde yatan açık, telefon kapalı */
const RULE_ON_BY_DEFAULT = { handsUp: true, lying: true, phone: false };

const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const r4 = (v) => Math.round(v * 1e4) / 1e4;
const clamp01 = (v) => r4(Math.min(1, Math.max(0, v)));

/** Kamerada açık kurallar (AREA_RULES sırasıyla) */
export function enabledRules(safety) {
  return AREA_RULES.filter((k) => {
    const on = safety?.[k]?.enabled;
    return typeof on === "boolean" ? on : RULE_ON_BY_DEFAULT[k];
  });
}

/**
 * Profildeki (eksik ya da eski) `safety.areas` → alan listesi (kopya; düzenleme kaynağı değiştirmez). Liste değilse boş;
 * nesne olmayan öğe atlanır, köşelerden sayı çifti olmayan, kurallardan bilinmeyen ya da yinelenen düşer.
 */
export function safetyAreas(safety) {
  const list = Array.isArray(safety?.areas) ? safety.areas : [];
  return list.filter((a) => a && typeof a === "object").map((a) => ({
    name: typeof a.name === "string" ? a.name : "",
    points: Array.isArray(a.points)
      ? a.points.filter((p) => Array.isArray(p) && p.length === 2 && isNum(p[0]) && isNum(p[1])).map((p) => [p[0], p[1]])
      : [],
    rules: Array.isArray(a.rules) ? [...new Set(a.rules.filter((k) => AREA_RULES.includes(k)))] : [],
  }));
}

/** Yeni alanın adı: "Alan N", N kullanılmayan en küçük sayı (adlar kırpılarak karşılaştırılır) */
export function nextAreaName(areas) {
  const taken = new Set(areas.map((a) => a.name.trim()));
  let n = 1;
  while (taken.has(`Alan ${n}`)) n += 1;
  return `Alan ${n}`;
}

/** `i`. yuvanın başlangıç karesi (0,16 × 0,16): 16 alan üst üste binmesin diye 4 sütun × 4 satır yerleşir */
export function areaSlot(i) {
  const x = 0.04 + (i % 4) * 0.24, y = 0.04 + (Math.floor(i / 4) % 4) * 0.24;
  return [[x, y], [x + 0.16, y], [x + 0.16, y + 0.16], [x, y + 0.16]].map((p) => [clamp01(p[0]), clamp01(p[1])]);
}

/**
 * Yeni alan ekler: adı `nextAreaName`, kuralları `rules` (kamerada açık olanlar), yeri mevcut bir alanla aynı olmayan ilk
 * yuva. Sınırdaysa (16) ya da kamerada açık kural yoksa liste değişmez.
 */
export function addArea(areas, rules) {
  const on = AREA_RULES.filter((k) => rules.includes(k));
  if (areas.length >= MAX_AREAS || on.length === 0) return areas;
  const taken = new Set(areas.map((a) => JSON.stringify(a.points)));
  let points = areaSlot(areas.length);
  for (let i = 0; i < MAX_AREAS; i++) {
    const slot = areaSlot(i);
    if (!taken.has(JSON.stringify(slot))) { points = slot; break; }
  }
  return [...areas, { name: nextAreaName(areas), points, rules: on }];
}

export function removeArea(areas, i) {
  return areas.filter((_, k) => k !== i);
}

/** Alanın adı: kırpılır, en çok 40 karakter; kırpınca boş kalırsa liste değişmez (boş ad kaydedilmez) */
export function renameArea(areas, i, raw) {
  const name = String(raw).trim().slice(0, AREA_NAME_MAX).trim();
  if (!name || !areas[i]) return areas;
  return areas.map((a, k) => (k === i ? { ...a, name } : a));
}

/** Alanda kuralı açar/kapatır (AREA_RULES sırasıyla yazılır); son kural kapatılamaz (alanın en az bir kuralı olmalı) */
export function toggleAreaRule(areas, i, rule, on) {
  const a = areas[i];
  if (!a || !AREA_RULES.includes(rule)) return areas;
  const rules = AREA_RULES.filter((k) => (k === rule ? on : a.rules.includes(k)));
  if (rules.length === 0) return areas;
  return areas.map((x, k) => (k === i ? { ...x, rules } : x));
}

/** Çokgen düzenleyicinin köşeleri (sıra alan listesiyle aynı) alanlara yazılır */
export function withAreaPoints(areas, zones) {
  return areas.map((a, i) => (Array.isArray(zones[i]) ? { ...a, points: zones[i] } : a));
}

/** `safety` bloğuna alan listesi: boşsa `areas` anahtarı hiç yazılmaz (bütün görüntü, bütün açık kurallar) */
export function withAreas(safety, areas) {
  const rest = { ...safety };
  delete rest.areas;
  return areas.length ? { ...rest, areas } : rest;
}

/** Adı (kırpılmış) başka bir alanınkiyle aynı olan alanların sırası: alarm yalnız adı taşıdığından hangisi olduğu
 * ayırt edilemez (izin verilir, panel uyarır) */
export function duplicateAreaNames(areas) {
  const count = new Map();
  for (const a of areas) count.set(a.name.trim(), (count.get(a.name.trim()) ?? 0) + 1);
  return new Set(areas.flatMap((a, i) => (count.get(a.name.trim()) > 1 ? [i] : [])));
}

/** "+ Alan ekle" neden kapalı (düğmenin yanında yazılır); eklenebiliyorsa null */
export function addAreaBlocked(areas, rules) {
  if (areas.length >= MAX_AREAS) return `En çok ${MAX_AREAS} alan eklenebilir.`;
  if (!AREA_RULES.some((k) => rules.includes(k))) return "Önce kamerada bir kuralı açın.";
  return null;
}

/** Alanın kamerada açık bir kuralı var mı (yoksa alan bir şey izlemez) */
export function areaWatches(area, safety) {
  const on = enabledRules(safety);
  return area.rules.some((k) => on.includes(k));
}
