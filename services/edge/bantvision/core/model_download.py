"""Model dosyası indirme (YOLOX kişi tanıma ve MoveNet poz için ortak): akış halinde, zaman aşımlı, SHA-256 doğrulamalı.

- Bağlanma ve her okuma `timeout` (30 sn) ile sınırlı: takılan ağ sonsuza dek beklemez.
- Tüm indirme `deadline` (300 sn) ile sınırlı: yavaş damlayan bağlantı da biter.
- Yarım dosya (`.part`) her hatada (bağlantı, kopma, süre, parmak izi, iptal) silinir; doğrulanan dosya atomik olarak
  yerine konur (yarım/bozuk model hiçbir zaman asıl adla durmaz).
"""
from __future__ import annotations

import contextlib
import errno
import hashlib
import pathlib
import time
import urllib.error
import urllib.request

DOWNLOAD_TIMEOUT_S = 30.0               # bağlanma ve her okuma için
DOWNLOAD_DEADLINE_S = 300.0             # tüm indirme için üst sınır
_CHUNK = 1 << 16


class DownloadTimeout(TimeoutError):
    """Genel süre sınırı aşıldı (ileti Türkçe, hangi model olduğu yazılı)."""


class ModelIntegrityError(RuntimeError):
    """İndirilen dosyanın parmak izi tutmuyor (ileti Türkçe, hangi model olduğu yazılı)."""


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: pathlib.Path, timeout: float, deadline: float, label: str) -> None:
    end = time.monotonic() + deadline
    with urllib.request.urlopen(url, timeout=timeout) as resp, dest.open("wb") as fh:
        while chunk := resp.read(_CHUNK):
            if time.monotonic() > end:
                raise DownloadTimeout(f"{label} {max(deadline, 0):.0f} sn içinde indirilemedi.")
            fh.write(chunk)


def download_verified(url: str, dest: pathlib.Path, sha256: str, timeout: float = DOWNLOAD_TIMEOUT_S,
                      deadline: float = DOWNLOAD_DEADLINE_S, label: str = "Model") -> pathlib.Path:
    """`dest` yoksa ya da parmak izi tutmuyorsa `url`'den indirir ve doğrular; hata fırlatırsa `.part` kalmaz."""
    if dest.exists() and sha256_file(dest) == sha256:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    try:
        _download(url, tmp, timeout, deadline, label)
        if sha256_file(tmp) != sha256:
            raise ModelIntegrityError(f"{label} doğrulanamadı (SHA-256 tutmuyor).")
        tmp.replace(dest)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise
    return dest


def failure_reason(e: BaseException) -> str:
    """Yükleme hatasının kullanıcıya gösterilecek Türkçe nedeni; kullanıcıya hiç İngilizce ileti gitmez, asıl ileti
    yalnızca günlüğe yazılır (çağıran yazar). Yalnızca kendi Türkçe iletilerimiz (süre aşımı, parmak izi) aynen geçer:
    - sunucu isteği reddetti (HTTP hatası) → "Model sunucusu isteği reddetti (HTTP <kod>)";
    - ağ hataları (adres çözülemedi, bağlantı reddedildi/koptu, zaman aşımı) → "internete ulaşılamadı (…)";
    - disk dolu / klasöre yazma izni yok → kendi iletisi; diğer OSError ve SSL hataları → "Model indirilemedi
      (bağlantı hatası)";
    - beklenmeyen diğer hatalar → genel ileti."""
    if isinstance(e, DownloadTimeout | ModelIntegrityError):   # kendi Türkçe iletilerimiz (önce bakılır)
        return str(e)
    if isinstance(e, urllib.error.HTTPError):                  # URLError alt sınıfı: önce bakılır
        return f"Model sunucusu isteği reddetti (HTTP {e.code})"
    if isinstance(e, urllib.error.URLError | ConnectionError | TimeoutError):
        return "internete ulaşılamadı (bağlantıyı kontrol edin)"
    if isinstance(e, OSError):
        if e.errno == errno.ENOSPC:
            return "Model kaydedilemedi (diskte yer yok)"
        if isinstance(e, PermissionError):
            return "Model klasörüne yazılamadı (erişim izni yok)"
        return "Model indirilemedi (bağlantı hatası)"
    if isinstance(e, ImportError):
        return "model çalıştırıcısı (onnxruntime) yüklenemedi"
    return "beklenmeyen hata (ayrıntı analiz sunucusunun günlüğünde)"
