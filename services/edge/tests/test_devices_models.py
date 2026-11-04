"""Model sınıfları (ObjectDetector, PoseEstimator) cihaz seçimini devices.open_session'a iletir; `used` oturumunkidir.
Video aracı (`--device`) ve `ozet.json` `device` alanı: yalnız model gerçekten kurulduysa."""
from __future__ import annotations

import json
import pathlib
from typing import Any

import numpy as np
import pytest
from test_video import write_video

from bantvision import sim, video
from bantvision.core import detect_count, devices, pose
from bantvision.core.detector import ObjectDetector
from bantvision.core.pose import PoseEstimator


class FakeSO:
    def __init__(self) -> None:
        self.intra_op_num_threads = 0
        self.entries: dict[str, str] = {}

    def add_session_config_entry(self, k: str, v: str) -> None:
        self.entries[k] = v


class FakeInput:
    name = "images"


class FakeGuarded:
    def __init__(self, used: devices.Used) -> None:
        self.used = used

    def get_inputs(self) -> list[FakeInput]:
        return [FakeInput()]

    def run(self, output_names: Any, feeds: Any) -> Any:
        return [np.zeros((1, 8400, 85), np.float32)]


GPU_USED = devices.Used("gpu", "gpu-10de-28a1", "NVIDIA Laptop GPU", None)


@pytest.fixture()
def opened(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_open(model_path: Any, configure: Any, choice: str) -> FakeGuarded:
        calls.append({"path": model_path, "configure": configure, "choice": choice})
        return FakeGuarded(GPU_USED)

    monkeypatch.setattr(devices, "open_session", fake_open)
    return calls


@pytest.fixture(autouse=True)
def _restore_default() -> Any:
    before = devices.default_choice()
    yield
    devices.set_default_choice(before)


@pytest.mark.parametrize("cls", [ObjectDetector, PoseEstimator], ids=lambda c: c.__name__)
def test_explicit_device_is_passed_to_open_session(cls: Any, opened: list[dict[str, Any]],
                                                   tmp_path: pathlib.Path) -> None:
    m = cls(path=tmp_path / "x.onnx", device="auto")
    assert [c["choice"] for c in opened] == ["auto"]
    assert opened[0]["path"] == tmp_path / "x.onnx"              # kod yolu olduğu gibi (Path) iletir
    assert m.used == GPU_USED


@pytest.mark.parametrize("cls", [ObjectDetector, PoseEstimator], ids=lambda c: c.__name__)
def test_device_none_uses_process_default(cls: Any, opened: list[dict[str, Any]], tmp_path: pathlib.Path) -> None:
    cls(path=tmp_path / "x.onnx")
    assert opened[-1]["choice"] == "cpu"                       # başlangıç varsayılanı
    devices.set_default_choice("gpu-10de-28a1")
    cls(path=tmp_path / "x.onnx", device=None)
    assert opened[-1]["choice"] == "gpu-10de-28a1"


@pytest.mark.parametrize("cls", [ObjectDetector, PoseEstimator], ids=lambda c: c.__name__)
def test_configure_applies_thread_and_spinning_settings(cls: Any, opened: list[dict[str, Any]],
                                                        tmp_path: pathlib.Path) -> None:
    cls(path=tmp_path / "x.onnx", device="cpu")
    so = FakeSO()
    opened[0]["configure"](so)
    assert so.intra_op_num_threads >= 1
    assert so.entries == {"session.intra_op.allow_spinning": "0"}


def test_detector_runs_through_guarded_session(opened: list[dict[str, Any]], tmp_path: pathlib.Path) -> None:
    det = ObjectDetector(path=tmp_path / "x.onnx", device="cpu")
    assert det.detect(np.zeros((48, 64, 3), np.uint8), ["person"]) == []


def test_pose_uses_model_module_download_path_only_without_explicit_path(
        opened: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    monkeypatch.setattr(pose, "ensure_pose_model", lambda: tmp_path / "p.onnx")
    PoseEstimator(device="cpu")
    assert opened[0]["path"] == tmp_path / "p.onnx"


# ---------------------------------------------------------------- video aracı

def _write(tmp_path: pathlib.Path) -> pathlib.Path:
    sc = sim.single_file(fps=30.0)
    return write_video(sc, tmp_path / "a.mp4")


def test_product_counting_summary_has_no_device(tmp_path: pathlib.Path) -> None:
    src = _write(tmp_path)
    out = tmp_path / "o"
    assert video.main([str(src), "--out", str(out), "--no-video", "--preset", "egg"]) == 0
    assert "device" not in json.loads((out / "ozet.json").read_text(encoding="utf-8"))


def test_invalid_device_is_a_usage_error(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as e:
        video.main([str(tmp_path / "a.mp4"), "--device", "nvidia"])
    assert e.value.code == 2
    assert "--device" in capsys.readouterr().err


class FakeDetector:
    """İlk tanımadan sonra `used` ekran kartından işlemciye düşer (N4): ozet.json'daki cihaz koşunun SONUNDA okunmalı."""
    built_with: str = ""

    def __init__(self, path: Any = None, device: str | None = None) -> None:
        FakeDetector.built_with = device if device is not None else devices.default_choice()
        self.used = devices.Used("gpu", "gpu-10de-28a1", "NVIDIA Laptop GPU", None)

    def detect(self, bgr: Any, classes: list[str], conf: float = 0.35, iou: float = 0.45) -> list[Any]:
        self.used = devices.cpu_used(DROP_NOTE)
        return []


DROP_NOTE = "Ekran kartı çalışırken hata verdi (örnek); işlemci kullanılıyor."


def test_detect_mode_records_device_and_sets_default(tmp_path: pathlib.Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detect_count, "ObjectDetector", FakeDetector)
    src = _write(tmp_path)
    out = tmp_path / "o"
    rc = video.main([str(src), "--out", str(out), "--no-video", "--preset", "people", "--mode", "detect",
                     "--device", "auto"])
    assert rc == 0
    s = json.loads((out / "ozet.json").read_text(encoding="utf-8"))
    assert s["device"] == {"kind": "cpu", "name": "İşlemci", "note": DROP_NOTE}   # koşu sonundaki `used`
    assert FakeDetector.built_with == "auto"
    assert devices.default_choice() == "auto"


def test_device_option_defaults_to_cpu(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detect_count, "ObjectDetector", FakeDetector)
    devices.set_default_choice("auto")                          # önceki test sızıntısına karşı
    src = _write(tmp_path)
    out = tmp_path / "o"
    assert video.main([str(src), "--out", str(out), "--no-video", "--preset", "people", "--mode", "detect"]) == 0
    assert FakeDetector.built_with == "cpu"
