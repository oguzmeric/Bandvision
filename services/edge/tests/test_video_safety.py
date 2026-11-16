"""Video aracı güvenlik modu (bantvision.video --preset safety): canlıdaki SafetyAnalyzer aynen, video zamanıyla.

Modeller sahtedir (indirme yok). Sahte poz, hangi karede olduğunu `read_frames` casusundan öğrenir: sıkıştırılmış videodan
kare numarası okunamaz, ama aracın verdiği kare zamanı tam olarak bilinir.
"""
from __future__ import annotations

import csv
import json
import pathlib
from types import SimpleNamespace
from typing import Any

import cv2
import numpy as np
import pytest
from fakes_safety import FakePhoneDetector, hands_up_kp, phone_kp

from bantvision import video
from bantvision.core import devices

FPS = 10.0
SECONDS = 10
W, H = 640, 480
PERSON = (280.0, 80.0, 360.0, 440.0)


class Clock:
    """`read_frames` her kareyi verirken zamanı buraya yazar; sahte poz buradan okur."""
    t = 0.0


class OnePerson:
    used = devices.Used("gpu", "gpu-10de-28a1", "NVIDIA Laptop GPU", None)

    def __init__(self, path: Any = None, device: str | None = None) -> None:
        pass

    def detect(self, _crop: np.ndarray, _classes: object, conf: float = 0.15, iou: float = 0.45) -> list[object]:
        return [SimpleNamespace(x1=PERSON[0], y1=PERSON[1], x2=PERSON[2], y2=PERSON[3], score=0.9)]


def standing_kp() -> np.ndarray:
    kp = hands_up_kp()
    kp[[9, 10], 1] = 300                                               # bilekler kalçaya yakın: eller aşağıda
    return kp


def pose_for(up: tuple[float, float]) -> type:
    """[up[0], up[1]) sn arası eller yukarı, dışında ayakta duran poz döndüren sahte modelin sınıfı."""
    class Pose:
        def __init__(self, path: Any = None, device: str | None = None) -> None:
            pass

        def estimate(self, _bgr: np.ndarray, _box: object) -> np.ndarray:
            return hands_up_kp() if up[0] <= Clock.t < up[1] else standing_kp()

    return Pose


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    orig = video.read_frames

    def spy(info: Any, start: float = 0.0, end: float | None = None, step: int = 1) -> Any:
        for k, t, f in orig(info, start, end, step):
            Clock.t = t
            yield k, t, f

    monkeypatch.setattr(video, "read_frames", spy)
    monkeypatch.setattr(video, "ObjectDetector", OnePerson)
    monkeypatch.setattr(video, "PoseEstimator", pose_for((2.0, 6.0)))


@pytest.fixture
def src(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / "guvenlik.mp4"
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for _ in range(int(FPS * SECONDS)):
        w.write(np.full((H, W, 3), 40, np.uint8))
    w.release()
    return path


def run(src: pathlib.Path, tmp_path: pathlib.Path, *extra: str) -> tuple[dict[str, Any], pathlib.Path]:
    out = tmp_path / "o"
    assert video.main([str(src), "--out", str(out), "--no-video", "--preset", "safety", *extra]) == 0
    return json.loads((out / "ozet.json").read_text(encoding="utf-8")), out


def test_hands_up_alarm_fires_at_rule_seconds_with_image(fakes: None, src: pathlib.Path,
                                                         tmp_path: pathlib.Path) -> None:
    s, out = run(src, tmp_path)
    assert s["count"] == 1 and len(s["alarms"]) == 1
    a = s["alarms"][0]
    assert a["kind"] == "handsUp" and isinstance(a["trackId"], int)
    assert a["startS"] == pytest.approx(2.0, abs=0.15)
    assert a["atS"] == pytest.approx(5.0, abs=0.15)                    # 3 sn kuralı: başlangıç + 3
    assert 5.9 <= a["endS"] <= 6.5                                     # eller 6 sn'de indi
    assert a["image"] == "alarm-1.jpg"
    img = cv2.imread(str(out / "alarm-1.jpg"))
    assert img is not None and img.shape[1] == 640
    raw = (out / "alarm-1.jpg").read_bytes()
    assert raw[:2] == b"\xff\xd8" and raw[-2:] == b"\xff\xd9"          # geçerli JPEG
    assert s["calibration"]["countMode"] == "safety"
    assert s["fps"] == FPS and s["size"] == [W, H] and s["processingFps"]


def test_alarm_time_is_video_time_not_processing_time(fakes: None, src: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """Aynı video iki kez işlenince alarm zamanları aynı: zaman kare numarası / fps'tir, saat değil."""
    a1 = run(src, tmp_path)[0]["alarms"]
    (tmp_path / "o" / "ozet.json").unlink()
    assert run(src, tmp_path)[0]["alarms"] == a1


def test_no_hands_up_gives_no_alarms(fakes: None, src: pathlib.Path, tmp_path: pathlib.Path) -> None:
    s, out = run(src, tmp_path, "--no-hands-up")
    assert s["count"] == 0 and s["alarms"] == []
    assert not list(out.glob("alarm-*.jpg"))


def test_hands_up_seconds_option_moves_the_alarm(fakes: None, monkeypatch: pytest.MonkeyPatch,
                                                 src: pathlib.Path, tmp_path: pathlib.Path) -> None:
    monkeypatch.setattr(video, "PoseEstimator", pose_for((2.0, 7.0)))
    s, _ = run(src, tmp_path, "--hands-up", "4")
    assert s["alarms"][0]["atS"] == pytest.approx(6.0, abs=0.15)       # başlangıç 2,0 + 4 sn
    s, _ = run(src, tmp_path, "--hands-up", "5")
    assert s["count"] == 0                                             # 5 sn dolmadan (6,9) eller iner


@pytest.mark.parametrize("args", [["--hands-up", "6"], ["--hands-up", "2.9"], ["--lying", "4"], ["--lying", "31"]])
def test_out_of_range_seconds_is_a_usage_error(src: pathlib.Path, tmp_path: pathlib.Path,
                                               capsys: pytest.CaptureFixture[str], args: list[str]) -> None:
    with pytest.raises(SystemExit) as e:
        video.main([str(src), "--out", str(tmp_path / "o"), "--preset", "safety", *args])
    assert e.value.code == 2
    assert "sn" in capsys.readouterr().err


def test_both_rules_off_is_a_usage_error(src: pathlib.Path, tmp_path: pathlib.Path,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as e:
        video.main([str(src), "--out", str(tmp_path / "o"), "--preset", "safety", "--no-hands-up", "--no-lying"])
    assert e.value.code == 2
    assert "En az bir kural açık olmalı." in capsys.readouterr().err


def test_rule_options_on_a_counting_preset_are_refused(src: pathlib.Path, tmp_path: pathlib.Path,
                                                       capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as e:
        video.main([str(src), "--out", str(tmp_path / "o"), "--preset", "people", "--no-lying"])
    assert e.value.code == 2
    assert "yalnızca güvenlik alarmı videosunda" in capsys.readouterr().err


@pytest.mark.parametrize("args", [["--truth", "3"], ["--truth-out", "1"], ["--direction", "down"], ["--line", "0.5"],
                                  ["--count-line", "0,0,1,1"], ["--roi", "0,0,1,1"],
                                  ["--roi-polygon", "0,0;1,0;1,1"], ["--bg-range", "0,1"],
                                  ["--product-length", "0.2"], ["--anchor", "bottom"],
                                  ["--expected-area", "0.01"], ["--threshold", "20"], ["--bg-percentile", "15"]])
def test_counting_options_on_safety_are_refused_without_leaving_output(
        src: pathlib.Path, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], args: list[str]) -> None:
    out = tmp_path / "o"
    with pytest.raises(SystemExit) as e:
        video.main([str(src), "--out", str(out), "--preset", "safety", *args])
    assert e.value.code == 2
    assert "Güvenlik alarmı videosunda sayım ayarları kullanılmaz." in capsys.readouterr().err
    assert not out.exists()                                            # reddedilen koşu boş klasör bırakmaz


def test_classes_on_safety_is_refused_without_leaving_output(src: pathlib.Path, tmp_path: pathlib.Path,
                                                             capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "o"
    with pytest.raises(SystemExit) as e:
        video.main([str(src), "--out", str(out), "--preset", "safety", "--classes", "people"])
    assert e.value.code == 2
    assert "Güvenlik alarmı videosunda sayım ayarları kullanılmaz." in capsys.readouterr().err
    assert not out.exists()


@pytest.mark.parametrize("count_mode", ["blob", "linescan", "detect", "safety"])
def test_profile_file_on_safety_preset_is_refused_without_leaving_output(
        src: pathlib.Path, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], count_mode: str) -> None:
    """Sayım profili dosyası güvenlik koşusunu sessizce sayıma çevirirdi: `--preset safety` ile profil dosyası reddedilir."""
    prof = tmp_path / "p.json"
    prof.write_text(json.dumps({"countMode": count_mode}), encoding="utf-8")
    out = tmp_path / "o"
    with pytest.raises(SystemExit) as e:
        video.main([str(src), "--out", str(out), "--preset", "safety", "--profile", str(prof)])
    assert e.value.code == 2
    assert "Güvenlik alarmı videosunda profil dosyası kullanılmaz." in capsys.readouterr().err
    assert not out.exists()


def test_missing_profile_file_on_safety_preset_is_refused_not_a_traceback(
        src: pathlib.Path, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as e:
        video.main([str(src), "--out", str(tmp_path / "o"), "--preset", "safety", "--profile", str(tmp_path / "yok.json")])
    assert e.value.code == 2
    assert "profil dosyası kullanılmaz" in capsys.readouterr().err


@pytest.mark.parametrize("mode", ["blob", "linescan", "detect"])
def test_mode_on_safety_is_refused_without_leaving_output(src: pathlib.Path, tmp_path: pathlib.Path,
                                                          capsys: pytest.CaptureFixture[str], mode: str) -> None:
    """`--mode` profili ezerdi (blob sayımı güvenlik adıyla çalışırdı): reddedilir."""
    out = tmp_path / "o"
    with pytest.raises(SystemExit) as e:
        video.main([str(src), "--out", str(out), "--preset", "safety", "--mode", mode])
    assert e.value.code == 2
    assert "Güvenlik alarmı videosunda sayım ayarları kullanılmaz." in capsys.readouterr().err
    assert not out.exists()


def test_refused_rule_options_leave_no_output_folder(src: pathlib.Path, tmp_path: pathlib.Path) -> None:
    out = tmp_path / "o"
    for argv in (["--preset", "people", "--no-lying"], ["--preset", "safety", "--no-hands-up", "--no-lying"]):
        with pytest.raises(SystemExit):
            video.main([str(src), "--out", str(out), *argv])
    assert not out.exists()


@pytest.mark.parametrize("args", [["--conf", "0.5"], ["--rotation", "0"], ["--width", "480"]])
def test_conf_rotation_width_stay_allowed_on_safety(fakes: None, src: pathlib.Path, tmp_path: pathlib.Path,
                                                    args: list[str]) -> None:
    s, _ = run(src, tmp_path, *args)
    assert s["count"] == 1


def test_alarm_still_active_at_video_end_ends_at_video_end(fakes: None, monkeypatch: pytest.MonkeyPatch,
                                                           src: pathlib.Path, tmp_path: pathlib.Path) -> None:
    monkeypatch.setattr(video, "PoseEstimator", pose_for((2.0, 99.0)))
    s, _ = run(src, tmp_path)
    assert s["count"] == 1
    assert s["alarms"][0]["endS"] == pytest.approx(10.0, abs=0.05)     # null değil, video sonu


def test_pose_ending_within_grace_before_video_end_keeps_its_own_end(
        fakes: None, monkeypatch: pytest.MonkeyPatch, src: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """Eller 8,5'te iner ama 3 sn tolerans video sonundan sonra dolar: bitiş video sonu (10,0) değil 8,5."""
    monkeypatch.setattr(video, "PoseEstimator", pose_for((2.0, 8.5)))
    s, _ = run(src, tmp_path)
    assert s["count"] == 1
    assert s["alarms"][0]["endS"] == pytest.approx(8.5, abs=0.05)


def test_two_episodes_on_one_track_get_their_own_ends(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Aynı izde [1,5) ve [9,13) sn: iki alarm, bitişler 5,0 ve 13,0 (ilk bölüm toleransla biter, ikincisi karışmaz)."""
    path = tmp_path / "uzun.mp4"
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for _ in range(int(FPS * 20)):
        w.write(np.full((H, W, 3), 40, np.uint8))
    w.release()
    orig = video.read_frames

    def spy(info: Any, start: float = 0.0, end: float | None = None, step: int = 1) -> Any:
        for k, t, f in orig(info, start, end, step):
            Clock.t = t
            yield k, t, f

    class TwoEpisodes:
        def __init__(self, path: Any = None, device: str | None = None) -> None:
            pass

        def estimate(self, _bgr: np.ndarray, _box: object) -> np.ndarray:
            up = 1.0 <= Clock.t < 5.0 or 9.0 <= Clock.t < 13.0
            return hands_up_kp() if up else standing_kp()

    monkeypatch.setattr(video, "read_frames", spy)
    monkeypatch.setattr(video, "ObjectDetector", OnePerson)
    monkeypatch.setattr(video, "PoseEstimator", TwoEpisodes)
    s, _ = run(path, tmp_path)
    assert s["count"] == 2
    a, b = s["alarms"]
    assert a["trackId"] == b["trackId"]
    assert a["startS"] == pytest.approx(1.0, abs=0.15) and a["endS"] == pytest.approx(5.0, abs=0.05)
    assert b["startS"] == pytest.approx(9.0, abs=0.15) and b["endS"] == pytest.approx(13.0, abs=0.05)


def test_end_option_closes_open_alarm_at_range_end(fakes: None, monkeypatch: pytest.MonkeyPatch,
                                                   src: pathlib.Path, tmp_path: pathlib.Path) -> None:
    monkeypatch.setattr(video, "PoseEstimator", pose_for((2.0, 99.0)))
    s, _ = run(src, tmp_path, "--end", "6.5")
    assert s["alarms"][0]["endS"] == pytest.approx(6.5, abs=0.05)
    assert s["range"] == [0.0, 6.5]


def test_start_option_uses_video_time(fakes: None, monkeypatch: pytest.MonkeyPatch,
                                      src: pathlib.Path, tmp_path: pathlib.Path) -> None:
    monkeypatch.setattr(video, "PoseEstimator", pose_for((0.0, 99.0)))
    s, _ = run(src, tmp_path, "--start", "4")
    a = s["alarms"][0]
    assert a["startS"] == pytest.approx(4.0, abs=0.35)                 # video zamanı: 0'dan değil 4. sn'den
    assert a["atS"] == pytest.approx(a["startS"] + 3.0, abs=0.15)


def grid_people(n: int) -> type:
    cols = 10
    boxes = [(c * 64 + 8.0, r * 80 + 8.0, c * 64 + 56.0, r * 80 + 72.0)
             for r in range((n + cols - 1) // cols) for c in range(cols)][:n]

    class Many(OnePerson):
        def detect(self, _crop: np.ndarray, _classes: object, conf: float = 0.15, iou: float = 0.45) -> list[object]:
            return [SimpleNamespace(x1=b[0], y1=b[1], x2=b[2], y2=b[3], score=0.9) for b in boxes]

    return Many


def test_image_cap_is_50_and_rest_listed_without_image(fakes: None, monkeypatch: pytest.MonkeyPatch,
                                                       src: pathlib.Path, tmp_path: pathlib.Path) -> None:
    monkeypatch.setattr(video, "ObjectDetector", grid_people(60))
    s, out = run(src, tmp_path)
    assert s["count"] == 60 and len(s["alarms"]) == 60
    assert len(list(out.glob("alarm-*.jpg"))) == 50
    with_image = [a["image"] for a in s["alarms"] if a["image"]]
    assert len(with_image) == 50 and len(set(with_image)) == 50
    assert all(a["image"] is None for a in s["alarms"][50:])
    assert s["alarms"][49]["image"] == "alarm-50.jpg" and not (out / "alarm-51.jpg").exists()


def test_list_cap_keeps_true_count(fakes: None, monkeypatch: pytest.MonkeyPatch, src: pathlib.Path,
                                   tmp_path: pathlib.Path) -> None:
    monkeypatch.setattr(video, "MAX_ALARM_IMAGES", 3)
    monkeypatch.setattr(video, "MAX_ALARMS", 7)
    monkeypatch.setattr(video, "ObjectDetector", grid_people(12))
    s, out = run(src, tmp_path)
    assert s["count"] == 12 and len(s["alarms"]) == 7
    assert [a["image"] for a in s["alarms"]] == ["alarm-1.jpg", "alarm-2.jpg", "alarm-3.jpg", None, None, None, None]
    assert len(list(out.glob("alarm-*.jpg"))) == 3
    rows = list(csv.reader((out / "alarmlar.csv").open(encoding="utf-8"), delimiter=";"))
    assert len(rows) == 1 + 7                                          # başlık + listedeki alarmlar
    assert all(a["endS"] is not None for a in s["alarms"])             # sınır aşılsa da biten alarm kapanır


def test_csv_and_outputs(fakes: None, src: pathlib.Path, tmp_path: pathlib.Path) -> None:
    s, out = run(src, tmp_path)
    assert not (out / "sayimlar.csv").exists()
    rows = list(csv.reader((out / "alarmlar.csv").open(encoding="utf-8"), delimiter=";"))
    assert rows[0] == ["baslangic_sn", "alarm_sn", "bitis_sn", "tur", "iz"]
    a = s["alarms"][0]
    assert rows[1] == [str(a["startS"]), str(a["atS"]), str(a["endS"]), "Eller yukarı", str(a["trackId"])]
    assert (out / "profil.json").exists()
    assert json.loads((out / "profil.json").read_text(encoding="utf-8"))["countMode"] == "safety"


def test_empty_video_writes_header_only_csv(fakes: None, src: pathlib.Path, tmp_path: pathlib.Path) -> None:
    _, out = run(src, tmp_path, "--no-hands-up")
    rows = list(csv.reader((out / "alarmlar.csv").open(encoding="utf-8"), delimiter=";"))
    assert len(rows) == 1


def test_device_is_the_detectors_used(fakes: None, src: pathlib.Path, tmp_path: pathlib.Path) -> None:
    s, _ = run(src, tmp_path)
    assert s["device"] == {"kind": "gpu", "name": "NVIDIA Laptop GPU", "note": None}


def test_marked_video_and_progress_json(fakes: None, src: pathlib.Path, tmp_path: pathlib.Path,
                                        capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "o"
    assert video.main([str(src), "--out", str(out), "--preset", "safety", "--progress-json"]) == 0
    marked = cv2.VideoCapture(str(out / "isaretli.mp4"))
    assert marked.isOpened() and int(marked.get(cv2.CAP_PROP_FRAME_COUNT)) == int(FPS * SECONDS)
    marked.release()
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    prog = [x for x in lines if "progress" in x]
    assert prog and prog[-1] == {"progress": 1.0, "count": 1}
    assert [x["stage"] for x in lines if "stage" in x] == ["calibrating", "counting"]


# ---- telefon kullanımı -----------------------------------------------------------------------------------------

PHONE_NEAR_WRIST = (16.0, 242.0, 36.0, 262.0, 0.4)   # kırpıntıya göre; phone_kp sol bileğinin (290, 260) yanı (test_safety.py ile aynı)


def install_phone_fakes(monkeypatch: pytest.MonkeyPatch, until: float = float("inf")) -> None:
    """Kişi 2 sn'den (`until`'e dek) bileğinin yanında telefon tutuyor; poz ayakta, eller göğüste (eller yukarı/yatma
    değil)."""
    orig = video.read_frames

    def spy(info: Any, start: float = 0.0, end: float | None = None, step: int = 1) -> Any:
        for k, t, f in orig(info, start, end, step):
            Clock.t = t
            yield k, t, f

    class Detector(FakePhoneDetector):
        used = devices.Used("cpu", "cpu", "CPU", None)

        def __init__(self, path: Any = None, device: str | None = None) -> None:
            super().__init__([PERSON])

        def detect(self, crop: np.ndarray, classes: list[str], conf: float = 0.15, iou: float = 0.45) -> list[object]:
            self.phones = [PHONE_NEAR_WRIST] if 2.0 <= Clock.t < until else []
            return super().detect(crop, classes, conf)

    class Pose:
        def __init__(self, path: Any = None, device: str | None = None) -> None:
            pass

        def estimate(self, _bgr: np.ndarray, _box: object) -> np.ndarray:
            return phone_kp()

    monkeypatch.setattr(video, "read_frames", spy)
    monkeypatch.setattr(video, "ObjectDetector", Detector)
    monkeypatch.setattr(video, "PoseEstimator", Pose)


@pytest.fixture
def phone_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    install_phone_fakes(monkeypatch)


def make_video(path: pathlib.Path, seconds: float) -> pathlib.Path:
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for _ in range(int(FPS * seconds)):
        w.write(np.full((H, W, 3), 40, np.uint8))
    w.release()
    return path


def test_phone_alarm_ends_at_last_sighting_not_end_s_later(monkeypatch: pytest.MonkeyPatch,
                                                           tmp_path: pathlib.Path) -> None:
    """Telefon 2–10 sn görünür, 40 sn video, kural 10 sn: bitiş son isabette (± bir arama aralığı), PHONE_END_S (15 sn)
    sonra değil; başlangıç ilk isabet."""
    install_phone_fakes(monkeypatch, until=10.0)
    s, _ = run(make_video(tmp_path / "kirk.mp4", 40), tmp_path, "--no-hands-up", "--no-lying", "--phone", "10")
    assert s["count"] == 1
    a = s["alarms"][0]
    assert a["startS"] == pytest.approx(2.0, abs=0.7)
    assert a["endS"] == pytest.approx(10.0, abs=0.6)


def test_phone_alone_is_accepted_and_alarm_in_csv_and_summary(phone_fakes: None, tmp_path: pathlib.Path) -> None:
    src = tmp_path / "uzun.mp4"                                       # kural en az 10 sn: 10 sn'lik ortak video yetmez
    w = cv2.VideoWriter(str(src), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for _ in range(int(FPS * 20)):
        w.write(np.full((H, W, 3), 40, np.uint8))
    w.release()
    s, out = run(src, tmp_path, "--no-hands-up", "--no-lying", "--phone", "10")
    assert s["count"] == 1 and [a["kind"] for a in s["alarms"]] == ["phone"]
    a = s["alarms"][0]
    assert a["startS"] == pytest.approx(2.0, abs=0.7) and 6.0 <= a["atS"] - a["startS"] <= 10.0   # dilimli kanıt: pencere dolmadan
    assert a["image"] == "alarm-1.jpg"
    rows = list(csv.reader((out / "alarmlar.csv").open(encoding="utf-8"), delimiter=";"))
    assert rows[1][3] == "Telefon kullanımı"


def test_phone_is_off_by_default(phone_fakes: None, src: pathlib.Path, tmp_path: pathlib.Path) -> None:
    s, _ = run(src, tmp_path)                                         # eller yukarı + yatma açık, telefon kapalı
    assert s["count"] == 0 and s["alarms"] == []


def test_no_rule_on_when_phone_is_default_off(src: pathlib.Path, tmp_path: pathlib.Path,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as e:
        video.main([str(src), "--out", str(tmp_path / "o"), "--preset", "safety", "--no-hands-up", "--no-lying"])
    assert e.value.code == 2 and "En az bir kural açık olmalı." in capsys.readouterr().err
    assert not (tmp_path / "o").exists()


def test_phone_rule_on_counting_preset_is_refused(src: pathlib.Path, tmp_path: pathlib.Path,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as e:
        video.main([str(src), "--out", str(tmp_path / "o"), "--preset", "people", "--phone", "30"])
    assert e.value.code == 2 and "yalnızca güvenlik alarmı" in capsys.readouterr().err


@pytest.mark.parametrize("sec", ["9", "601"])
def test_phone_seconds_out_of_range_is_a_usage_error(src: pathlib.Path, tmp_path: pathlib.Path,
                                                     capsys: pytest.CaptureFixture[str], sec: str) -> None:
    with pytest.raises(SystemExit) as e:
        video.main([str(src), "--out", str(tmp_path / "o"), "--preset", "safety", "--phone", sec])
    assert e.value.code == 2
    assert "Telefon kullanımı süresi 10–600 sn arasında bir sayı olmalı." in capsys.readouterr().err


def test_phone_flags_are_mutually_exclusive(src: pathlib.Path, tmp_path: pathlib.Path) -> None:
    with pytest.raises(SystemExit) as e:
        video.main([str(src), "--out", str(tmp_path / "o"), "--preset", "safety", "--phone", "30", "--no-phone"])
    assert e.value.code == 2


def test_summary_line_lists_enabled_rules(phone_fakes: None, src: pathlib.Path, tmp_path: pathlib.Path,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    run(src, tmp_path, "--no-lying", "--phone", "90")
    out = capsys.readouterr().out
    assert "Telefon kullanımı 90 sn" in out and "Eller yukarı 3 sn" in out and "Yerde yatma" not in out
    assert "telefon kullanımı)" in video.MODE_TR["safety"]


@pytest.mark.parametrize("cls", ["cell phone", "person,cell phone", "people,cell phone"])
def test_cell_phone_is_not_a_user_class(src: pathlib.Path, tmp_path: pathlib.Path, cls: str) -> None:
    with pytest.raises(SystemExit) as e:
        video.main([str(src), "--out", str(tmp_path / "o"), "--mode", "detect", "--classes", cls])
    msg = str(e.value)
    assert "bilinmeyen sınıf ['cell phone']" in msg and "cell phone" not in msg.split("seçenekler:")[1]
