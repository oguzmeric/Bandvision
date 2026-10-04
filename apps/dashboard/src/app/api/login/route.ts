import { timingSafeEqual } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, SESSION_MAX_AGE, panelPassword, sessionToken } from "@/lib/session";

export const runtime = "nodejs";

function same(a: string, b: string): boolean {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

/** Giriş (POST, JSON {password}): doğruysa oturum çerezi; değilse kısa beklemeyle 401. Yönlendirmeyi tarayıcı yapar. */
export async function POST(req: NextRequest) {
  const pw = panelPassword();
  let given = "";
  try {
    given = String(((await req.json()) as { password?: unknown }).password ?? "");
  } catch {
    return NextResponse.json({ error: "Geçersiz istek." }, { status: 400 });
  }
  if (!pw || !same(given, pw)) {
    await new Promise((r) => setTimeout(r, 600));                // deneme yanılmayı yavaşlat
    return NextResponse.json({ error: "Şifre yanlış." }, { status: 401 });
  }
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, await sessionToken(pw), {
    httpOnly: true,
    sameSite: "lax",
    secure: (req.headers.get("x-forwarded-proto") ?? req.nextUrl.protocol.replace(":", "")) === "https",
    maxAge: SESSION_MAX_AGE,
    path: "/",
  });
  return res;
}
