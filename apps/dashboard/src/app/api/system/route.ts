import { analyzerHeaders, analyzerUrl } from "@/lib/analyzer";
import pkg from "../../../../package.json";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Durum şeridi için sistem özeti: analiz sunucusunun işlemci yükü ve çalışma süresi + sürümler.
 * Analiz sunucusuna ulaşılamazsa 502 değil `200 {"analyzer":"down"}` döner (şerit "kapalı" gösterir, hata sayılmaz).
 * Oturum denetimi ara katmanda (middleware) yapılır.
 */
export async function GET(req: Request): Promise<Response> {
  try {
    const res = await fetch(analyzerUrl("/api/v1/system/status"), {
      headers: analyzerHeaders(),
      cache: "no-store",
      signal: AbortSignal.any([req.signal, AbortSignal.timeout(5000)]),
    });
    if (!res.ok) return Response.json({ analyzer: "down" });
    const s = (await res.json()) as { cpuPercent: number; uptimeS: number; version: string };
    return Response.json({
      analyzer: "up",
      cpuPercent: s.cpuPercent,
      uptimeS: s.uptimeS,
      analyzerVersion: s.version,
      panelVersion: pkg.version,
    });
  } catch {
    return Response.json({ analyzer: "down" });
  }
}
