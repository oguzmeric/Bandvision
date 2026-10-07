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

const LOG_EVERY_MS = 60_000;
const logged = new Map<string, { at: number; skipped: number }>();

/** Aynı hata ileti başına dakikada bir günlüğe yazılır: analiz sunucusu kapalıyken panel 2 sn'de bir yoklar,
 * günlük dolmasın. Atlanan sayısı bir sonraki satıra eklenir. */
function logRateLimited(err: unknown): void {
  const cause = err instanceof Error && err.cause instanceof Error ? ` (${err.cause.message})` : "";
  const key = (err instanceof Error ? `${err.name}: ${err.message}` : String(err)) + cause;
  const now = Date.now();
  const prev = logged.get(key);
  if (prev && now - prev.at < LOG_EVERY_MS) {
    prev.skipped += 1;
    return;
  }
  if (logged.size >= 50) logged.clear();                         // değişken iletilerle sınırsız büyümesin
  logged.set(key, { at: now, skipped: 0 });
  console.error(`analiz sunucusuna ulaşılamadı${prev?.skipped ? ` (bu arada ${prev.skipped} istek daha)` : ""}:`, err);
}

/** Analiz sunucusuna ulaşılamazsa anlaşılır bir 502 yanıtı. */
export function unreachable(err: unknown): Response {
  logRateLimited(err);
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
