"""Yangın/duman modeli: sınıf başına eşik/NMS, letterbox geri ölçek, model yolu ve indirme."""
from __future__ import annotations

import pathlib
from typing import Any

import numpy as np
import pytest

from bantvision.core import devices, fire_model
from bantvision.core.fire_model import FireDetector, FireModelMissing


class FakeSession:
    def __init__(self, out: np.ndarray) -> None:
        self.out = out
        self.used = devices.Used("cpu", "cpu", "İşlemci", None)
        self.broken: str | None = None
        self.fed: list[np.ndarray] = []

    def get_inputs(self) -> list[Any]:
        return [type("I", (), {"name": "images"})()]

    def run(self, names: Any, feeds: dict[str, np.ndarray]) -> list[np.ndarray]:
        self.fed.append(feeds["images"])
        return [self.out[None]]


def _cell(out: np.ndarray, idx: int, cx: float, cy: float, w: float, h: float, obj: float,
          fire: float, smoke: float) -> None:
    """stride-8 ızgarası (idx = satır*80+sütun) için ham hücre; cx,cy hücre içi sapma, w,h girdi pikseli."""
    out[idx, :2] = (cx, cy)
    out[idx, 2:4] = (np.log(w / 8), np.log(h / 8))
    out[idx, 4:] = (obj, fire, smoke)


def _detector(monkeypatch: pytest.MonkeyPatch, out: np.ndarray) -> tuple[FireDetector, FakeSession]:
    sess = FakeSession(out)
    monkeypatch.setattr(devices, "open_session", lambda path, configure, choice: sess)
    return FireDetector(path=pathlib.Path("x.onnx"), device="cpu"), sess


def _empty() -> np.ndarray:
    return np.zeros((8400, 7), np.float32)


def test_per_class_threshold_and_names(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _empty()
    _cell(out, 0, 0, 0, 40, 40, 1.0, 0.55, 0.0)           # fire 0.55
    _cell(out, 1000, 0, 0, 40, 40, 1.0, 0.0, 0.55)        # smoke 0.55
    det, _ = _detector(monkeypatch, out)
    frame = np.zeros((640, 640, 3), np.uint8)
    both = det.detect(frame, {"fire": 0.5, "smoke": 0.5})
    assert sorted(d.cls for d in both) == ["fire", "smoke"]
    only_fire = det.detect(frame, {"fire": 0.5, "smoke": 0.6})
    assert [d.cls for d in only_fire] == ["fire"]
    assert det.detect(frame, {"fire": 0.6, "smoke": 0.6}) == []
    assert [d.cls for d in det.detect(frame, {"smoke": 0.5})] == ["smoke"]      # eşiği verilmeyen sınıf işlenmez


def test_nms_is_per_class(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _empty()
    # aynı yerde iki üst üste kutu: fire (0.9, 0.8) ve smoke (0.7) -> fire içinde bastırma, smoke kalır
    _cell(out, 0, 0, 0, 40, 40, 1.0, 0.9, 0.0)
    _cell(out, 1, 0, 0, 40, 40, 1.0, 0.8, 0.0)
    _cell(out, 2, 0, 0, 40, 40, 1.0, 0.0, 0.7)
    det, _ = _detector(monkeypatch, out)
    res = det.detect(np.zeros((640, 640, 3), np.uint8), {"fire": 0.5, "smoke": 0.5})
    by = sorted((d.cls, round(d.score, 2)) for d in res)
    assert by == [("fire", 0.9), ("smoke", 0.7)]


def test_letterbox_rescale_to_original_pixels(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _empty()
    # 1280×720 kare: r = 0.5; kutu girdi uzayında merkez (80+... ) hücre 85 = satır1,sütun5 -> merkez (5*8, 1*8) = (40, 8)
    _cell(out, 85, 0, 0, 16, 16, 1.0, 0.9, 0.0)
    det, sess = _detector(monkeypatch, out)
    res = det.detect(np.zeros((720, 1280, 3), np.uint8), {"fire": 0.5})
    assert len(res) == 1
    d = res[0]
    assert (d.x1, d.y1, d.x2, d.y2) == pytest.approx((64.0, 0.0, 96.0, 32.0))   # (40∓8, 8∓8) / 0.5, üst kırpık
    assert sess.fed[0].shape == (1, 3, 640, 640)


def test_used_and_broken_follow_the_session(monkeypatch: pytest.MonkeyPatch) -> None:
    det, sess = _detector(monkeypatch, _empty())
    assert det.used == sess.used and det.broken is None
    sess.broken = "Model kullanılamıyor"
    assert det.broken == "Model kullanılamıyor"


def test_device_choice_is_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[Any, str]] = []
    monkeypatch.setattr(devices, "open_session", lambda p, c, choice: seen.append((p, choice)) or FakeSession(_empty()))
    FireDetector(path=pathlib.Path("m.onnx"), device="gpu-10de-28a1")
    devices.set_default_choice("cpu")
    try:
        FireDetector(path=pathlib.Path("m.onnx"))
    finally:
        devices.set_default_choice("auto")
    assert [c for _, c in seen] == ["gpu-10de-28a1", "cpu"]


def test_model_path_uses_model_dir(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BANTVISION_MODEL_DIR", str(tmp_path))
    assert fire_model.fire_model_path() == tmp_path / "fire_smoke_v1.onnx"


def test_missing_model_without_url_raises_turkish(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BANTVISION_MODEL_DIR", str(tmp_path))
    assert fire_model.FIRE_MODEL_URL is None
    with pytest.raises(FireModelMissing, match="Yangın/duman modeli kurulu değil.") as e:
        fire_model.ensure_fire_model()
    assert isinstance(e.value, RuntimeError)
    with pytest.raises(FireModelMissing):
        FireDetector(device="cpu")                      # yolu verilmezse aynı hata


def test_existing_file_is_used_without_url(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BANTVISION_MODEL_DIR", str(tmp_path))
    (tmp_path / "fire_smoke_v1.onnx").write_bytes(b"x")
    assert fire_model.ensure_fire_model() == tmp_path / "fire_smoke_v1.onnx"


def test_url_set_uses_verified_download(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BANTVISION_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(fire_model, "FIRE_MODEL_URL", "https://example.invalid/fire.onnx")
    monkeypatch.setattr(fire_model, "FIRE_MODEL_SHA256", "ab" * 32)
    calls: list[tuple[Any, ...]] = []

    def fake(url: str, dest: pathlib.Path, sha: str, **kw: Any) -> pathlib.Path:
        calls.append((url, dest, sha, kw))
        return dest

    monkeypatch.setattr(fire_model, "download_verified", fake)
    assert fire_model.ensure_fire_model() == tmp_path / "fire_smoke_v1.onnx"
    assert calls == [("https://example.invalid/fire.onnx", tmp_path / "fire_smoke_v1.onnx", "ab" * 32,
                      {"label": "Yangın/duman modeli"})]
