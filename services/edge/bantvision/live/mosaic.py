"""Çoklu izleme birleştiricisi: şablonun kutularını tek JPEG'de birleştirip tek MJPEG akışı olarak verir.

Anahtar (şablon, genişlik, yükseklik). Yalnızca abonesi varken çalışır (saniyede en çok FPS). Abone her kare isteğinde
"görüldü" sayılır; SUB_TTL_S boyunca istemeyen abone gitmiş sayılır (tarayıcı kapandı, telefon uyudu). Şablon her
karede yeniden okunur: düzenleme bağlantı kopmadan yansır. Kamera adı/rozet/alarm tuvale çizilmez (panel HTML çizer).
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
EMPTY = (40, 40, 40)                     # BGR koyu gri: boş ya da karesiz kutu
_TOKENS = itertools.count(1)


def fit_canvas(w: int, h: int) -> tuple[int, int]:
    """Tarayıcının istediği boyut: en çok 1920×1080'e sığdırılır, kenarlar 16'nın katı (en az 16)."""
    s = min(1.0, CANVAS_MAX[0] / max(1, w), CANVAS_MAX[1] / max(1, h))
    return max(16, int(w * s) // 16 * 16), max(16, int(h * s) // 16 * 16)


def compose(layout: Layout, w: int, h: int, frames: Sequence[np.ndarray | None]) -> np.ndarray:
    canvas = np.zeros((h, w, 3), np.uint8)
    for (x0, y0, x1, y1), f in zip(cell_rects(layout, w, h), frames, strict=False):
        x0, y0, x1, y1 = x0 + 1, y0 + 1, x1 - 1, y1 - 1           # kutular arası 2 px aralık
        cw, ch = x1 - x0, y1 - y0
        if cw <= 0 or ch <= 0:
            continue
        if f is None:
            canvas[y0:y1, x0:x1] = EMPTY
            continue
        if f.ndim == 2:
            f = cv2.cvtColor(f, cv2.COLOR_GRAY2BGR)
        fh, fw = f.shape[:2]
        s = min(cw / fw, ch / fh)
        nw, nh = max(1, int(fw * s)), max(1, int(fh * s))
        img = cv2.resize(f, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        ox, oy = x0 + (cw - nw) // 2, y0 + (ch - nh) // 2
        canvas[oy:oy + nh, ox:ox + nw] = img
    return canvas


class Composer:
    def __init__(self, view_id: str, w: int, h: int, views_get: Callable[[str], dict[str, Any] | None],
                 hub: Any, clock: Callable[[], float]) -> None:
        self.view_id, self.w, self.h = view_id, w, h
        self._views_get, self._hub, self._clock = views_get, hub, clock
        self._cv = threading.Condition(threading.Lock())
        self._seq = 0
        self._jpeg: bytes | None = None
        self._subs: dict[int, float] = {}
        self._gone = False                                   # şablon silindi: akış biter
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def ensure_running(self) -> None:
        if not self.running() and not self._stop.is_set():
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
        end = time.monotonic() + timeout
        with self._cv:
            self._subs[tok] = self._clock()
            while self._seq <= after and not self._gone and not self._stop.is_set():
                left = end - time.monotonic()
                if left <= 0:
                    break
                self._cv.wait(left)
            return self._seq, (None if self._gone else self._jpeg)

    @property
    def gone(self) -> bool:
        return self._gone

    def stop(self) -> None:
        self._stop.set()
        with self._cv:
            self._cv.notify_all()
        if self._thread is not None:
            self._thread.join(2.0)

    def _alive(self) -> bool:
        now = self._clock()
        with self._cv:
            self._subs = {t: s for t, s in self._subs.items() if now - s <= SUB_TTL_S}
            return bool(self._subs)

    def _run(self) -> None:
        idle_since: float | None = None
        period = 1.0 / FPS
        while not self._stop.is_set():
            t0 = time.monotonic()
            if not self._alive():
                idle_since = idle_since or time.monotonic()
                if time.monotonic() - idle_since >= IDLE_STOP_S:
                    return                                   # abonesiz: dur (yeniden abone olunca başlar)
                self._stop.wait(0.2)
                continue
            idle_since = None
            view = self._views_get(self.view_id)
            lay = layout_by_id(str(view.get("layout"))) if view else None
            if view is None or lay is None:
                with self._cv:
                    self._gone = True
                    self._cv.notify_all()
                return
            try:
                frames: list[np.ndarray | None] = []
                for t in list(view.get("tiles", []))[:len(lay.cells)]:
                    frames.append(None if not t else self._hub.tile(t["sourceId"], t.get("channelId")).frame)
                ok, buf = cv2.imencode(".jpg", compose(lay, self.w, self.h, frames),
                                       [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            except Exception:  # noqa: BLE001 — bir karenin hatası akışı öldürmesin
                _LOG.exception("Mozaik karesi üretilemedi")
                ok = False
            if ok:
                with self._cv:
                    self._seq += 1
                    self._jpeg = buf.tobytes()
                    self._cv.notify_all()
            self._stop.wait(max(0.0, period - (time.monotonic() - t0)))


class MosaicHub:
    def __init__(self, views_get: Callable[[str], dict[str, Any] | None], hub: Any,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._views_get, self._hub, self._clock = views_get, hub, clock
        self._lock = threading.Lock()
        self._comps: dict[tuple[str, int, int], Composer] = {}

    def acquire(self, view_id: str, w: int, h: int) -> tuple[Composer, int]:
        if self._views_get(view_id) is None:
            raise LookupError("Şablon bulunamadı.")
        w, h = fit_canvas(w, h)
        with self._lock:
            key = (view_id, w, h)
            comp = self._comps.get(key)
            if comp is None or comp.gone:
                comp = Composer(view_id, w, h, self._views_get, self._hub, self._clock)
                self._comps[key] = comp
        return comp, comp.subscribe()

    def release(self, comp: Composer, tok: int) -> None:
        comp.unsubscribe(tok)

    def stop(self) -> None:
        with self._lock:
            comps = list(self._comps.values())
            self._comps.clear()
        for c in comps:
            c.stop()
