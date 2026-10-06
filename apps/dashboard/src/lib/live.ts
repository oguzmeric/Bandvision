/** Canlı sayım API'si (analiz sunucusu `/api/v1/live`, panel vekili `/api/live`) — services/edge/bantvision/live/api.py */
import type { CountAnchor, CountMode, Direction, Point } from "./types";

export type SourceKind = "camera" | "recorder";
export type CameraBrand = "hikvision" | "dahua" | "axis" | "vivotek" | "milesight" | "custom";
export type RecorderBrand = "trassir" | "hikvision" | "dahua";

export interface Source {
  id: string;
  kind: SourceKind;
  name: string;
  brand: CameraBrand;
  host: string;
  port: number;
  channel: number;
  substream: boolean;
  customUrl: string;
  recorderBrand: RecorderBrand;
  httpPort: number | null;
  rtspPort: number | null;
  username: string;
  hasPassword: boolean;
  createdAt: number;
}

export type SourceForm = Omit<Source, "id" | "hasPassword" | "createdAt"> & { password?: string | null };

export interface Channel {
  id: string;
  name: string;
  number: number | null;
  title: string;
  hasSubstream: boolean;
}

/** Personel üniforma rengi (CIE Lab, D65; sözleşme `staffColors`) */
export interface LabColor { L: number; a: number; b: number }

/** Profil (sözleşme `product-profile.schema.json`); panelin kullandığı alanlar, gerisi olduğu gibi taşınır */
export interface Profile {
  id: string;
  name: string;
  roi: { x: number; y: number; width: number; height: number };
  roiPolygon?: Point[];
  countLine?: { a: Point; b: Point };
  linePosition: number;
  direction: Direction;
  diffThreshold: number;
  expectedArea: number;
  splitTouching: boolean;
  countMode?: CountMode;
  productLength?: number;
  countAnchor?: CountAnchor;
  /** Kişi sayımı: personel renkleri (en çok 3); yoksa kapalı */
  staffColors?: LabColor[];
  [key: string]: unknown;
}

export interface CatalogCategory {
  id: string;
  title: string;
  subtitle: string;
  available: boolean;
  presets: Array<{ key: string; name: string }>;
}

export interface LiveSession {
  id: string;
  name: string;
  state: "connecting" | "live" | "reconnecting" | "ended" | "error" | "stopped";
  message: string;
  fps: number;
  width: number;
  height: number;
  counting: boolean;
  total: number;
  totalOut: number;
  /** Kişi sayımı: personel geçişleri (giriş/çıkışa eklenmez) */
  staffIn: number;
  staffOut: number;
  twoWay: boolean;
  ratePerMinute: number;
  calibrating: "background" | "sample" | null;
  calibrationMessage: string;
  profile: Profile;
  sourceId: string | null;
  channelId: string | null;
  profileId: string | null;
  /** true alt akış (hızlı), false ana akış (net); null: kaynak ayarı bilinmiyor */
  substream: boolean | null;
}

export const CAMERA_BRANDS: Array<[CameraBrand, string]> = [
  ["hikvision", "Hikvision"], ["dahua", "Dahua"], ["axis", "Axis"], ["vivotek", "Vivotek"],
  ["milesight", "Milesight"], ["custom", "Diğer (tam RTSP adresi)"],
];
export const RECORDER_BRANDS: Array<[RecorderBrand, string, number, number]> = [
  ["trassir", "TRASSIR", 8080, 555], ["hikvision", "Hikvision", 80, 554], ["dahua", "Dahua", 80, 554],
];

export const STATE_LABELS: Record<LiveSession["state"], string> = {
  connecting: "Bağlanıyor…",
  live: "Canlı",
  reconnecting: "Yeniden bağlanıyor…",
  ended: "Video bitti",
  error: "Hata",
  stopped: "Kapandı",
};

/** JSON isteği; hata gövdesindeki `detail` Türkçe iletiyle fırlatılır */
const FIELD_LABELS: Record<string, string> = {
  host: "IP adresi", port: "RTSP portu", channel: "Kanal", httpPort: "Web/SDK portu", rtspPort: "Görüntü portu",
  username: "Kullanıcı adı", password: "Şifre", name: "Ad", customUrl: "RTSP adresi",
};

/** Sunucunun alan doğrulama hataları (FastAPI 422) → kullanıcıya Türkçe, tekrarsız ileti */
function validationMessage(errors: unknown[]): string {
  const msgs = errors.map((e) => {
    const { type = "", loc = [] } = e as { type?: string; loc?: unknown[] };
    const field = String(loc[loc.length - 1] ?? "");
    const label = FIELD_LABELS[field] ?? field;
    if (type.startsWith("greater_than") || type.startsWith("less_than")) return `${label}: geçersiz sayı.`;
    if (type === "string_too_long") return `${label} çok uzun.`;
    if (type === "extra_forbidden") return "Panel ile analiz sunucusu sürümleri uyuşmuyor; ikisini de güncelleyip yeniden başlatın.";
    return `${label || "Bilgi"} geçersiz.`;
  });
  return [...new Set(msgs)].join(" ");
}

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const res = await fetch(`/api/live/${path}`, {
    cache: "no-store",
    ...rest,
    headers: json !== undefined ? { "content-type": "application/json", ...(rest.headers ?? {}) } : rest.headers,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const d = (body as { detail?: unknown } | null)?.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? validationMessage(d)
      : `İstek başarısız (HTTP ${res.status}).`);
  }
  return body as T;
}
