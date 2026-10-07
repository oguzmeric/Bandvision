"""Canlı sayımın küçük JSON dosyaları (alarm günlüğü, bildirim kuyruğu, izlenen kameralar, ayarlar): atomik yazma ve
Windows kilidine dayanıklı okuma.

- Yazma: geçici dosya + `os.replace` (yarım yazılmış dosya hiçbir zaman asıl adla durmaz).
- Okuma: virüs tarayıcısı ya da yedekleme yazılımı dosyayı kısa süre kilitleyebilir (`PermissionError`). Okuma hataları
  artan beklemeyle yeniden denenir; yalnızca JSON çözülemiyorsa dosya **bozuk** sayılır. Kilitli dosya bozuk sayılıp
  kenara alınmaz (alarm geçmişi kaybolmasın).
"""
from __future__ import annotations

import contextlib
import json
import os
import pathlib
import time
from typing import Any, Literal, NamedTuple

READ_RETRY_DELAYS_S = (0.2, 0.4, 0.6, 0.8, 1.0)        # 5 yeniden deneme, toplam ≈ 3 sn


class JsonRead(NamedTuple):
    data: Any
    status: Literal["ok", "missing", "corrupt", "unreadable"]


def write_json_atomic(path: pathlib.Path, data: Any, *, indent: int | None = None, private: bool = False) -> None:
    """`data`'yı JSON olarak atomik yazar; `private`: POSIX'te yalnızca sahibi okur (0600). Hata `OSError` fırlatır."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")
    if private:
        with contextlib.suppress(OSError):                  # Windows'ta POSIX izni yok
            os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def read_json(path: pathlib.Path, delays: tuple[float, ...] = READ_RETRY_DELAYS_S) -> JsonRead:
    """Dosyayı okur. "missing": yok; "unreadable": okuma hatası (ör. kilit) tüm denemelerden sonra sürüyor;
    "corrupt": JSON (ya da UTF-8) çözülemedi."""
    for attempt in range(len(delays) + 1):
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return JsonRead(None, "missing")
        except UnicodeDecodeError:
            return JsonRead(None, "corrupt")
        except OSError:                                     # PermissionError (Windows kilidi) ve diğer okuma hataları
            if attempt < len(delays):
                time.sleep(delays[attempt])
                continue
            return JsonRead(None, "unreadable")
        try:
            return JsonRead(json.loads(text), "ok")
        except ValueError:
            return JsonRead(None, "corrupt")
    return JsonRead(None, "unreadable")                     # pragma: no cover — döngü her yolda döner


def quarantine(path: pathlib.Path) -> None:
    """Bozuk dosyayı `<ad>.json.corrupt` olarak kenara alır (incelenebilsin; varsa eskisinin üstüne)."""
    with contextlib.suppress(OSError):
        os.replace(path, path.with_suffix(".json.corrupt"))
