"""`Host` başlığı denetimi (DNS yeniden bağlama savunması; docs/13-web-platform.md "Analiz sunucusu API" → Güvenlik).

Erişim anahtarı (ANALYZER_TOKEN) tanımlı değilken analiz sunucusu yalnızca bu bilgisayarın adlarıyla konuşur: her HTTP ve
WebSocket isteğinde (sağlık ucu `/healthz` ve API belge sayfaları dahil) `Host` `localhost`, `127.0.0.1` ya da `[::1]`
olmalıdır (büyük/küçük harf ve port fark etmez). Kötü niyetli bir site kendi alan adını 127.0.0.1'e çevirip ziyaretçinin
tarayıcısı üzerinden analiz sunucusuna ulaşamaz, varlığını bile yoklayamaz. Başka ad, `Host`'suz, bozuk ya da birden
çok `Host` içeren HTTP isteği `403` (`HOST_REFUSED`) alır; WebSocket kabul edilmeden 1008 koduyla kapanır.

Ayrıştırıcı panelin `apps/dashboard/src/lib/hostCheck.mjs` `hostName` işleviyle birebir aynıdır (aynı girdi → aynı ad).
Ara katman saf ASGI'dir (BaseHTTPMiddleware değil): MJPEG akışları ve `Range` yanıtları olduğu gibi geçer.
"""
from __future__ import annotations

import re

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
HOST_REFUSED = ("Bu adres kabul edilmiyor: erişim anahtarı (ANALYZER_TOKEN) tanımlı değilken analiz sunucusuna "
                "yalnızca bu bilgisayardan (localhost, 127.0.0.1) bağlanılabilir.")
WS_POLICY_VIOLATION = 1008

# JavaScript `String.prototype.trim`'in attığı karakterler (boşluk + satır sonu). Python'un `str.strip()`'i farklıdır
# (\x1c-\x1f ve \x85'i de atar, \ufeff'i atmaz): ayrıştırıcı panelinkiyle her girdide aynı sonucu versin diye açık küme.
_JS_WHITESPACE = ("\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
                  "\u2028\u2029\u202f\u205f\u3000\ufeff")
# JS `/^\d{1,5}$/`: yalnızca ASCII rakam (Python'da `\d` Unicode rakamlarını da tutar; `$` sondaki satır sonunu geçer)
_PORT = re.compile(r"[0-9]{1,5}")


def host_name(header: str | None) -> str | None:
    """`Host` başlığındaki ana makine adı: küçük harf, port atılmış, IPv6 köşeli parantezsiz. Geçersiz başlık (boş, bozuk
    port, kapanmamış köşeli parantez, köşeli parantezsiz IPv6…) None."""
    if not isinstance(header, str):
        return None
    h = header.strip(_JS_WHITESPACE).lower()
    port = ""
    if h.startswith("["):
        end = h.find("]")
        if end < 0:
            return None
        name = h[1:end]
        rest = h[end + 1:]
        if rest != "":
            if not rest.startswith(":"):
                return None
            port = rest[1:]
    else:
        parts = h.split(":")
        if len(parts) > 2:
            return None
        name = parts[0]
        port = parts[1] if len(parts) == 2 else ""
    if not name or (port != "" and not _PORT.fullmatch(port)):
        return None
    return name


def is_loopback_host(header: str | None) -> bool:
    """Geri döngü adı mı (localhost, 127.0.0.1, [::1]): anahtarsız kipte analiz sunucusu yalnızca bu adlarla açılır."""
    return host_name(header) in LOOPBACK_NAMES


def _host_header(scope: Scope) -> str | None:
    """İsteğin tek `Host` başlığı; yoksa ya da birden çoksa (RFC 9112: geçersiz istek) None."""
    values = [v for k, v in scope.get("headers") or () if k.lower() == b"host"]
    return values[0].decode("latin-1") if len(values) == 1 else None


class LoopbackHostMiddleware:
    """Anahtarsız kipte `Host` geri döngü adı olmayan HTTP/WebSocket isteğini uygulamaya ulaştırmadan reddeder.
    `lifespan` (ve öteki kapsam türleri) olduğu gibi geçer."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or is_loopback_host(_host_header(scope)):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "http":
            await JSONResponse({"detail": HOST_REFUSED}, status_code=403)(scope, receive, send)
            return
        # WebSocket: bağlantı kabul edilmeden kapanır (ASGI: sunucu el sıkışmasını HTTP 403 ile reddeder). Gerekçe metni
        # kapanış iletisinin 123 baytına sığmadığı için yalnızca kod gönderilir.
        if (await receive())["type"] == "websocket.connect":
            await send({"type": "websocket.close", "code": WS_POLICY_VIOLATION, "reason": ""})
