import { analyzerHeaders, analyzerUrl, logRateLimited } from "@/lib/analyzer";
import { classify, parseStatus } from "@/lib/systemStatus.mjs";
import { PANEL_VERSION, getPanelCommit } from "@/lib/panelVersion";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const TIMEOUT_MS = 5000;

/**
 * Durum şeridi için sistem özeti: analiz sunucusunun işlemci yükü ve çalışma süresi + sürümler.
 * `analyzer`: "up" | "down" (ağ hatası, zaman aşımı, 5xx, bozuk gövde) | "auth" (401/403: ANALYZER_TOKEN yanlış ya da eksik).
 * Hepsi 200 döner (şerit durumu gösterir, hata sayılmaz). Panel oturum denetimi ara katmanda (middleware) yapılır.
 */
export async function GET(req: Request): Promise<Response> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  const onAbort = () => ctrl.abort();
  req.signal.addEventListener("abort", onAbort);
  try {
    const res = await fetch(analyzerUrl("/api/v1/system/status"), {
      headers: analyzerHeaders(),
      cache: "no-store",
      signal: ctrl.signal,
    });
    const state = classify({ ok: res.ok, status: res.status });
    if (state === "auth") {
      logRateLimited(new Error(`HTTP ${res.status}: ANALYZER_TOKEN yanlış ya da eksik`), "analiz sunucusu erişimi reddetti");
      return Response.json({ analyzer: "auth" });
    }
    if (state === "down") {
      logRateLimited(new Error(`HTTP ${res.status}`), "analiz sunucusu hata döndürdü");
      return Response.json({ analyzer: "down" });
    }
    const s = parseStatus(await res.json());
    if (!s) {
      logRateLimited(new Error("beklenmeyen gövde"), "analiz sunucusu durum yanıtı geçersiz");
      return Response.json({ analyzer: "down" });
    }
    return Response.json({
      analyzer: "up",
      cpuPercent: s.cpuPercent,
      uptimeS: s.uptimeS,
      analyzerVersion: s.version,
      analyzerCommit: s.commit,
      panelVersion: PANEL_VERSION,
      panelCommit: getPanelCommit(),
    });
  } catch (err) {
    logRateLimited(err);
    return Response.json({ analyzer: "down" });
  } finally {
    clearTimeout(timer);
    req.signal.removeEventListener("abort", onAbort);
  }
}
