"""Yanlış alarm → zor örnek: kullanıcının "Yanlış alarm" dediği yangın/duman alarmlarının resmi ve olay kaydı, ileride
modeli yeniden eğitmek için bu bilgisayarda saklanır (hiçbir yere gönderilmez).

Klasör: `<data>/live/hard-negatives/<id>/` — `frame.jpg` (çizimsiz alarm karesi, eğitimde kullanılan; varsa),
`image.jpg` (kutular çizili alarm resmi, insan içindir; varsa), `clip.webm` (olay kaydı, yazılmışsa) ve `meta.json`
`{id, type, camera, firedAt, sourceId, channelId}`. `meta.json` en son yazılır: varlığı örneğin tamam olduğunu
gösterir. İşaret geri alınınca klasör silinir. Kayıt işaretten sonra yazılırsa (`clipPending`) yazıldığında kopyalanır
(`add_clip`; klasör yoksa — işaret geri alınmış — hiçbir şey yapılmaz). En çok `MAX_HARD_NEGATIVES` alarm; aşınca en eski
alarmlar (meta'daki `firedAt`) silinir, yeni eklenen hiç silinmez. Yalnızca `fire`/`smoke` türleri.

Hiçbir hata çağırana ulaşmaz: dosya hatası uyarı olarak günlüğe yazılır (alarm işlemi bozulmaz); ilk kopyalama
yarıda kalırsa yarım örnek bırakılmaz, daha önce tamamlanmış bir örnek (yeniden işaretleme) ise silinmez. Tüm işlemler
tek kilit altında (işaret ve geç kayıt yarışmaz).
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Any

from .jsonfile import write_json_atomic

_LOG = logging.getLogger(__name__)
_ID = re.compile(r"[0-9a-f]{32}")
KINDS = frozenset({"fire", "smoke"})
MAX_HARD_NEGATIVES = 500                # en çok bu kadar alarm klasörü; fazlası en eski alarmdan silinir
_META_KEYS = ("id", "type", "camera", "firedAt", "sourceId", "channelId")


class HardNegatives:
    def __init__(self, root: Path, cap: int = MAX_HARD_NEGATIVES) -> None:
        self.root = root
        self.cap = cap
        self._lock = threading.Lock()

    def _folder(self, alarm_id: str) -> Path | None:
        return self.root / alarm_id if _ID.fullmatch(alarm_id) else None

    def add(self, record: dict[str, Any], image: Path | None, clip: Path | None, raw: Path | None = None) -> bool:
        """Yanlış alarm işaretlendi: çizimsiz kare (`raw` → `frame.jpg`), resim ve (yazılmışsa) kayıt kopyalanır,
        `meta.json` yazılır, sınır uygulanır. Tür `fire`/`smoke` değilse hiçbir şey yapılmaz. Başarıda True; hata günlüğe
        yazılır, False (yeni klasör yarım kaldıysa silinir; önceden tamamlanmış örnek — `meta.json` vardı — korunur)."""
        aid = str(record.get("id", ""))
        folder = self._folder(aid)
        if record.get("type") not in KINDS or folder is None:
            return False
        with self._lock:
            complete_before = (folder / "meta.json").is_file()
            try:
                folder.mkdir(parents=True, exist_ok=True)
                for src, name in ((raw, "frame.jpg"), (image, "image.jpg"), (clip, "clip.webm")):
                    if src is not None and src.is_file():
                        _copy(src, folder / name)
                write_json_atomic(folder / "meta.json", {k: record.get(k) for k in _META_KEYS})
            except (OSError, ValueError, TypeError) as e:
                _LOG.warning("Zor örnek kaydedilemedi (%s): %s", aid, e)
                if not complete_before:                     # önceki tam örnek (yeniden işaretleme) silinmez
                    shutil.rmtree(folder, ignore_errors=True)
                return False
            self._enforce_cap(keep=aid)
        return True

    def add_clip(self, alarm_id: str, clip: Path) -> bool:
        """Olay kaydı işaretten sonra yazıldı: örnek klasörü varsa (işaret geri alınmamış) kayıt kopyalanır."""
        folder = self._folder(alarm_id)
        if folder is None:
            return False
        with self._lock:
            if not (folder / "meta.json").is_file():
                return False
            try:
                _copy(clip, folder / "clip.webm")
            except OSError as e:
                _LOG.warning("Zor örnek kaydı kopyalanamadı (%s): %s", alarm_id, e)
                return False
        return True

    def remove(self, alarm_id: str) -> bool:
        """İşaret geri alındı: örnek klasörü silinir (yoksa bir şey yapılmaz). Silinemezse uyarı, False."""
        folder = self._folder(alarm_id)
        if folder is None:
            return False
        with self._lock:
            if not folder.exists():
                return True
            try:
                shutil.rmtree(folder)
            except OSError as e:
                _LOG.warning("Zor örnek silinemedi (%s): %s", alarm_id, e)
                return False
        return True

    def _enforce_cap(self, keep: str) -> None:
        """Kilit altında: en çok `cap` alarm klasörü kalır; fazlası en eski alarmdan (`firedAt`; okunamazsa klasör
        zamanı) silinir. `keep` (yeni eklenen) silinmez. Tanımadığı dosya/klasöre dokunmaz."""
        try:
            folders = [p for p in self.root.iterdir() if p.is_dir() and _ID.fullmatch(p.name)]
        except OSError as e:
            _LOG.warning("Zor örnek klasörü okunamadı: %s", e)
            return
        if len(folders) <= self.cap:
            return
        ranked = sorted((p for p in folders if p.name != keep), key=lambda p: (_fired_at(p), p.name))
        excess = len(folders) - self.cap
        for p in ranked[:excess]:
            try:
                shutil.rmtree(p)
            except OSError as e:
                _LOG.warning("Eski zor örnek silinemedi (%s): %s", p.name, e)
        _LOG.info("Zor örnek sınırı (%d alarm) aşıldı: en eski %d örnek silindi", self.cap, min(excess, len(ranked)))


def _copy(src: Path, dst: Path) -> None:
    """Geçici adla kopyalar ve atomik olarak yeniden adlandırır (yarım dosya kalmaz)."""
    tmp = dst.with_name(dst.name + ".tmp")
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)


def _fired_at(folder: Path) -> float:
    try:
        v = json.loads((folder / "meta.json").read_text("utf-8")).get("firedAt")
        if isinstance(v, int | float) and not isinstance(v, bool):
            return float(v)
    except (OSError, ValueError, AttributeError):
        pass
    try:
        return folder.stat().st_mtime
    except OSError:
        return 0.0
