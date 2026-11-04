"""Cihaz ayarları (<data>/devices.json): canlı modellerin ve "Video ile test" işlerinin hangi cihazda çalışacağı.

Biçim: `{"choices": {"detector": c, "pose": c, "video": c}}`; her seçim "auto" | "cpu" | kart kimliği
(`devices.valid_choice`). Eksik dosya ya da anahtar → "auto"; bilinmeyen anahtar yok sayılır.

- Bozuk dosya (JSON çözülemedi ya da biçim yanlış) `devices.json.bozuk` olarak kenara alınır, varsayılanlar geçerlidir.
- Kilitli dosya (Windows) açılışta okunamazsa varsayılanlar yalnızca bellekte kullanılır, dosyaya dokunulmaz; sonraki
  kayıt kullanıcının yeni seçimini yazar.
- Yazma atomiktir (jsonfile.py).
"""
from __future__ import annotations

import logging
import os
import pathlib
import threading
from collections.abc import Mapping
from typing import Any

from ..core import devices
from .jsonfile import read_json, write_json_atomic

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
        self._choices = self._load()

    def _set_aside(self) -> None:
        """Bozuk dosyayı `devices.json.bozuk` olarak kenara alır (incelenebilsin; varsa eskisinin üstüne)."""
        try:
            os.replace(self._file, self._file.with_name(self._file.name + ".bozuk"))
        except OSError:
            _LOG.exception("Bozuk cihaz ayarları dosyası kenara alınamadı (%s)", self._file.name)

    def _load(self) -> dict[str, str]:
        r = read_json(self._file)
        if r.status == "missing":
            return _defaults()
        if r.status == "unreadable":
            _LOG.error("Cihaz ayarları okunamadı (dosya kilitli olabilir); varsayılanlar kullanılıyor, dosyaya "
                       "dokunulmadı (%s)", self._file.name)
            return _defaults()
        data: Any = r.data
        raw = data.get("choices", {}) if isinstance(data, dict) else None
        if r.status == "corrupt" or not isinstance(raw, dict):
            _LOG.error("Cihaz ayarları dosyası bozuk; kenara alındı (%s.bozuk), varsayılanlar kullanılıyor",
                       self._file.name)
            self._set_aside()
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
            self._choices = new
            return dict(new)
