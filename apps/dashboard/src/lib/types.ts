/** contracts/analysis-job.schema.json (bantvision.analysis-job.v1) — panelin okuduğu kısmı. */

export type JobStatus = "queued" | "running" | "done" | "failed" | "expired";
export type JobStage = "calibrating" | "counting" | "encoding";
export type Preset = "generic" | "egg" | "flour" | "box";
export type CountMode = "blob" | "linescan";
export type Direction = "down" | "up" | "right" | "left";
export type ResultFile = "annotated.mp4" | "counts.csv" | "profile.json" | "background.png";

export interface Point {
  x: number;
  y: number;
}

export interface JobOptions {
  preset?: Preset;
  countMode?: CountMode;
  productLength?: number;
  truth?: number;
  direction?: Direction;
  roi?: { x: number; y: number; width: number; height: number };
  roiPolygon?: Point[];
  countLine?: { a: Point; b: Point };
  line?: number;
  bgRange?: [number, number];
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
    count: number;
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
    files: ResultFile[];
  };
  error?: string;
}

export const RESULT_FILES: ResultFile[] = ["annotated.mp4", "counts.csv", "profile.json", "background.png"];

export const PRESET_LABELS: Record<Preset, string> = {
  egg: "Yumurta",
  flour: "Un torbası",
  box: "Koli / kutu",
  generic: "Genel ürün",
};

/** Hazır profilin varsayılan sayım yöntemi (services/edge Profile ile aynı) */
export const PRESET_MODE: Record<Preset, CountMode> = { egg: "blob", flour: "linescan", box: "linescan", generic: "blob" };

export const MODE_LABELS: Record<CountMode, string> = {
  blob: "Ayrık ürün (arka plan farkı)",
  linescan: "Bitişik / hacimli (şerit tarama)",
};

export const DIRECTION_LABELS: Record<Direction, string> = {
  down: "Yukarıdan aşağı",
  up: "Aşağıdan yukarı",
  right: "Soldan sağa",
  left: "Sağdan sola",
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const isJobId = (id: string) => UUID.test(id);
