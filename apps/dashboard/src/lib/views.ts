/** Çoklu izleme (analiz sunucusu `/api/v1/live/views…`; sözleşme contracts/view-layouts.json, view-template.schema.json) */
import type { AlarmType } from "./live";

export interface ViewLayout { id: string; name: string; cols: number; rows: number; cells: Array<[number, number, number, number]> }
export interface TileRef { sourceId: string; channelId: string | null }
export interface ViewTemplate { id: string; name: string; layout: string; tiles: Array<TileRef | null>; createdAt: number; updatedAt: number }
export interface TileAnalysis {
  mode: "blob" | "linescan" | "detect" | "safety";
  sessionId: string;
  name: string;
  entered?: number; exited?: number; total?: number;
  healthy?: boolean | null; reason?: string | null;
  alarm: { id: string; type: AlarmType } | null;
}
export interface TileStatus { sourceId: string; channelId: string | null; name: string; state: "connecting" | "live" | "error"; message: string; fps: number; analysis: TileAnalysis | null }
export interface ViewStatus { id: string; layout: string; tiles: Array<TileStatus | null> }
/** `cameras/status` cevabı: kutu durumuyla aynı, kaynak/kanal kimliği olmadan */
export type CameraStatus = Omit<TileStatus, "sourceId" | "channelId">;

export const LAST_VIEW_KEY = "bv.watch.last";
export const STATUS_POLL_MS = 1500;
export const STREAM_RETRY_MS = 2000;
/** Şablon listesi alınamazsa (analiz sunucusu yok) bu aralıkla yeniden denenir */
export const RELOAD_RETRY_MS = 5000;
/** Kapsayıcı boyutu değişince yeni akış boyutu bu kadar durulduktan sonra istenir (ilk ölçüm hemen) */
export const RESIZE_DEBOUNCE_MS = 300;

/** Kutunun ızgaradaki yeri (yüzde): birleşik görüntü aynı oranlarla çizilir */
export function cellBox(l: ViewLayout, i: number): { left: string; top: string; width: string; height: string } {
  const [x, y, w, h] = l.cells[i];
  const pct = (v: number) => `${v * 100}%`;
  return { left: pct(x / l.cols), top: pct(y / l.rows), width: pct(w / l.cols), height: pct(h / l.rows) };
}

/** İstenecek birleşik görüntü boyutu: kapsayıcının gerçek pikselleri (en çok 2× yoğunluk; sunucu 1920×1080'e sığdırır) */
export function streamSize(el: HTMLElement): { w: number; h: number } {
  const r = el.getBoundingClientRect();
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const round = (v: number) => Math.max(16, Math.round((v * dpr) / 16) * 16);
  return { w: round(r.width), h: round(r.height) };
}

/** Kutunun/kameranın bağlantı durumu metni; "Kamera silinmiş." ve "Sınır aşıldı…" kendi başına anlaşılır, öneksiz gösterilir */
export function stateText(t: { state: "connecting" | "live" | "error"; message: string }): string {
  if (t.state === "connecting") return "Bağlanıyor…";
  const m = t.message.trim();
  if (!m) return "Bağlantı yok";
  if (m === "Kamera silinmiş." || m.startsWith("Sınır aşıldı")) return m;
  return `Bağlantı yok — ${m}`;
}

/** "Canlı sayıma git": analiz çalışıyorsa o oturum, çalışmıyorsa Kameralar sayfası (oradan başlatılır) */
export function liveHref(a: TileAnalysis | null | undefined): string {
  return a ? `/live?s=${a.sessionId}` : "/cameras";
}

export function badge(a: TileAnalysis): { text: string; tone: "ok" | "warn" | "info" } {
  if (a.mode === "safety") return a.healthy === false ? { text: "Uyarı", tone: "warn" } : { text: "Nöbette", tone: "ok" };
  if (a.mode === "detect") return { text: `G ${a.entered ?? 0} · Ç ${a.exited ?? 0}`, tone: "info" };
  return { text: `Sayılan ${a.total ?? 0}`, tone: "info" };
}

/** Düzen değişince kutular sırasıyla korunur; sığmayanlar düşer (kaç kamera düştüğü uyarı için döner) */
export function retile(tiles: Array<TileRef | null>, count: number): { tiles: Array<TileRef | null>; dropped: number } {
  const next = tiles.slice(0, count);
  while (next.length < count) next.push(null);
  return { tiles: next, dropped: tiles.slice(count).filter(Boolean).length };
}
