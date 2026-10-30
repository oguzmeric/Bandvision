import { analyzerHeaders, analyzerUrl, logRateLimited } from "@/lib/analyzer";
import { analyzerSummary } from "@/lib/systemStatus.mjs";
import { PANEL_VERSION, getPanelCommit } from "@/lib/panelVersion";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const TIMEOUT_MS = 5000;

/**
 * Durum şeridi için sistem özeti: analiz sunucusunun işlemci yükü ve çalışma süresi + sürümler (`analyzerSummary`).
 * `analyzer`: "up" | "down" (ağ hatası, zaman aşımı, 5xx, bozuk gövde) | "auth" (401/403: ANALYZER_TOKEN yanlış ya da
 * eksik). Durum ucu olmayan eski analiz sunucusu (404) `/healthz` çalışıyorsa "up" ve bilinmeyen alanlar (işlemci ve süre
 * null, sürüm ve özet "?"). Hepsi 200 döner (şerit durumu gösterir, hata sayılmaz). Panel oturum denetimi ara katmanda
 * (middleware) yapılır. İstemci istek sürerken giderse (sayfa kapandı, yoklama iptal edildi) analiz sunucusuna giden istek
 * de kesilir ve bu günlüğe "ulaşılamadı" diye YAZILMAZ; gerçek ulaşılamama ve zaman aşımı dakikada en çok bir kez yazılır.
 */
export async function GET(req: Request): Promise<Response> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(new Error(`zaman aşımı (${TIMEOUT_MS / 1000} sn)`)), TIMEOUT_MS);
  const onAbort = () => ctrl.abort();
  req.signal.addEventListener("abort", onAbort);
  try {
    const s = await analyzerSummary((path) => fetch(analyzerUrl(path), {
      headers: analyzerHeaders(),
      cache: "no-store",
      signal: ctrl.signal,
    }));
    if (s.log) logRateLimited(new Error(s.log.message), s.log.what);
    if (s.analyzer !== "up") return Response.json({ analyzer: s.analyzer });
    return Response.json({
      analyzer: "up",
      cpuPercent: s.cpuPercent,
      uptimeS: s.uptimeS,
      analyzerVersion: s.version,
      analyzerCommit: s.commit,
      panelVersion: PANEL_VERSION,
      panelCommit: await getPanelCommit(),
    });
  } catch (err) {
    // İstemci gitti: yanıtı okuyan yok, analiz sunucusu da hatalı değil (günlüğe yazılmaz)
    if (req.signal.aborted) return new Response(null, { status: 499 });
    logRateLimited(err);
    return Response.json({ analyzer: "down" });
  } finally {
    clearTimeout(timer);
    req.signal.removeEventListener("abort", onAbort);
  }
}
