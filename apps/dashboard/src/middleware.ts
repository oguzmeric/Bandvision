import { NextResponse, type NextRequest } from "next/server";
import { CROSS_SITE_REFUSED, crossSiteRefused, isLoopbackHost } from "@/lib/hostCheck.mjs";
import { SESSION_COOKIE, authMode, expectedToken, sameToken } from "@/lib/session";

/** Şifre kipi açıksa (DASHBOARD_PASSWORD ya da telefondan erişimin şifre özeti) giriş yapılmamış istekler: sayfada aynı
 * adreste giriş formu (yeniden yazma; tarayıcının kullandığı ana makine adına dokunulmaz, proxy arkasında da çerez
 * kaybolmaz), API'de 401.
 * Şifresiz kipte panel yalnızca bu bilgisayarda (127.0.0.1) dinler; yine de `Host` geri döngü adı (localhost,
 * 127.0.0.1, [::1]) değilse 403: kötü niyetli bir sitenin DNS yeniden bağlamayla (alan adını 127.0.0.1'e çevirip)
 * tarayıcı üzerinden panele ve API'ye ulaşması engellenir. API'de ayrıca başka siteden gelen tarayıcı isteği de 403 alır
 * (`crossSiteRefused`): vekil isteği sunucu tarafından, `Origin`'siz iletir, analiz sunucusunun denetimi bunu göremez.
 * Sayfalar etkilenmez: başka siteden gelen bağlantı paneli açar. Şifreli kipte kural yok: oturum çerezi SameSite=Lax,
 * başka siteden gelen yazma isteği çerezsiz gelir ve 401 alır. */
export async function middleware(req: NextRequest) {
  const mode = authMode();
  if (!mode) {
    const isApi = req.nextUrl.pathname.startsWith("/api/");
    if (isLoopbackHost(req.headers.get("host"))) {
      if (isApi && crossSiteRefused(req.headers.get("origin"), req.headers.get("sec-fetch-site"))) {
        return NextResponse.json({ error: CROSS_SITE_REFUSED }, { status: 403 });
      }
      return NextResponse.next();
    }
    if (isApi) {
      return NextResponse.json({ error: "Geçersiz adres." }, { status: 403 });
    }
    return new NextResponse("Geçersiz adres.", { status: 403, headers: { "content-type": "text/plain; charset=utf-8" } });
  }
  if (sameToken(req.cookies.get(SESSION_COOKIE)?.value, await expectedToken(mode))) return NextResponse.next();
  if (req.nextUrl.pathname.startsWith("/api/")) {
    return NextResponse.json({ error: "Giriş gerekli." }, { status: 401 });
  }
  // Giriş formu İÇ yeniden yazmayla: hedef, isteğin geldiği kökende olmalı. `req.url` sunucunun kendi adresidir
  // (next.config `skipMiddlewareUrlNormalize`); `req.nextUrl` ise 127.0.0.1'i "localhost" yapar. Köken farklı görününce Next
  // yeniden yazmayı dış adres sanıp kendine HTTP vekil isteği açıyordu (yük altında "Failed to proxy … ECONNREFUSED" →
  // giriş sayfası 500; istemci giderken vekilde "aborted ECONNRESET").
  const url = new URL(req.url);
  url.pathname = "/login";
  url.search = `?next=${encodeURIComponent(req.nextUrl.pathname + req.nextUrl.search)}`;
  return NextResponse.rewrite(url);
}

export const config = {
  // Yalnızca giriş sayfası ve uç noktası (tam yol: /login, /api/login), Next iç dosyaları ve marka görselleri herkese açık
  matcher: ["/((?!login(?:/|$)|api/login(?:/|$)|_next/|brand/|favicon\\.ico).*)"],
};
