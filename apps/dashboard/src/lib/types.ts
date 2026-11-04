/** contracts/analysis-job.schema.json (bantvision.analysis-job.v1) — panelin okuduğu kısmı. */

export type JobStatus = "queued" | "running" | "done" | "failed" | "expired";
export type JobStage = "calibrating" | "counting" | "encoding";
export type Preset = "generic" | "egg" | "flour" | "box" | "people" | "vehicle" | "animal" | "safety";
export type CountMode = "blob" | "linescan" | "detect" | "safety";
/** Kişi sayımı: kamera tepeden (center) ya da yandan/eğik (bottom, çizgi zeminde) */
export type CountAnchor = "center" | "bottom";
export type Direction = "down" | "up" | "right" | "left";
export type ResultFile = "annotated.mp4" | "counts.csv" | "alarms.csv" | "profile.json" | "background.png";
/** Güvenlik alarmı: pozun türü */
export type AlarmKind = "handsUp" | "lying";

/** Güvenlik kuralı: verilmeyen alan varsayılana düşer (eller yukarı 3 sn, yerde yatma 10 sn); en az biri açık olmalı */
export interface SafetyRule {
  enabled?: boolean;
  seconds?: number;
}

/** `result.alarms` öğesi: süreler video saniyesi; `endS` null ise bitiş bilinmiyor; resim yalnızca ilk 50 alarmda */
export interface Alarm {
  kind: AlarmKind;
  trackId: number;
  startS: number;
  atS: number;
  endS: number | null;
  image: string | null;
}

export interface Point {
  x: number;
  y: number;
}

export interface JobOptions {
  preset?: Preset;
  countMode?: CountMode;
  countAnchor?: CountAnchor;
  productLength?: number;
  truth?: number;
  direction?: Direction;
  roi?: { x: number; y: number; width: number; height: number };
  roiPolygon?: Point[];
  countLine?: { a: Point; b: Point };
  line?: number;
  bgRange?: [number, number];
  /** Yalnızca preset safety */
  safety?: { handsUp?: SafetyRule; lying?: SafetyRule };
}

export interface AnalysisJob {
  schema: "bantvision.analysis-job.v1";
  id: string;
  status: JobStatus;
  createdAt: string;
  updatedAt: string;
  expiresAt: string;
  video: { name: string; sizeBytes: number; seconds?: number; fps?: number; width?: number; height?: number };
  options: JobOptions;
  progress: number;
  stage?: JobStage;
  result?: {
    /** Sayılan adet; iki yönlü sayımda giriş; güvenlikte alarm sayısı */
    count: number;
    /** Yalnızca iki yönlü sayımda (kişi, araç, hayvan): çıkış */
    countOut?: number;
    truth: number | null;
    errorPct: number | null;
    calibration?: {
      countMode?: CountMode;
      productLength?: number;
      threshold?: number;
      direction?: Direction;
      background?: string;
      expectedArea?: number;
      areaSamples?: number;
      notes?: string[];
    };
    processingFps: number | null;
    /** Yalnızca güvenlik işinde: alarm listesi (en çok 500; `count` gerçek toplam) */
    alarms?: Alarm[];
    /** Modelin çalıştığı cihaz (yalnız model kullanan analizlerde) */
    device?: { kind: "cpu" | "gpu"; name: string; note?: string | null };
    /** Sabit adlar ve `alarm-N.jpg` resimleri */
    files: (ResultFile | `alarm-${number}.jpg`)[];
  };
  error?: string;
}

export const PRESET_LABELS: Record<Preset, string> = {
  egg: "Yumurta",
  flour: "Un torbası",
  box: "Koli / kutu",
  generic: "Genel ürün",
  people: "Kişi (mağaza girişi)",
  vehicle: "Araç (giriş / çıkış)",
  animal: "Hayvan (giriş / çıkış)",
  safety: "Güvenlik alarmı (poz)",
};

/** Kişi gibi iki yönlü (giriş / çıkış) sayılan ön ayarlar */
export const TWO_WAY_PRESETS: Preset[] = ["people", "vehicle", "animal"];

/** İki yönlü ön ayarın metinlerdeki adları: çoğul, tamlayan ve geçiş alanının adı (sayım çizgisi yönergesi) */
export const TWO_WAY_NOUNS: Record<"people" | "vehicle" | "animal", { plural: string; genitive: string; area: string }> = {
  people: { plural: "kişiler", genitive: "kişilerin", area: "yürüme alanının" },
  vehicle: { plural: "araçlar", genitive: "araçların", area: "geçiş alanının" },
  animal: { plural: "hayvanlar", genitive: "hayvanların", area: "geçiş alanının" },
};

/** Hazır profilin varsayılan sayım yöntemi (services/edge Profile ile aynı) */
export const PRESET_MODE: Record<Preset, CountMode> = {
  egg: "blob", flour: "linescan", box: "linescan", generic: "blob", people: "detect", vehicle: "detect", animal: "detect",
  safety: "safety",
};

export const MODE_LABELS: Record<CountMode, string> = {
  blob: "Ayrık ürün (arka plan farkı)",
  linescan: "Bitişik / hacimli (şerit tarama)",
  detect: "Kişi tanıma (giriş / çıkış)",
  safety: "Güvenlik",
};

/** Bant üstü ürün yöntemleri (yöntem seçicisi); kişi tanıma hazır profille gelir */
export const BELT_MODES: CountMode[] = ["blob", "linescan"];

export const ANCHOR_LABELS: Record<CountAnchor, string> = {
  center: "Tepeden bakıyor",
  bottom: "Yandan / eğik bakıyor",
};

export const DIRECTION_LABELS: Record<Direction, string> = {
  down: "Yukarıdan aşağı",
  up: "Aşağıdan yukarı",
  right: "Soldan sağa",
  left: "Sağdan sola",
};

/** Güvenlik alarmı (poz) işi: sonuç sayım değil alarm listesidir */
export const isSafetyJob = (job: Pick<AnalysisJob, "options" | "result">) =>
  job.options.preset === "safety" || job.result?.alarms !== undefined;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const isJobId = (id: string) => UUID.test(id);
