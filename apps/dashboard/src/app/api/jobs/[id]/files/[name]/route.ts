import { analyzerHeaders, analyzerUrl, passThrough, unreachable } from "@/lib/analyzer";
import { isJobId, RESULT_FILES, type ResultFile } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ id: string; name: string }> };

/** Sonuç dosyaları; Range başlığı aktarılır (video oynatıcıda ileri/geri sarma). */
export async function GET(req: Request, { params }: Ctx): Promise<Response> {
  const { id, name } = await params;
  if (!isJobId(id) || !RESULT_FILES.includes(name as ResultFile)) {
    return Response.json({ detail: "Dosya bulunamadı." }, { status: 404 });
  }
  const range = req.headers.get("range");
  try {
    const res = await fetch(analyzerUrl(`/api/v1/jobs/${id}/files/${name}`), {
      headers: analyzerHeaders(range ? { range } : undefined),
      cache: "no-store",
    });
    return passThrough(res, ["content-type", "content-length", "content-range", "accept-ranges",
                             "content-disposition", "etag", "last-modified"]);
  } catch (err) {
    return unreachable(err);
  }
}
