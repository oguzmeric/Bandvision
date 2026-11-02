import { NextResponse, type NextRequest } from "next/server";
import { isApiPath, isLoopbackHost } from "@/lib/hostCheck.mjs";
import { apiRefusal } from "@/lib/panelGate";
import { SESSION_COOKIE, authMode, expectedToken, sameToken } from "@/lib/session";

/** Şifre kipi açıksa (DASHBOARD_PASSWORD ya da telefondan erişimin şifre özeti) giriş yapılmamış istekler: sayfada aynı
 * adreste giriş formu (yeniden yazma; tarayıcının kullandığı ana makine adına dokunulmaz, proxy arkasında da çerez
 * kaybolmaz), API'de 401.
 * Şifresiz kipte panel yalnızca bu bilgisayarda (127.0.0.1) dinler; yine de `Host` geri döngü adı (localhost,
 * 127.0.0.1, [::1]) değilse 403: kötü niyetli bir sitenin DNS yeniden bağlamayla (alan adını 127.0.0.1'e çevirip)
 * tarayıcı üzerinden panele ve API'ye ulaşması engellenir. API'de ayrıca başka siteden gelen tarayıcı isteği de 403 alır
 * (`apiRefusal`, kararın tamamı orada); Next'in `/_next/data/…` veri yolları da API sayılır (`isApiPath`). Sayfalar
 * etkilenmez: başka siteden gelen bağlantı paneli açar. Şifreli kipte kural yok: oturum çerezi SameSite=Lax, başka
 * siteden gelen yazma isteği çerezsiz gelir ve 401 alır. */
export async function middleware(req: NextRequest) {
  if (isApiPath(req.nextUrl.pathname)) return (await apiRefusal(req)) ?? NextResponse.next();
  const mode = authMode();
  if (!mode) {
    if (isLoopbackHost(req.headers.get("host"))) return NextResponse.next();
    return new NextResponse("Geçersiz adres.", { status: 403, headers: { "content-type": "text/plain; charset=utf-8" } });
  }
  if (sameToken(req.cookies.get(SESSION_COOKIE)?.value, await expectedToken(mode))) return NextResponse.next();
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
  // Yalnızca giriş sayfası ve uç noktası (tam yol: /login, /api/login), Next iç dosyaları ve marka görselleri herkese açık.
  // Tam yol /api/jobs da burada değil ama açık DEĞİL: Next, ara katmanın eşleştiği isteğin gövdesini 10 MB'a kadar kopyalar,
  // 10 MB üstü video yüklemesi kesilirdi. İşleyici aynı kararı (`apiRefusal`) gövdeyi okumadan kendisi verir; /api/jobs/...
  // burada kalır.
  matcher: ["/((?!login(?:/|$)|api/login(?:/|$)|api/jobs$|_next/|brand/|favicon\\.ico).*)"],
};
