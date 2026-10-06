"""Canlı sayım API'si (`/api/v1/live`): kaynaklar, kanal listesi ve küçük resimler, profiller, canlı oturumlar.

Panel (apps/dashboard) bu uçlara sunucu tarafından, erişim anahtarıyla konuşur. Şifreler hiçbir yanıtta yer almaz
(`hasPassword` dışında); hata iletileri şifre içermez. Görüntü bu bilgisayarda kalır.
"""
from __future__ import annotations

import os
import pathlib
import threading
import time
from collections.abc import Iterator
from typing import Any, Literal

import cv2
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core import Profile
from . import recorders as rec
from .power import disable_power_throttling
from .session import LiveSession, open_capture
from .store import CATALOG, LiveStore, make_preset


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceIn(_Strict):
    kind: Literal["camera", "recorder"]
    name: str = Field(default="", max_length=80)
    # kamera
    brand: Literal["hikvision", "dahua", "axis", "vivotek", "milesight", "custom"] = "hikvision"
    host: str = Field(default="", max_length=255)
    port: int = Field(default=554, ge=1, le=65535)
    channel: int = Field(default=1, ge=1, le=512)
    substream: bool = True
    customUrl: str = Field(default="", max_length=1024)
    # kayıt cihazı
    recorderBrand: Literal["trassir", "hikvision", "dahua"] = "trassir"
    httpPort: int | None = Field(default=None, ge=1, le=65535)
    rtspPort: int | None = Field(default=None, ge=1, le=65535)
    # ortak
    username: str = Field(default="admin", max_length=128)
    password: str | None = Field(default=None, max_length=256)     # None: kayıtlı şifre korunur

    @model_validator(mode="before")
    @classmethod
    def _drop_read_only(cls, data: Any) -> Any:
        """Kaynağın kendi görünümü (kimlik, zaman, şifre var mı) geri gönderilirse yok sayılır; bilinmeyen alan yine 422."""
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if k not in ("id", "createdAt", "hasPassword")}
        return data


class StreamIn(_Strict):
    substream: bool


class SharedDetector:
    """Tüm canlı kameralarda tek tanıma modeli: bellek bir kez, kareler sırayla işlenir (işlemci aşırı yüklenmez;
    N kamera varsa her biri toplam hızın yaklaşık 1/N'ini alır)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._inner: Any = None

    def detect(self, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            if self._inner is None:
                from ..core.detector import ObjectDetector

                self._inner = ObjectDetector()
            return self._inner.detect(*args, **kwargs)


class SessionIn(_Strict):
    sourceId: str
    channelId: str | None = None
    profileId: str
    substream: bool | None = None           # None: kaynağın ayarı; True alt akış (hızlı), False ana akış (net)


class ActionIn(_Strict):
    action: Literal["start", "stop", "reset", "learnBackground", "learnSample", "cancelCalibration"]


def _err(e: Exception) -> HTTPException:
    if isinstance(e, rec.RecorderError):
        return HTTPException(401 if e.kind == "unauthorized" else 502, str(e))
    return HTTPException(502, f"Kaynağa ulaşılamadı: {e}")


class LiveManager:
    """Kaynak bağlantıları ve çalışan oturumlar (süreç ömrü boyunca bellekte)."""

    def __init__(self, store: LiveStore) -> None:
        self.store = store
        self.sessions: dict[str, LiveSession] = {}
        self._clients: dict[str, tuple[str, rec.RecorderClient]] = {}   # kaynak → (ayar imzası, istemci)
        self._channels: dict[str, list[rec.RecorderChannel]] = {}
        self._lock = threading.Lock()
        self.detector = SharedDetector()
        self._snap_failed: dict[str, float] = {}         # küçük resmi alınamayan kamera → zaman (1 dk tekrar denenmez)
        disable_power_throttling()          # canlı sayım gerçek zamanlı: Windows verimlilik modu kare hızını 2–3'e düşürüyordu

    def source_or_404(self, source_id: str) -> dict[str, Any]:
        src = self.store.source(source_id)
        if src is None:
            raise HTTPException(404, "Kaynak bulunamadı.")
        return src

    def recorder(self, src: dict[str, Any]) -> rec.RecorderClient:
        brand = rec.RecorderBrand(src.get("recorderBrand", "trassir"))
        host = rec.clean_host(src.get("host", ""))
        if not host:
            raise HTTPException(400, "Kayıt cihazının adresi boş.")
        http_port = int(src.get("httpPort") or brand.default_http_port)
        rtsp_port = int(src.get("rtspPort") or brand.default_rtsp_port)
        password = self.store.password(src["id"]) if src.get("id") else src.get("password", "")
        sig = f"{brand}|{host}|{http_port}|{rtsp_port}|{src.get('username', '')}|{hash(password)}"
        with self._lock:
            cached = self._clients.get(src.get("id", ""))
            if cached and cached[0] == sig:
                return cached[1]
            if cached:
                cached[1].close()
            client = rec.make_recorder(brand, host, http_port, rtsp_port, src.get("username", ""), password)
            if src.get("id"):
                self._clients[src["id"]] = (sig, client)
            return client

    def forget(self, source_id: str) -> None:
        with self._lock:
            cached = self._clients.pop(source_id, None)
            self._channels.pop(source_id, None)
        if cached:
            cached[1].close()

    def channels(self, src: dict[str, Any], refresh: bool = False) -> list[rec.RecorderChannel]:
        sid = src["id"]
        if not refresh and sid in self._channels:
            return self._channels[sid]
        chans = self.recorder(src).channels()
        self._channels[sid] = chans
        return chans

    def channel(self, src: dict[str, Any], channel_id: str) -> rec.RecorderChannel:
        for refresh in (False, True):
            for c in self.channels(src, refresh):
                if c.id == channel_id:
                    return c
        raise HTTPException(404, "Kamera kayıt cihazında bulunamadı.")

    def camera_url(self, src: dict[str, Any]) -> str:
        custom = str(src.get("customUrl", "")).strip()
        if (src.get("brand") == "custom" and os.environ.get("ANALYZER_ALLOW_FILE_SOURCES") == "1"
                and custom and pathlib.Path(custom).is_file()):
            return custom                                   # yalnızca test: yerel video dosyası "kamera" gibi
        url = rec.camera_rtsp_url(rec.CameraBrand(src.get("brand", "hikvision")), rec.clean_host(src.get("host", "")),
                                  int(src.get("port", 554)), int(src.get("channel", 1)), bool(src.get("substream", True)),
                                  src.get("customUrl", ""))
        if not url:
            raise HTTPException(400, "Kamera adresi eksik ya da geçersiz.")
        password = self.store.password(src["id"])
        return rec.with_credentials(url, src.get("username", ""), password) if src.get("username") else url

    def opener(self, src: dict[str, Any], channel_id: str | None, substream: bool | None = None
               ) -> tuple[Any, Any]:
        """(adres üretici, canlı tutma). Kayıt cihazında adres her bağlanışta yeniden alınır (TRASSIR jetonu).
        `substream` verilirse kaynağın alt/ana akış ayarı yerine o kullanılır (oturum başına seçim)."""
        if substream is not None:
            src = {**src, "substream": substream}
        if src["kind"] == "camera":
            url = self.camera_url(src)
            return (lambda: url), None
        if not channel_id:
            raise HTTPException(400, "Kayıt cihazından bir kamera seçin.")
        client = self.recorder(src)
        ch = self.channel(src, channel_id)
        substream = bool(src.get("substream", True))
        brand = rec.RecorderBrand(src.get("recorderBrand", "trassir"))
        username, password = src.get("username", ""), self.store.password(src["id"])

        def open_url() -> str:
            url = client.stream_url(ch, substream)
            if brand != rec.RecorderBrand.TRASSIR and username:
                url = rec.with_credentials(url, username, password)
            return url

        return open_url, client.keep_alive

    def snapshot(self, src: dict[str, Any], channel_id: str | None) -> bytes:
        key = f"{src['id']}|{channel_id}"
        if time.monotonic() - self._snap_failed.get(key, -1e9) < SNAPSHOT_RETRY_S:
            raise HTTPException(502, "Kameradan görüntü gelmiyor (kapalı ya da sinyal yok).")
        try:
            jpeg = self._snapshot(src, channel_id)
        except HTTPException:
            self._snap_failed[key] = time.monotonic()
            raise
        self._snap_failed.pop(key, None)
        return jpeg

    def _snapshot(self, src: dict[str, Any], channel_id: str | None) -> bytes:
        if src["kind"] == "recorder" and channel_id:
            client = self.recorder(src)
            ch = self.channel(src, channel_id)
            try:
                return client.snapshot(ch)
            except rec.RecorderError as e:
                if e.kind == "unauthorized":
                    raise
        open_url, _ = self.opener(src, channel_id)          # küçük resim API'si yok: RTSP'den ilk kare
        return grab_jpeg(open_url())


SNAPSHOT_RETRY_S = 60.0
_GRAB_SLOTS = threading.BoundedSemaphore(2)   # aynı anda en çok 2 RTSP küçük resim: kayıt cihazını ve canlı oturumu boğmasın


def grab_jpeg(url: str, timeout: float = 10.0) -> bytes:
    result: dict[str, bytes] = {}

    def run() -> None:
        if not _GRAB_SLOTS.acquire(timeout=timeout):
            return
        try:
            _grab(url, result)
        finally:
            _GRAB_SLOTS.release()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    if "jpeg" not in result:
        raise HTTPException(502, "Kameradan görüntü alınamadı (adres, port, kullanıcı ve şifreyi kontrol edin).")
    return result["jpeg"]


def _grab(url: str, result: dict[str, bytes]) -> None:
    cap = open_capture(url)
    try:
        for _ in range(30):                                 # ilk tam kareye kadar (anahtar kare)
            ok, frame = cap.read()
            if ok and frame is not None:
                ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok2:
                    result["jpeg"] = buf.tobytes()
                return
    finally:
        cap.release()


def _public_channel(c: rec.RecorderChannel) -> dict[str, Any]:
    return {"id": c.id, "name": c.name.strip(), "number": c.number, "title": c.title.strip(),
            "hasSubstream": c.has_substream}


def make_router(manager: LiveManager, auth: Any) -> APIRouter:
    r = APIRouter(prefix="/api/v1/live", dependencies=[auth])
    store = manager.store

    # ---------------------------------------------------------------- katalog ve profiller

    @r.get("/catalog")
    def catalog() -> list[dict[str, Any]]:
        return CATALOG

    @r.get("/profiles")
    def profiles() -> list[dict[str, Any]]:
        return store.profiles()

    @r.post("/profiles", status_code=201)
    def create_profile(body: dict[str, Any]) -> dict[str, Any]:
        """{"preset": "egg"} → hazır profilden yeni profil; ya da tam profil (sözleşme)."""
        if "preset" in body:
            try:
                p = make_preset(str(body["preset"]))
            except KeyError as e:
                raise HTTPException(422, "Bilinmeyen hazır profil.") from e
            if body.get("name"):
                p.name = str(body["name"])[:80]
        else:
            p = _profile_from(body)
            p.id = Profile().id                             # yeni kimlik
        return store.save_profile(p)

    @r.put("/profiles/{profile_id}")
    def update_profile(profile_id: str, body: dict[str, Any]) -> dict[str, Any]:
        if store.profile(profile_id) is None:
            raise HTTPException(404, "Profil bulunamadı.")
        p = _profile_from(body)
        p.id = profile_id
        return store.save_profile(p)

    @r.delete("/profiles/{profile_id}", status_code=204)
    def delete_profile(profile_id: str) -> Response:
        if not store.delete_profile(profile_id):
            raise HTTPException(409, "Profil silinemedi (bulunamadı ya da son profil).")
        return Response(status_code=204)

    # ---------------------------------------------------------------- kaynaklar

    @r.get("/sources")
    def sources() -> list[dict[str, Any]]:
        return store.sources()

    @r.post("/sources", status_code=201)
    def create_source(body: SourceIn) -> dict[str, Any]:
        data = body.model_dump(exclude={"password"})
        data["name"] = data["name"].strip()
        if not data["name"]:
            data["name"] = _default_name(data)
        return store.save_source(data, body.password or "")

    @r.put("/sources/{source_id}")
    def update_source(source_id: str, body: SourceIn) -> dict[str, Any]:
        manager.source_or_404(source_id)
        data = body.model_dump(exclude={"password"})
        data["name"] = data["name"].strip()
        if not data["name"]:
            data["name"] = _default_name(data)
        manager.forget(source_id)
        return store.save_source(data, body.password, source_id)

    @r.delete("/sources/{source_id}", status_code=204)
    def delete_source(source_id: str) -> Response:
        for s in [s for s in manager.sessions.values() if getattr(s, "source_id", None) == source_id]:
            s.stop()
            manager.sessions.pop(s.id, None)
        manager.forget(source_id)
        if not store.delete_source(source_id):
            raise HTTPException(404, "Kaynak bulunamadı.")
        return Response(status_code=204)

    @r.get("/sources/{source_id}/channels")
    def channels(source_id: str, refresh: bool = False) -> list[dict[str, Any]]:
        src = manager.source_or_404(source_id)
        if src["kind"] != "recorder":
            raise HTTPException(400, "Bu kaynak bir kayıt cihazı değil.")
        try:
            return [_public_channel(c) for c in manager.channels(src, refresh)]
        except rec.RecorderError as e:
            raise _err(e) from e

    @r.get("/sources/{source_id}/snapshot")
    def snapshot(source_id: str, channel: str | None = None) -> Response:
        src = manager.source_or_404(source_id)
        try:
            jpeg = manager.snapshot(src, channel)
        except rec.RecorderError as e:
            raise _err(e) from e
        return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    # ---------------------------------------------------------------- canlı oturumlar

    @r.get("/sessions")
    def sessions() -> list[dict[str, Any]]:
        return [_session_view(s) for s in manager.sessions.values()]

    @r.post("/sessions", status_code=201)
    def create_session(body: SessionIn) -> dict[str, Any]:
        src = manager.source_or_404(body.sourceId)
        profile = store.profile(body.profileId)
        if profile is None:
            raise HTTPException(404, "Profil bulunamadı.")
        for s in list(manager.sessions.values()):           # aynı kamera iki kez açılmasın
            if getattr(s, "source_id", None) == body.sourceId and getattr(s, "channel_id", None) == body.channelId:
                s.stop()
                manager.sessions.pop(s.id, None)
        try:
            open_url, keep_alive = manager.opener(src, body.channelId, body.substream)
            name = str(src.get("name") or "").strip() or "Kamera"
            if body.channelId:
                name = f"{name} · {manager.channel(src, body.channelId).title.strip()}"
        except rec.RecorderError as e:
            raise _err(e) from e
        s = LiveSession(name, open_url, profile, keep_alive, detector=manager.detector)
        s.loop_file = os.environ.get("ANALYZER_ALLOW_FILE_SOURCES") == "1"   # yalnızca test: dosya başa sarar
        s.source_id, s.channel_id, s.profile_id = body.sourceId, body.channelId, body.profileId  # type: ignore[attr-defined]
        fixed_url = src["kind"] == "camera" and src.get("brand") == "custom"      # tam RTSP adresi: seçim yok
        sub = bool(src.get("substream", True)) if body.substream is None else body.substream
        s.substream = None if fixed_url else sub  # type: ignore[attr-defined]
        manager.sessions[s.id] = s
        return _session_view(s)

    def session_or_404(session_id: str) -> LiveSession:
        s = manager.sessions.get(session_id)
        if s is None:
            raise HTTPException(404, "Canlı oturum bulunamadı (sunucu yeniden başlatılmış olabilir).")
        return s

    @r.get("/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        return _session_view(session_or_404(session_id))

    @r.delete("/sessions/{session_id}", status_code=204)
    def delete_session(session_id: str) -> Response:
        s = session_or_404(session_id)
        s.stop()
        manager.sessions.pop(session_id, None)
        return Response(status_code=204)

    @r.post("/sessions/{session_id}/actions")
    def action(session_id: str, body: ActionIn) -> dict[str, Any]:
        s = session_or_404(session_id)
        {"start": lambda: s.set_counting(True), "stop": lambda: s.set_counting(False), "reset": s.reset,
         "learnBackground": s.learn_background, "learnSample": s.learn_sample,
         "cancelCalibration": s.cancel_calibration}[body.action]()
        return _session_view(s)

    @r.put("/sessions/{session_id}/stream")
    def set_stream(session_id: str, body: StreamIn) -> dict[str, Any]:
        """Alt ↔ ana akış: aynı oturum yeni akışa bağlanır; sayaçlar sıfırlanmaz."""
        s = session_or_404(session_id)
        if getattr(s, "substream", None) is None:
            raise HTTPException(400, "Bu kaynakta akış seçilemez (tam RTSP adresi).")
        src = manager.source_or_404(getattr(s, "source_id", ""))
        try:
            open_url, keep_alive = manager.opener(src, getattr(s, "channel_id", None), body.substream)
        except rec.RecorderError as e:
            raise _err(e) from e
        if body.substream != s.substream:  # type: ignore[attr-defined]
            s.switch_source(open_url, keep_alive)
            s.substream = body.substream  # type: ignore[attr-defined]
        return _session_view(s)

    @r.put("/sessions/{session_id}/profile")
    def set_profile(session_id: str, body: dict[str, Any], save: bool = False) -> dict[str, Any]:
        """Oturumun profilini değiştirir (alan, çizgi, yön, yöntem…); `save=true` ise profili de kaydeder."""
        s = session_or_404(session_id)
        p = _profile_from(body)
        p.id = getattr(s, "profile_id", p.id)
        s.set_profile(p)
        if save:
            store.save_profile(p)
        return _session_view(s)

    @r.get("/sessions/{session_id}/stream")
    def stream(session_id: str) -> StreamingResponse:
        s = session_or_404(session_id)

        def frames() -> Iterator[bytes]:
            seq = 0
            idle = time.monotonic()
            while s.id in manager.sessions:
                seq2, jpeg = s.jpeg(seq, timeout=2.0)
                if jpeg is None or seq2 == seq:
                    if time.monotonic() - idle > 60:            # bir dakika kare yok: bağlantıyı bırak
                        return
                    continue
                idle = time.monotonic()
                seq = seq2
                yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode()
                       + b"\r\n\r\n" + jpeg + b"\r\n")

        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store"})

    @r.get("/sessions/{session_id}/frame.jpg")
    def frame(session_id: str) -> Response:
        jpeg = session_or_404(session_id).raw_jpeg()
        if jpeg is None:
            raise HTTPException(503, "Henüz görüntü yok.")
        return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @r.get("/sessions/{session_id}/counts.csv")
    def counts_csv(session_id: str) -> Response:
        s = session_or_404(session_id)
        return Response(s.counts_csv(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="sayimlar.csv"'})

    return r


def _profile_from(body: dict[str, Any]) -> Profile:
    try:
        return Profile.from_dict(body)
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(422, f"Profil geçersiz: {e}") from e


def _default_name(data: dict[str, Any]) -> str:
    host = rec.clean_host(data.get("host", "")) or "kamera"
    if data["kind"] == "recorder":
        return f"{rec.RecorderBrand(data['recorderBrand']).title} · {host}"
    return f"{data['brand'].capitalize() if data['brand'] != 'custom' else 'RTSP'} · {host}"


def _session_view(s: LiveSession) -> dict[str, Any]:
    v = s.snapshot_status()
    v.update(sourceId=getattr(s, "source_id", None), channelId=getattr(s, "channel_id", None),
             profileId=getattr(s, "profile_id", None), substream=getattr(s, "substream", None))
    return v
