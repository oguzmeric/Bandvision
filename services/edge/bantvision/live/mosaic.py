"""Çoklu izleme birleştiricisi: şablonun kutularını tek JPEG'de birleştirip tek MJPEG akışı olarak verir.

Anahtar (şablon, genişlik, yükseklik). Yalnızca abonesi varken çalışır (saniyede en çok FPS). Abone her kare isteğinde
"görüldü" sayılır; SUB_TTL_S boyunca istemeyen abone gitmiş sayılır (tarayıcı kapandı, telefon uyudu), abonesiz kalan
birleştirici IDLE_STOP_S sonra durur ve eski tuvali bırakır. Durmuş birleştirici, kare isteyen (eski ya da yeni) ilk
aboneyle yeniden başlar; başlatma/durdurma kararı tek kilit altındadır (iki iş parçacığı çalışmaz, abone kaçmaz).
Şablon her karede yeniden okunur: düzenleme bağlantı kopmadan yansır. Bir kutunun hatası yalnızca o kutuyu griye
çevirir. Kamera adı/rozet/alarm tuvale çizilmez (panel HTML çizer).
Hiçbir kutu değişmediyse (kareler aynı: kamera kopuk ya da görüntü durağan) tuval yeniden çizilip kodlanmaz; akış
60 sn'de bitmesin diye en az KEEPALIVE_S'de bir aynı tuval yeniden gönderilir. Kutular yine de her turda sorulur
(okuyucular canlı kalır). Bir şablon için en çok MAX_SIZES_PER_VIEW farklı boyutta birleştirici çalışır.
"""
from __future__ import annotations

import itertools
import logging
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

import cv2
import numpy as np

from .layouts import Layout, cell_rects, layout_by_id

_LOG = logging.getLogger(__name__)
FPS = 10.0
CANVAS_MAX = (1920, 1080)
SUB_TTL_S = 10.0
IDLE_STOP_S = 5.0
JPEG_QUALITY = 75
LOG_EVERY_S = 60.0                       # aynı şablonun hata günlüğü bu aralıkla en çok bir satır
KEEPALIVE_S = 5.0                        # kutular değişmese de bu aralıkla (aynı) tuval gönderilir
MAX_SIZES_PER_VIEW = 8                   # bir şablonun aynı anda en çok bu kadar farklı boyutta birleştiricisi olur
TOO_MANY_SIZES_MSG = "Bu şablon için çok fazla farklı boyutta izleyici var."
STOPPED_MSG = "İzleme durduruldu."
EMPTY = (40, 40, 40)                     # BGR koyu gri: boş ya da karesiz kutu
_TOKENS = itertools.count(1)
_LOGGED: dict[str, float] = {}
_LOGGED_LOCK = threading.Lock()


class MosaicStopped(RuntimeError):
    """Birleştirici kapatıldı (sunucu kapanıyor); yeni abone alınmaz."""


class TooManySizes(RuntimeError):
    """Şablonun MAX_SIZES_PER_VIEW farklı boyutta birleştiricisi zaten çalışıyor (her boyut ayrı tuval ve kodlama)."""


def _warn_limited(key: str, message: str, *args: object) -> None:
    """Çağrıldığı `except` içinde: aynı anahtar için `LOG_EVERY_S` içinde ikinci kez günlüğe yazmaz."""
    now = time.monotonic()
    with _LOGGED_LOCK:
        last = _LOGGED.get(key)
        if last is not None and now - last < LOG_EVERY_S:
            return
        _LOGGED[key] = now
    _LOG.warning(message, *args, exc_info=True)


def fit_canvas(w: int, h: int) -> tuple[int, int]:
    """Tarayıcının istediği boyut: en çok 1920×1080'e sığdırılır, kenarlar 16'nın katı (en az 16)."""
    s = min(1.0, CANVAS_MAX[0] / max(1, w), CANVAS_MAX[1] / max(1, h))
    return max(16, int(w * s) // 16 * 16), max(16, int(h * s) // 16 * 16)


def compose(layout: Layout, w: int, h: int, frames: Sequence[np.ndarray | None], log_key: str = "") -> np.ndarray:
    """Kareleri kutulara oran koruyarak yerleştirir. Yazılamayan kare (bozuk biçim) yalnızca kendi kutusunu griye çevirir."""
    canvas = np.zeros((h, w, 3), np.uint8)
    for (x0, y0, x1, y1), f in zip(cell_rects(layout, w, h), frames, strict=False):
        x0, y0, x1, y1 = x0 + 1, y0 + 1, x1 - 1, y1 - 1           # kutular arası 2 px aralık
        cw, ch = x1 - x0, y1 - y0
        if cw <= 0 or ch <= 0:
            continue
        if f is None:
            canvas[y0:y1, x0:x1] = EMPTY
            continue
        try:
            if f.ndim == 2:
                f = cv2.cvtColor(f, cv2.COLOR_GRAY2BGR)
            fh, fw = f.shape[:2]
            s = min(cw / fw, ch / fh)
            nw, nh = max(1, int(fw * s)), max(1, int(fh * s))
            img = cv2.resize(f, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
            ox, oy = x0 + (cw - nw) // 2, y0 + (ch - nh) // 2
            canvas[oy:oy + nh, ox:ox + nw] = img
        except Exception:  # noqa: BLE001 — bozuk bir kare tüm tuvali öldürmesin
            canvas[y0:y1, x0:x1] = EMPTY
            _warn_limited(f"compose:{log_key}", "Mozaik kutusu çizilemedi (şablon %s)", log_key or "-")
    return canvas


class Composer:
    def __init__(self, view_id: str, w: int, h: int, views_get: Callable[[str], dict[str, Any] | None],
                 hub: Any, clock: Callable[[], float]) -> None:
        self.view_id, self.w, self.h = view_id, w, h
        self._views_get, self._hub, self._clock = views_get, hub, clock
        self._cv = threading.Condition(threading.Lock())
        # Aşağıdakilerin hepsi `_cv` altında okunur/yazılır
        self._seq = 0                                        # tekdüze: durup kalkınca geri sarmaz
        self._jpeg: bytes | None = None
        self._subs: dict[int, float] = {}
        self._gone = False                                   # şablon silindi: akış biter
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- yaşam döngüsü (tek kilit altında) -----------------------------------------------------------------------

    def running(self) -> bool:
        with self._cv:
            return self._running

    @property
    def gone(self) -> bool:
        return self._gone

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def ensure_running(self) -> None:
        """İş parçacığı yoksa başlatır; denetle-ve-başlat tek adım (iki çağrı iki iş parçacığı başlatmaz)."""
        with self._cv:
            if self._running or self._gone or self._stop.is_set():
                return
            self._running = True
            self._thread = threading.Thread(target=self._run, name=f"mozaik-{self.view_id[:8]}", daemon=True)
            self._thread.start()

    def subscribe(self) -> int:
        tok = next(_TOKENS)
        with self._cv:
            self._subs[tok] = self._clock()
        self.ensure_running()
        return tok

    def unsubscribe(self, tok: int) -> None:
        with self._cv:
            self._subs.pop(tok, None)

    def jpeg(self, tok: int, after: int, timeout: float) -> tuple[int, bytes | None]:
        """`after`'dan yeni tuval gelene dek bekler. Kare isteyen jeton "görüldü" sayılır ve durmuş birleştirici yeniden
        başlar (uyuyan telefon, arka plan sekmesi). Silinmiş (`gone`) ya da durdurulmuş (`stopped`) birleştirici
        bekletmez; çağıran bu özelliklere bakıp akışı bitirir."""
        with self._cv:
            self._subs[tok] = self._clock()
        self.ensure_running()
        end = time.monotonic() + timeout
        with self._cv:
            while (self._jpeg is None or self._seq <= after) and not self._gone and not self._stop.is_set():
                left = end - time.monotonic()
                if left <= 0:
                    break
                self._cv.wait(left)
            return self._seq, (None if self._gone else self._jpeg)

    def retirable(self) -> bool:
        """Silinmiş ya da çalışmayan ve abonesiz: `MosaicHub` sözlüğünden atılabilir."""
        with self._cv:
            self._prune_locked()
            return self._gone or (not self._running and not self._subs)

    def request_stop(self) -> None:
        self._stop.set()
        with self._cv:
            self._cv.notify_all()

    def join(self, timeout: float) -> None:
        with self._cv:
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(max(0.0, timeout))

    def stop(self) -> None:
        self.request_stop()
        self.join(2.0)

    # -- iş parçacığı --------------------------------------------------------------------------------------------

    def _prune_locked(self) -> None:
        now = self._clock()
        self._subs = {t: s for t, s in self._subs.items() if now - s <= SUB_TTL_S}

    def _alive(self) -> bool:
        with self._cv:
            self._prune_locked()
            return bool(self._subs)

    def _retire_if_idle(self) -> bool:
        """Boşta durma kararı: abone yeniden bakılır ve bayrak AYNI kilitte düşer. O anda gelen abone ya iş
        parçacığını canlı tutar ya da (bayrak düştüğü için) kendi `ensure_running`'iyle yenisini başlatır."""
        with self._cv:
            self._prune_locked()
            if self._subs:
                return False
            self._running = False
            self._jpeg = None                                # saatler öncesinin tuvali sonraki aboneye verilmez
            return True

    def _run(self) -> None:
        try:
            self._loop()
        except Exception:  # noqa: BLE001 — beklenmeyen çıkış: bayrak düşsün, sonraki abone yeniden başlatsın
            _warn_limited(f"loop:{self.view_id}", "Mozaik iş parçacığı beklenmedik şekilde durdu (şablon %s)",
                          self.view_id)
        finally:
            with self._cv:
                if self._thread is threading.current_thread():
                    self._running = False

    def _tile_frame(self, tile: dict[str, Any] | None) -> tuple[np.ndarray | None, object]:
        """Kutunun karesi ve değişim imzası (kamera, sıra no, kare nesnesi): imza aynıysa kutu değişmemiştir."""
        if not tile:
            return None, None
        ref = (tile["sourceId"], tile.get("channelId"))
        try:
            t = self._hub.tile(tile["sourceId"], tile.get("channelId"))
        except Exception:  # noqa: BLE001 — bir kutunun hatası tuvali öldürmesin: o kutu gri
            _warn_limited(f"tile:{self.view_id}", "Mozaik kutusu okunamadı (şablon %s)", self.view_id)
            return None, (ref, "hata")
        frame: np.ndarray | None = t.frame
        return frame, (ref, t.seq, None if frame is None else id(frame))

    def _loop(self) -> None:
        idle_since: float | None = None
        period = 1.0 / FPS
        last_sig: object = None                              # son gönderilen tuvalin imzası (düzen + kutular)
        sent_at = 0.0
        while not self._stop.is_set():
            t0 = time.monotonic()
            if not self._alive():
                now = self._clock()
                idle_since = now if idle_since is None else idle_since
                if now - idle_since >= IDLE_STOP_S and self._retire_if_idle():
                    return                                   # abonesiz: dur (kare isteyen yeniden başlatır)
                self._stop.wait(0.2)
                continue
            idle_since = None
            try:
                view = self._views_get(self.view_id)
            except Exception:  # noqa: BLE001 — şablon deposu geçici okunamadı: silinmiş sayılmaz, sonra yeniden denenir
                _warn_limited(f"views:{self.view_id}", "Şablon okunamadı (%s)", self.view_id)
                self._stop.wait(period)
                continue
            lay = layout_by_id(str(view.get("layout"))) if view else None
            if view is None or lay is None:
                with self._cv:
                    self._gone = True
                    self._running = False
                    self._jpeg = None
                    self._cv.notify_all()
                return
            try:
                got = [self._tile_frame(t) for t in list(view.get("tiles", []))[:len(lay.cells)]]
                sig = (lay.id, tuple(g[1] for g in got))
                now = self._clock()
                with self._cv:
                    same = sig == last_sig and self._jpeg is not None
                    if same and now - sent_at >= KEEPALIVE_S:     # değişmedi: aynı tuval yeniden (kodlama yok)
                        self._seq += 1
                        sent_at = now
                        self._cv.notify_all()
                if not same:
                    ok, buf = cv2.imencode(".jpg", compose(lay, self.w, self.h, [g[0] for g in got], self.view_id),
                                           [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                    if ok:
                        with self._cv:
                            self._seq += 1
                            self._jpeg = buf.tobytes()
                            self._cv.notify_all()
                        last_sig, sent_at = sig, now
            except Exception:  # noqa: BLE001 — bir karenin hatası akışı öldürmesin
                _warn_limited(f"frame:{self.view_id}", "Mozaik karesi üretilemedi (şablon %s)", self.view_id)
            self._stop.wait(max(0.0, period - (time.monotonic() - t0)))


class MosaicHub:
    def __init__(self, views_get: Callable[[str], dict[str, Any] | None], hub: Any,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._views_get, self._hub, self._clock = views_get, hub, clock
        self._lock = threading.Lock()
        self._comps: dict[tuple[str, int, int], Composer] = {}
        self._stopped = False

    def acquire(self, view_id: str, w: int, h: int) -> tuple[Composer, int]:
        """Şablonun bu boyuttaki birleştiricisine abone olur. Abonelik hub kilidi altında yapılır: aynı anda bir
        başka `acquire` bu birleştiriciyi "boşta" sanıp sözlükten atamaz. Şablon yoksa `LookupError`, hub kapalıysa
        `MosaicStopped`, şablonun MAX_SIZES_PER_VIEW farklı boyutu zaten izleniyorsa `TooManySizes`."""
        if self._stopped:
            raise MosaicStopped(STOPPED_MSG)
        if self._views_get(view_id) is None:
            raise LookupError("Şablon bulunamadı.")
        w, h = fit_canvas(w, h)
        key = (view_id, w, h)
        with self._lock:
            if self._stopped:
                raise MosaicStopped(STOPPED_MSG)
            # Boşta/silinmiş birleştiriciler atılır. Durdurulur: elinde tutan uyuyan bir istemci uyanınca sahipsiz bir
            # kopyayı canlandırmasın, akışı bitsin ve yeniden bağlansın. İstenen anahtar atılmaz (sıra numarası sürer).
            for k in [k for k, c in self._comps.items() if k != key and c.retirable()]:
                self._comps.pop(k).stop()
            comp = self._comps.get(key)
            if comp is None or comp.gone or comp.stopped:
                if sum(1 for k in self._comps if k[0] == view_id and k != key) >= MAX_SIZES_PER_VIEW:
                    raise TooManySizes(TOO_MANY_SIZES_MSG)
                comp = Composer(view_id, w, h, self._views_get, self._hub, self._clock)
                self._comps[key] = comp
            return comp, comp.subscribe()

    def release(self, comp: Composer, tok: int) -> None:
        comp.unsubscribe(tok)

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            comps = list(self._comps.values())
            self._comps.clear()
        for c in comps:
            c.request_stop()
        deadline = time.monotonic() + 2.0
        for c in comps:
            c.join(deadline - time.monotonic())
