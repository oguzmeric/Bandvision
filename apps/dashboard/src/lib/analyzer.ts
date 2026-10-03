import "server-only";

/**
 * Analiz sunucusu (services/edge, `python -m bantvision.analyzer`) ile sunucu tarafında konuşur.
 * ANALYZER_TOKEN yalnızca burada kullanılır; tarayıcıya hiç gitmez (docs/13-web-platform.md).
 */
const BASE = (process.env.ANALYZER_URL ?? "http://127.0.0.1:8090").replace(/\/+$/, "");

export function analyzerUrl(path: string): string {
  return `${BASE}${path}`;
}

export function analyzerHeaders(extra?: HeadersInit): Headers {
  const h = new Headers(extra);
  const token = process.env.ANALYZER_TOKEN;
  if (token) h.set("Authorization", `Bearer ${token}`);
  return h;
}

/** Analiz sunucusuna ulaşılamazsa anlaşılır bir 502 yanıtı. */
export function unreachable(err: unknown): Response {
  console.error("analiz sunucusuna ulaşılamadı:", err);
  return Response.json(
    { detail: "Analiz sunucusuna ulaşılamadı. Sunucunun çalıştığından emin olun (python -m bantvision.analyzer)." },
    { status: 502 },
  );
}

/** Yukarı akış yanıtını, yalnızca güvenli başlıkları taşıyarak tarayıcıya aktarır. */
export function passThrough(res: Response, keep: string[] = ["content-type"]): Response {
  const headers = new Headers();
  for (const name of keep) {
    const v = res.headers.get(name);
    if (v) headers.set(name, v);
  }
  return new Response(res.body, { status: res.status, headers });
}
