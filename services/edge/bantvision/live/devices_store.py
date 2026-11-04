"""Cihaz ayarları (<data>/devices.json): canlı modellerin ve "Video ile test" işlerinin hangi cihazda çalışacağı.

Biçim: `{"choices": {"detector": c, "pose": c, "video": c}}`; her seçim "auto" | "cpu" | kart kimliği
(`devices.valid_choice`). Eksik dosya ya da anahtar → "auto"; bilinmeyen anahtar yok sayılır.

- Bozuk dosya (JSON çözülemedi ya da biçim yanlış) diğer ayar dosyaları gibi kenara alınır (`devices.json.corrupt`,
  jsonfile.quarantine), varsayılanlar geçerlidir.
- Kilitli dosya (Windows) açılışta okunamazsa varsayılanlar yalnızca bellekte kullanılır, dosyaya dokunulmaz; `refresh()`
  (Cihaz ayarları sayfası her okuyuşta) dosyayı beklemesiz yeniden dener. Kayıt kullanıcının yeni seçimini yazar.
- Yazma atomiktir (jsonfile.py).
"""
from __future__ import annotations

import logging
import pathlib
import threading
from collections.abc import Mapping
from typing import Any

from ..core import devices
from .jsonfile import JsonRead, quarantine, read_json, write_json_atomic

_LOG = logging.getLogger(__name__)

KEYS = ("detector", "pose", "video")
DEFAULT_CHOICE = "auto"
FILE_NAME = "devices.json"


class DeviceSettingsBusy(Exception):
    """Ayar dosyası yazılamadı (disk ya da dosya kilidi)."""


def _defaults() -> dict[str, str]:
    return dict.fromkeys(KEYS, DEFAULT_CHOICE)


class DeviceSettings:
    def __init__(self, root: pathlib.Path) -> None:
        self._root = root
        self._file = root / FILE_NAME
        self._lock = threading.Lock()
        self._unread = False                            # açılışta dosya okunamadı (kilit): bellekte varsayılanlar
        parsed = self._parse(read_json(self._file))
        if parsed is None:
            _LOG.error("Cihaz ayarları okunamadı (dosya kilitli olabilir); varsayılanlar kullanılıyor, dosyaya "
                       "dokunulmadı (%s)", self._file.name)
            self._unread = True
            parsed = _defaults()
        self._choices = parsed

    @property
    def unread(self) -> bool:
        """Dosya açılışta okunamadı ve o zamandan beri ne okunabildi ne kaydedildi."""
        with self._lock:
            return self._unread

    def _parse(self, r: JsonRead) -> dict[str, str] | None:
        """Okunan dosyayı seçimlere çevirir; `None`: dosya okunamıyor (kilitli). Bozuk dosya kenara alınır."""
        if r.status == "unreadable":
            return None
        if r.status == "missing":
            return _defaults()
        data: Any = r.data
        raw = data.get("choices", {}) if isinstance(data, dict) else None
        if r.status == "corrupt" or not isinstance(raw, dict):
            _LOG.error("Cihaz ayarları dosyası bozuk; kenara alındı (%s.corrupt), varsayılanlar kullanılıyor",
                       self._file.name)
            quarantine(self._file)
            return _defaults()
        choices = _defaults()
        for key in KEYS:
            if key not in raw:
                continue
            if devices.valid_choice(raw[key]):
                choices[key] = raw[key]
            else:
                _LOG.warning("Cihaz ayarlarında geçersiz seçim (%s); varsayılan kullanılıyor", key)
        return choices

    def choices(self) -> dict[str, str]:
        with self._lock:
            return dict(self._choices)

    def refresh(self) -> dict[str, str] | None:
        """Açılışta okunamayan dosyayı tek, beklemesiz denemeyle yeniden okur. Okunduysa yeni seçimleri döndürür (çağıran
        canlı modellere uygular); dosya zaten okunmuşsa ya da hâlâ okunamıyorsa None."""
        with self._lock:
            if not self._unread:
                return None
            parsed = self._parse(read_json(self._file, ()))
            if parsed is None:
                return None
            self._unread, self._choices = False, parsed
            _LOG.info("Cihaz ayarları dosyası yeniden okundu")
            return dict(parsed)

    def save(self, choices: Mapping[str, str]) -> dict[str, str]:
        """Üç seçimi birden kaydeder ve döndürür. Eksik/fazla anahtar ya da geçersiz değer `ValueError`; yazma hatası
        `DeviceSettingsBusy` (bellekteki seçimler değişmez)."""
        if set(choices) != set(KEYS) or not all(devices.valid_choice(choices[k]) for k in KEYS):
            raise ValueError("Geçersiz cihaz seçimi.")
        new = {k: choices[k] for k in KEYS}
        with self._lock:
            try:
                self._root.mkdir(parents=True, exist_ok=True)
                write_json_atomic(self._file, {"choices": new}, indent=2)
            except OSError as e:
                _LOG.error("Cihaz ayarları yazılamadı: %s", e)
                raise DeviceSettingsBusy("Cihaz ayarları kaydedilemedi (disk ya da dosya kilidi); biraz sonra "
                                         "yeniden deneyin.") from e
            self._choices, self._unread = new, False   # kullanıcının seçimi kazanır (kilitli dosyanınki değil)
            return dict(new)
