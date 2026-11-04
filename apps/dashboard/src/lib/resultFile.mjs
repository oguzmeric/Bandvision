// Analiz sunucusunun herkese açık sonuç dosyaları (contracts/analysis-job.schema.json `result.files`): vekil yalnızca bu
// adları iletir. Saf ve içe aktarmasız; `node --test` ile sınanır. Analiz sunucusundaki `is_public_file` ile aynı kural.

export const FIXED_RESULT_FILES = Object.freeze(["annotated.mp4", "counts.csv", "alarms.csv", "profile.json", "background.png"]);

/** Alarm resmi: yalnızca bu ad (tam eşleşme: yol, uzantı eki, büyük harf, boşluk ve satır sonu geçmez) */
const ALARM_IMAGE = /^alarm-[0-9]{1,2}\.jpg$/;

/** `name` bir alarm resmi (`alarm-N.jpg`) mi */
export function isAlarmImage(name) {
  return typeof name === "string" && ALARM_IMAGE.test(name);
}

/** `name` sabit adlardan biri ya da `alarm-N.jpg` mi */
export function isResultFile(name) {
  return typeof name === "string" && (FIXED_RESULT_FILES.includes(name) || isAlarmImage(name));
}
