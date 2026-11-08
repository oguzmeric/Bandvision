"""Kayıttan izleme API'si: `/api/v1/live/archive/…` (canlı yönlendiricisine `make_router` ekler; panel vekili değişmez).

| Yöntem | Yol | İş |
|---|---|---|
| GET | `/archive/calendar?source=&channel=&year=&month=` | `{days: [...]}` |
| GET | `/archive/timeline?source=&channel=&day=` | `{ranges: [[başlangıç, bitiş], ...]}` epoch sn |
| POST | `/archive/players` `{sourceId, channelId?, at, speed?, substream?}` | 201 görünüm; sınır aşılırsa 429 |
| GET | `/archive/players/{id}` | görünüm (boşta sayacını sıfırlar) |
| GET | `/archive/players/{id}/stream` | MJPEG |
| POST | `/archive/players/{id}/actions` `{action, at?, speed?}` | görünüm |
| DELETE | `/archive/players/{id}` | 204 |
| POST | `/archive/export` `{sourceId, channelId?, start, end}` | `video/mp4` akışı (en çok 30 dk; TRASSIR dışı 501; süren görev 409) |

Yanıtlarda adres, şifre ya da jeton yoktur: görünüm yalnız kimlik, ad, durum ve konumdur.
"""
from __future__ import annotations

import contextlib
import re
import time
import urllib.parse
from collections.abc import AsyncIterator, Iterator
from typing import Any, Literal

import cv2
from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import Field
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from .api import _REF, LiveManager, _ClosingStream, _err, _part, _Strict
from .archive_player import (
    ArchiveManager,
    ArchivePlayer,
    ExportBusy,
    PlayerView,
    SourceMissing,
    TooManyPlayers,
)
from .recorders import RecorderError

__all__ = ["add_archive_routes", "export_response"]

MAX_EXPORT_S = 1800.0
_EPOCH_MAX = 4_102_444_800.0            # 2100-01-01
_STAMP = re.compile(r"-(\d{8}-\d{4})\.mp4$")
_UNSAFE_NAME = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]+')

PLAYER_MISSING = "Kayıt oynatıcısı bulunamadı."
SPEED_MSG = "Hız desteklenmiyor."


class PlayerIn(_Strict):
    sourceId: str = Field(pattern=_REF, max_length=120)
    channelId: str | None = Field(default=None, pattern=_REF, max_length=120)
    at: float = Field(ge=0, le=_EPOCH_MAX, allow_inf_nan=False)
    speed: int = Field(default=1, ge=1, le=64)
    substream: bool = True


class PlayerActionIn(_Strict):
    action: Literal["pause", "resume", "seek", "speed"]
    at: float | None = Field(default=None, ge=0, le=_EPOCH_MAX, allow_inf_nan=False)
    speed: int | None = Field(default=None, ge=1, le=64)


class ExportIn(_Strict):
    sourceId: str = Field(pattern=_REF, max_length=120)
    channelId: str | None = Field(default=None, pattern=_REF, max_length=120)
    start: float = Field(ge=0, le=_EPOCH_MAX, allow_inf_nan=False)
    end: float = Field(ge=0, le=_EPOCH_MAX, allow_inf_nan=False)


def _view(v: PlayerView) -> dict[str, Any]:
    return {"id": v.id, "sourceId": v.source_id, "channelId": v.channel_id, "name": v.name, "state": v.state,
            "message": v.message, "at": v.at, "speed": v.speed, "speeds": list(v.speeds), "fps": v.fps,
            "canExport": v.can_export}


def _archive_err(e: Exception) -> HTTPException:
    """Yönetici istisnası → HTTP (iletiler Türkçe, adres/şifre içermez)."""
    if isinstance(e, HTTPException):
        return e
    if isinstance(e, SourceMissing):
        return HTTPException(404, "Kaynak bulunamadı.")
    if isinstance(e, TooManyPlayers):
        return HTTPException(429, str(e))
    if isinstance(e, ExportBusy):
        return HTTPException(409, str(e))
    if isinstance(e, RecorderError):
        return _err(e)
    if isinstance(e, ValueError):
        msg = str(e)
        return HTTPException(422, SPEED_MSG if "hız" in msg.lower() else msg)
    if isinstance(e, LookupError):
        return HTTPException(404, str(e))
    return HTTPException(503, str(e))                   # RuntimeError: yönetici durduruldu (kapanış)


_MAPPED = (HTTPException, SourceMissing, TooManyPlayers, ExportBusy, RecorderError, ValueError, LookupError,
           RuntimeError)


def _utf8_name(name: str, ascii_name: str) -> str:
    """İndirilecek dosyanın UTF-8 adı: kamera adı + ASCII adla aynı tarih-saat damgası (yerel saat) + `.mp4`."""
    m = _STAMP.search(ascii_name)
    stamp = m.group(1) if m else time.strftime("%Y%m%d-%H%M")
    clean = _UNSAFE_NAME.sub("-", name).strip(" .-") or "kayit"
    return f"{clean}-{stamp}.mp4"


class _ExportResponse(_ClosingStream):
    """Dışa aktarma akışı: yanıt hangi yoldan biterse bitsin (sona dek okundu, istemci koptu, gövde hiç başlamadı)
    alttaki akış kapanır ve dışa aktarma kilidi kalkar."""

    def __init__(self, stream: Iterator[bytes], **kw: Any) -> None:
        self._stream = stream

        async def body() -> AsyncIterator[bytes]:
            with contextlib.closing(stream):        # type: ignore[type-var]
                async for chunk in iterate_in_threadpool(stream):
                    yield chunk

        super().__init__(body(), media_type="video/mp4", **kw)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            close = getattr(self._stream, "close", None)
            if close is not None:
                await run_in_threadpool(close)


def export_response(stream: Iterator[bytes], ascii_name: str, utf8_name: str) -> StreamingResponse:
    disposition = (f'attachment; filename="{ascii_name}"; '
                   f"filename*=UTF-8''{urllib.parse.quote(utf8_name, safe='')}")
    return _ExportResponse(stream, headers={"Content-Disposition": disposition, "Cache-Control": "no-store"})


def add_archive_routes(r: APIRouter, manager: LiveManager) -> None:
    """Arşiv uçlarını canlı yönlendiricisine ekler. Yönetici her istekte `manager.archive`'dan okunur (uygulama kurar)."""

    def archive() -> ArchiveManager:
        a = manager.archive
        if a is None:
            raise HTTPException(503, "Kayıttan izleme kullanılamıyor.")
        return a

    def player(player_id: str) -> ArchivePlayer:
        p = archive().get(player_id)
        if p is None or p.closed:
            raise HTTPException(404, PLAYER_MISSING)
        return p

    @r.get("/archive/calendar")
    def archive_calendar(source: str = Query(pattern=_REF, max_length=120),
                         channel: str | None = Query(None, pattern=_REF, max_length=120),
                         year: int = Query(ge=1970, le=2100), month: int = Query(ge=1, le=12)) -> dict[str, Any]:
        try:
            days = archive().calendar(source, channel, year, month)
        except _MAPPED as e:
            raise _archive_err(e) from e
        return {"days": sorted(days)}

    @r.get("/archive/timeline")
    def archive_timeline(source: str = Query(pattern=_REF, max_length=120),
                         channel: str | None = Query(None, pattern=_REF, max_length=120),
                         day: float = Query(ge=0, le=_EPOCH_MAX, allow_inf_nan=False)) -> dict[str, Any]:
        try:
            ranges = archive().timeline(source, channel, day)
        except _MAPPED as e:
            raise _archive_err(e) from e
        return {"ranges": [[float(a), float(b)] for a, b in ranges]}

    @r.post("/archive/players", status_code=201)
    def archive_open(body: PlayerIn) -> dict[str, Any]:
        try:
            v = archive().open(body.sourceId, body.channelId, body.at, body.speed, body.substream)
        except _MAPPED as e:
            raise _archive_err(e) from e
        return _view(v)

    @r.get("/archive/players/{player_id}")
    def archive_player(player_id: str) -> dict[str, Any]:
        return _view(player(player_id).view())          # `view` boşta sayacını sıfırlar

    @r.get("/archive/players/{player_id}/stream")
    def archive_stream(player_id: str, limit: int | None = Query(None, ge=1, le=100)) -> StreamingResponse:
        """MJPEG (`/cameras/stream` kalıbı). `limit`: yalnızca test/teşhis. Her kare yoklaması boşta sayacını sıfırlar;
        oynatıcı kapanınca ya da 60 sn yeni kare gelmezse akış biter."""
        p = player(player_id)

        def frames() -> Iterator[bytes]:
            last, idle, sent = -1, time.monotonic(), 0
            while (limit is None or sent < limit) and not p.closed:
                seq, frame = p.frame()
                if frame is not None and seq != last:
                    last, idle = seq, time.monotonic()
                    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if ok:
                        sent += 1
                        yield _part(buf.tobytes())
                elif time.monotonic() - idle > 60:
                    return
                time.sleep(0.08)

        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store"})

    @r.post("/archive/players/{player_id}/actions")
    def archive_action(player_id: str, body: PlayerActionIn) -> dict[str, Any]:
        p = player(player_id)
        match body.action:
            case "pause":
                p.pause()
            case "resume":
                p.resume()
            case "seek":
                if body.at is None:
                    raise HTTPException(422, "Sarılacak konum belirtilmedi.")
                p.seek(body.at)
            case "speed":
                if body.speed is None:
                    raise HTTPException(422, "Hız belirtilmedi.")
                try:
                    p.set_speed(body.speed)
                except ValueError as e:
                    raise HTTPException(422, SPEED_MSG) from e
        return _view(p.view())

    @r.delete("/archive/players/{player_id}", status_code=204)
    def archive_close(player_id: str) -> Response:
        if not archive().close(player_id):
            raise HTTPException(404, PLAYER_MISSING)
        return Response(status_code=204)

    @r.post("/archive/export")
    def archive_export(body: ExportIn) -> StreamingResponse:
        if body.start >= body.end:
            raise HTTPException(422, "Bitiş, başlangıçtan sonra olmalı.")
        if body.end - body.start > MAX_EXPORT_S:
            raise HTTPException(422, "En çok 30 dakika dışa aktarılabilir.")
        a = archive()
        try:
            filename, stream = a.export(body.sourceId, body.channelId, body.start, body.end)
        except _MAPPED as e:
            raise _archive_err(e) from e
        try:
            return export_response(stream, filename, _utf8_name(a.name(body.sourceId, body.channelId), filename))
        except BaseException:
            getattr(stream, "close", lambda: None)()
            raise
