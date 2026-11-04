// Güvenlik alarmı (poz) videosu: yükleme formundaki kural alanlarının sözleşmedeki `options`a çevrilmesi ve sonuçtaki alarm
// listesinin tablo satırlarına dönüşmesi. Saf; `node --test` ile sınanır.
// contracts/analysis-job.schema.json (`options.safety`, `result.alarms`), docs/13-web-platform.md "Video ile test".

import { isAlarmImage } from "./resultFile.mjs";

/** Kural aralıkları ve varsayılanları: canlıdaki güvenlik kamerası ve analiz sunucusuyla aynı (saniye) */
export const SAFETY_RULES = {
  handsUp: { title: "Eller yukarı", min: 3, max: 5, def: 3 },
  lying: { title: "Yerde yatma", min: 5, max: 30, def: 10 },
};

export const NO_RULE_ON = "En az bir kural açık olmalı.";

/** Alarm türü → tablodaki ad */
export const ALARM_LABELS = { handsUp: "Eller yukarı", lying: "Yerde yatan kişi" };

const SECONDS = /^[0-9]+(?:[.,][0-9]+)?$/;

/** Form durumu: iki kural, her birinde işaret kutusu ve metin olarak saniye */
export function defaultSafetyForm() {
  return {
    handsUp: { enabled: true, seconds: String(SAFETY_RULES.handsUp.def) },
    lying: { enabled: true, seconds: String(SAFETY_RULES.lying.def) },
  };
}

/**
 * Formdan gönderilecek `options` (yalnızca preset ve kurallar; güvenlikte sayım ayarı gönderilmez) ya da Türkçe hata metni.
 * Kapalı kural `{enabled:false}` gider, süresi denetlenmez. Süre ondalıkta virgül ya da nokta alır.
 */
export function safetyOptions(form) {
  const safety = {};
  for (const [key, rule] of Object.entries(SAFETY_RULES)) {
    const f = form[key];
    if (!f.enabled) {
      safety[key] = { enabled: false };
      continue;
    }
    const text = String(f.seconds).trim();
    const sec = SECONDS.test(text) ? Number(text.replace(",", ".")) : Number.NaN;
    if (!(sec >= rule.min && sec <= rule.max)) return `${rule.title} süresi ${rule.min}–${rule.max} sn arasında bir sayı olmalı.`;
    safety[key] = { enabled: true, seconds: sec };
  }
  if (!Object.values(safety).some((r) => r.enabled)) return NO_RULE_ON;
  return { preset: "safety", safety };
}

/** Saniye → `mm:ss` (aşağı yuvarlanır; bir saati aşan videoda dakika büyür). Sayı değilse "—" */
export function formatClock(s) {
  if (typeof s !== "number" || !Number.isFinite(s)) return "—";
  const t = Math.max(0, Math.floor(s));
  return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
}

/**
 * Sonuçtaki alarmlar → tablo satırları. Resim yalnızca `files` içinde listeliyse gösterilir (süresi dolan işte `files`
 * boştur ve resimler gitmiştir); sözleşme dışı ad hiç kullanılmaz. Süre: `endS` yoksa "—", yoksa `endS − startS` yuvarlanmış.
 */
export function alarmRows(result) {
  const files = new Set(result?.files ?? []);
  return (result?.alarms ?? []).map((a, key) => ({
    key,
    kind: a.kind,
    label: ALARM_LABELS[a.kind] ?? String(a.kind),
    startS: a.startS,
    clock: formatClock(a.startS),
    duration: a.endS === null || a.endS === undefined ? "—" : `${Math.round(Math.max(0, a.endS - a.startS))} sn`,
    image: isAlarmImage(a.image) && files.has(a.image) ? a.image : null,
  }));
}

/** İşin kuralları tek satırda ("Eller yukarı 3 sn · Yerde yatan kişi kapalı"); verilmeyen alan varsayılandır */
export function rulesSummary(safety) {
  return Object.entries(SAFETY_RULES).map(([key, rule]) => {
    const r = safety?.[key];
    if (r?.enabled === false) return `${ALARM_LABELS[key]} kapalı`;
    return `${ALARM_LABELS[key]} ${(r?.seconds ?? rule.def).toLocaleString("tr-TR")} sn`;
  }).join(" · ");
}
