import { timingSafeEqual } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { verifyPassword } from "@/lib/accessCore.mjs";
import { SESSION_COOKIE, SESSION_MAX_AGE, authMode, expectedToken } from "@/lib/session";

export const runtime = "nodejs";

function same(a: string, b: string): boolean {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

/** Giriş (POST, JSON {password}): doğruysa oturum çerezi; değilse kısa beklemeyle 401. Yönlendirmeyi tarayıcı yapar. */
export async function POST(req: NextRequest) {
  const mode = authMode();
  let given = "";
  try {
    given = String(((await req.json()) as { password?: unknown }).password ?? "");
  } catch {
    return NextResponse.json({ error: "Geçersiz istek." }, { status: 400 });
  }
  const valid = mode?.kind === "env" ? same(given, mode.password)
    : mode?.kind === "hash" ? verifyPassword(given, mode.salt, mode.hash) : false;
  if (!mode || !valid) {
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
