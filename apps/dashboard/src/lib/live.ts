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

/** Poz güvenlik alarmı ayarları (sözleşme `safety`) */
export interface SafetyConfig {
  handsUp: { enabled: boolean; seconds: number };
  lying: { enabled: boolean; seconds: number };
  sendImage: boolean;
}

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
  /** Güvenlik (`countMode = "safety"`): poz alarmı ayarları; yoksa varsayılanlar */
  safety?: SafetyConfig;
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
  /** Güvenlik oturumunda: süren bölümler, son alarm zamanı, modellerin durumu ve izleme sağlığı; diğerlerinde null */
  safety: {
    active: Array<{ type: AlarmType; trackId: number; seconds: number }>;
    lastAlarmAt: number | null;
    model?: ModelState;
    /** Poz modeli yüklenemediyse Türkçe neden */
    modelError?: string | null;
    /** Kişi tanıma modeli (YOLOX) */
    detector?: ModelState;
    detectorError?: string | null;
    /** Son karenin işleme hatası (sonraki başarılı karede temizlenir) */
    processingError?: string | null;
    /** Son başarıyla işlenen kare (unix saniye) */
    lastOkAt?: number | null;
    /** Gerçekten izleniyor mu: canlı, iki model hazır, işleme hatası yok, son 10 sn'de kare işlendi */
    healthy?: boolean;
    /** Sağlıklı değilse ilk tutmayan koşul (Türkçe) */
    reason?: string | null;
    /** Kaç saniyedir sağlıksız (sağlıklıysa null) */
    unhealthyFor?: number | null;
  } | null;
}

export type ModelState = "loading" | "ready" | "error";

/** Güvenlik kamerası bu kadar süredir izlenmiyorsa alarm şeridinde uyarı satırı çıkar */
export const WATCH_WARN_AFTER_S = 60;

/** Sağlıksızlığın nedeni hangi koşuldan geliyor: kamera, model yükleniyor, model yüklenemedi (1 dk sonra yeniden
 * denenir), görüntü işlenemiyor */
export type HealthCause = "camera" | "loading" | "modelError" | "processing";

/**
 * Sunucunun `safety_health` sırasıyla ilk tutmayan koşul: kamera → poz modeli → kişi tanıma modeli → işleme. Gerekçe
 * metni ile aynı koşuldan çıkar (ör. poz modeli yüklenirken tanıma modelinin hatası "yeniden denenir" eki almaz).
 */
function healthCause(s: LiveSession): HealthCause {
  if (s.state !== "live") return "camera";
  for (const st of [s.safety?.model, s.safety?.detector]) {
    if (st === "loading") return "loading";
    if (st === "error") return "modelError";
  }
  return "processing";
}

/**
 * Güvenlik oturumu gerçekten izleniyor mu (analiz sunucusunun `safety.healthy`/`reason`'ı). Sağlık alanı olmayan eski
 * sunucuda kamera durumu ve poz modelinden çıkarılır. `cause`: gerekçenin geldiği koşul (sağlıklıysa null).
 */
export function safetyHealth(s: LiveSession): { healthy: boolean; reason: string | null; cause: HealthCause | null } {
  const sf = s.safety;
  if (sf && typeof sf.healthy === "boolean") {
    return sf.healthy ? { healthy: true, reason: null, cause: null } : { healthy: false, reason: sf.reason ?? null, cause: healthCause(s) };
  }
  if (s.state !== "live") return { healthy: false, reason: s.state === "connecting" ? "Kameraya bağlanılıyor" : "Kamera bağlantısı yok", cause: "camera" };
  if (sf?.model === "loading") return { healthy: false, reason: "Poz modeli yükleniyor", cause: "loading" };
  if (sf?.model === "error") return { healthy: false, reason: sf.modelError || "Poz modeli yüklenemedi", cause: "modelError" };
  return { healthy: true, reason: null, cause: null };
}

export type AlarmType = "hands_up" | "lying" | "test";
export interface Alarm {
  id: string; sessionId: string | null; camera: string; type: AlarmType;
  startedAt: number; firedAt: number; endedAt: number | null; acked: boolean;
  notify: "disabled" | "queued" | "sent" | "failed" | "suppressed"; image: boolean;
  /** İhlal anının kaydı (video) hazır mı; alarmdan sonra ≈4 sn toplanıp arka planda yazılır */
  clip?: boolean;
  /** Kaydın ilk karesinin zamanı (unix saniye); kayıt yoksa null */
  clipStartedAt?: number | null;
  /** Kullanıcı "Yanlış alarm" dedi (onaylanmış sayılır) */
  falseAlarm?: boolean;
}
/** Alarm penceresinin büyük başlığı */
export const ALARM_TITLES: Record<AlarmType, string> = { hands_up: "ELLER YUKARI", lying: "YERDE YATAN KİŞİ", test: "DENEME ALARMI" };
/** Alarmdan sonra bu kadar saniye kayıt yoksa "Kayıt hazırlanıyor…" (ön 8 + son 4 sn + yazım) yerine resim gösterilir */
export const CLIP_PENDING_S = 20;
/** Alarmlar sayfasının bir aralıkta istediği en çok alarm */
export const ALARM_LIST_LIMIT = 1000;
export const alarmClipUrl = (id: string) => `/api/live/alarms/${id}/clip.webm`;
export const alarmImageUrl = (id: string) => `/api/live/alarms/${id}/image.jpg`;
export interface NotifyConfig {
  enabled: boolean; chatId: string; hasToken: boolean;
  /** Son Telegram gönderim hatası (Türkçe, anahtarsız); başarılı gönderimde silinir */
  lastError?: { text: string; at: number } | null;
}
export const ALARM_LABELS: Record<AlarmType, string> = { hands_up: "Eller yukarı", lying: "Yerde yatan kişi", test: "Deneme alarmı" };
export const NOTIFY_LABELS: Record<Alarm["notify"], string> = {
  disabled: "Telegram kapalı", queued: "Gönderiliyor", sent: "Telegram'a gitti", failed: "Gönderilemedi", suppressed: "Tekrar (gönderilmedi)",
};

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

/** Bugünkü zamanda yalnızca saat, eskisinde tarih de (unix saniye) */
export function stamp(sec: number): string {
  const d = new Date(sec * 1000);
  return d.toDateString() === new Date().toDateString() ? d.toLocaleTimeString("tr-TR") : d.toLocaleString("tr-TR");
}

/** Oturum durumu noktası: canlı yeşil, hata/bitti kırmızı, bağlanıyor/kapandı turuncu */
export function stateDot(state: LiveSession["state"]): string {
  return state === "live" ? "bg-ok-600" : state === "error" || state === "ended" ? "bg-nok-600" : "bg-[#f08a24]";
}

/** JSON isteği; hata gövdesindeki `detail` Türkçe iletiyle fırlatılır */
const FIELD_LABELS: Record<string, string> = {
  host: "IP adresi", port: "RTSP portu", channel: "Kanal", httpPort: "Web/SDK portu", rtspPort: "Görüntü portu",
  username: "Kullanıcı adı", password: "Şifre", name: "Ad", customUrl: "RTSP adresi",
  chatId: "Sohbet / grup kimliği", token: "Bot anahtarı",
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

/** HTTP hatası: `status` ile 401 (oturum süresi doldu) ya da 502 (analiz sunucusu yok) ayırt edilir */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
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
    throw new ApiError(typeof d === "string" ? d : Array.isArray(d) ? validationMessage(d)
      : `İstek başarısız (HTTP ${res.status}).`, res.status);
  }
  return body as T;
}
