import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, authMode, expectedToken, sameToken } from "@/lib/session";

/** Şifre kipi açıksa (DASHBOARD_PASSWORD ya da telefondan erişimin şifre özeti) giriş yapılmamış istekler: sayfada aynı
 * adreste giriş formu (yeniden yazma; tarayıcının kullandığı ana makine adına dokunulmaz, proxy arkasında da çerez
 * kaybolmaz), API'de 401. */
export async function middleware(req: NextRequest) {
  const mode = authMode();
  if (!mode) return NextResponse.next();
  if (sameToken(req.cookies.get(SESSION_COOKIE)?.value, await expectedToken(mode))) return NextResponse.next();
  if (req.nextUrl.pathname.startsWith("/api/")) {
    return NextResponse.json({ error: "Giriş gerekli." }, { status: 401 });
  }
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = `?next=${encodeURIComponent(req.nextUrl.pathname + req.nextUrl.search)}`;
  return NextResponse.rewrite(url);
}

export const config = {
  // Giriş sayfası/uç noktası, Next iç dosyaları ve marka görselleri herkese açık
  matcher: ["/((?!login|api/login|_next/|brand/|favicon\\.ico).*)"],
};
