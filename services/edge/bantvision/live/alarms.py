"""Poz güvenlik alarm günlüğü: <data>/live/alarms.json ve alarm-images/<id>.jpg (yalnızca bu bilgisayarda, 7 gün).

Kayıt: {id, sessionId, camera, type ("hands_up"|"lying"|"test"), startedAt, firedAt, endedAt, acked,
notify ("disabled"|"queued"|"sent"|"failed"|"suppressed"), image}. Tüm yazmalar kilit altında ve atomik.
"""
from __future__ import annotations

import json
import os
import pathlib
import threading
import uuid
from typing import Any


class AlarmStore:
    def __init__(self, root: pathlib.Path) -> None:
        self.root = root / "live"
        self.images = self.root / "alarm-images"
        self.images.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._file = self.root / "alarms.json"
        try:
            self._items: list[dict[str, Any]] = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._items = []

    def _save(self) -> None:
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._items, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._file)

    def add(self, session_id: str | None, camera: str, kind: str, started_at: float, fired_at: float,
            jpeg: bytes | None, notify: str) -> dict[str, Any]:
        a = {"id": uuid.uuid4().hex, "sessionId": session_id, "camera": camera, "type": kind,
             "startedAt": started_at, "firedAt": fired_at, "endedAt": None, "acked": False, "notify": notify,
             "image": jpeg is not None}
        with self._lock:
            if jpeg is not None:
                (self.images / f"{a['id']}.jpg").write_bytes(jpeg)
            self._items.append(a)
            self._save()
        return dict(a)

    def _find(self, alarm_id: str) -> dict[str, Any] | None:
        return next((a for a in self._items if a["id"] == alarm_id), None)

    def _update(self, alarm_id: str, **fields: Any) -> bool:
        with self._lock:
            a = self._find(alarm_id)
            if a is None:
                return False
            a.update(fields)
            self._save()
            return True

    def end(self, alarm_id: str, ts: float) -> None:
        self._update(alarm_id, endedAt=ts)

    def set_notify(self, alarm_id: str, status: str) -> None:
        self._update(alarm_id, notify=status)

    def ack(self, alarm_id: str) -> bool:
        return self._update(alarm_id, acked=True)

    def get(self, alarm_id: str) -> dict[str, Any] | None:
        with self._lock:
            a = self._find(alarm_id)
            return dict(a) if a else None

    def list(self, active_only: bool = False, since: float | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            items = [dict(a) for a in self._items if (not active_only or not a["acked"])
                     and (since is None or a["firedAt"] >= since)]
        return sorted(items, key=lambda a: a["firedAt"], reverse=True)[:limit]

    def image_path(self, alarm_id: str) -> pathlib.Path | None:
        p = self.images / f"{alarm_id}.jpg"
        return p if p.exists() else None

    def expire(self, now: float, days: float = 7) -> int:
        cutoff = now - days * 86400
        with self._lock:
            old = [a for a in self._items if a["firedAt"] < cutoff]
            for a in old:
                (self.images / f"{a['id']}.jpg").unlink(missing_ok=True)
            if old:
                self._items = [a for a in self._items if a["firedAt"] >= cutoff]
                self._save()
        return len(old)
