import { analyzerHeaders, analyzerUrl, passThrough, unreachable } from "@/lib/analyzer";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Son analiz işleri. */
export async function GET(): Promise<Response> {
  try {
    const res = await fetch(analyzerUrl("/api/v1/jobs"), { headers: analyzerHeaders(), cache: "no-store" });
    return passThrough(res);
  } catch (err) {
    return unreachable(err);
  }
}

/** Video yükleme: çok parçalı gövde belleğe alınmadan analiz sunucusuna akıtılır (büyük videolar). */
export async function POST(req: Request): Promise<Response> {
  const type = req.headers.get("content-type") ?? "";
  if (!type.startsWith("multipart/form-data") || !req.body) {
    return Response.json({ detail: "Video multipart/form-data olarak gönderilmeli." }, { status: 400 });
  }
  try {
    const headers = analyzerHeaders({ "content-type": type });
    const length = req.headers.get("content-length");
    if (length) headers.set("content-length", length);
    const res = await fetch(analyzerUrl("/api/v1/jobs"), {
      method: "POST",
      headers,
      body: req.body,
      // Node fetch akan gövde için gerekli
      duplex: "half",
    } as RequestInit & { duplex: "half" });
    return passThrough(res);
  } catch (err) {
    return unreachable(err);
  }
}
