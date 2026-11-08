/** Kayıttan izleme API'si (analiz sunucusu `/api/v1/live/archive`, panel vekili `/api/live/archive`) —
 * services/edge/bantvision/live/archive_api.py. Zaman ve dosya adı hesapları `archiveTime.mjs`'tedir (birim testli). */
import { ApiError, api } from "./live";
import { dispositionFilename, fallbackFilename, type Range } from "./archiveTime.mjs";

export type { Range } from "./archiveTime.mjs";

export type PlayerState = "connecting" | "playing" | "paused" | "ended" | "error";

/** Oynatıcı görünümü (sunucu `_view`): adres, şifre ya da jeton yoktur */
export interface PlayerView {
  id: string;
  sourceId: string;
  channelId: string | null;
  /** "Kaynak · kanal" */
  name: string;
  state: PlayerState;
  /** `error` durumunda Türkçe neden */
  message: string;
  /** Konum (epoch sn) */
  at: number;
  speed: number;
  speeds: number[];
  fps: number;
  canExport: boolean;
}

/** Seçili kayıt cihazı kamerası */
export interface ArchiveCamera { sourceId: string; channelId: string }

export type PlayerAction = { action: "pause" } | { action: "resume" } | { action: "seek"; at: number } | { action: "speed"; speed: number };

const q = (cam: ArchiveCamera) => `source=${encodeURIComponent(cam.sourceId)}&channel=${encodeURIComponent(cam.channelId)}`;

/** Ayın kayıtlı günleri (1–31) */
export async function calendarDays(cam: ArchiveCamera, year: number, month: number, signal?: AbortSignal): Promise<number[]> {
  const r = await api<{ days: number[] }>(`archive/calendar?${q(cam)}&year=${year}&month=${month}`, { signal });
  return r.days;
}

/** Günün (`day`: yerel gün başı, epoch sn) kayıtlı aralıkları */
export async function timelineRanges(cam: ArchiveCamera, day: number, signal?: AbortSignal): Promise<Range[]> {
  const r = await api<{ ranges: Range[] }>(`archive/timeline?${q(cam)}&day=${day}`, { signal });
  return r.ranges;
}

export function createPlayer(cam: ArchiveCamera, at: number, speed: number): Promise<PlayerView> {
  return api<PlayerView>("archive/players", { method: "POST", json: { sourceId: cam.sourceId, channelId: cam.channelId, at, speed } });
}

export function getPlayer(id: string): Promise<PlayerView> {
  return api<PlayerView>(`archive/players/${encodeURIComponent(id)}`);
}

export function playerAction(id: string, body: PlayerAction): Promise<PlayerView> {
  return api<PlayerView>(`archive/players/${encodeURIComponent(id)}/actions`, { method: "POST", json: body });
}

/** Oynatıcıyı kapatır; sayfa kapanırken de gitsin diye `keepalive` (yanıt beklenmez, hata yutulur) */
export function deletePlayer(id: string): void {
  void fetch(`/api/live/archive/players/${encodeURIComponent(id)}`, { method: "DELETE", keepalive: true, cache: "no-store" })
    .catch(() => undefined);
}

export function streamUrl(id: string): string {
  return `/api/live/archive/players/${encodeURIComponent(id)}/stream`;
}

/** Dışa aktarma: `video/mp4` yanıtı Blob'a alınır; ad `Content-Disposition`'dan. Hata iletisi sunucunun `detail`'i. */
export async function exportClip(cam: ArchiveCamera, start: number, end: number, signal?: AbortSignal): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch("/api/live/archive/export", {
    method: "POST",
    cache: "no-store",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ sourceId: cam.sourceId, channelId: cam.channelId, start, end }),
    signal,
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: unknown; error?: unknown } | null;
    const d = body?.detail ?? body?.error;
    throw new ApiError(typeof d === "string" ? d : `Dışa aktarılamadı (HTTP ${res.status}).`, res.status);
  }
  const blob = await res.blob();
  return { blob, filename: dispositionFilename(res.headers.get("content-disposition"), fallbackFilename(start)) };
}
