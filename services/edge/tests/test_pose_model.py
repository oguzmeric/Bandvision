from __future__ import annotations

import hashlib
import pathlib
import re
import urllib.request
from typing import Self

import pytest

from bantvision.core import pose
from bantvision.core import pose_model as pm


def test_pose_model_constants() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", pm.MODEL_SHA256)
    assert pm.MODEL_URL.startswith("https://github.com/oguzmeric/Bandvision/releases/download/models-v1/")
    assert pm.MODEL_URL.endswith(pm.MODEL_NAME) and pm.INPUT_SIZE == 256


# ---------------------------------------------------------------------- indirme (ağsız: urlopen sahte)

class _Resp:
    """urlopen yanıtı yerine geçer: verilen parçaları sırayla okutur; sonunda `fail` varsa onu fırlatır."""

    def __init__(self, chunks: list[bytes], fail: Exception | None = None, part: pathlib.Path | None = None) -> None:
        self.chunks, self.fail, self.part = list(chunks), fail, part

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_a: object) -> None:
        return None

    def read(self, _n: int = -1) -> bytes:
        if self.chunks:
            return self.chunks.pop(0)
        if self.fail is not None:
            if self.part is not None:
                assert self.part.exists()                              # yarım dosya indirme sırasında var
            raise self.fail
        return b""


def _model_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> pathlib.Path:
    monkeypatch.setenv("BANTVISION_MODEL_DIR", str(tmp_path))
    return tmp_path / pm.MODEL_NAME


def test_ensure_pose_model_downloads_streaming_with_timeout_and_verifies(
        monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    target = _model_dir(monkeypatch, tmp_path)
    seen: list[tuple[str, float]] = []

    def fake_urlopen(url: str, timeout: float = 0.0) -> _Resp:
        seen.append((url, timeout))
        return _Resp([b"ab", b"c"])

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(pose, "MODEL_SHA256", hashlib.sha256(b"abc").hexdigest())
    assert pose.ensure_pose_model() == target and target.read_bytes() == b"abc"
    assert seen == [(pm.MODEL_URL, pose.DOWNLOAD_TIMEOUT_S)] and pose.DOWNLOAD_TIMEOUT_S <= 30
    assert not list(tmp_path.glob("*.part"))


def test_ensure_pose_model_removes_part_when_connection_fails(
        monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    target = _model_dir(monkeypatch, tmp_path)

    def refused(url: str, timeout: float = 0.0) -> _Resp:
        raise OSError("ağ yok")

    monkeypatch.setattr(urllib.request, "urlopen", refused)
    with pytest.raises(OSError):
        pose.ensure_pose_model()
    assert not list(tmp_path.glob("*.part")) and not target.exists()


def test_ensure_pose_model_removes_part_when_download_breaks_midway(
        monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    target = _model_dir(monkeypatch, tmp_path)
    part = target.with_suffix(".part")
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=0.0: _Resp(
        [b"yarim"], fail=ConnectionResetError("koptu"), part=part))
    with pytest.raises(ConnectionResetError):
        pose.ensure_pose_model()
    assert not part.exists() and not target.exists()


def test_ensure_pose_model_removes_part_on_checksum_mismatch_and_on_deadline(
        monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    target = _model_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=0.0: _Resp([b"bozuk"]))
    with pytest.raises(RuntimeError, match="doğrulanamadı"):
        pose.ensure_pose_model()
    assert not list(tmp_path.glob("*.part")) and not target.exists()

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=0.0: _Resp([b"a", b"b"]))
    with pytest.raises(TimeoutError):                                  # genel süre sınırı aşıldı (damlayan bağlantı)
        pose.ensure_pose_model(deadline_s=-1.0)
    assert not list(tmp_path.glob("*.part")) and not target.exists()


# ---------------------------------------------------------------------- GERÇEK MODEL (yalnızca dosya zaten varsa)

_CACHED = pose.pose_model_path()


@pytest.mark.skipif(not _CACHED.is_file(), reason=f"GERÇEK MODEL testi: {_CACHED} yok (testte asla indirilmez)")
def test_real_movenet_model_smoke() -> None:
    """GERÇEK MODEL: önbellekteki movenet_thunder.onnx (BANTVISION_MODEL_DIR ya da ~/.cache/bantvision) yüklenir;
    girdi/çıktı adları, şekilleri ve türleri sözleşmeye (core/pose_model.py) uyar, sentetik görüntüde çıkarım çalışır.
    Dosya yoksa atlanır; indirme yapılmaz (PoseEstimator'a yol verilir, ensure_pose_model çağrılmaz)."""
    import numpy as np

    est = pose.PoseEstimator(_CACHED)
    inp, (out,) = est._session.get_inputs()[0], est._session.get_outputs()
    assert inp.name == "input" and inp.type == "tensor(int32)" and list(inp.shape)[1:] == [256, 256, 3]
    assert out.name == "output_0" and out.type == "tensor(float)" and list(out.shape)[-2:] == [17, 3]
    img = np.zeros((480, 640, 3), np.uint8)
    img[100:400, 280:360] = 200                                        # kişi boyunda açık renkli dikdörtgen
    kp = est.estimate(img, (280, 100, 360, 400))
    assert kp.shape == (17, 3) and np.isfinite(kp).all() and ((kp[:, 2] >= 0) & (kp[:, 2] <= 1)).all()
