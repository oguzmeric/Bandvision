"""Çoklu izleme okuyucuları: kameranın ham görüntüsünü analiz oturumu açmadan okur
(tasarım docs/superpowers/specs/2026-10-08-coklu-izleme-design.md).

- Anahtar (kaynak, kanal, kalite). Aynı anahtar için tek okuyucu.
- Kamerada analiz oturumu varsa onun son karesi kullanılır (NVR'a ikinci bağlantı yok). İzleme oturumlara dokunmaz.
- IDLE_S boyunca istenmeyen okuyucu kapanır. En çok MAX_SUB alt akış ve MAX_MAIN ana akış.
- Kopunca katlanarak bekler (1 → 30 sn).
"""
from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import cv2
import numpy as np

from .session import open_capture

_LOG = logging.getLogger(__name__)
Quality = Literal["sub", "main"]
Key = tuple[str, str | None, str]
MAX_SUB = 16
MAX_MAIN = 2
IDLE_S = 30.0
REAP_EVERY_S = 5.0
BACKOFF_MAX_S = 30.0
MAX_WIDTH: dict[str, int] = {"sub": 960, "main": 1920}
LIMITS: dict[str, tuple[int, str]] = {
    "sub": (MAX_SUB, "Sınır aşıldı (en çok 16 kamera)."),
    "main": (MAX_MAIN, "Sınır aşıldı (aynı anda en çok 2 net görüntü)."),
}
Opener = Callable[[str, str | None, bool], tuple[Callable[[], str], Callable[[str], None] | None]]


class SourceGone(LookupError):
    """Şablondaki kamera artık yok (kaynak silinmiş)."""


@dataclass
class TileFrame:
    seq: int
    frame: np.ndarray | None
    state: str                  # "connecting" | "live" | "error"
    message: str
    fps: float


def downscale(frame: np.ndarray, max_w: int) -> np.ndarray:
    h, w = frame.shape[:2]
    if w <= max_w:
        return frame
    return cv2.resize(frame, (max_w, max(1, round(h * max_w / w))), interpolation=cv2.INTER_AREA)


class CameraViewer:
    """Bir kameranın izleme okuyucusu (kendi iş parçacığı)."""

    def __init__(self, key: Key, open_url: Callable[[], str], keep_alive: Callable[[str], None] | None,
                 capture: Callable[[str], Any], clock: Callable[[], float]) -> None:
        self.key = key
        self._open_url, self._keep_alive, self._capture, self._clock = open_url, keep_alive, capture, clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._seq = 0
        self._frame: np.ndarray | None = None
        self._state, self._message = "connecting", ""
        self._stamps: list[float] = []
        self.last_used = clock()
        self._thread = threading.Thread(target=self._run, name=f"izleme-{key[0][:8]}", daemon=True)
        self._thread.start()

    def touch(self) -> None:
        self.last_used = self._clock()

    def snapshot(self) -> TileFrame:
        with self._lock:
            fps = 0.0
            if len(self._stamps) >= 2:
                span = self._stamps[-1] - self._stamps[0]
                fps = (len(self._stamps) - 1) / span if span > 0 else 0.0
            return TileFrame(self._seq, self._frame, self._state, self._message, round(fps, 1))

    def stop(self, join: float = 2.0) -> None:
        self._stop.set()
        self._thread.join(join)

    def _set(self, state: str, message: str) -> None:
        with self._lock:
            self._state, self._message = state, message

    def _run(self) -> None:
        backoff = 1.0
        max_w = MAX_WIDTH[self.key[2]]
        while not self._stop.is_set():
            try:
                url = self._open_url()
            except Exception as e:  # noqa: BLE001 — kayıt cihazı yanıt vermedi; yeniden denenir
                self._set("error", f"Kaynağa ulaşılamadı: {e}")
                self._stop.wait(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX_S)
                continue
            cap = self._capture(url)
            if not cap.isOpened():
                cap.release()
                self._set("error", "Görüntü açılamadı; yeniden deneniyor.")
                self._stop.wait(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX_S)
                continue
            is_file = not url.lower().startswith(("rtsp://", "http://", "https://"))
            file_fps = (cap.get(cv2.CAP_PROP_FPS) if hasattr(cap, "get") else 0.0) or 25.0
            started, n, last_ping = time.monotonic(), 0, time.monotonic()
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    break
                n += 1
                small = downscale(frame, max_w)
                now = self._clock()
                with self._lock:
                    self._seq += 1
                    self._frame = small
                    self._state, self._message = "live", ""
                    self._stamps = [s for s in self._stamps if now - s <= 2.0] + [now]
                backoff = 1.0
                if is_file:                                  # yalnızca test: dosya gerçek zamanlı oynar
                    lag = n / file_fps - (time.monotonic() - started)
                    if lag > 0:
                        self._stop.wait(lag)
                if self._keep_alive and time.monotonic() - last_ping > 5:
                    last_ping = time.monotonic()
                    threading.Thread(target=self._ping, args=(url,), daemon=True).start()
            cap.release()
            if self._stop.is_set():
                return
            if is_file:                                       # test dosyası başa sarar (canlı kamera gibi)
                continue
            self._set("error", "Görüntü kesildi; yeniden bağlanılıyor.")
            self._stop.wait(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX_S)

    def _ping(self, url: str) -> None:
        with contextlib.suppress(Exception):
            if self._keep_alive:
                self._keep_alive(url)


class ViewHub:
    """Tüm izleme okuyucuları. `find_session(kaynak, kanal)` o kamerada çalışan analiz oturumunu ya da None verir."""

    def __init__(self, opener: Opener, find_session: Callable[[str, str | None], Any],
                 capture: Callable[[str], Any] = open_capture, clock: Callable[[], float] = time.monotonic,
                 reaper: bool = True) -> None:
        self._opener, self._find_session, self._capture, self._clock = opener, find_session, capture, clock
        self._lock = threading.Lock()
        self._viewers: dict[Key, CameraViewer] = {}
        self._stop = threading.Event()
        if reaper:
            threading.Thread(target=self._reap, name="izleme-temizlik", daemon=True).start()

    def _from_session(self, s: Any, quality: str) -> TileFrame:
        got = s.latest_frame()
        st = s.status
        state = {"live": "live", "connecting": "connecting", "reconnecting": "connecting"}.get(st.state, "error")
        frame = downscale(got[1], MAX_WIDTH[quality]) if got else None
        return TileFrame(got[0] if got else 0, frame, state, st.message, float(st.fps))

    def tile(self, source_id: str, channel_id: str | None, quality: str = "sub") -> TileFrame:
        s = self._find_session(source_id, channel_id)
        if s is not None:
            return self._from_session(s, quality)
        key: Key = (source_id, channel_id, quality)
        with self._lock:
            v = self._viewers.get(key)
            if v is None:
                limit, msg = LIMITS[quality]
                if sum(1 for k in self._viewers if k[2] == quality) >= limit:
                    return TileFrame(0, None, "error", msg, 0.0)
                try:
                    open_url, keep_alive = self._opener(source_id, channel_id, quality == "sub")
                except SourceGone as e:
                    return TileFrame(0, None, "error", str(e) or "Kamera silinmiş.", 0.0)
                except Exception as e:  # noqa: BLE001 — kaynak ayarı geçersiz (ör. adres eksik)
                    detail = getattr(e, "detail", None) or str(e)
                    return TileFrame(0, None, "error", f"Kaynağa ulaşılamadı: {detail}", 0.0)
                v = CameraViewer(key, open_url, keep_alive, self._capture, self._clock)
                self._viewers[key] = v
            v.touch()
        return v.snapshot()

    def peek(self, source_id: str, channel_id: str | None, quality: str = "sub") -> TileFrame:
        s = self._find_session(source_id, channel_id)
        if s is not None:
            return self._from_session(s, quality)
        with self._lock:
            v = self._viewers.get((source_id, channel_id, quality))
        return v.snapshot() if v else TileFrame(0, None, "connecting", "", 0.0)

    def open_count(self, quality: str) -> int:
        with self._lock:
            return sum(1 for k in self._viewers if k[2] == quality)

    def sweep(self) -> int:
        now = self._clock()
        with self._lock:
            idle = [k for k, v in self._viewers.items() if now - v.last_used > IDLE_S]
            gone = [self._viewers.pop(k) for k in idle]
        for v in gone:
            v.stop(join=0.5)
        return len(gone)

    def _reap(self) -> None:
        while not self._stop.wait(REAP_EVERY_S):
            try:
                self.sweep()
            except Exception:  # noqa: BLE001 — temizlik iş parçacığı ölmesin
                _LOG.exception("İzleme okuyucusu temizliği başarısız")

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            gone = list(self._viewers.values())
            self._viewers.clear()
        for v in gone:
            v.stop()
