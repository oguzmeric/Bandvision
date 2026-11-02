"""Anahtarsız analiz sunucusu yalnızca bu bilgisayarla konuşur (docs/13-web-platform.md "Analiz sunucusu API" → Güvenlik).

Erişim anahtarı (ANALYZER_TOKEN) tanımlı değilken her HTTP ve WebSocket isteği (sağlık ucu `/healthz` ve API belge
sayfaları dahil) sırayla iki denetimden geçer:

1. `Host` (DNS yeniden bağlama savunması): `localhost`, `127.0.0.1` ya da `[::1]` olmalıdır (büyük/küçük harf ve port fark
   etmez). Kötü niyetli bir site kendi alan adını 127.0.0.1'e çevirse de ziyaretçinin tarayıcısı üzerinden hiçbir veriye ve
   denetime ulaşamaz; görebildiği yalnızca ret yanıtıdır. Başka ad, `Host`'suz, bozuk ya da birden çok `Host` içeren istek
   reddedilir (`HOST_REFUSED`).
2. Başka site: `Host` denetimi bunu durdurmaz, çünkü her site 127.0.0.1'e geçerli `Host` ile doğrudan istek atabilir ve
   çok parçalı `POST` CORS ön uçuşu gerektirmez. `Origin` varsa bu bilgisayarın bir kaynağı (`is_loopback_origin`) ya da
   ANALYZER_CORS_ORIGINS'teki bir değerle birebir aynı olmalıdır; `null` (listede yazılı olsa da), başka şema, bozuk değer ya
   da birden çok `Origin` reddedilir. `Origin` yoksa yalnızca `Sec-Fetch-Site: cross-site` reddedilir: panelin sunucu
   tarafı, curl ve başlatıcı bu başlıkları göndermez (`CROSS_SITE_REFUSED`).

Ret: HTTP `403`; WebSocket kabul edilmeden 1008 koduyla kapanır.

`host_name` panelin `apps/dashboard/src/lib/hostCheck.mjs` `hostName` işleviyle birebir aynıdır (aynı girdi → aynı ad).
Ara katman saf ASGI'dir (BaseHTTPMiddleware değil): MJPEG akışları ve `Range` yanıtları olduğu gibi geçer.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .jobs import JS_WHITESPACE

LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
HOST_REFUSED = ("Bu adres kabul edilmiyor: erişim anahtarı (ANALYZER_TOKEN) tanımlı değilken analiz sunucusuna "
                "yalnızca bu bilgisayardan (localhost, 127.0.0.1) bağlanılabilir.")
CROSS_SITE_REFUSED = ("Bu istek başka bir siteden geldiği için kabul edilmedi: erişim anahtarı (ANALYZER_TOKEN) tanımlı "
                      "değilken analiz sunucusu yalnızca bu bilgisayarın sayfalarından gelen istekleri kabul eder.")
WS_POLICY_VIOLATION = 1008

# JS `/^\d{1,5}$/`: yalnızca ASCII rakam (Python'da `\d` Unicode rakamlarını da tutar; `$` sondaki satır sonunu geçer)
_PORT = re.compile(r"[0-9]{1,5}")
# Origin tarayıcının ürettiği biçimdedir: şema://ad[:port]; yol, kullanıcı bilgisi ve boşluk içermez. Bu yüzden `host_name`in
# hoş gördüğü biçimler (`[localhost]`, boş port) burada bozuktur. re.ASCII: büyük/küçük harf eşlemesi `ſ`'yi `s` saymasın.
_LOOPBACK_ORIGIN = re.compile(r"https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?", re.ASCII | re.IGNORECASE)


def host_name(header: str | None) -> str | None:
    """`Host` başlığındaki ana makine adı: küçük harf, port atılmış, IPv6 köşeli parantezsiz. Geçersiz başlık (boş, bozuk
    port, kapanmamış köşeli parantez, köşeli parantezsiz IPv6…) None."""
    if not isinstance(header, str):
        return None
    h = header.strip(JS_WHITESPACE).lower()
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


def is_loopback_origin(origin: str | None) -> bool:
    """`Origin` bu bilgisayarın bir kaynağı mı: `http` ya da `https`, geri döngü adı, port olsun olmasın, yol yok. `null`,
    başka şema ve bozuk değer False. Panelin `isLoopbackOrigin` işleviyle aynıdır (ortak tablo: contracts/loopback-origins.json)."""
    return isinstance(origin, str) and _LOOPBACK_ORIGIN.fullmatch(origin) is not None


def _header_values(scope: Scope, name: bytes) -> list[str]:
    return [v.decode("latin-1") for k, v in scope.get("headers") or () if k.lower() == name]


class LocalOnlyMiddleware:
    """Anahtarsız kipte bu bilgisayardan gelmeyen HTTP/WebSocket isteğini uygulamaya ulaştırmadan reddeder (modül açıklaması).
    `allowed_origins`: ANALYZER_CORS_ORIGINS (izin verilen yabancı siteler). `lifespan` ve öteki kapsam türleri olduğu gibi
    geçer."""

    def __init__(self, app: ASGIApp, allowed_origins: Iterable[str] = ()) -> None:
        self.app = app
        self.allowed_origins = frozenset(allowed_origins)

    def _refusal(self, scope: Scope) -> str | None:
        """Ret iletisi; istek kabul ediliyorsa None. Önce `Host`, sonra başka site denetimi."""
        hosts = _header_values(scope, b"host")
        if len(hosts) != 1 or not is_loopback_host(hosts[0]):       # yok ya da birden çok (RFC 9112: geçersiz istek)
            return HOST_REFUSED
        origins = _header_values(scope, b"origin")
        if origins:                                                 # Origin varsa karar onundur
            # `null` listede yazılı olsa da reddedilir: her sitedeki korumalı iframe gönderir, tek bir siteyi göstermez
            if len(origins) != 1 or origins[0].strip().lower() == "null":
                return CROSS_SITE_REFUSED
            allowed = is_loopback_origin(origins[0]) or origins[0] in self.allowed_origins
            return None if allowed else CROSS_SITE_REFUSED
        # Her satır ve satır içindeki her virgüllü parça ayrı değerlendirilir: panel `Headers.get` ile satırları ", " ile birleştirip
        # böler; tek satırda `same-origin, cross-site` de aynı sonucu vermeli (contracts/loopback-origins.json)
        if any(part.strip().lower() == "cross-site"
               for v in _header_values(scope, b"sec-fetch-site") for part in v.split(",")):
            return CROSS_SITE_REFUSED
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        refusal = self._refusal(scope) if scope["type"] in ("http", "websocket") else None
        if refusal is None:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "http":
            await JSONResponse({"detail": refusal}, status_code=403)(scope, receive, send)
            return
        # WebSocket: bağlantı kabul edilmeden kapanır (ASGI: sunucu el sıkışmasını HTTP 403 ile reddeder). Gerekçe metni
        # kapanış iletisinin 123 baytına sığmadığı için yalnızca kod gönderilir.
        if (await receive())["type"] == "websocket.connect":
            await send({"type": "websocket.close", "code": WS_POLICY_VIOLATION, "reason": ""})
