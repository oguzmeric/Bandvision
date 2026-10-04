import { NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/session";

/** Çıkış (POST): oturum çerezini siler; giriş sayfasına geçişi tarayıcı yapar. */
export async function POST() {
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, "", { httpOnly: true, sameSite: "lax", maxAge: 0, path: "/" });
  return res;
}
