"""Poz güvenlik alarm günlüğü: <data>/live/alarms.json ve alarm-images/<id>.jpg (yalnızca bu bilgisayarda, 7 gün).

Kayıt: {id, sessionId, camera, type ("hands_up"|"lying"|"test"), startedAt, firedAt, endedAt, acked,
notify ("disabled"|"queued"|"sent"|"failed"|"suppressed"), image}. Tüm yazmalar kilit altında ve atomik.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import threading
import uuid
from typing import Any

_LOG = logging.getLogger(__name__)
_ID = re.compile(r"[0-9a-f]{32}")


class AlarmStore:
    def __init__(self, root: pathlib.Path) -> None:
        self.root = root / "live"
        self.images = self.root / "alarm-images"
        self.images.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._file = self.root / "alarms.json"
        self._items: list[dict[str, Any]] = []
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("firedAt"), (int, float)):
                        item.setdefault("sessionId", None)
                        item.setdefault("camera", "")
                        item.setdefault("type", "")
                        item.setdefault("startedAt", 0.0)
                        item.setdefault("endedAt", None)
                        item.setdefault("acked", False)
                        item.setdefault("notify", "disabled")
                        item.setdefault("image", False)
                        self._items.append(item)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            _LOG.warning(f"Failed to load alarms.json: {e}")
            try:
                self._file.rename(self._file.with_suffix(".json.corrupt"))
            except OSError:
                pass

    def _save(self) -> None:
        try:
            tmp = self._file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._items, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._file)
        except OSError as e:
            _LOG.warning(f"Failed to save alarms.json: {e}")

    def add(self, session_id: str | None, camera: str, kind: str, started_at: float, fired_at: float,
            jpeg: bytes | None, notify: str) -> dict[str, Any]:
        a = {"id": uuid.uuid4().hex, "sessionId": session_id, "camera": camera, "type": kind,
             "startedAt": started_at, "firedAt": fired_at, "endedAt": None, "acked": False, "notify": notify,
             "image": jpeg is not None}
        with self._lock:
            if jpeg is not None:
                try:
                    (self.images / f"{a['id']}.jpg").write_bytes(jpeg)
                except OSError as e:
                    _LOG.warning(f"Failed to write image {a['id']}: {e}")
                    a["image"] = False
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
            try:
                self._save()
            except OSError as e:
                _LOG.warning(f"Failed to save after update: {e}")
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

    def list(self, active_only: bool = False, since: float | None = None, limit: int = 50,
             session_id: str | None = None) -> list[dict[str, Any]]:
        """En yeni önce; `limit` süzgeçlerden SONRA uygulanır (`session_id` verilince yalnızca o oturumun alarmları)."""
        with self._lock:
            items = [dict(a) for a in self._items if (not active_only or not a["acked"])
                     and (since is None or a["firedAt"] >= since)
                     and (session_id is None or a["sessionId"] == session_id)]
        return sorted(items, key=lambda a: a["firedAt"], reverse=True)[:limit]

    def image_path(self, alarm_id: str) -> pathlib.Path | None:
        if not _ID.fullmatch(alarm_id):
            return None
        p = self.images / f"{alarm_id}.jpg"
        return p if p.is_file() else None

    def image_bytes(self, alarm_id: str) -> bytes | None:
        if not _ID.fullmatch(alarm_id):
            return None
        with self._lock:
            try:
                return (self.images / f"{alarm_id}.jpg").read_bytes()
            except (FileNotFoundError, OSError):
                return None

    def expire(self, now: float, days: float = 7) -> int:
        cutoff = now - days * 86400
        with self._lock:
            old = [a for a in self._items if a["firedAt"] < cutoff]
            to_keep = []  # Records that failed to delete (retry later)
            to_remove = []  # Records successfully processed

            for a in old:
                if a.get("image"):
                    try:
                        (self.images / f"{a['id']}.jpg").unlink(missing_ok=True)
                    except OSError as e:
                        _LOG.warning(f"Failed to delete image {a['id']}: {e}")
                        to_keep.append(a)
                        continue
                to_remove.append(a)

            # Delete orphan images (no record, older than cutoff)
            if self.images.exists():
                for img_file in self.images.iterdir():
                    if img_file.is_file() and img_file.suffix.lower() == ".jpg":
                        try:
                            mtime = img_file.stat().st_mtime
                            if mtime < cutoff:
                                alarm_id = img_file.stem
                                if not self._find(alarm_id):
                                    img_file.unlink()
                        except OSError:
                            pass

            # Remove old records (but keep those whose images failed to delete)
            if to_remove:
                self._items = [a for a in self._items if a not in to_remove]
                self._save()
        return len(to_remove)
