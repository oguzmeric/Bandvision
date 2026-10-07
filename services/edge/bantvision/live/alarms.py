"""Poz güvenlik alarm günlüğü: <data>/live/alarms.json ve alarm-images/<id>.jpg (yalnızca bu bilgisayarda, 7 gün).

Kayıt: {id, sessionId, camera, type ("hands_up"|"lying"|"test"), startedAt, firedAt, endedAt, acked,
notify ("disabled"|"queued"|"sent"|"failed"|"suppressed"), image}. Tüm yazmalar kilit altında ve atomik.

Dosya açılışta okunamazsa (Windows'ta virüs tarayıcı/yedekleme kilidi) birkaç kez yeniden denenir; yine okunamazsa günlük
boş başlar ama dosyaya dokunulmaz: ilk kayıtta yeniden okunup birleştirilir (geçmiş ezilmez). Yalnızca JSON'u bozuk
dosya kenara alınır (`alarms.json.corrupt`). Kimliği 32 küçük onaltılık olmayan kayıt yüklenmez (resim yolu olarak
kullanılır).
"""
from __future__ import annotations

import logging
import math
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .jsonfile import quarantine, read_json, write_json_atomic

_LOG = logging.getLogger(__name__)
_ID = re.compile(r"[0-9a-f]{32}")
_DEFAULTS: dict[str, Any] = {"sessionId": None, "camera": "", "type": "", "startedAt": 0.0, "endedAt": None,
                             "acked": False, "notify": "disabled", "image": False}


def _record(item: Any) -> dict[str, Any] | None:
    """Diskten gelen kayıt: geçerliyse eksik alanları varsayılanla tamamlanmış hali, değilse None."""
    if not (isinstance(item, dict) and isinstance(item.get("id"), str) and _ID.fullmatch(item["id"])):
        return None
    fired = item.get("firedAt")
    if isinstance(fired, bool) or not isinstance(fired, int | float):
        return None
    for k, v in _DEFAULTS.items():
        item.setdefault(k, v)
    return item


class AlarmStore:
    def __init__(self, root: Path) -> None:
        self.root = root / "live"
        self.images = self.root / "alarm-images"
        self.images.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._file = self.root / "alarms.json"
        self._items: list[dict[str, Any]] = []
        self._load_failed = False
        res = read_json(self._file)
        if res.status == "unreadable":
            _LOG.error("alarms.json okunamadı (dosya kilitli olabilir); alarm günlüğü boş başlıyor, dosyaya "
                       "dokunulmadı — ilk kayıtta yeniden okunup birleştirilecek")
            self._load_failed = True
        elif res.status == "corrupt" or (res.status == "ok" and not isinstance(res.data, list)):
            _LOG.warning("alarms.json bozuk; kenara alındı (alarms.json.corrupt), alarm günlüğü boş başlıyor")
            quarantine(self._file)
        elif res.status == "ok":
            self._items = [r for r in map(_record, res.data) if r is not None]

    def _save(self) -> None:
        """Kilit altında çağrılır. Yazma hatası günlüğe yazılır (günlük bellekte sürer)."""
        if self._load_failed and not self._merge_disk():
            _LOG.warning("alarms.json hâlâ okunamıyor; diskteki geçmiş ezilmesin diye yazma ertelendi")
            return
        try:
            write_json_atomic(self._file, self._items)
        except OSError as e:
            _LOG.warning("alarms.json yazılamadı: %s", e)

    def _merge_disk(self) -> bool:
        """Açılışta okunamayan dosyayı yeniden okur ve bellektekilerle birleştirir; okunamazsa False. Diskten gelen ve
        sonu yazılmamış (deneme dışı) kayıtlar önceki çalışmadandır: sonları şimdi yazılır."""
        res = read_json(self._file, delays=())
        if res.status == "unreadable":
            return False
        if res.status == "ok" and isinstance(res.data, list):
            mine = {a["id"] for a in self._items}
            disk = [r for r in map(_record, res.data) if r is not None and r["id"] not in mine]
            now = time.time()
            for r in disk:
                if r["endedAt"] is None and r["type"] != "test":
                    r["endedAt"] = now
            self._items = disk + self._items
        self._load_failed = False
        return True

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
                    _LOG.warning("Olay resmi yazılamadı (%s): %s", a["id"], e)
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
            self._save()
            return True

    def end(self, alarm_id: str, ts: float) -> None:
        self._update(alarm_id, endedAt=ts)

    def close_stale(self, now: float) -> int:
        """Açılışta: önceki çalışmadan sonu yazılmamış (temiz kapanış olmadı) alarmların sonu `now` olur; panelde
        sonsuza dek "devam ediyor" kalmasın. Deneme alarmının sonu yoktur, dokunulmaz. Kapatılan sayısı döner."""
        with self._lock:
            stale = [a for a in self._items if a["endedAt"] is None and a["type"] != "test"]
            for a in stale:
                a["endedAt"] = now
            if stale:
                self._save()
        return len(stale)

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

    def image_bytes(self, alarm_id: str) -> bytes | None:
        if not _ID.fullmatch(alarm_id):
            return None
        with self._lock:
            try:
                return (self.images / f"{alarm_id}.jpg").read_bytes()
            except OSError:
                return None

    def expire(self, now: float, days: float = 7) -> int:
        """`days`'ten eski kayıtlar (zamanı sonlu olmayan bozuk kayıtlar da) ve resimleri silinir; resmi silinemeyen
        kayıt sonraki temizliğe kalır. Kaydı olmayan eski resimler de silinir. Silinen kayıt sayısı döner."""
        cutoff = now - days * 86400
        with self._lock:
            removed: set[str] = set()
            for a in self._items:
                fired = float(a["firedAt"])
                if math.isfinite(fired) and fired >= cutoff:
                    continue
                if a.get("image"):
                    try:
                        (self.images / f"{a['id']}.jpg").unlink(missing_ok=True)
                    except OSError as e:
                        _LOG.warning("Olay resmi silinemedi (%s): %s", a["id"], e)
                        continue                            # kayıt kalır, sonraki temizlikte yeniden denenir
                removed.add(a["id"])
            known = {a["id"] for a in self._items} - removed
            if self.images.exists():                        # kaydı olmayan eski resimler
                for img in self.images.iterdir():
                    try:
                        if (img.is_file() and img.suffix.lower() == ".jpg" and img.stem not in known
                                and img.stat().st_mtime < cutoff):
                            img.unlink()
                    except OSError:
                        pass
            if removed:
                self._items = [a for a in self._items if a["id"] not in removed]
                self._save()
        return len(removed)
