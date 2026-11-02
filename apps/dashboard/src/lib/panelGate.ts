import { NextResponse, type NextRequest } from "next/server";
import { CROSS_SITE_REFUSED, crossSiteRefused, isLoopbackHost } from "./hostCheck.mjs";
import { SESSION_COOKIE, authMode, expectedToken, sameToken } from "./session";

/**
 * API isteğinin giriş kapısı; geçerse null. Ara katman `/api/` yolları için çağırır. Ara katmandan geçmeyen `/api/jobs`
 * (video yükleme; nedeni `middleware.ts` `matcher`) işleyicisinde, gövdeden hiçbir şey okumadan kendisi çağırır: karar ve
 * yanıtlar aynıdır. Edge ve Node'da çalışır.
 *   - Şifreli kip: oturum çerezi yoksa ya da yanlışsa 401.
 *   - Şifresiz kip: `Host` geri döngü adı değilse 403 (DNS yeniden bağlama), başka siteden gelen tarayıcı isteği 403:
 *     vekil isteği sunucu tarafından, `Origin`'siz iletir, analiz sunucusunun aynı denetimi bunu göremez.
 */
export async function apiRefusal(req: NextRequest): Promise<Response | null> {
  const mode = authMode();
  if (!mode) {
    if (!isLoopbackHost(req.headers.get("host"))) return NextResponse.json({ error: "Geçersiz adres." }, { status: 403 });
    if (crossSiteRefused(req.headers.get("origin"), req.headers.get("sec-fetch-site"))) {
      return NextResponse.json({ error: CROSS_SITE_REFUSED }, { status: 403 });
    }
    return null;
  }
  if (sameToken(req.cookies.get(SESSION_COOKIE)?.value, await expectedToken(mode))) return null;
  return NextResponse.json({ error: "Giriş gerekli." }, { status: 401 });
}
