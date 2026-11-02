import type { NextRequest } from "next/server";
import { analyzerHeaders, analyzerUrl, passThrough, unreachable } from "@/lib/analyzer";
import { refusalFor } from "@/lib/analyzerRefusal.mjs";
import { apiRefusal } from "@/lib/panelGate";
import { STREAM_BODY_INIT } from "@/lib/streamUpload.mjs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const PROBE_TIMEOUT_MS = 5000;

/**
 * Yüklemeden önce analiz sunucusuna sorulur: panelin anahtarını ya da adresini reddediyorsa vekilin reddi hemen döner,
 * yanlış anahtar bütün videonun gitmesini beklemez. Başka her sonuç (çalışıyor, eski sunucu, ulaşılamıyor, zaman aşımı)
 * yüklemeye geçer: gerçek hata orada çıkar.
 */
async function refusedByAnalyzer(): Promise<Response | null> {
  try {
    const res = await fetch(analyzerUrl("/api/v1/system/status"), {
      headers: analyzerHeaders(),
      cache: "no-store",
      signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
    });
    if (refusalFor(res.status)) return passThrough(res);
    void res.body?.cancel().catch(() => undefined);
  } catch {
    // yükleme aynı nedenle başarısız olur ve onu söyler
  }
  return null;
}

/** Yolun öteki yöntemleri de aynı kapıdan geçer (ara katmandayken de öyleydi), sonra Next'in kendi yanıtı: 405, OPTIONS 204 */
const ALLOW = { Allow: "GET, HEAD, OPTIONS, POST" };
async function notAllowed(req: NextRequest): Promise<Response> {
  return (await apiRefusal(req)) ?? new Response(null, { status: 405, headers: ALLOW });
}
export const PUT = notAllowed;
export const DELETE = notAllowed;
export const PATCH = notAllowed;
export async function OPTIONS(req: NextRequest): Promise<Response> {
  return (await apiRefusal(req)) ?? new Response(null, { status: 204, headers: ALLOW });
}

/** Son analiz işleri. Bu yol ara katmandan geçmez (`middleware.ts` `matcher`): giriş kapısını kendisi çağırır. */
export async function GET(req: NextRequest): Promise<Response> {
  const refused = await apiRefusal(req);
  if (refused) return refused;
  try {
    const res = await fetch(analyzerUrl("/api/v1/jobs"), { headers: analyzerHeaders(), cache: "no-store" });
    return passThrough(res);
  } catch (err) {
    return unreachable(err);
  }
}

/**
 * Video yükleme: çok parçalı gövde belleğe alınmadan analiz sunucusuna akıtılır (büyük videolar). Bu yol ara katmandan geçmez
 * (`middleware.ts` `matcher`): giriş kapısını kendisi çağırır, reddedilen istekte gövdeden hiçbir şey okunmaz (okunmayan
 * gövdeyi Node boşaltır, istemci yanıtı alır).
 */
export async function POST(req: NextRequest): Promise<Response> {
  const refused = await apiRefusal(req);
  if (refused) return refused;
  const type = req.headers.get("content-type") ?? "";
  if (!type.startsWith("multipart/form-data") || !req.body) {
    return Response.json({ detail: "Video multipart/form-data olarak gönderilmeli." }, { status: 400 });
  }
  const refusal = await refusedByAnalyzer();
  if (refusal) return refusal;
  try {
    const headers = analyzerHeaders({ "content-type": type });
    const length = req.headers.get("content-length");
    if (length) headers.set("content-length", length);
    const res = await fetch(analyzerUrl("/api/v1/jobs"), {
      method: "POST",
      headers,
      body: req.body,
      ...STREAM_BODY_INIT,
    } as RequestInit);
    return passThrough(res);
  } catch (err) {
    // Yükleme sürerken istemci ayrıldı (sekme kapandı, iptal): gövde akışı kopar ve fetch "aborted ECONNRESET" ile düşer; analiz
    // sunucusu sağlam, "ulaşılamadı" diye günlüğe yazılmaz (canlı vekilindeki gibi)
    if (req.signal.aborted) return new Response(null, { status: 499 });
    return unreachable(err);
  }
}
