"""Video aracı yangın/duman modu (bantvision.video --preset fire): canlıdaki FireAnalyzer aynen, video zamanıyla.

Dedektör sahtedir (model yok, indirme yok). Sahte dedektör hangi karede olduğunu `read_frames` casusundan öğrenir; kutunun
içi pencere boyunca her karede değişir (gürültü), böylece hareket denetimi geçer.
"""
from __future__ import annotations

import csv
import json
import pathlib
from typing import Any, ClassVar

import cv2
import numpy as np
import pytest

from bantvision import video
from bantvision.core import devices
from bantvision.core.detector import Detection

FPS = 10.0
SECONDS = 10
W, H = 640, 480
BOX = (200, 120, 360, 300)                                             # piksel: x1, y1, x2, y2


class Clock:
    """`read_frames` her kareyi verirken zamanı buraya yazar; sahte dedektör buradan okur."""
    t = 0.0
    calls = 0
    conf: ClassVar[dict[str, float]] = {}


def fake_detector(windows: dict[str, tuple[float, float]]) -> type:
    """`windows`: tür → [başla, bitir) sn arası kutuyu bulan sahte dedektör sınıfı."""
    class Fake:
        used = devices.Used("gpu", "gpu-10de-28a1", "NVIDIA Laptop GPU", None)

        def __init__(self, path: Any = None, device: str | None = None) -> None:
            pass

        def detect(self, _bgr: np.ndarray, conf: dict[str, float]) -> list[Detection]:
            Clock.calls += 1
            Clock.conf = dict(conf)
            return [Detection(*map(float, BOX), 0.9, kind) for kind, (a, b) in windows.items()
                    if a <= Clock.t < b and kind in conf]

    return Fake


def make_video(path: pathlib.Path, noisy: tuple[float, float], seconds: int = SECONDS) -> pathlib.Path:
    """Gri sahne; `noisy` aralığında kutunun içi her karede rastgele (alev gibi oynar), dışı sabit."""
    rng = np.random.default_rng(3)
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for k in range(int(FPS * seconds)):
        f = np.full((H, W, 3), 40, np.uint8)
        if noisy[0] <= k / FPS < noisy[1]:
            x1, y1, x2, y2 = BOX
            f[y1:y2, x1:x2] = rng.integers(0, 256, (y2 - y1, x2 - x1, 1), dtype=np.uint8)
        w.write(f)
    w.release()
    return path


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> None:
    orig = video.read_frames
    Clock.calls = 0

    def wrapped(info: Any, start: float = 0.0, end: float | None = None, step: int = 1) -> Any:
        for k, t, f in orig(info, start, end, step):
            Clock.t = t
            yield k, t, f

    monkeypatch.setattr(video, "read_frames", wrapped)


@pytest.fixture
def fakes(spy: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(video, "FireDetector", fake_detector({"fire": (2.0, 6.0)}))


@pytest.fixture
def src(tmp_path: pathlib.Path) -> pathlib.Path:
    return make_video(tmp_path / "yangin.mp4", (2.0, 6.0))


def run(src: pathlib.Path, tmp_path: pathlib.Path, *extra: str) -> tuple[dict[str, Any], pathlib.Path]:
    out = tmp_path / "o"
    assert video.main([str(src), "--out", str(out), "--no-video", "--preset", "fire", *extra]) == 0
    return json.loads((out / "ozet.json").read_text(encoding="utf-8")), out


def test_fire_alarm_at_rule_seconds_with_image_and_csv(fakes: None, src: pathlib.Path, tmp_path: pathlib.Path) -> None:
    s, out = run(src, tmp_path)
    assert s["count"] == 1 and len(s["alarms"]) == 1
    a = s["alarms"][0]
    assert a["kind"] == "fire" and a["trackId"] == 0
    assert a["startS"] == pytest.approx(2.0, abs=0.3)
    assert a["atS"] == pytest.approx(5.0, abs=0.35)                    # 3 sn kuralı: başlangıç + 3
    assert a["endS"] == pytest.approx(6.0, abs=0.35)                   # alev 6 sn'de bitti
    assert a["image"] == "alarm-1.jpg"
    img = cv2.imread(str(out / "alarm-1.jpg"))
    assert img is not None and img.shape[1] == 640
    raw = (out / "alarm-1.jpg").read_bytes()
    assert raw[:2] == b"\xff\xd8" and raw[-2:] == b"\xff\xd9"          # geçerli JPEG
    orange = int(np.sum((img[..., 2] > 200) & (img[..., 1] > 90) & (img[..., 1] < 190) & (img[..., 0] < 60)))
    assert orange > 100                                                # alarm kutusu turuncu çizilir
    assert s["calibration"]["countMode"] == "fire"
    assert s["fps"] == FPS and s["size"] == [W, H] and s["processingFps"]
    assert s["device"]["kind"] == "gpu"
    rows = list(csv.reader((out / "alarmlar.csv").open(encoding="utf-8"), delimiter=";"))
    assert rows[0] == ["baslangic_sn", "alarm_sn", "bitis_sn", "tur", "iz"]
    assert rows[1][3] == "Yangın" and rows[1][4] == "0" and len(rows) == 2


def test_alarm_time_is_video_time_not_processing_time(fakes: None, src: pathlib.Path, tmp_path: pathlib.Path) -> None:
    a1 = run(src, tmp_path)[0]["alarms"]
    (tmp_path / "o" / "ozet.json").unlink()
    assert run(src, tmp_path)[0]["alarms"] == a1


def test_smoke_alarm_uses_its_own_rule_and_label(spy: None, monkeypatch: pytest.MonkeyPatch,
                                                 tmp_path: pathlib.Path) -> None:
    monkeypatch.setattr(video, "FireDetector", fake_detector({"smoke": (1.0, 9.0)}))
    path = make_video(tmp_path / "duman.mp4", (1.0, 9.0))
    s, out = run(path, tmp_path, "--smoke", "5")
    a = s["alarms"][0]
    assert a["kind"] == "smoke" and a["trackId"] == 1 and a["atS"] == pytest.approx(6.0, abs=0.35)
    rows = list(csv.reader((out / "alarmlar.csv").open(encoding="utf-8"), delimiter=";"))
    assert rows[1][3] == "Duman" and rows[1][4] == "1"


def test_no_fire_option_gives_no_alarms_and_fire_class_not_asked(fakes: None, src: pathlib.Path,
                                                                 tmp_path: pathlib.Path) -> None:
    s, out = run(src, tmp_path, "--no-fire")
    assert s["count"] == 0 and s["alarms"] == [] and "fire" not in Clock.conf
    assert not list(out.glob("alarm-*.jpg"))


def test_fire_seconds_option_moves_the_alarm(fakes: None, src: pathlib.Path, tmp_path: pathlib.Path) -> None:
    s, _ = run(src, tmp_path, "--fire", "2")
    assert s["alarms"][0]["atS"] == pytest.approx(4.0, abs=0.35)


@pytest.mark.parametrize("level,fire,smoke", [("low", .60, .65), ("normal", .45, .50), ("high", .35, .40)])
def test_sensitivity_sets_detector_thresholds(fakes: None, src: pathlib.Path, tmp_path: pathlib.Path,
                                              level: str, fire: float, smoke: float) -> None:
    run(src, tmp_path, "--sensitivity", level)
    assert Clock.conf == {"fire": fire, "smoke": smoke}


def test_static_flame_picture_gives_no_alarm(spy: None, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    """Dedektör her karede yüksek skor verir ama kutunun içi hiç değişmez (resim/lamba): alarm yok."""
    monkeypatch.setattr(video, "FireDetector", fake_detector({"fire": (0.0, 99.0)}))
    path = make_video(tmp_path / "lamba.mp4", (99.0, 99.0))
    s, _ = run(path, tmp_path)
    assert s["count"] == 0


def test_analysis_rate_is_capped_at_five_fps(fakes: None, src: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """10 fps dosya canlıdaki gibi en çok 5 kare/sn analiz edilir (100 kare → ~50 dedektör çağrısı)."""
    run(src, tmp_path)
    assert 48 <= Clock.calls <= 52


def test_marked_video_is_written_with_every_frame(fakes: None, src: pathlib.Path, tmp_path: pathlib.Path) -> None:
    out = tmp_path / "o"
    assert video.main([str(src), "--out", str(out), "--preset", "fire"]) == 0
    cap = cv2.VideoCapture(str(out / "isaretli.mp4"))
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == int(FPS * SECONDS)
    cap.release()


def test_end_option_closes_open_alarm_at_range_end(spy: None, monkeypatch: pytest.MonkeyPatch,
                                                   tmp_path: pathlib.Path) -> None:
    monkeypatch.setattr(video, "FireDetector", fake_detector({"fire": (2.0, 99.0)}))
    path = make_video(tmp_path / "s.mp4", (2.0, 99.0))
    s, _ = run(path, tmp_path, "--end", "6.5")
    assert s["alarms"][0]["endS"] == pytest.approx(6.5, abs=0.25)
    assert s["range"] == [0.0, 6.5]


def test_alarm_still_active_at_video_end_ends_at_video_end(spy: None, monkeypatch: pytest.MonkeyPatch,
                                                           tmp_path: pathlib.Path) -> None:
    monkeypatch.setattr(video, "FireDetector", fake_detector({"fire": (2.0, 99.0)}))
    path = make_video(tmp_path / "s.mp4", (2.0, 99.0))
    s, _ = run(path, tmp_path)
    assert s["alarms"][0]["endS"] == pytest.approx(10.0, abs=0.25)


def test_image_cap_and_list_cap_keep_true_count(spy: None, monkeypatch: pytest.MonkeyPatch,
                                                tmp_path: pathlib.Path) -> None:
    monkeypatch.setattr(video, "MAX_ALARM_IMAGES", 1)
    monkeypatch.setattr(video, "MAX_ALARMS", 1)
    monkeypatch.setattr(video, "FireDetector", fake_detector({"fire": (1.0, 9.0), "smoke": (1.0, 9.0)}))
    path = make_video(tmp_path / "s.mp4", (1.0, 9.0))
    s, out = run(path, tmp_path, "--smoke", "5")
    assert s["count"] == 2 and len(s["alarms"]) == 1 and s["alarms"][0]["image"] == "alarm-1.jpg"
    assert len(list(out.glob("alarm-*.jpg"))) == 1
    rows = list(csv.reader((out / "alarmlar.csv").open(encoding="utf-8"), delimiter=";"))
    assert len(rows) == 2


def test_missing_model_fails_with_turkish_message(src: pathlib.Path, tmp_path: pathlib.Path,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    """Model dosyası yok (testte indirme yasak): çıkış kodu 1 ve son satır Türkçe ileti (iş `failed` olur)."""
    code = video.main([str(src), "--out", str(tmp_path / "o"), "--no-video", "--preset", "fire"])
    cap = capsys.readouterr()
    assert code == 1
    lines = [ln for ln in (cap.out + cap.err).splitlines() if ln.strip()]
    assert lines[-1] == "Yangın/duman modeli kurulu değil."


@pytest.mark.parametrize("args", [["--fire", "1.9"], ["--fire", "11"], ["--smoke", "4"], ["--smoke", "31"],
                                  ["--sensitivity", "max"]])
def test_out_of_range_options_are_usage_errors(src: pathlib.Path, tmp_path: pathlib.Path, args: list[str]) -> None:
    with pytest.raises(SystemExit) as e:
        video.main([str(src), "--out", str(tmp_path / "o"), "--preset", "fire", *args])
    assert e.value.code == 2 and not (tmp_path / "o").exists()


def test_both_rules_off_is_a_usage_error(src: pathlib.Path, tmp_path: pathlib.Path,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as e:
        video.main([str(src), "--out", str(tmp_path / "o"), "--preset", "fire", "--no-fire", "--no-smoke"])
    assert e.value.code == 2 and "En az bir kural açık olmalı." in capsys.readouterr().err
    assert not (tmp_path / "o").exists()


@pytest.mark.parametrize("args", [["--truth", "3"], ["--direction", "down"], ["--line", "0.5"], ["--roi", "0,0,1,1"],
                                  ["--mode", "blob"], ["--classes", "people"], ["--anchor", "bottom"],
                                  ["--threshold", "20"]])
def test_counting_options_on_fire_are_refused(src: pathlib.Path, tmp_path: pathlib.Path,
                                              capsys: pytest.CaptureFixture[str], args: list[str]) -> None:
    with pytest.raises(SystemExit) as e:
        video.main([str(src), "--out", str(tmp_path / "o"), "--preset", "fire", *args])
    assert e.value.code == 2
    assert "Yangın/duman analizi sayım seçenekleriyle birlikte kullanılamaz." in capsys.readouterr().err
    assert not (tmp_path / "o").exists()


@pytest.mark.parametrize("preset,args", [("people", ["--no-fire"]), ("generic", ["--smoke", "6"]),
                                         ("safety", ["--sensitivity", "high"]), ("generic", ["--fire", "4"])])
def test_fire_rules_outside_fire_preset_are_refused(src: pathlib.Path, tmp_path: pathlib.Path,
                                                    capsys: pytest.CaptureFixture[str], preset: str,
                                                    args: list[str]) -> None:
    with pytest.raises(SystemExit) as e:
        video.main([str(src), "--out", str(tmp_path / "o"), "--preset", preset, *args])
    assert e.value.code == 2
    assert "Yangın/duman kuralları yalnız yangın/duman analizinde geçerlidir." in capsys.readouterr().err
    assert not (tmp_path / "o").exists()


def test_safety_rules_on_fire_preset_are_refused(src: pathlib.Path, tmp_path: pathlib.Path,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as e:
        video.main([str(src), "--out", str(tmp_path / "o"), "--preset", "fire", "--no-lying"])
    assert e.value.code == 2 and "yalnızca güvenlik alarmı videosunda" in capsys.readouterr().err


def test_profile_file_on_fire_preset_is_refused(src: pathlib.Path, tmp_path: pathlib.Path,
                                                capsys: pytest.CaptureFixture[str]) -> None:
    prof = tmp_path / "p.json"
    prof.write_text(json.dumps({"countMode": "blob"}), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        video.main([str(src), "--out", str(tmp_path / "o"), "--preset", "fire", "--profile", str(prof)])
    assert e.value.code == 2 and "profil dosyası kullanılmaz" in capsys.readouterr().err
    assert not (tmp_path / "o").exists()
