import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, panelPassword, sessionToken } from "@/lib/session";

/** Şifre tanımlıysa giriş yapılmamış istekler: sayfada aynı adreste giriş formu (yeniden yazma; tarayıcının kullandığı
 * ana makine adına dokunulmaz, proxy arkasında da çerez kaybolmaz), API'de 401. */
export async function middleware(req: NextRequest) {
  const pw = panelPassword();
  if (!pw) return NextResponse.next();
  if (req.cookies.get(SESSION_COOKIE)?.value === (await sessionToken(pw))) return NextResponse.next();
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
