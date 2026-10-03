import { analyzerHeaders, analyzerUrl, passThrough, unreachable } from "@/lib/analyzer";
import { isJobId } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ id: string }> };

const notFound = () => Response.json({ detail: "İş bulunamadı." }, { status: 404 });

export async function GET(_req: Request, { params }: Ctx): Promise<Response> {
  const { id } = await params;
  if (!isJobId(id)) return notFound();
  try {
    const res = await fetch(analyzerUrl(`/api/v1/jobs/${id}`), { headers: analyzerHeaders(), cache: "no-store" });
    return passThrough(res);
  } catch (err) {
    return unreachable(err);
  }
}

export async function DELETE(_req: Request, { params }: Ctx): Promise<Response> {
  const { id } = await params;
  if (!isJobId(id)) return notFound();
  try {
    const res = await fetch(analyzerUrl(`/api/v1/jobs/${id}`), { method: "DELETE", headers: analyzerHeaders() });
    return new Response(null, { status: res.status });
  } catch (err) {
    return unreachable(err);
  }
}
