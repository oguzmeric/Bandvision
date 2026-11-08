"""Kayıt cihazı arşivi (kayıttan izleme): marka bağdaştırıcıları, yanıt ayrıştırıcıları, zaman biçimleri.

Her bağdaştırıcı `recorders.py`'deki canlı istemciyi sarar (aynı HTTP oturumu, adres, RTSP portu, TRASSIR'da
aynı sid). API zamanları epoch saniyedir (UTC, float). Hikvision'a UTC, Dahua ve TRASSIR'a yerel saat gider
(`tz=None`: bu bilgisayarın saat dilimi; testler belirli bir dilim verebilir). Gün sınırları yerel saattedir:
`day` yerel gece yarısıdır, gün sonu bir sonraki yerel gece yarısıdır (yaz saati gününde 23/25 saat).

- TRASSIR (SDK belgesi): `get_video stream=archive_main|archive_sub` jetonu + `archive_command play/stop`;
  çizelge ve takvim `archive_status type=timeline|calendar`; dışa aktarma `jit-export-*`. Ofis cihazında
  doğrulanacak; yanıt biçimi farklıysa ayrıştırıcı düzelir.
- Hikvision ISAPI ve Dahua CGI: cihazda doğrulanmadı.

`stream_url` şifresiz RTSP adresi döner (Hikvision/Dahua kimliği çağıran `with_credentials` ile ekler, canlı
akıştaki gibi). Jeton ve şifre günlüğe yazılmaz.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from collections.abc import Callable, Generator, Iterable, Iterator
from datetime import UTC, date, datetime, timedelta, tzinfo
from types import TracebackType
from typing import Any, Self, TypeVar

import cv2

from bantvision.live.recorders import (
    _TOKEN_RE,
    DahuaClient,
    HikvisionClient,
    RecorderBrand,
    RecorderChannel,
    RecorderClient,
    RecorderError,
    TrassirClient,
    _channel_number,
    _DeviceHTTP,
    _local_name,
    _rtsp_url,
    flag,
    parse_trassir_any,
    trassir_error,
)

__all__ = [
    "ArchiveClient",
    "DahuaArchive",
    "ExportStream",
    "FileArchive",
    "HikvisionArchive",
    "TrassirArchive",
    "dahua_time",
    "day_end",
    "hik_iso",
    "hik_utc",
    "make_archive",
    "merge_ranges",
    "parse_dahua_find",
    "parse_hik_daily",
    "parse_hik_search",
    "parse_trassir_calendar",
    "parse_trassir_timeline",
    "trassir_time",
]

log = logging.getLogger(__name__)
R = TypeVar("R")

DAY_S = 86400
HIK_PAGE = 400
HIK_MAX_PAGES = 10
DAHUA_PAGE = 100
DAHUA_MAX_PAGES = 50
TRASSIR_STATUS_TRIES = 3
TRASSIR_STATUS_WAIT_S = 0.5
EXPORT_READ_TIMEOUT_S = 600.0
EXPORT_READY_TRIES = 20
EXPORT_READY_WAIT_S = 1.0
_EXPORT_PEEK_LIMIT = 64 * 1024
_EXPORT_HEAD = 12           # MP4: 4 bayt kutu boyu + `ftyp` + marka
_RESPONSE = "arşiv yanıtı"


# MARK: - Zaman biçimleri


def hik_utc(epoch: float) -> str:
    """Hikvision RTSP oynatma zamanı: `YYYYMMDDTHHMMSSZ` (UTC)."""
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y%m%dT%H%M%SZ")


def hik_iso(epoch: float) -> str:
    """Hikvision ISAPI zamanı: `YYYY-MM-DDTHH:MM:SSZ` (UTC)."""
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def dahua_time(epoch: float, sep: str, tz: tzinfo | None = None) -> str:
    """Dahua yerel saati. `sep="_"`: RTSP `YYYY_MM_DD_HH_MM_SS`; başka ayraç (ör. "-"): CGI `YYYY-MM-DD HH:MM:SS`."""
    local = _local(epoch, tz)
    if sep == "_":
        return local.strftime("%Y_%m_%d_%H_%M_%S")
    return local.strftime(f"%Y{sep}%m{sep}%d %H:%M:%S")


def trassir_time(epoch: float, tz: tzinfo | None = None) -> str:
    """TRASSIR `archive_command` zamanı: yerel `YYYYMMDDTHHMMSS` (SDK'nın kabul ettiği biçimlerden adreste güvenli olanı)."""
    return _local(epoch, tz).strftime("%Y%m%dT%H%M%S")


def _local(epoch: float, tz: tzinfo | None) -> datetime:
    """Yerel saat (bölge bilgili). `tz=None`: bu bilgisayarın saat dilimi."""
    return datetime.fromtimestamp(epoch, UTC).astimezone(tz)


def _local_epoch(d: date, tz: tzinfo | None, hour: int = 0, minute: int = 0, second: int = 0) -> float:
    if tz is None:
        return time.mktime((d.year, d.month, d.day, hour, minute, second, 0, 0, -1))
    return datetime(d.year, d.month, d.day, hour, minute, second, tzinfo=tz).timestamp()


def day_end(day: float, tz: tzinfo | None = None) -> float:
    """`day` gününün bitişi: bir sonraki yerel gece yarısı (yaz saati gününde 23 ya da 25 saat sonra)."""
    return _local_epoch(_local(day, tz).date() + timedelta(days=1), tz)


def _month_bounds(year: int, month: int, tz: tzinfo | None) -> tuple[float, float]:
    first = date(year, month, 1)
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return _local_epoch(first, tz), _local_epoch(nxt, tz)


# MARK: - Aralıklar


def merge_ranges(ranges: Iterable[tuple[float, float]], gap: float = 2.0) -> list[tuple[float, float]]:
    """Sıralar; örtüşen ya da en çok `gap` sn boşluklu aralıkları birleştirir; boş/ters aralıkları atar."""
    out: list[tuple[float, float]] = []
    for start, end in sorted((float(a), float(b)) for a, b in ranges if b > a):
        if out and start <= out[-1][1] + gap:
            if end > out[-1][1]:
                out[-1] = (out[-1][0], end)
        else:
            out.append((start, end))
    return out


def _clip(ranges: Iterable[tuple[float, float]], lo: float, hi: float) -> list[tuple[float, float]]:
    """Aralıkları [lo, hi] içine kırpar ve birleştirir (gece yarısını aşan kayıt çizelgede o güne sığar)."""
    return merge_ranges((max(a, lo), min(b, hi)) for a, b in ranges)


# MARK: - TRASSIR ayrıştırıcıları


def _trassir_items(obj: object) -> list[dict[str, Any]]:
    """`archive_status` yanıtı tek nesne ya da nesne listesi olabilir; hata yanıtı TRASSIR hatasına çevrilir."""
    items = obj if isinstance(obj, list) else [obj]
    if not all(isinstance(i, dict) for i in items):
        raise RecorderError.unexpected(_RESPONSE)
    for item in items:
        if "success" in item and not flag(item["success"]):
            code = item.get("error_code")
            raise trassir_error(code if isinstance(code, str) else "arşiv durumu alınamadı")
    return items


def _for_token(items: list[dict[str, Any]], token: str | None) -> list[dict[str, Any]]:
    """Liste birden çok jetonun durumunu içerebilir: jeton verilmişse ve öğede varsa yalnız eşleşen öğe."""
    if token is None:
        return items
    return [i for i in items if not isinstance(i.get("token"), str) or i["token"] == token]


_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_trassir_calendar(obj: object, token: str | None = None) -> set[str]:
    """`archive_status type=calendar`: `calendar` listesindeki `YYYY-MM-DD` dizgileri (biçimsiz öğeler atlanır)."""
    found: set[str] = set()
    for item in _for_token(_trassir_items(obj), token):
        days = item.get("calendar")
        if not isinstance(days, list):
            raise RecorderError.unexpected(_RESPONSE)
        found.update(d for d in days if isinstance(d, str) and _DATE_RE.fullmatch(d))
    return found


def _parse_day(value: object) -> date:
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                parsed = time.strptime(value.strip(), fmt)
            except ValueError:
                continue
            return date(parsed.tm_year, parsed.tm_mon, parsed.tm_mday)
    raise RecorderError.unexpected(_RESPONSE)


def _trassir_timeline(obj: object, day: float, token: str | None,
                      tz: tzinfo | None) -> tuple[list[tuple[float, float]], bool]:
    """(aralıklar, gün uyuşmadı mı). `begin`/`end` `day_start` gününün yerel gece yarısından saniyedir."""
    wanted = _local(day, tz).date()
    ranges: list[tuple[float, float]] = []
    mismatch = False
    for item in _for_token(_trassir_items(obj), token):
        entries = item.get("timeline")
        if not isinstance(entries, list) or "day_start" not in item:
            raise RecorderError.unexpected(_RESPONSE)
        got = _parse_day(item["day_start"])
        if got != wanted:
            mismatch = True
            continue
        base = _local_epoch(got, tz)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            begin, end = entry.get("begin"), entry.get("end")
            if isinstance(begin, int | float) and isinstance(end, int | float) \
                    and not isinstance(begin, bool) and not isinstance(end, bool):
                ranges.append((base + begin, base + end))
    return _clip(ranges, day, day_end(day, tz)), mismatch


def parse_trassir_timeline(obj: object, day: float, token: str | None = None,
                           tz: tzinfo | None = None) -> list[tuple[float, float]]:
    """`archive_status type=timeline`: `[{"token", "day_start": "YYYY-MM-DD", "timeline": [{"begin", "end"}]}]`.
    `day_start` istenen gün değilse boş liste."""
    return _trassir_timeline(obj, day, token, tz)[0]


# MARK: - Hikvision ayrıştırıcıları


def _xml_root(data: bytes) -> ET.Element:
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        raise RecorderError.unexpected(_RESPONSE) from None


def _child_text(element: ET.Element, name: str) -> str | None:
    for child in element.iter():
        if child is not element and _local_name(child.tag) == name:
            return "".join(child.itertext()).strip()
    return None


def _parse_hik_time(text: str | None) -> float | None:
    """ISAPI zamanı; `Z`/ofsetli ya da ofsetsiz (UTC sayılır, aramayı UTC istedik)."""
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


_HIK_STATUSES = frozenset({"OK", "MORE", "NO MATCHES"})


def parse_hik_search(xml: bytes) -> tuple[list[tuple[float, float]], str]:
    """`/ISAPI/ContentMgmt/search` yanıtı → (aralıklar, `OK|MORE|NO MATCHES`). Ad alanı yok sayılır."""
    root = _xml_root(xml)
    if _local_name(root.tag) != "CMSearchResult":
        raise RecorderError.unexpected(_RESPONSE)
    status = (_child_text(root, "responseStatusStrg") or "").upper()
    if status not in _HIK_STATUSES:
        raise RecorderError.unexpected(_RESPONSE)
    ranges: list[tuple[float, float]] = []
    for item in root.iter():
        if _local_name(item.tag) != "searchMatchItem":
            continue
        start = _parse_hik_time(_child_text(item, "startTime"))
        end = _parse_hik_time(_child_text(item, "endTime"))
        if start is not None and end is not None:
            ranges.append((start, end))
    return ranges, status


def parse_hik_daily(xml: bytes) -> set[int]:
    """`dailyDistribution` yanıtı: `<dayList><day><dayOfMonth>D</dayOfMonth><record>true</record>` → kayıtlı günler."""
    root = _xml_root(xml)
    lists = [e for e in root.iter() if _local_name(e.tag) == "dayList"]
    if not lists:
        raise RecorderError.unexpected(_RESPONSE)
    days: set[int] = set()
    for day_list in lists:
        for day in day_list:
            if _local_name(day.tag) != "day":
                continue
            number = _child_text(day, "dayOfMonth") or ""
            if re.fullmatch(r"\d{1,2}", number) and (_child_text(day, "record") or "").lower() == "true":
                days.add(int(number))
    return days


# MARK: - Dahua ayrıştırıcısı

_DAHUA_FOUND = re.compile(r"^found=(\d+)\s*$", re.MULTILINE)
_DAHUA_ITEM = re.compile(r"^items\[(\d+)\]\.(StartTime|EndTime)=(.*?)\s*$", re.MULTILINE)
_DAHUA_TIME = re.compile(r"(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})")


def _parse_dahua_time(text: str, tz: tzinfo | None) -> float | None:
    match = _DAHUA_TIME.fullmatch(text)
    if match is None:
        return None
    y, mo, d, h, mi, s = (int(g) for g in match.groups())
    try:
        return _local_epoch(date(y, mo, d), tz, h, mi, s)
    except (ValueError, OverflowError):
        return None


def _dahua_page(text: str, tz: tzinfo | None) -> tuple[list[tuple[float, float]], int]:
    """Bir `findNextFile` sayfası → (aralıklar, `found`); `found=` satırı yoksa `unexpected`."""
    found = _DAHUA_FOUND.search(text)
    if found is None:
        raise RecorderError.unexpected(_RESPONSE)
    fields: dict[int, dict[str, str]] = {}
    for match in _DAHUA_ITEM.finditer(text):
        fields.setdefault(int(match.group(1)), {})[match.group(2)] = match.group(3)
    ranges: list[tuple[float, float]] = []
    for index in sorted(fields):
        start = _parse_dahua_time(fields[index].get("StartTime", ""), tz)
        end = _parse_dahua_time(fields[index].get("EndTime", ""), tz)
        if start is not None and end is not None:
            ranges.append((start, end))
    return ranges, int(found.group(1))


def parse_dahua_find(text: str, tz: tzinfo | None = None) -> list[tuple[float, float]]:
    """`mediaFileFind.cgi?action=findNextFile`: `found=k` ve `items[i].StartTime=`/`EndTime=` (yerel saat)."""
    return _dahua_page(text, tz)[0]


# MARK: - Dışa aktarma akışı


class ExportStream(Iterator[bytes]):
    """Dışa aktarılan dosyanın parçaları. `close()` (ya da `with`) cihaz bağlantısını kapatır; ilk parça
    okunmadan bırakılsa da kapanır. Sonuna kadar okununca kendiliğinden kapanır."""

    def __init__(self, head: bytes, rest: Generator[bytes, None, None]) -> None:
        self._head: bytes | None = head
        self._rest = rest

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> bytes:
        if self._head is not None:
            head, self._head = self._head, None
            return head
        return next(self._rest)

    def close(self) -> None:
        self._head = None
        self._rest.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        self.close()


# MARK: - Bağdaştırıcılar


class ArchiveClient(ABC):
    """Bir kayıt cihazının arşivi: oynatma adresi, takvim, çizelge, dışa aktarma.

    Takvim/çizelge çağrıları aynı sid üzerinde eşzamanlı yapılmamalı (TRASSIR `archive_status` jetonsuz; ofis
    NVR'ında doğrulanacak). `ArchiveManager` (Task 2) bu çağrıları kaynak başına bir kilitle sıralar.
    `tz`: Dahua/TRASSIR yerel saat çevrimi (None = bu bilgisayarın saat dilimi)."""

    speeds: tuple[int, ...] = (1, 2, 4)
    can_export: bool = False
    tz: tzinfo | None = None

    @abstractmethod
    def stream_url(self, channel: RecorderChannel, start: float, end: float | None, substream: bool,
                   speed: int) -> str:
        """Şifresiz oynatma adresi. Her açılışta yeniden çağrılmalı (TRASSIR jetonu kısa ömürlü).
        `speed` `speeds` içinde değilse `ValueError` (programlama hatası)."""

    def stop(self, stream_url: str) -> None:
        """Oynatma kapanırken çağrılır. Varsayılan: hiçbir şey."""

    def keep_alive(self, stream_url: str) -> None:
        """Akış açıkken düzenli çağrılır. Varsayılan: hiçbir şey."""

    @abstractmethod
    def calendar(self, channel: RecorderChannel, year: int, month: int) -> set[int]:
        """Ayın kayıt olan günleri (1..31)."""

    @abstractmethod
    def timeline(self, channel: RecorderChannel, day: float) -> list[tuple[float, float]]:
        """`day` (yerel gece yarısı) gününün birleştirilmiş kayıt aralıkları, gün sınırına kırpılmış."""

    def export(self, channel: RecorderChannel, start: float, end: float) -> ExportStream:
        """Aralığın video dosyası (parça parça). Desteklenmiyorsa `RecorderError.unsupported()`."""
        raise RecorderError.unsupported()

    def _check_speed(self, speed: int) -> None:
        if speed not in self.speeds:
            raise ValueError(f"hız {speed} desteklenmiyor")


class TrassirArchive(ArchiveClient):
    """TRASSIR SDK arşivi; canlı `TrassirClient`'ın oturumunu ve jeton yardımcılarını kullanır."""

    speeds = (1, 2, 4, 8, 16)
    can_export = True

    def __init__(self, client: TrassirClient, tz: tzinfo | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._live = client
        self._http: _DeviceHTTP = client._http
        self.tz = tz
        self._sleep = sleep

    def stream_url(self, channel: RecorderChannel, start: float, end: float | None, substream: bool,
                   speed: int) -> str:
        self._check_speed(speed)
        token = self._token(channel, substream)
        self._play(token, start, end, speed)
        return _rtsp_url(self._live.host, self._live.rtsp_port, "/" + token)

    def stop(self, stream_url: str) -> None:
        """`archive_command stop`: tek istek, yineleme ve yeniden giriş yok (ölü jeton paylaşılan sid'i
        düşürmesin). Hata yutulur (oynatıcı zaten kapanıyor)."""
        token = _url_token(stream_url)
        if token is None:
            return
        try:
            data = self._http.get("/archive_command", [("command", "stop"), ("token", token),
                                                       ("sid", self._live._session())])
            _trassir_items(parse_trassir_any(data))
        except RecorderError as exc:
            log.debug("TRASSIR arşiv durdurma başarısız: %s", exc.kind)

    def keep_alive(self, stream_url: str) -> None:
        self._live.keep_alive(stream_url)

    def calendar(self, channel: RecorderChannel, year: int, month: int) -> set[int]:
        first, nxt = _month_bounds(year, month, self.tz)
        prefix = f"{year:04d}-{month:02d}-"

        def parse(obj: object, token: str) -> tuple[set[int], bool]:
            days = {int(d[len(prefix):]) for d in parse_trassir_calendar(obj, token) if d.startswith(prefix)}
            return days, False

        days, _ = self._status(channel, "calendar", first, nxt - 1, parse, set())
        return days

    def timeline(self, channel: RecorderChannel, day: float) -> list[tuple[float, float]]:
        """Gün uyuşmazlığında da 3 kez denenir: cihaz bir önceki `play`'in gününü bildiriyor olabilir
        (yeni `play` henüz işlenmemiş). Sonunda hâlâ uyuşmuyorsa boş liste ve bir uyarı."""
        ranges, mismatch = self._status(channel, "timeline", day, day_end(day, self.tz) - 1,
                                        lambda obj, token: _trassir_timeline(obj, day, token, self.tz), [])
        if mismatch and not ranges:
            log.warning("TRASSIR arşiv çizelgesi başka bir günü döndürdü; çizelge boş gösteriliyor.")
        return ranges

    def export(self, channel: RecorderChannel, start: float, end: float) -> ExportStream:
        """`jit-export-create-task` → `jit-export-download`. Cihaz dosyayı hazırlarken JSON (ya da boş gövde,
        HTTP hata durumu) döner; 1 sn arayla en çok 20 kez yeniden istenir. Baş kısım burada okunur ve MP4
        (`ftyp`) olduğu doğrulanır: hata çağıranın elinde, akış başlamadan çıkar."""
        body = json.dumps({"resource_guid": channel.id, "start_ts": round(start * 1_000_000),
                           "end_ts": round(end * 1_000_000), "is_hardware": 0, "prefer_substream": 0}).encode()

        def create(sid: str) -> str:
            items = _trassir_items(parse_trassir_any(
                self._http.post("/jit-export-create-task", body, "application/json", [("sid", sid)])))
            task = items[0].get("task_id") if items else None
            if isinstance(task, bool) or not isinstance(task, str | int) or not _TOKEN_RE.fullmatch(str(task)):
                raise RecorderError.unexpected(_RESPONSE)
            return str(task)

        task_id = self._session_retry(create)
        for attempt in range(EXPORT_READY_TRIES):
            if attempt:
                self._sleep(EXPORT_READY_WAIT_S)
            url = self._http.url("/jit-export-download", [("sid", self._live._session()), ("task_id", task_id)])
            chunks = self._http.stream(url, EXPORT_READ_TIMEOUT_S)
            head = b""
            try:
                for chunk in chunks:
                    head += chunk
                    if len(head) >= _EXPORT_HEAD or head.lstrip().startswith(b"{"):
                        break
            except RecorderError as exc:
                if exc.kind != "http":       # "hazır değil" HTTP durumuyla da gelebilir: yeniden denenir
                    raise
                continue
            if head.strip() and not head.lstrip().startswith(b"{"):
                if head[4:8] == b"ftyp":
                    return ExportStream(head, chunks)
                chunks.close()
                raise RecorderError.unexpected("dışa aktarma yanıtı")
            # JSON (hazır değil ya da hata) ya da boş gövde
            try:
                for chunk in chunks:
                    head += chunk
                    if len(head) > _EXPORT_PEEK_LIMIT:
                        break
            finally:
                chunks.close()
            _raise_if_auth(head)
        raise RecorderError.trassir("Dışa aktarma dosyası hazırlanamadı.")

    # MARK: yardımcılar

    def _session_retry(self, body: Callable[[str], R]) -> R:
        """Yalnızca oturum hatasında (`sid`/`session` geçen TRASSIR hata kodu) bir kez yeniden giriş + yineleme.
        `http`/`unexpected` yinelenmez: cihazda ikinci görev açılmasın."""
        sid = self._live._session()
        try:
            return body(sid)
        except RecorderError as exc:
            if not _is_session_error(exc):
                raise
            self._live._drop_session(sid)
            return body(self._live._session())

    def _token(self, channel: RecorderChannel, substream: bool) -> str:
        return self._live._video_token(channel, "rtsp",
                                       "archive_sub" if substream and channel.has_substream else "archive_main")

    def _command(self, token: str, params: list[tuple[str, str]]) -> None:
        def body(sid: str) -> None:
            data = self._http.get("/archive_command", [*params, ("token", token), ("sid", sid)])
            _trassir_items(parse_trassir_any(data))

        self._live._with_session(body)

    def _play(self, token: str, start: float, end: float | None, speed: int) -> None:
        params = [("command", "play"), ("start", trassir_time(start, self.tz))]
        if end is not None:
            params.append(("stop", trassir_time(end, self.tz)))
        params.append(("speed", str(speed)))
        self._command(token, params)

    def _status(self, channel: RecorderChannel, kind: str, start: float, stop: float,
                parse: Callable[[object, str], tuple[R, bool]], empty: R) -> tuple[R, bool]:
        """Arşiv jetonu → `play` → `archive_status type=<kind>` (boşsa 0,5 sn arayla en çok 3 deneme) → `stop`."""
        token = self._token(channel, False)
        try:
            self._play(token, start, stop, 1)
            result: tuple[R, bool] = (empty, False)
            for attempt in range(TRASSIR_STATUS_TRIES):
                if attempt:
                    self._sleep(TRASSIR_STATUS_WAIT_S)
                data = self._live._with_session(
                    lambda sid: self._http.get("/archive_status", [("type", kind), ("sid", sid)]))
                result = parse(parse_trassir_any(data), token)
                if result[0]:
                    break
            return result
        finally:
            self.stop(_rtsp_url(self._live.host, self._live.rtsp_port, "/" + token))


def _is_session_error(exc: RecorderError) -> bool:
    """TRASSIR oturum hatası: ayrıntıda tam kelime `sid` ya da `session` geçer ("consider" eşleşmez)."""
    return exc.kind == "trassir" and re.search(r"\bsid\b|session", exc.detail, re.IGNORECASE) is not None


def _url_token(stream_url: str) -> str | None:
    path = urllib.parse.urlsplit(stream_url).path
    if not path.startswith("/") or not _TOKEN_RE.fullmatch(path[1:]):
        return None
    return path[1:]


def _raise_if_auth(data: bytes) -> None:
    """Dışa aktarma "hazır değil" JSON'u yeniden denenir; oturum/yetki hatası hemen yükselir."""
    try:
        _trassir_items(parse_trassir_any(data))
    except RecorderError as exc:
        if exc.kind == "unauthorized":
            raise


class HikvisionArchive(ArchiveClient):
    """Hikvision ISAPI arşivi (cihazda doğrulanmadı). Hız istemci tarafında kare atlamayla. Saatler UTC."""

    def __init__(self, client: HikvisionClient, tz: tzinfo | None = None) -> None:
        self._live = client
        self._http: _DeviceHTTP = client._http
        self.tz = tz          # yalnız gün sınırı (yerel gece yarısı) için

    @staticmethod
    def _track(channel: RecorderChannel, substream: bool) -> int:
        return _channel_number(channel) * 100 + (2 if substream and channel.has_substream else 1)

    def stream_url(self, channel: RecorderChannel, start: float, end: float | None, substream: bool,
                   speed: int) -> str:
        self._check_speed(speed)
        stop = start + DAY_S if end is None else end
        track = self._track(channel, substream)
        return _rtsp_url(self._live.host, self._live.rtsp_port,
                         f"/Streaming/tracks/{track}?starttime={hik_utc(start)}&endtime={hik_utc(stop)}")

    def calendar(self, channel: RecorderChannel, year: int, month: int) -> set[int]:
        track = self._track(channel, False)
        body = (f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><trackDailyParam><year>{year}</year>"
                f"<monthOfYear>{month}</monthOfYear></trackDailyParam>").encode()
        return parse_hik_daily(self._http.post(f"/ISAPI/ContentMgmt/record/tracks/{track}/dailyDistribution",
                                               body, "application/xml"))

    def timeline(self, channel: RecorderChannel, day: float) -> list[tuple[float, float]]:
        track = self._track(channel, False)
        end = day_end(day, self.tz)
        search_id = str(uuid.uuid4()).upper()
        ranges: list[tuple[float, float]] = []
        for page in range(HIK_MAX_PAGES):
            body = (
                "<?xml version=\"1.0\" encoding=\"UTF-8\"?><CMSearchDescription>"
                f"<searchID>{search_id}</searchID>"
                f"<trackIDList><trackID>{track}</trackID></trackIDList>"
                f"<timeSpanList><timeSpan><startTime>{hik_iso(day)}</startTime>"
                f"<endTime>{hik_iso(end)}</endTime></timeSpan></timeSpanList>"
                f"<maxResults>{HIK_PAGE}</maxResults>"
                f"<searchResultPostion>{page * HIK_PAGE}</searchResultPostion>"
                "<metadataList><metadataDescriptor>//recordType.meta.std-cgi.com</metadataDescriptor>"
                "</metadataList></CMSearchDescription>"
            ).encode()
            found, status = parse_hik_search(self._http.post("/ISAPI/ContentMgmt/search", body,
                                                             "application/xml"))
            ranges += found
            if status != "MORE":
                break
        return _clip(ranges, day, end)


class DahuaArchive(ArchiveClient):
    """Dahua CGI arşivi (cihazda doğrulanmadı; kanal numarası 1 tabanlı varsayılır). Hız istemci tarafında."""

    def __init__(self, client: DahuaClient, tz: tzinfo | None = None) -> None:
        self._live = client
        self._http: _DeviceHTTP = client._http
        self.tz = tz

    def stream_url(self, channel: RecorderChannel, start: float, end: float | None, substream: bool,
                   speed: int) -> str:
        self._check_speed(speed)
        stop = start + DAY_S if end is None else end
        n = _channel_number(channel)
        sub = 1 if substream and channel.has_substream else 0
        return _rtsp_url(self._live.host, self._live.rtsp_port,
                         f"/cam/playback?channel={n}&subtype={sub}"
                         f"&starttime={dahua_time(start, '_', self.tz)}&endtime={dahua_time(stop, '_', self.tz)}")

    def calendar(self, channel: RecorderChannel, year: int, month: int) -> set[int]:
        first, nxt = _month_bounds(year, month, self.tz)
        days: set[int] = set()
        for start, end in _clip(self._find(channel, first, nxt), first, nxt):
            d = _local(start, self.tz).date()
            last = _local(max(start, end - 0.001), self.tz).date()
            while d <= last:
                if (d.year, d.month) == (year, month):
                    days.add(d.day)
                d += timedelta(days=1)
        return days

    def timeline(self, channel: RecorderChannel, day: float) -> list[tuple[float, float]]:
        end = day_end(day, self.tz)
        return _clip(self._find(channel, day, end), day, end)

    def _cgi(self, params: list[tuple[str, str]]) -> str:
        """`mediaFileFind.cgi`: `condition.Types[0]` köşeli ayraçları ve zamandaki `:` kodlanmadan gider."""
        q = "&".join(f"{urllib.parse.quote(k, safe='[].')}={urllib.parse.quote(v, safe=':-_')}"
                     for k, v in params)
        data = self._http.get_url(self._http.url("/cgi-bin/mediaFileFind.cgi") + "?" + q)
        return data.decode("utf-8", errors="replace")

    def _find(self, channel: RecorderChannel, start: float, end: float) -> list[tuple[float, float]]:
        n = _channel_number(channel)
        created = re.search(r"result=(\d+)", self._cgi([("action", "factory.create")]))
        if created is None:
            raise RecorderError.unexpected(_RESPONSE)
        obj = created.group(1)
        ranges: list[tuple[float, float]] = []
        try:
            ok = self._cgi([("action", "findFile"), ("object", obj), ("condition.Channel", str(n)),
                            ("condition.StartTime", dahua_time(start, "-", self.tz)),
                            ("condition.EndTime", dahua_time(end, "-", self.tz)), ("condition.Types[0]", "dav")])
            if ok.strip() != "OK":
                raise RecorderError.unexpected(_RESPONSE)
            for _ in range(DAHUA_MAX_PAGES):
                page, found = _dahua_page(
                    self._cgi([("action", "findNextFile"), ("object", obj), ("count", str(DAHUA_PAGE))]), self.tz)
                ranges += page
                if found < DAHUA_PAGE:
                    break
        finally:
            for action in ("close", "destroy"):
                try:
                    self._cgi([("action", action), ("object", obj)])
                except RecorderError as exc:
                    log.debug("Dahua arama kapatılamadı (%s): %s", action, exc.kind)
        return ranges


class FileArchive(ArchiveClient):
    """Test kancası: video dosyası (yalnız `ANALYZER_ALLOW_FILE_SOURCES=1`). Zaman ekseni dosya saniyesidir;
    oynatıcı dosyayı açıp başlangıca kendisi sarar."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._duration: float | None = None

    def stream_url(self, channel: RecorderChannel, start: float, end: float | None, substream: bool,
                   speed: int) -> str:
        self._check_speed(speed)
        return self.path

    def calendar(self, channel: RecorderChannel, year: int, month: int) -> set[int]:
        return {1} if (year, month) == (1970, 1) else set()

    def timeline(self, channel: RecorderChannel, day: float) -> list[tuple[float, float]]:
        if day != 0:
            return []
        duration = self.duration()
        return [(0.0, duration)] if duration > 0 else []

    def duration(self) -> float:
        if self._duration is None:
            cap = cv2.VideoCapture(self.path)
            try:
                if not cap.isOpened():
                    raise RecorderError.unexpected("dosya açılamadı")
                frames = max(0.0, cap.get(cv2.CAP_PROP_FRAME_COUNT))
                fps = cap.get(cv2.CAP_PROP_FPS)
            finally:
                cap.release()
            if not 0 < fps <= 120:
                fps = 25.0
            self._duration = frames / fps
        return self._duration


def make_archive(client: RecorderClient, brand: RecorderBrand | str, tz: tzinfo | None = None) -> ArchiveClient:
    """Canlı istemciyi markasının arşiv bağdaştırıcısıyla sarar (istemci kapanınca bağdaştırıcı da kullanılamaz)."""
    try:
        kind = RecorderBrand(brand)
    except ValueError:
        raise RecorderError.unexpected("bilinmeyen marka") from None
    match kind, client:
        case RecorderBrand.TRASSIR, TrassirClient():
            return TrassirArchive(client, tz)
        case RecorderBrand.HIKVISION, HikvisionClient():
            return HikvisionArchive(client, tz)
        case RecorderBrand.DAHUA, DahuaClient():
            return DahuaArchive(client, tz)
    raise RecorderError.unexpected("marka ile istemci uyuşmuyor")
