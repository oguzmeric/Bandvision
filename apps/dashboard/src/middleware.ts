import { NextResponse, type NextRequest } from "next/server";
import { isLoopbackHost } from "@/lib/hostCheck.mjs";
import { SESSION_COOKIE, authMode, expectedToken, sameToken } from "@/lib/session";

/** Şifre kipi açıksa (DASHBOARD_PASSWORD ya da telefondan erişimin şifre özeti) giriş yapılmamış istekler: sayfada aynı
 * adreste giriş formu (yeniden yazma; tarayıcının kullandığı ana makine adına dokunulmaz, proxy arkasında da çerez
 * kaybolmaz), API'de 401.
 * Şifresiz kipte panel yalnızca bu bilgisayarda (127.0.0.1) dinler; yine de `Host` geri döngü adı (localhost,
 * 127.0.0.1, [::1]) değilse 403: kötü niyetli bir sitenin DNS yeniden bağlamayla (alan adını 127.0.0.1'e çevirip)
 * tarayıcı üzerinden panele ve API'ye ulaşması engellenir. */
export async function middleware(req: NextRequest) {
  const mode = authMode();
  if (!mode) {
    if (isLoopbackHost(req.headers.get("host"))) return NextResponse.next();
    if (req.nextUrl.pathname.startsWith("/api/")) {
      return NextResponse.json({ error: "Geçersiz adres." }, { status: 403 });
    }
    return new NextResponse("Geçersiz adres.", { status: 403, headers: { "content-type": "text/plain; charset=utf-8" } });
  }
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
  // Yalnızca giriş sayfası ve uç noktası (tam yol: /login, /api/login), Next iç dosyaları ve marka görselleri herkese açık
  matcher: ["/((?!login(?:/|$)|api/login(?:/|$)|_next/|brand/|favicon\\.ico).*)"],
};
