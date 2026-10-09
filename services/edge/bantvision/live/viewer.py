"""Çoklu izleme okuyucuları: kameranın ham görüntüsünü analiz oturumu açmadan okur
(tasarım docs/superpowers/specs/2026-10-08-coklu-izleme-design.md).

- Anahtar (kaynak, kanal, kalite). Aynı anahtar için tek okuyucu.
- Kamerada analiz oturumu varsa onun son karesi kullanılır (NVR'a ikinci bağlantı yok). İzleme oturumlara dokunmaz.
  Oturum kare vermeye başlayınca aynı anahtarın okuyucusu kapanır; oturum ilk karesini verene dek okuyucunun karesi,
  okuyucu ilk karesini verene dek son gösterilen kare kullanılır (karo griye dönmez).
- IDLE_S boyunca istenmeyen okuyucu kapanır. En çok MAX_SUB alt akış ve MAX_MAIN ana akış.
- Kopunca katlanarak bekler (1 → 30 sn); bekleme, akış en az GOOD_AFTER_S sn kare verdikten sonra sıfırlanır.
- Kaynak silinir ya da düzenlenirse `drop(kaynak)` o kaynağın okuyucularını kapatır.
- Verilen kareler salt okunurdur (yanlışlıkla üzerine çizen kod gürültüyle hata alır).
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
GOOD_AFTER_S = 5.0          # bekleme yalnızca akış bu kadar süre kare verdiyse sıfırlanır (tek kare yetmez)
REJECT_TTL_S = 10.0         # reddedilen isteğin iletisi bu süre `peek()` ile görülür
CLOSE_WAIT_S = 3.0          # stop(): tüm okuyucular için ortak bekleme
SWEEP_WAIT_S = 0.5
DROP_WAIT_S = 1.0
STOPPED_MSG = "İzleme durduruldu."
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


def _readonly(frame: np.ndarray) -> np.ndarray:
    """Aynı belleğe salt okunur görünüm (asıl dizi değişmez)."""
    view = frame.view()
    view.flags.writeable = False
    return view


def _detail(e: BaseException) -> str:
    return str(getattr(e, "detail", None) or e)


def _pause(stop: threading.Event, seconds: float) -> None:
    """Yeniden deneme beklemesi (kapanınca hemen uyanır); testler hızlandırmak için değiştirir."""
    stop.wait(seconds)


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

    def request_stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float) -> None:
        self._thread.join(max(0.0, timeout))

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _fail(self, message: str) -> None:
        """Hata durumu: son kare kalır, ama eski fps gösterilmez."""
        with self._lock:
            self._state, self._message = "error", message
            self._stamps = []

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                frames, good, message, rewind = self._attempt()
            except Exception as e:  # noqa: BLE001 — iş parçacığı sessizce ölmesin; hata gösterilir, yeniden denenir
                _LOG.warning("İzleme okuyucusu hatası (%s): %s: %s", self.key[0], type(e).__name__, e)
                frames, good, message, rewind = 0, 0.0, "Görüntü okunamadı; yeniden deneniyor.", False
            if self._stop.is_set():
                return
            if rewind and frames > 0:                         # test dosyası başa sarar (canlı kamera gibi)
                continue
            self._fail(message)
            if good >= GOOD_AFTER_S:
                backoff = 1.0
            _pause(self._stop, backoff)
            backoff = min(backoff * 2, BACKOFF_MAX_S)

    def _attempt(self) -> tuple[int, float, str, bool]:
        """Bir bağlantı denemesi: (okunan kare, kare gelen süre sn, kopma iletisi, dosya kaynağı mı)."""
        try:
            url = self._open_url()
        except Exception as e:  # noqa: BLE001 — kayıt cihazı yanıt vermedi; yeniden denenir
            return 0, 0.0, f"Kaynağa ulaşılamadı: {_detail(e)}", False
        cap = self._capture(url)
        try:
            if not cap.isOpened():
                return 0, 0.0, "Görüntü açılamadı; yeniden deneniyor.", False
            max_w = MAX_WIDTH[self.key[2]]
            is_file = not url.lower().startswith(("rtsp://", "http://", "https://"))
            file_fps = (cap.get(cv2.CAP_PROP_FPS) if hasattr(cap, "get") else 0.0) or 25.0
            started, n, last_ping, first = time.monotonic(), 0, time.monotonic(), 0.0
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    break
                n += 1
                if n == 1:
                    first = time.monotonic()
                small = _readonly(downscale(frame, max_w))
                now = self._clock()
                with self._lock:
                    self._seq += 1
                    self._frame = small
                    self._state, self._message = "live", ""
                    self._stamps = [s for s in self._stamps if now - s <= 2.0] + [now]
                if is_file:                                  # yalnızca test: dosya gerçek zamanlı oynar
                    lag = n / file_fps - (time.monotonic() - started)
                    if lag > 0:
                        self._stop.wait(lag)
                if self._keep_alive and time.monotonic() - last_ping > 5:
                    last_ping = time.monotonic()
                    threading.Thread(target=self._ping, args=(url,), daemon=True).start()
            good = time.monotonic() - first if n else 0.0
            return n, good, "Görüntü kesildi; yeniden bağlanılıyor.", is_file
        finally:
            with contextlib.suppress(Exception):
                cap.release()

    def _ping(self, url: str) -> None:
        with contextlib.suppress(Exception):
            if self._keep_alive:
                self._keep_alive(url)


@dataclass
class _Shown:
    """Bir anahtar için en son gösterilen kare (kaynak değişince karo griye dönmesin; oturum karesi bir kez küçülsün)."""
    frame: np.ndarray
    seq: int
    origin: object              # kareyi veren oturum ya da okuyucu
    at: float


def _stop_viewers(viewers: list[CameraViewer], deadline: float) -> None:
    """Önce hepsine durma isteği, sonra tek ortak süre içinde beklenir (sırayla değil)."""
    for v in viewers:
        v.request_stop()
    for v in viewers:
        v.join(deadline - time.monotonic())


class ViewHub:
    """Tüm izleme okuyucuları. `find_session(kaynak, kanal)` o kamerada çalışan analiz oturumunu ya da None verir."""

    def __init__(self, opener: Opener, find_session: Callable[[str, str | None], Any],
                 capture: Callable[[str], Any] = open_capture, clock: Callable[[], float] = time.monotonic,
                 reaper: bool = True) -> None:
        self._opener, self._find_session, self._capture, self._clock = opener, find_session, capture, clock
        self._lock = threading.Lock()
        self._viewers: dict[Key, CameraViewer] = {}
        self._rejected: dict[Key, tuple[TileFrame, float]] = {}    # son red (sınır, silinmiş kaynak) + geçerlilik sonu
        self._last: dict[Key, _Shown] = {}
        self._stop = threading.Event()
        self._reaper_wanted = reaper
        self._reaper: threading.Thread | None = None               # ilk okuyucu açılınca başlar

    # -- oturum / okuyucu karesi ---------------------------------------------------------------------------------

    def _session(self, source_id: str, channel_id: str | None) -> Any:
        """Kamerada çalışan analiz oturumu; durdurulmuş oturum yok sayılır."""
        s = self._find_session(source_id, channel_id)
        if s is not None and getattr(getattr(s, "status", None), "state", None) == "stopped":
            return None
        return s

    def _from_session(self, s: Any, key: Key) -> TileFrame:
        got = s.latest_frame()
        st = s.status
        state = {"live": "live", "connecting": "connecting", "reconnecting": "connecting"}.get(st.state, "error")
        if got is None:
            return TileFrame(0, None, state, st.message, float(st.fps))
        with self._lock:
            shown = self._last.get(key)
        if shown is not None and shown.origin is s and shown.seq == got[0]:
            frame = shown.frame                              # aynı kare: yeniden küçültülmez
        else:
            frame = _readonly(downscale(got[1], MAX_WIDTH[key[2]]))
        return TileFrame(got[0], frame, state, st.message, float(st.fps))

    def _remember(self, key: Key, t: TileFrame, origin: object) -> None:
        if t.frame is None:
            return
        now = self._clock()
        with self._lock:
            cur = self._last.get(key)
            if cur is not None and cur.origin is origin and cur.seq == t.seq:
                cur.at = now
            else:
                self._last[key] = _Shown(t.frame, t.seq, origin, now)

    def _or_last(self, key: Key, t: TileFrame) -> TileFrame:
        """Kare henüz yoksa son gösterilen kare ("bağlanıyor" durumuyla) kullanılır; hiç yoksa karesiz kalır."""
        if t.frame is not None:
            return t
        with self._lock:
            shown = self._last.get(key)
        if shown is None:
            return t
        return TileFrame(shown.seq, shown.frame, "error" if t.state == "error" else "connecting", t.message, t.fps)

    def _session_tile(self, key: Key, s: Any, touch: bool) -> TileFrame:
        t = self._from_session(s, key)
        if t.frame is not None:
            self._remember(key, t, s)
            if touch:                                        # oturum kare veriyor: ikinci bağlantı gereksiz
                with self._lock:
                    v = self._viewers.pop(key, None)
                if v is not None:
                    v.request_stop()
            return t
        with self._lock:                                     # oturumun ilk karesi gelene dek okuyucu sürer
            v = self._viewers.get(key)
        if v is not None:
            if touch:
                v.touch()
            snap = v.snapshot()
            if snap.frame is not None:
                self._remember(key, snap, v)
                return snap
        return self._or_last(key, t)

    def _reject(self, key: Key, t: TileFrame) -> TileFrame:
        """Reddi sakla: durum uç noktaları (`peek`) "bağlanıyor" yerine nedenini göstersin. Kilit altında çağrılır."""
        self._rejected[key] = (t, self._clock() + REJECT_TTL_S)
        return t

    def _ensure_reaper(self) -> None:
        if self._reaper_wanted and self._reaper is None:
            self._reaper = threading.Thread(target=self._reap, name="izleme-temizlik", daemon=True)
            self._reaper.start()

    # -- genel arayüz --------------------------------------------------------------------------------------------

    def tile(self, source_id: str, channel_id: str | None, quality: str = "sub") -> TileFrame:
        if self._stop.is_set():
            return TileFrame(0, None, "error", STOPPED_MSG, 0.0)
        key: Key = (source_id, channel_id, quality)
        s = self._session(source_id, channel_id)
        if s is not None:
            return self._session_tile(key, s, touch=True)
        with self._lock:
            if self._stop.is_set():                          # stop() ile yarışta yeni okuyucu açılmaz
                return TileFrame(0, None, "error", STOPPED_MSG, 0.0)
            v = self._viewers.get(key)
            if v is None:
                limit, msg = LIMITS[quality]
                if sum(1 for k in self._viewers if k[2] == quality) >= limit:
                    return self._reject(key, TileFrame(0, None, "error", msg, 0.0))
                try:
                    open_url, keep_alive = self._opener(source_id, channel_id, quality == "sub")
                except SourceGone as e:
                    return self._reject(key, TileFrame(0, None, "error", str(e) or "Kamera silinmiş.", 0.0))
                except Exception as e:  # noqa: BLE001 — kaynak ayarı geçersiz (ör. adres eksik)
                    return self._reject(key, TileFrame(0, None, "error", f"Kaynağa ulaşılamadı: {_detail(e)}", 0.0))
                v = CameraViewer(key, open_url, keep_alive, self._capture, self._clock)
                self._viewers[key] = v
                self._rejected.pop(key, None)
                self._ensure_reaper()
            v.touch()
        snap = v.snapshot()
        self._remember(key, snap, v)
        return self._or_last(key, snap)

    def peek(self, source_id: str, channel_id: str | None, quality: str = "sub") -> TileFrame:
        """Okuyucu açmaz, canlı tutmaz. Okuyucu yoksa son red (sınır, silinmiş kaynak…) kısa süre bildirilir."""
        key: Key = (source_id, channel_id, quality)
        s = self._session(source_id, channel_id)
        if s is not None:
            return self._session_tile(key, s, touch=False)
        with self._lock:
            v = self._viewers.get(key)
            rejected = self._rejected.get(key)
        if v is not None:
            return self._or_last(key, v.snapshot())
        if rejected is not None and rejected[1] > self._clock():
            return rejected[0]
        return self._or_last(key, TileFrame(0, None, "connecting", "", 0.0))

    def open_count(self, quality: str) -> int:
        with self._lock:
            return sum(1 for k in self._viewers if k[2] == quality)

    def drop(self, source_id: str) -> int:
        """Kaynak silindi ya da düzenlendi: o kaynağın okuyucuları kapanır, bir sonraki `tile()` güncel ayarla açar."""
        with self._lock:
            gone = [self._viewers.pop(k) for k in [k for k in self._viewers if k[0] == source_id]]
            for table in (self._rejected, self._last):
                for k in [k for k in table if k[0] == source_id]:
                    del table[k]
        _stop_viewers(gone, time.monotonic() + DROP_WAIT_S)
        return len(gone)

    def sweep(self) -> int:
        now = self._clock()
        with self._lock:
            idle = [k for k, v in self._viewers.items() if now - v.last_used > IDLE_S]
            gone = [self._viewers.pop(k) for k in idle]
            for k in [k for k, x in self._last.items() if now - x.at > IDLE_S]:
                del self._last[k]
            for k in [k for k, x in self._rejected.items() if x[1] <= now]:
                del self._rejected[k]
        _stop_viewers(gone, time.monotonic() + SWEEP_WAIT_S)
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
            self._rejected.clear()
            self._last.clear()
            reaper = self._reaper
        deadline = time.monotonic() + CLOSE_WAIT_S
        _stop_viewers(gone, deadline)
        if reaper is not None:
            reaper.join(max(0.0, deadline - time.monotonic()))
