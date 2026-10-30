/**
 * `GET /api/system` yanıtı (app/api/system/route.ts): durum şeridi ve Hakkında sayfası okur. Çalışan analiz sunucusunda
 * bilinmeyen alanlar: işlemci yükü ve çalışma süresi null, sürüm ve git özeti "?" (psutil'siz kurulum ya da durum ucu
 * olmayan eski analiz sunucusu).
 */
export type SystemInfo =
  | {
      analyzer: "up";
      cpuPercent: number | null;
      uptimeS: number | null;
      analyzerVersion: string;
      analyzerCommit: string;
      panelVersion: string;
      panelCommit: string;
    }
  | { analyzer: "down" }
  | { analyzer: "auth" };

/** Analiz sunucusu durumunun kullanıcıya görünen adı */
export const ANALYZER_STATE_TEXT: Record<SystemInfo["analyzer"], string> = {
  up: "çalışıyor",
  down: "kapalı",
  auth: "yetki hatası",
};

/** Sistem özetini ister; panele ulaşılamazsa ya da oturum düşmüşse (401) null (durum bilinmiyor). */
export async function fetchSystem(signal?: AbortSignal): Promise<SystemInfo | null> {
  try {
    const res = await fetch("/api/system", { cache: "no-store", signal });
    if (!res.ok) return null;
    const body: unknown = await res.json();
    const state = (body as { analyzer?: unknown } | null)?.analyzer;
    return state === "up" || state === "down" || state === "auth" ? (body as SystemInfo) : null;
  } catch {
    return null;
  }
}
