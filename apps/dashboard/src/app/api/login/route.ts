import { timingSafeEqual } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { MAX_PASSWORD, createLoginThrottle, isJsonContentType, verifyPasswordAsync } from "@/lib/accessCore.mjs";
import { SESSION_COOKIE, SESSION_MAX_AGE, authMode, expectedToken } from "@/lib/session";

export const runtime = "nodejs";

/** İstek gövdesi üst sınırı: giriş isteği birkaç yüz bayttır */
const MAX_BODY = 4096;
/** Hatalı denemeler için ortak kısıt (uzak adres güvenilir olmadığından istemciye bakılmaz): 5 hatadan sonra kilit */
const throttle = createLoginThrottle();

function same(a: string, b: string): boolean {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

/** Gövdeyi en çok `max` bayta kadar okur; büyükse null (kalanı okunmadan bırakılır). */
async function readLimited(req: NextRequest, max: number): Promise<string | null> {
  const declared = Number(req.headers.get("content-length") ?? "0");
  if (Number.isFinite(declared) && declared > max) return null;
  const reader = req.body?.getReader();
  if (!reader) return "";
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > max) { await reader.cancel().catch(() => undefined); return null; }
    chunks.push(value);
  }
  return Buffer.concat(chunks).toString("utf8");
}

/** Giriş (POST, JSON {password}): doğruysa oturum çerezi; değilse kısa beklemeyle 401. Yönlendirmeyi tarayıcı yapar.
 * Sınırlar: gövde türü yalnızca application/json (415; site dışı text/plain ve form istekleri ön kontrolsüz gelebilir,
 * ortak kısıtı kilitleyebilirdi), gövde ≤ 4 KB, şifre ≤ 256 karakter (400, scrypt çalıştırılmadan); art arda hatalarda
 * 429 (scrypt çalıştırılmadan). */
export async function POST(req: NextRequest) {
  if (!isJsonContentType(req.headers.get("content-type"))) {
    return NextResponse.json({ error: "Geçersiz istek." }, { status: 415 });
  }
  const mode = authMode();
  let given = "";
  try {
    const text = await readLimited(req, MAX_BODY);
    if (text === null) throw new Error("gövde çok büyük");
    given = String(((JSON.parse(text) as { password?: unknown }).password) ?? "");
  } catch {
    return NextResponse.json({ error: "Geçersiz istek." }, { status: 400 });
  }
  if (given.length > MAX_PASSWORD) return NextResponse.json({ error: "Geçersiz istek." }, { status: 400 });
  if (!mode) {
    await new Promise((r) => setTimeout(r, 600));
    return NextResponse.json({ error: "Şifre yanlış." }, { status: 401 });
  }
  const wait = throttle.begin();
  if (wait > 0) {
    return NextResponse.json({ error: "Çok fazla hatalı deneme; biraz sonra yeniden deneyin." },
      { status: 429, headers: { "Retry-After": String(Math.ceil(wait / 1000)) } });
  }
  let ok = false;
  try {
    ok = mode.kind === "env" ? same(given, mode.password) : await verifyPasswordAsync(given, mode.salt, mode.hash);
  } finally {
    throttle.end(ok);
  }
  if (!ok) {
    await new Promise((r) => setTimeout(r, 600));                // deneme yanılmayı yavaşlat
    return NextResponse.json({ error: "Şifre yanlış." }, { status: 401 });
  }
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, await expectedToken(mode), {
    httpOnly: true,
    sameSite: "lax",
    secure: (req.headers.get("x-forwarded-proto") ?? req.nextUrl.protocol.replace(":", "")) === "https",
    maxAge: SESSION_MAX_AGE,
    path: "/",
  });
  return res;
}
