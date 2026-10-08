"""Ortak model indirme yardımcısı (core/model_download.py): akış halinde, zaman aşımlı, SHA-256 doğrulamalı; yarım
dosya (.part) her hatada silinir. Ağ yok: urllib.request.urlopen sahte."""
from __future__ import annotations

import hashlib
import pathlib
import urllib.request
from typing import Self

import pytest

from bantvision.core import detector, model_download


class _Resp:
    def __init__(self, chunks: list[bytes], fail: Exception | None = None) -> None:
        self.chunks, self.fail = list(chunks), fail

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_a: object) -> None:
        return None

    def read(self, _n: int = -1) -> bytes:
        if self.chunks:
            return self.chunks.pop(0)
        if self.fail is not None:
            raise self.fail
        return b""


SHA_ABC = hashlib.sha256(b"abc").hexdigest()


def test_download_verified_streams_with_timeout_and_replaces_atomically(
        monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    seen: list[tuple[str, float]] = []

    def fake(url: str, timeout: float = 0.0) -> _Resp:
        seen.append((url, timeout))
        return _Resp([b"a", b"bc"])

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    dest = tmp_path / "m" / "model.onnx"
    assert model_download.download_verified("https://x/model.onnx", dest, SHA_ABC) == dest
    assert dest.read_bytes() == b"abc" and seen == [("https://x/model.onnx", 30.0)]
    assert not list(dest.parent.glob("*.part"))
    # dosya zaten doğruysa yeniden indirilmez
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("indirme olmamalı"))
    assert model_download.download_verified("https://x/model.onnx", dest, SHA_ABC) == dest


@pytest.mark.parametrize("case", ["refused", "midway", "sha", "deadline"])
def test_download_verified_removes_part_on_every_failure(
        monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, case: str) -> None:
    dest = tmp_path / "model.onnx"
    part = dest.with_suffix(".part")

    def fake(url: str, timeout: float = 0.0) -> _Resp:
        if case == "refused":
            raise OSError("ağ yok")
        if case == "midway":
            assert not part.exists()
            return _Resp([b"yarim"], fail=ConnectionResetError("koptu"))
        return _Resp([b"bozuk"] if case == "sha" else [b"a", b"b", b"c"])

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    expected = {"refused": OSError, "midway": ConnectionResetError, "sha": RuntimeError,
                "deadline": model_download.DownloadTimeout}[case]
    with pytest.raises(expected) as e:
        model_download.download_verified("https://x/m", dest, SHA_ABC, deadline=-1.0 if case == "deadline" else 300.0,
                                         label="Kişi tanıma modeli")
    if case in ("sha", "deadline"):
        assert str(e.value).startswith("Kişi tanıma modeli")           # Türkçe ve hangi model olduğu belli
    assert not part.exists() and not dest.exists()


def test_detector_ensure_model_uses_shared_helper(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    """YOLOX indirmesi de akış halinde ve zaman aşımlı (eskiden urlretrieve: zaman aşımı yok, .part kalabiliyordu)."""
    monkeypatch.setenv("BANTVISION_MODEL_DIR", str(tmp_path))
    seen: list[float] = []

    def fake(url: str, timeout: float = 0.0) -> _Resp:
        seen.append(timeout)
        return _Resp([b"bozuk"])

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    with pytest.raises(RuntimeError, match="doğrulanamadı"):
        detector.ensure_model()
    assert seen == [30.0] and not list(tmp_path.glob("*.part")) and not (tmp_path / detector.MODEL_NAME).exists()
    monkeypatch.setattr(detector, "MODEL_SHA256", SHA_ABC)
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=0.0: _Resp([b"abc"]))
    assert detector.ensure_model().read_bytes() == b"abc"


def test_failure_reason_is_turkish_for_network_errors() -> None:
    import urllib.error

    net = "internete ulaşılamadı (bağlantıyı kontrol edin)"
    assert model_download.failure_reason(urllib.error.URLError("getaddrinfo failed")) == net
    assert model_download.failure_reason(ConnectionResetError("reset")) == net
    assert model_download.failure_reason(TimeoutError("timed out")) == net
    assert model_download.failure_reason(
        model_download.ModelIntegrityError("Poz modeli doğrulanamadı (SHA-256 tutmuyor).")).startswith("Poz")
    assert model_download.failure_reason(model_download.DownloadTimeout("Poz modeli 300 sn içinde indirilemedi.")) \
        == "Poz modeli 300 sn içinde indirilemedi."
    # Wave-A kalıntısı 5: kullanıcıya İngilizce ileti gitmez (asıl metin yalnızca günlükte)
    import errno
    import ssl

    reason = model_download.failure_reason
    http = urllib.error.HTTPError("https://x", 404, "Not Found", {}, None)  # type: ignore[arg-type]
    assert reason(http) == "Model sunucusu isteği reddetti (HTTP 404)"
    bad = "Model indirilemedi (bağlantı hatası)"
    assert reason(OSError("ağ yok")) == bad
    assert reason(ssl.SSLError("CERTIFICATE_VERIFY_FAILED")) == bad
    assert reason(OSError(errno.ENOSPC, "No space left on device")) == "Model kaydedilemedi (diskte yer yok)"
    assert reason(PermissionError(13, "Access is denied")) == "Model klasörüne yazılamadı (erişim izni yok)"
    assert reason(ImportError("No module named onnxruntime")) == "model çalıştırıcısı (onnxruntime) yüklenemedi"
    assert reason(ValueError("INVALID_PROTOBUF : Load model failed")) == \
        "beklenmeyen hata (ayrıntı analiz sunucusunun günlüğünde)"
