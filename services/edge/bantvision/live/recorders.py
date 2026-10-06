"""Ağ kamerası ve kayıt cihazı (NVR/XVR) istemcileri: kanal listesi, küçük resim ve RTSP adresi.

iPhone uygulamasındaki katmanın Python karşılığı (apps/ios/BantSayac/Camera/RecorderClient.swift,
Core/Recorder.swift, Core/NetworkCamera.swift); davranış oradakiyle aynı tutulur.

- TRASSIR SDK (docs/08-trassir-integration.md): HTTPS (kendinden imzalı sertifika) `/login` → sid →
  `/channels` → `/get_video?container=rtsp` → kısa ömürlü jeton → `rtsp://sunucu:555/<jeton>`.
- Hikvision ISAPI ve Dahua CGI: HTTP Digest (Basic'e de düşer) kimlik doğrulama.

API eşzamanlıdır (web sunucusu iş parçacıklarından çağırır). Şifre hiçbir hata metnine yazılmaz; httpx'in
istek günlüğünde sorgu dizgisi (TRASSIR `/login?password=…`) gizlenir.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import threading
import urllib.parse
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from collections.abc import Callable, Generator
from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType
from typing import Any, Literal, Self, TypeVar

import httpx

__all__ = [
    "CameraBrand",
    "DahuaClient",
    "HikvisionClient",
    "RecorderBrand",
    "RecorderChannel",
    "RecorderClient",
    "RecorderError",
    "RecorderErrorKind",
    "TrassirClient",
    "camera_rtsp_url",
    "clean_host",
    "dahua_channels",
    "flag",
    "hikvision_channels",
    "make_recorder",
    "parse_trassir_json",
    "trassir_channels",
    "trassir_error",
    "trassir_value",
    "with_credentials",
]

T = TypeVar("T")

REQUEST_TIMEOUT_S = 8.0
_JPEG_MAGIC = b"\xff\xd8"
_TOKEN_RE = re.compile(r"[A-Za-z0-9._-]+")


# MARK: - Markalar ve modeller


class RecorderBrand(StrEnum):
    """Desteklenen kayıt cihazları (docs/10-field-setup.md §3c, docs/08-trassir-integration.md)."""

    TRASSIR = "trassir"
    HIKVISION = "hikvision"
    DAHUA = "dahua"

    @property
    def title(self) -> str:
        return {"trassir": "TRASSIR", "hikvision": "Hikvision", "dahua": "Dahua"}[self.value]

    @property
    def default_http_port(self) -> int:
        """Kanal listesi ve küçük resim için HTTP(S) portu. TRASSIR: SDK web sunucusu."""
        return 8080 if self is RecorderBrand.TRASSIR else 80

    @property
    def default_rtsp_port(self) -> int:
        """Görüntü portu. TRASSIR jetonlu akışı 555'ten verir."""
        return 555 if self is RecorderBrand.TRASSIR else 554

    @property
    def uses_https(self) -> bool:
        """TRASSIR SDK yalnızca HTTPS (kendinden imzalı sertifika) konuşur."""
        return self is RecorderBrand.TRASSIR


@dataclass(frozen=True)
class RecorderChannel:
    """Kayıt cihazındaki bir kamera. `id`: TRASSIR'da kanal GUID'i, Hikvision/Dahua'da kanal numarası."""

    id: str
    name: str
    number: int | None  # ekranda gösterilecek kanal numarası (TRASSIR'da yok)
    has_substream: bool

    @property
    def title(self) -> str:
        if self.number is not None:
            return self.name or f"Kanal {self.number}"
        return self.name or self.id

    @property
    def subtitle(self) -> str | None:
        return None if self.number is None else f"Kanal {self.number}"


RecorderErrorKind = Literal["unauthorized", "unreachable", "http", "unexpected", "trassir", "no_channels"]


class RecorderError(Exception):
    """Kayıt cihazı hatası; `str()` kullanıcıya gösterilecek Türkçe metindir (şifre içermez)."""

    def __init__(self, kind: RecorderErrorKind, detail: str = "", status: int | None = None) -> None:
        self.kind: RecorderErrorKind = kind
        self.detail = detail
        self.status = status
        super().__init__(self._message())

    @classmethod
    def unauthorized(cls) -> RecorderError:
        return cls("unauthorized")

    @classmethod
    def unreachable(cls, why: str) -> RecorderError:
        return cls("unreachable", why)

    @classmethod
    def http(cls, status: int) -> RecorderError:
        return cls("http", status=status)

    @classmethod
    def unexpected(cls, why: str) -> RecorderError:
        return cls("unexpected", why)

    @classmethod
    def trassir(cls, why: str) -> RecorderError:
        return cls("trassir", why)

    @classmethod
    def no_channels(cls) -> RecorderError:
        return cls("no_channels")

    def _message(self) -> str:
        match self.kind:
            case "unauthorized":
                return "Kullanıcı adı ya da şifre hatalı."
            case "unreachable":
                return f"Kayıt cihazına bağlanılamadı ({self.detail})."
            case "http":
                return f"Kayıt cihazı isteği reddetti (HTTP {self.status})."
            case "unexpected":
                return f"Kayıt cihazının yanıtı anlaşılamadı ({self.detail})."
            case "trassir":
                return f"TRASSIR: {self.detail}"
            case _:
                return "Kayıt cihazında kamera bulunamadı."

    def __str__(self) -> str:
        return self._message()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RecorderError):
            return NotImplemented
        return (self.kind, self.detail, self.status) == (other.kind, other.detail, other.status)

    def __hash__(self) -> int:
        return hash((self.kind, self.detail, self.status))

    def __reduce__(self) -> tuple[Any, ...]:
        return (RecorderError, (self.kind, self.detail, self.status))


# MARK: - Yanıt ayrıştırıcıları (ağdan bağımsız)


def flag(value: object) -> bool:
    """"1", 1, true → True."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return int(value) != 0
    if isinstance(value, str):
        return value == "1" or value.lower() == "true"
    return False


def parse_trassir_json(data: bytes) -> dict[str, Any]:
    """TRASSIR SDK yanıtı JSON'dur ama sonuna `/* … */` açıklaması ekleyebilir; açıklamalar ayıklanır."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise RecorderError.unexpected("UTF-8 değil") from None
    while (start := text.find("/*")) != -1:
        end = text.find("*/", start + 2)
        if end == -1:
            text = text[:start]
            break
        text = text[:start] + text[end + 2:]
    try:
        obj = json.loads(text)
    except ValueError:
        raise RecorderError.unexpected("JSON değil") from None
    if not isinstance(obj, dict):
        raise RecorderError.unexpected("JSON değil")
    return obj


def trassir_error(code: str) -> RecorderError:
    """TRASSIR hata kodlarını kullanıcının anlayacağı dile çevirir."""
    c = code.lower()
    if any(word in c for word in ("password", "user", "auth", "login")):
        return RecorderError.unauthorized()
    if "sdk" in c or "disabled" in c:
        return RecorderError.trassir("SDK kapalı. TRASSIR'da Ayarlar → Web sunucusu (SDK) bölümünden açın.")
    return RecorderError.trassir(code)


def trassir_value(json_obj: dict[str, Any], key: str) -> str:
    """`/login` ve `/get_video` yanıtı: {"success":1,"sid"|"token":"…"} ya da {"success":0,"error_code":"…"}."""
    value = json_obj.get(key)
    if flag(json_obj.get("success")) and isinstance(value, str) and value:
        return value
    code = json_obj.get("error_code")
    if not isinstance(code, str):
        code = json_obj.get("error")
    raise trassir_error(code if isinstance(code, str) else "bilinmeyen hata")


def trassir_channels(json_obj: dict[str, Any]) -> list[RecorderChannel]:
    """`/channels`: yerel ve uzak kanallar; kayıp kanallar (zombies) ve yinelenen GUID'ler listelenmez."""
    out: list[RecorderChannel] = []
    seen: set[str] = set()
    for key in ("channels", "remote_channels"):
        items = json_obj.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            guid = item.get("guid")
            if not isinstance(guid, str) or not guid or guid in seen:
                continue
            seen.add(guid)
            # Alan yoksa alt akış var sayılır; yoksa ana akışa düşülür
            sub = flag(item["have_substream"]) if "have_substream" in item else True
            name = item.get("name")
            out.append(RecorderChannel(id=guid, name=name if isinstance(name, str) else "",
                                       number=None, has_substream=sub))
    return out


_DAHUA_PREFIX = "table.ChannelTitle["


def dahua_channels(text: str) -> list[RecorderChannel]:
    """Dahua `configManager.cgi?action=getConfig&name=ChannelTitle`:
    `table.ChannelTitle[0].Name=Bant 1` satırları (dizin 0'dan, kanal numarası 1'den)."""
    names: dict[int, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith(_DAHUA_PREFIX):
            continue
        close = line.find("]")
        eq = line.find("=")
        if close == -1 or eq == -1 or close > eq:
            continue
        index_text = line[len(_DAHUA_PREFIX):close]
        if not re.fullmatch(r"\d+", index_text) or line[close + 1:eq] != ".Name":
            continue
        names[int(index_text)] = line[eq + 1:].strip()
    return [RecorderChannel(id=str(i + 1), name=names[i], number=i + 1, has_substream=True)
            for i in sorted(names)]


_HIKVISION_CHANNEL_TAGS = frozenset({"InputProxyChannel", "VideoInputChannel"})


def _local_name(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def hikvision_channels(data: bytes) -> list[RecorderChannel]:
    """Hikvision ISAPI: `InputProxyChannelList` (IP kanalları) ya da `VideoInputChannelList` (analog kanallar).
    Yalnızca kanal öğesinin doğrudan altındaki `<id>` ve `<name>` okunur; ad alanları yok sayılır."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return []
    channels: list[RecorderChannel] = []

    def walk(element: ET.Element) -> None:
        if _local_name(element.tag) in _HIKVISION_CHANNEL_TAGS:
            fields: dict[str, str] = {}
            for child in element:
                local = _local_name(child.tag)
                if local in ("id", "name"):
                    fields[local] = "".join(child.itertext()).strip()
            ident = fields.get("id", "")
            if re.fullmatch(r"\d+", ident) and int(ident) > 0:
                channels.append(RecorderChannel(id=ident, name=fields.get("name", ""),
                                                number=int(ident), has_substream=True))
            return  # iç içe kanal öğeleri okunmaz
        for child in element:
            walk(child)

    walk(root)
    return channels


# MARK: - Doğrudan IP kamera (RTSP adresi)


class CameraBrand(StrEnum):
    """Marka bazında RTSP yol şablonları (docs/10-field-setup.md §3b). Uymazsa `custom` ile tam adres girilir."""

    HIKVISION = "hikvision"
    DAHUA = "dahua"
    AXIS = "axis"
    VIVOTEK = "vivotek"
    MILESIGHT = "milesight"
    CUSTOM = "custom"

    @property
    def title(self) -> str:
        return {
            "hikvision": "Hikvision",
            "dahua": "Dahua",
            "axis": "Axis",
            "vivotek": "Vivotek",
            "milesight": "Milesight",
            "custom": "Diğer (tam RTSP adresi)",
        }[self.value]

    def path(self, channel: int, substream: bool) -> str:
        match self:
            case CameraBrand.HIKVISION:
                return f"/Streaming/Channels/{channel}0{2 if substream else 1}"
            case CameraBrand.DAHUA:
                return f"/cam/realmonitor?channel={channel}&subtype={1 if substream else 0}"
            case CameraBrand.AXIS:
                return "/axis-media/media.amp" + ("?resolution=640x360&fps=25" if substream else "")
            case CameraBrand.VIVOTEK:
                return f"/live{channel}s{2 if substream else 1}.sdp"
            case CameraBrand.MILESIGHT:
                return "/sub" if substream else "/main"
            case _:
                return ""


def clean_host(text: str) -> str:
    """Kullanıcının yazdığı adresten şema, kimlik, yol ve portu ayıklar ("http://192.168.1.64/" → "192.168.1.64")."""
    h = text.strip()
    if "://" in h:
        h = h.split("://", 1)[1]
    if "@" in h:
        h = h.rsplit("@", 1)[1]
    h = h.split("/", 1)[0]
    return h.split(":", 1)[0]


_BAD_HOST_CHARS = frozenset('<>"{}|\\^`#?[]%')


def _valid_host(host: str) -> bool:
    return bool(host) and not any(ch.isspace() or ch in _BAD_HOST_CHARS for ch in host)


def camera_rtsp_url(brand: CameraBrand, host: str, port: int, channel: int, substream: bool,
                    custom_url: str = "") -> str | None:
    """Şifresiz RTSP adresi; ayar eksik ya da geçersizse None."""
    if brand is CameraBrand.CUSTOM:
        s = custom_url.strip()
        if not s.lower().startswith("rtsp://"):
            return None
        try:
            hostname = urllib.parse.urlsplit(s).hostname
        except ValueError:
            return None
        return s if hostname and not any(ch.isspace() for ch in s) else None
    h = clean_host(host)
    if not _valid_host(h) or not 1 <= port <= 65535:
        return None
    return f"rtsp://{h}:{port}{brand.path(channel, substream)}"


def with_credentials(url: str, username: str, password: str) -> str:
    """RTSP adresine yüzde kodlanmış `kullanıcı:şifre@` ekler (OpenCV/FFmpeg için). Sonuç günlüğe yazılmamalı.

    Adreste zaten kimlik varsa yenisiyle değiştirilir; ikisi de boşsa adres olduğu gibi döner."""
    if not username and not password:
        return url
    parts = urllib.parse.urlsplit(url)
    hostport = parts.netloc.rsplit("@", 1)[-1]
    userinfo = urllib.parse.quote(username, safe="")
    if password:
        userinfo += ":" + urllib.parse.quote(password, safe="")
    return urllib.parse.urlunsplit(parts._replace(netloc=f"{userinfo}@{hostport}"))


# MARK: - HTTP


class _RedactQueryFilter(logging.Filter):
    """httpx her isteği INFO düzeyinde tam adresle günlüğe yazar; TRASSIR `/login` sorgusunda şifre vardır."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and any(isinstance(a, httpx.URL) and a.query for a in record.args):
            record.args = tuple(
                f"{str(a).split('?', 1)[0]}?…" if isinstance(a, httpx.URL) and a.query else a
                for a in record.args
            )
        return True


_httpx_logger = logging.getLogger("httpx")
if not any(isinstance(f, _RedactQueryFilter) for f in _httpx_logger.filters):
    _httpx_logger.addFilter(_RedactQueryFilter())


class _DeviceAuth(httpx.Auth):
    """Cihaz 401 ile isterse Digest (tercih) ya da Basic; ikinci deneme yok (yanlış şifre → 401 → "şifre hatalı").
    Her istek için yeni nesne: iş parçacıkları arasında paylaşılan nonce durumu olmaz."""

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        response = yield request
        if response.status_code != 401 or not self._username:
            return
        challenges = [h.strip().lower() for h in response.headers.get_list("www-authenticate")]
        if any(c.startswith("digest ") for c in challenges):
            flow = httpx.DigestAuth(self._username, self._password).auth_flow(request)
            next(flow)
            try:
                retry = flow.send(response)
            except StopIteration:
                return
            yield retry
        elif any(c.startswith("basic") for c in challenges):
            raw = f"{self._username}:{self._password}".encode()
            request.headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
            yield request


def _encode(value: str) -> str:
    """Yalnızca ayrılmamış karakterler bırakılır (şifredeki `+`, `&`, `=` güvenli)."""
    return urllib.parse.quote(value, safe="")


def _describe_connect_error(exc: httpx.ConnectError, target: str) -> RecorderError:
    text = str(exc).lower()
    if "ssl" in text or "certificate" in text or "tls" in text:
        return RecorderError.unreachable("güvenli bağlantı kurulamadı")
    if any(s in text for s in ("getaddrinfo", "name or service", "nodename", "name resolution", "11001")):
        return RecorderError.unreachable("adres bulunamadı")
    return RecorderError.unreachable(f"{target} bağlantıyı kabul etmedi")


class _DeviceHTTP:
    """Yerel ağdaki cihazla HTTP(S). Yalnızca kullanıcının girdiği adrese gider; yönlendirme izlenmez.
    `insecure`: kendinden imzalı sertifika kabul edilir (yalnızca TRASSIR, yalnızca bu adres)."""

    def __init__(self, host: str, port: int, https: bool, username: str, password: str,
                 insecure: bool = False) -> None:
        self.host = host
        self.port = port
        self.https = https
        self._username = username
        self._password = password
        self._client = httpx.Client(verify=not insecure, follow_redirects=False,
                                    timeout=httpx.Timeout(REQUEST_TIMEOUT_S), trust_env=False)

    def get(self, path: str, query: list[tuple[str, str]] | None = None) -> bytes:
        scheme = "https" if self.https else "http"
        url = f"{scheme}://{self.host}:{self.port}{path}"
        if query:
            url += "?" + "&".join(f"{_encode(k)}={_encode(v)}" for k, v in query)
        return self.get_url(url)

    def get_url(self, url: str) -> bytes:
        try:
            parsed = httpx.URL(url)
        except httpx.InvalidURL:
            raise RecorderError.unexpected("geçersiz adres") from None
        if parsed.host != self.host.lower():
            raise RecorderError.unexpected("geçersiz adres")
        target = f"{self.host}:{parsed.port or ''}"
        try:
            response = self._client.get(parsed, auth=_DeviceAuth(self._username, self._password))
        except httpx.TimeoutException:
            raise RecorderError.unreachable(f"{target} yanıt vermedi") from None
        except httpx.ConnectError as exc:
            raise _describe_connect_error(exc, target) from None
        except (httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError):
            raise RecorderError.unreachable("bağlantı koptu") from None
        except httpx.InvalidURL:
            raise RecorderError.unexpected("geçersiz adres") from None
        except httpx.HTTPError:
            raise RecorderError.unreachable("ağ hatası") from None
        if 200 <= response.status_code < 300:
            return response.content
        if response.status_code == 401:
            raise RecorderError.unauthorized()
        raise RecorderError.http(response.status_code)

    def close(self) -> None:
        self._client.close()


def _rtsp_url(host: str, port: int, path: str) -> str:
    return f"rtsp://{host}:{port}{path}"


def _require_jpeg(data: bytes) -> bytes:
    if not data.startswith(_JPEG_MAGIC):
        raise RecorderError.unexpected("JPEG değil")
    return data


# MARK: - İstemciler


class RecorderClient(ABC):
    """Kayıt cihazının kanal listesi, akış adresi ve küçük resim API'si. İş parçacığı güvenlidir."""

    _http: _DeviceHTTP

    @abstractmethod
    def channels(self) -> list[RecorderChannel]: ...

    @abstractmethod
    def stream_url(self, channel: RecorderChannel, substream: bool) -> str:
        """Şifresiz RTSP adresi. Her bağlanışta yeniden çağrılmalı: TRASSIR'da adres kısa ömürlü jeton içerir."""

    @abstractmethod
    def snapshot(self, channel: RecorderChannel) -> bytes:
        """JPEG; desteklenmiyorsa RecorderError (arayüz RTSP ile ilk kareye düşer)."""

    def keep_alive(self, stream_url: str) -> None:
        """Akış açıkken düzenli çağrılır (TRASSIR jetonu canlı tutulur). Varsayılan: hiçbir şey."""

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        self.close()


def _channel_number(channel: RecorderChannel) -> int:
    if channel.number is None:
        raise RecorderError.unexpected("kanal numarası yok")
    return channel.number


class HikvisionClient(RecorderClient):
    """Hikvision ISAPI."""

    def __init__(self, http: _DeviceHTTP, host: str, rtsp_port: int) -> None:
        self._http = http
        self.host = host
        self.rtsp_port = rtsp_port

    def channels(self) -> list[RecorderChannel]:
        """IP kanalları (NVR) ve analog kanallar (DVR/XVR); karma cihazda ikisi birlikte."""
        found: list[RecorderChannel] = []
        first_error: RecorderError | None = None
        for path in ("/ISAPI/ContentMgmt/InputProxy/channels", "/ISAPI/System/Video/inputs/channels"):
            try:
                found += hikvision_channels(self._http.get(path))
            except RecorderError as exc:
                if exc.kind == "unauthorized":
                    raise
                first_error = first_error or exc
        seen: set[str] = set()
        unique: list[RecorderChannel] = []
        for ch in found:
            if ch.id not in seen:
                seen.add(ch.id)
                unique.append(ch)
        unique.sort(key=lambda c: c.number or 0)
        if not unique:
            raise first_error or RecorderError.no_channels()
        return unique

    def stream_url(self, channel: RecorderChannel, substream: bool) -> str:
        n = _channel_number(channel)
        return _rtsp_url(self.host, self.rtsp_port, f"/Streaming/Channels/{n}0{2 if substream else 1}")

    def snapshot(self, channel: RecorderChannel) -> bytes:
        n = _channel_number(channel)
        try:
            return _require_jpeg(self._http.get(f"/ISAPI/Streaming/channels/{n}01/picture"))
        except RecorderError as exc:
            if exc.kind == "unauthorized":
                raise
        return _require_jpeg(self._http.get(f"/ISAPI/Streaming/channels/{n}02/picture"))


class DahuaClient(RecorderClient):
    """Dahua CGI."""

    def __init__(self, http: _DeviceHTTP, host: str, rtsp_port: int) -> None:
        self._http = http
        self.host = host
        self.rtsp_port = rtsp_port

    def channels(self) -> list[RecorderChannel]:
        data = self._http.get("/cgi-bin/configManager.cgi", [("action", "getConfig"), ("name", "ChannelTitle")])
        found = dahua_channels(data.decode("utf-8", errors="replace"))
        if not found:
            raise RecorderError.no_channels()
        return found

    def stream_url(self, channel: RecorderChannel, substream: bool) -> str:
        n = _channel_number(channel)
        return _rtsp_url(self.host, self.rtsp_port, f"/cam/realmonitor?channel={n}&subtype={1 if substream else 0}")

    def snapshot(self, channel: RecorderChannel) -> bytes:
        n = _channel_number(channel)
        return _require_jpeg(self._http.get("/cgi-bin/snapshot.cgi", [("channel", str(n))]))


class TrassirClient(RecorderClient):
    """TRASSIR SDK: `/login` → sid (15 dk, her istekle uzar) → `/channels` → `/get_video` → jeton (~10 sn).
    Oturum düşmüşse bir kez yeniden giriş yapılıp istek tekrarlanır."""

    def __init__(self, http: _DeviceHTTP, host: str, rtsp_port: int, username: str, password: str) -> None:
        self._http = http
        self.host = host
        self.rtsp_port = rtsp_port
        self._username = username
        self._password = password
        self._sid: str | None = None
        self._lock = threading.Lock()

    def channels(self) -> list[RecorderChannel]:
        def body(sid: str) -> list[RecorderChannel]:
            obj = parse_trassir_json(self._http.get("/channels", [("sid", sid)]))
            if "success" in obj and not flag(obj["success"]):
                code = obj.get("error_code")
                raise trassir_error(code if isinstance(code, str) else "kanal listesi alınamadı")
            found = trassir_channels(obj)
            if not found:
                raise RecorderError.no_channels()
            return found

        return self._with_session(body)

    def stream_url(self, channel: RecorderChannel, substream: bool) -> str:
        token = self._video_token(channel, "rtsp", "sub" if substream and channel.has_substream else "main")
        return _rtsp_url(self.host, self.rtsp_port, "/" + token)

    def snapshot(self, channel: RecorderChannel) -> bytes:
        token = self._video_token(channel, "jpeg", "sub" if channel.has_substream else "main")
        return _require_jpeg(self._http.get_url(f"http://{self.host}:{self.rtsp_port}/{token}"))

    def keep_alive(self, stream_url: str) -> None:
        """Jeton yalnızca istek geldikçe yaşar; akış açıkken düzenli `?ping`. Hata yutulur."""
        path = urllib.parse.urlsplit(stream_url).path
        if not path.startswith("/") or not _TOKEN_RE.fullmatch(path[1:]):
            return
        try:
            self._http.get_url(f"http://{self.host}:{self.rtsp_port}{path}?ping")
        except RecorderError:
            pass

    def _video_token(self, channel: RecorderChannel, container: str, stream: str) -> str:
        def body(sid: str) -> str:
            data = self._http.get("/get_video", [("channel", channel.id), ("container", container),
                                                 ("stream", stream), ("sid", sid)])
            token = trassir_value(parse_trassir_json(data), "token")
            # Jeton yola girer: yalnızca güvenli karakterler
            if not _TOKEN_RE.fullmatch(token):
                raise RecorderError.unexpected("jeton biçimi")
            return token

        return self._with_session(body)

    def _with_session(self, body: Callable[[str], T]) -> T:
        current = self._session()
        try:
            return body(current)
        except RecorderError as exc:
            if exc.kind in ("unreachable", "unauthorized"):
                raise
            with self._lock:                       # oturum düşmüş olabilir: bir kez yeniden giriş
                if self._sid == current:
                    self._sid = None
            return body(self._session())

    def _session(self) -> str:
        with self._lock:
            if self._sid is not None:
                return self._sid
            data = self._http.get("/login", [("username", self._username), ("password", self._password)])
            self._sid = trassir_value(parse_trassir_json(data), "sid")
            return self._sid


def make_recorder(brand: RecorderBrand, host: str, http_port: int, rtsp_port: int,
                  username: str, password: str) -> RecorderClient:
    """Markaya göre istemci. `host` temizlenir (şema/port/yol atılır). İş bitince `close()` çağrılmalı."""
    brand = RecorderBrand(brand)
    host = clean_host(host)
    if not _valid_host(host):
        raise RecorderError.unexpected("geçersiz adres")
    http = _DeviceHTTP(host, http_port, brand.uses_https, username, password, insecure=brand.uses_https)
    match brand:
        case RecorderBrand.TRASSIR:
            return TrassirClient(http, host, rtsp_port, username, password)
        case RecorderBrand.HIKVISION:
            return HikvisionClient(http, host, rtsp_port)
        case RecorderBrand.DAHUA:
            return DahuaClient(http, host, rtsp_port)
