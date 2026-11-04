import { TWO_WAY_NOUNS, isSafetyJob, type AnalysisJob } from "./types";

/** Aşama adları: bant üstü ürün ve iki yönlü sayımda kalibrasyon/sayım; güvenlik alarmında kalibrasyon yoktur */
const STAGE_COUNTING = {
  long: { calibrating: "Kalibrasyon: arka plan, eşik ve ürün boyu öğreniliyor", counting: "Sayılıyor", encoding: "İşaretli video hazırlanıyor" },
  short: { calibrating: "Kalibrasyon", counting: "Sayılıyor", encoding: "Video hazırlanıyor" },
} as const;
const STAGE_SAFETY = {
  long: { calibrating: "Hazırlanıyor", counting: "Alarm analizi", encoding: "İşaretli video hazırlanıyor" },
  short: { calibrating: "Hazırlanıyor", counting: "Alarm analizi", encoding: "Video hazırlanıyor" },
} as const;

/** Sürmekte olan işin aşama metni; `form`: ayrıntıda uzun, listede kısa */
export function stageText(job: Pick<AnalysisJob, "options" | "result" | "stage">, form: "long" | "short"): string | undefined {
  const stages = isSafetyJob(job) ? STAGE_SAFETY : STAGE_COUNTING;
  return job.stage ? stages[form][job.stage] : undefined;
}

/** Başarısız işin ipucu: işe uygun (bant tavsiyesi yalnızca bant üstü ürün sayımında) */
export function failureHint(job: Pick<AnalysisJob, "options" | "result">): string {
  if (isSafetyJob(job)) {
    return "İpucu: video açılabiliyor ve kamera sabit olmalı; karedeki kişiler net görünmeli. Sorun sürerse videoyu yeniden yükle.";
  }
  const preset = job.options.preset;
  if (preset === "people" || preset === "vehicle" || preset === "animal") {
    return `İpucu: kamera sabit olmalı ve sayılacak ${TWO_WAY_NOUNS[preset].plural} karede net görünmeli. Giriş yönünü ve sayım çizgisini kontrol edip yeniden dene.`;
  }
  return "İpucu: video sabit kamerayla, bandın tepesinden çekilmiş olmalı. Bant başta doluysa \"boş bant aralığı\"nı belirterek yeniden dene.";
}
