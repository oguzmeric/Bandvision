"""Çoklu izleme şablonları (<data>/live/views.json). Biçim: contracts/view-template.schema.json.

Kilitli dosya (Windows) açılışta okunamazsa liste boş görünür ama dosyaya **yazılmaz**: sonraki yazmada yeniden okunur;
hâlâ okunamıyorsa `ViewsBusy` (API 503). Bozuk dosya kenara alınır (`views.json.corrupt`).
"""
from __future__ import annotations

import copy
import logging
import pathlib
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from .jsonfile import JsonRead, quarantine, read_json, write_json_atomic
from .layouts import layout_by_id

_LOG = logging.getLogger(__name__)
__all__ = ["JsonRead", "ViewStore", "ViewsBusy", "read_json"]


class ViewsBusy(Exception):
    """Şablon dosyası şu an okunamıyor ya da yazılamıyor."""


def _valid(rec: Any) -> bool:
    return (isinstance(rec, dict) and isinstance(rec.get("id"), str) and isinstance(rec.get("name"), str)
            and layout_by_id(str(rec.get("layout"))) is not None and isinstance(rec.get("tiles"), list))


class ViewStore:
    def __init__(self, root: pathlib.Path, clock: Callable[[], float] = time.time) -> None:
        self._file = root / "live" / "views.json"
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.Lock()
        self._unread = False
        self._views: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        r = read_json(self._file)
        if r.status == "missing":
            return []
        if r.status == "corrupt" or (r.status == "ok" and not isinstance(r.data, list)):
            _LOG.error("Şablon dosyası bozuk; kenara alındı (%s)", self._file.name)
            quarantine(self._file)
            return []
        if r.status == "unreadable":
            _LOG.error("Şablon dosyası okunamadı (kilitli olabilir); yazmadan önce yeniden denenecek")
            self._unread = True
            return []
        return [v for v in r.data if _valid(v)]

    def _ensure_read(self) -> None:
        if not self._unread:
            return
        r = read_json(self._file)
        if r.status == "unreadable":
            raise ViewsBusy("Şablon dosyası şu an okunamıyor; biraz sonra yeniden deneyin.")
        self._unread = False
        self._views = [v for v in r.data if _valid(v)] if r.status == "ok" and isinstance(r.data, list) else []

    def _save(self) -> None:
        try:
            write_json_atomic(self._file, self._views, indent=2)
        except OSError as e:
            raise ViewsBusy("Şablonlar kaydedilemedi (disk ya da dosya kilidi).") from e

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._views)

    def get(self, view_id: str) -> dict[str, Any] | None:
        with self._lock:
            for v in self._views:
                if v["id"] == view_id:
                    return copy.deepcopy(v)
        return None

    def create(self, name: str, layout: str, tiles: list[dict[str, Any] | None]) -> dict[str, Any]:
        with self._lock:
            self._ensure_read()
            now = self._clock()
            v = {"id": uuid.uuid4().hex, "name": name, "layout": layout, "tiles": copy.deepcopy(tiles),
                 "createdAt": now, "updatedAt": now}
            self._views.append(v)
            try:
                self._save()
            except ViewsBusy:
                self._views.remove(v)
                raise
            return copy.deepcopy(v)

    def update(self, view_id: str, name: str, layout: str,
               tiles: list[dict[str, Any] | None]) -> dict[str, Any] | None:
        with self._lock:
            self._ensure_read()
            for i, v in enumerate(self._views):
                if v["id"] == view_id:
                    old = self._views[i]
                    self._views[i] = {**v, "name": name, "layout": layout, "tiles": copy.deepcopy(tiles),
                                      "updatedAt": max(self._clock(), v["updatedAt"])}
                    try:
                        self._save()
                    except ViewsBusy:
                        self._views[i] = old
                        raise
                    return copy.deepcopy(self._views[i])
        return None

    def delete(self, view_id: str) -> bool:
        with self._lock:
            self._ensure_read()
            keep = [v for v in self._views if v["id"] != view_id]
            if len(keep) == len(self._views):
                return False
            old, self._views = self._views, keep
            try:
                self._save()
            except ViewsBusy:
                self._views = old
                raise
            return True
