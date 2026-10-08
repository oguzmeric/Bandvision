"""Poz güvenlik alarm günlüğü: <data>/live/alarms.json, alarm-images/<id>.jpg ve olay kaydı alarm-clips/<id>.webm
(yalnızca bu bilgisayarda, 7 gün; kayıt dosyası en çok `MAX_CLIPS`).

Kayıt: {id, sessionId, camera, type ("hands_up"|"lying"|"test"), startedAt, firedAt, endedAt, acked,
notify ("disabled"|"queued"|"sent"|"failed"|"suppressed"), image, clip, clipStartedAt, falseAlarm}. `clip`: olay
kaydı (video) var mı; `clipStartedAt`: kaydın ilk karesinin duvar saati; `falseAlarm`: kullanıcı "Yanlış alarm" dedi
(kayıt onaylanmış da sayılır). Eski kayıtlarda eksik alanlar varsayılanla dolar. Tüm yazmalar kilit altında ve atomik.

Saklama: 7 günden eski kayıt resmi ve kaydıyla birlikte silinir; kaydı olmayan eski resim/kayıt dosyaları ve yarım
kalmış geçici kayıt dosyaları da temizlenir; kayıt dosyası sayısı `MAX_CLIPS`'i aşarsa en eskiler silinir.

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
                             "acked": False, "notify": "disabled", "image": False, "clip": False,
                             "clipStartedAt": None, "falseAlarm": False}
MAX_CLIPS = 500                     # en çok bu kadar olay kaydı dosyası (≈1–3 MB); fazlası en eskiden silinir
TEMP_CLIP_MAX_AGE_S = 3600.0        # yazılırken yarım kalmış (çökme) geçici kayıt dosyası bu kadar eskiyse silinir
_TEMP_CLIP = ".tmp.webm"


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
        self.clips = self.root / "alarm-clips"
        self.clips.mkdir(parents=True, exist_ok=True)
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
             "image": jpeg is not None, "clip": False, "clipStartedAt": None,
             "falseAlarm": False}
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

    def set_clip(self, alarm_id: str, started_at: float) -> bool:
        """Olay kaydı yazıldı: `clip: true`, `clipStartedAt` (ilk karenin duvar saati). Kayıt yoksa False."""
        return self._update(alarm_id, clip=True, clipStartedAt=started_at)

    def clip_file(self, alarm_id: str) -> Path | None:
        """Olay kaydı dosyası (varsa); kimlik 32 küçük onaltılık değilse None (yol olarak kullanılır)."""
        if not _ID.fullmatch(alarm_id):
            return None
        p = self.clips / f"{alarm_id}.webm"
        return p if p.is_file() else None

    def enforce_clip_cap(self, max_clips: int = MAX_CLIPS) -> int:
        """En çok `max_clips` kayıt dosyası kalır: fazlası en eskiden (dosya zamanı) silinir, kayıtları `clip: false`
        olur; günlüğe yazılır. Silinen sayısı döner."""
        with self._lock:
            files: list[tuple[float, Path]] = []
            for p in self.clips.glob("*.webm"):
                if not _ID.fullmatch(p.stem):
                    continue                                # geçici dosya (yazılıyor)
                try:
                    files.append((p.stat().st_mtime, p))
                except OSError:
                    continue
            if len(files) <= max_clips:
                return 0
            files.sort(key=lambda x: (x[0], x[1].name))
            removed: set[str] = set()
            for _, p in files[: len(files) - max_clips]:
                try:
                    p.unlink(missing_ok=True)
                    removed.add(p.stem)
                except OSError as e:
                    _LOG.warning("Olay kaydı silinemedi (%s): %s", p.stem, e)
            changed = False
            for a in self._items:
                if a["id"] in removed and a.get("clip"):
                    a["clip"], a["clipStartedAt"] = False, None
                    changed = True
            if changed:
                self._save()
        if removed:
            _LOG.warning("Olay kaydı sınırı (%d dosya) aşıldı: en eski %d kayıt silindi", max_clips, len(removed))
        return len(removed)

    def set_notify(self, alarm_id: str, status: str) -> None:
        self._update(alarm_id, notify=status)

    def ack(self, alarm_id: str) -> bool:
        return self._update(alarm_id, acked=True)

    def mark_false_alarm(self, alarm_id: str) -> bool:
        """Kullanıcı "Yanlış alarm" dedi: `falseAlarm` ve `acked` (alarm kapanır). Kayıt yoksa False."""
        return self._update(alarm_id, falseAlarm=True, acked=True)

    def get(self, alarm_id: str) -> dict[str, Any] | None:
        with self._lock:
            a = self._find(alarm_id)
            return dict(a) if a else None

    def list(self, active_only: bool = False, since: float | None = None, limit: int = 50,
             session_id: str | None = None, kind: str | None = None, until: float | None = None,
             ) -> list[dict[str, Any]]:
        """En yeni önce; `limit` süzgeçlerden SONRA uygulanır. Süzgeçler: yalnızca onaylanmamış, `since` ≤ firedAt ≤
        `until`, `session_id` (yalnızca o oturumun alarmları), `kind` (tür)."""
        with self._lock:
            items = [dict(a) for a in self._items if (not active_only or not a["acked"])
                     and (since is None or a["firedAt"] >= since)
                     and (until is None or a["firedAt"] <= until)
                     and (session_id is None or a["sessionId"] == session_id)
                     and (kind is None or a["type"] == kind)]
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
        """`days`'ten eski kayıtlar (zamanı sonlu olmayan bozuk kayıtlar da) resim ve olay kaydıyla birlikte silinir;
        dosyası silinemeyen kayıt sonraki temizliğe kalır. Kaydı olmayan eski resim ve kayıt dosyaları, `now`'dan
        `TEMP_CLIP_MAX_AGE_S` önceden kalan yarım geçici kayıt dosyaları da silinir; sonra `MAX_CLIPS` sınırı uygulanır.
        Silinen kayıt sayısı döner."""
        cutoff = now - days * 86400
        with self._lock:
            removed: set[str] = set()
            for a in self._items:
                fired = float(a["firedAt"])
                if math.isfinite(fired) and fired >= cutoff:
                    continue
                try:
                    (self.images / f"{a['id']}.jpg").unlink(missing_ok=True)
                    (self.clips / f"{a['id']}.webm").unlink(missing_ok=True)
                except OSError as e:
                    _LOG.warning("Olay resmi/kaydı silinemedi (%s): %s", a["id"], e)
                    continue                                # kayıt kalır, sonraki temizlikte yeniden denenir
                removed.add(a["id"])
            known = {a["id"] for a in self._items} - removed
            self._remove_orphans(self.images, ".jpg", known, cutoff)
            self._remove_orphans(self.clips, ".webm", known, cutoff)
            if self.clips.exists():                         # çökmeden kalan yarım geçici kayıtlar
                for f in self.clips.glob(f"*{_TEMP_CLIP}"):
                    try:
                        if f.stat().st_mtime < now - TEMP_CLIP_MAX_AGE_S:
                            f.unlink()
                    except OSError:
                        pass
            if removed:
                self._items = [a for a in self._items if a["id"] not in removed]
                self._save()
        self.enforce_clip_cap()
        return len(removed)

    @staticmethod
    def _remove_orphans(folder: Path, suffix: str, known: set[str], cutoff: float) -> None:
        """Kaydı olmayan (ve `cutoff`'tan eski: yazılmakta olan yeni dosyaya dokunulmaz) `<id><suffix>` dosyaları."""
        if not folder.exists():
            return
        for f in folder.iterdir():
            try:
                if (f.is_file() and f.name.endswith(suffix) and not f.name.endswith(_TEMP_CLIP)
                        and f.name[: -len(suffix)] not in known and f.stat().st_mtime < cutoff):
                    f.unlink()
            except OSError:
                pass
