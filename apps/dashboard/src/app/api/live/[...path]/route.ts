import { analyzerHeaders, analyzerUrl, passThrough, unreachable } from "@/lib/analyzer";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ path: string[] }> };

/** Yalnızca beklenen yol parçaları (kimlik, ad) geçer: yol enjeksiyonu yok ("." / ".." ile /live dışına çıkılamaz) */
const SAFE = /^(?!\.+$)[A-Za-z0-9._-]{1,80}$/;

/**
 * Canlı sayım API'si (`/api/v1/live/...`) vekili. Erişim anahtarı yalnızca sunucuda; canlı görüntü (MJPEG) akışı
 * tamponlanmadan aktarılır.
 */
async function forward(req: Request, { params }: Ctx): Promise<Response> {
  const { path } = await params;
  if (!path.length || !path.every((p) => SAFE.test(p))) {
    return Response.json({ detail: "Geçersiz adres." }, { status: 404 });
  }
  const url = new URL(req.url);
  const target = analyzerUrl(`/api/v1/live/${path.join("/")}${url.search}`);
  const init: RequestInit & { duplex?: "half" } = {
    method: req.method,
    headers: analyzerHeaders(req.headers.get("content-type") ? { "content-type": req.headers.get("content-type")! } : undefined),
    cache: "no-store",
    signal: req.signal,
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.text();
  }
  try {
    const res = await fetch(target, init);
    return passThrough(res, ["content-type", "content-length", "content-disposition", "cache-control"]);
  } catch (err) {
    if (req.signal.aborted) return new Response(null, { status: 499 });
    return unreachable(err);
  }
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const DELETE = forward;
