"""Kaydedilmemiş şablon taslakları (yalnızca bellekte; diske YAZILMAZ).

Panelin düzenleyicisi, kaydetmeden önce değişikliği canlı görmek için taslak açar; taslak şablon gibi akıtılır
(aynı kamera okuyucuları paylaşılır, bağlantı yeniden kurulmaz). `get` taslağa dokunur; IDLE_S boyunca
istenmeyen taslak `sweep` ile silinir. Aynı anda en çok MAX_DRAFTS taslak açılır; fazlası `DraftsFull` (API 503):
açık bir düzenleyicinin taslağı başkası için silinmez, yer ancak taslak kapanınca ya da boşta silinince açılır.

`createdAt` / `updatedAt` şablonlardaki gibi duvar saatidir (epoch sn); boşta kalma süresi ise monoton saatle ölçülür
(duvar saati ileri/geri atlasa da taslak zamanında silinir).
"""
from __future__ import annotations

import copy
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from .views import check_layout_tiles

IDLE_S = 600.0
MAX_DRAFTS = 32
FULL_MSG = "Çok fazla açık taslak var; biraz sonra yeniden deneyin."


class DraftsFull(Exception):
    """En çok taslak sayısına ulaşıldı (Türkçe ileti: FULL_MSG)."""


class DraftStore:
    def __init__(self, clock: Callable[[], float] = time.monotonic, idle_s: float = IDLE_S,
                 wall: Callable[[], float] = time.time, max_drafts: int = MAX_DRAFTS) -> None:
        self._clock, self._idle_s, self._wall, self._max = clock, idle_s, wall, max_drafts
        self._lock = threading.Lock()
        self._drafts: dict[str, dict[str, Any]] = {}
        self._touched: dict[str, float] = {}

    def create(self, layout: str, tiles: list[dict[str, Any] | None]) -> dict[str, Any]:
        layout = check_layout_tiles(layout, tiles)
        with self._lock:
            if len(self._drafts) >= self._max:
                raise DraftsFull(FULL_MSG)
            at = self._wall()
            d = {"id": "draft-" + uuid.uuid4().hex[:12], "layout": layout, "tiles": copy.deepcopy(tiles),
                 "name": "Taslak", "createdAt": at, "updatedAt": at}
            self._drafts[d["id"]] = d
            self._touched[d["id"]] = self._clock()
            return copy.deepcopy(d)

    def update(self, draft_id: str, layout: str, tiles: list[dict[str, Any] | None]) -> dict[str, Any] | None:
        layout = check_layout_tiles(layout, tiles)
        with self._lock:
            d = self._drafts.get(draft_id)
            if d is None:
                return None
            d.update(layout=layout, tiles=copy.deepcopy(tiles), updatedAt=self._wall())
            self._touched[draft_id] = self._clock()
            return copy.deepcopy(d)

    def get(self, draft_id: str) -> dict[str, Any] | None:
        with self._lock:
            d = self._drafts.get(draft_id)
            if d is None:
                return None
            self._touched[draft_id] = self._clock()
            return copy.deepcopy(d)

    def delete(self, draft_id: str) -> bool:
        with self._lock:
            self._touched.pop(draft_id, None)
            return self._drafts.pop(draft_id, None) is not None

    def sweep(self) -> int:
        with self._lock:
            now = self._clock()
            old = [k for k, t in self._touched.items() if now - t >= self._idle_s]
            for k in old:
                del self._drafts[k]
                del self._touched[k]
            return len(old)
