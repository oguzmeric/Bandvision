from __future__ import annotations

import importlib.util
import json
import pathlib
import types
from typing import Any

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CLIP = ROOT / "apps" / "ios" / "BantSayacUITests" / "ui_test_clip.mp4"

spec = importlib.util.spec_from_file_location("eval_pose", pathlib.Path(__file__).resolve().parents[1] / "eval_pose.py")
ev = importlib.util.module_from_spec(spec)                      # type: ignore[arg-type]
spec.loader.exec_module(ev)                                     # type: ignore[union-attr]

# Profil/video testleri edge bağımlılıkları (numpy, OpenCV) ister: CI'da edge-core işinde koşar, contracts işinde atlanır
needs_edge = pytest.mark.skipif(importlib.util.find_spec("cv2") is None, reason="edge bağımlılıkları yok")


def test_match_pose_window_type_and_false_alarms() -> None:
    labels = [{"t": 10.0, "type": "hands_up"}, {"t": 40.0, "type": "lying"}, {"t": 80.0, "type": "hands_up"}]
    alarms = [(13.2, "hands_up"), (51.0, "lying"), (95.0, "hands_up"), (200.0, "lying")]
    r = ev.match_pose(labels, alarms, {"hands_up": 3.0, "lying": 10.0})
    assert r["hands_up"] == {"labels": 2, "caught": 1}           # 95 > 80 + 3 + 2: geç
    assert r["lying"] == {"labels": 1, "caught": 1}
    assert r["false"] == 2                                       # 95 (geç) ve 200 (etiketsiz)


def test_match_pose_window_bounds_are_inclusive() -> None:
    sec = {"hands_up": 3.0, "lying": 10.0}
    on_time = ev.match_pose([{"t": 10.0, "type": "hands_up"}], [(15.0, "hands_up")], sec)        # t + 3 + 2 tam sınır
    assert on_time["hands_up"]["caught"] == 1 and on_time["false"] == 0
    early = ev.match_pose([{"t": 10.0, "type": "hands_up"}], [(9.9, "hands_up")], sec)           # olaydan önce: eşleşmez
    assert early["hands_up"]["caught"] == 0 and early["false"] == 1
    at_start = ev.match_pose([{"t": 10.0, "type": "lying"}], [(10.0, "lying")], sec)
    assert at_start["lying"]["caught"] == 1


def test_match_pose_one_alarm_serves_one_label_and_type_must_match() -> None:
    sec = {"hands_up": 3.0, "lying": 10.0}
    labels = [{"t": 10.0, "type": "hands_up"}, {"t": 11.0, "type": "hands_up"}]
    r = ev.match_pose(labels, [(12.0, "hands_up")], sec)
    assert r["hands_up"] == {"labels": 2, "caught": 1} and r["false"] == 0       # tek alarm tek etiketi yakalar
    wrong_type = ev.match_pose([{"t": 10.0, "type": "lying"}], [(12.0, "hands_up")], sec)
    assert wrong_type["lying"] == {"labels": 1, "caught": 0} and wrong_type["false"] == 1


def test_match_pose_does_not_depend_on_alarm_order() -> None:
    sec = {"hands_up": 3.0, "lying": 10.0}
    labels = [{"t": 10.0, "type": "hands_up"}, {"t": 12.0, "type": "hands_up"}]
    for alarms in ([(13.0, "hands_up"), (16.5, "hands_up")], [(16.5, "hands_up"), (13.0, "hands_up")]):
        r = ev.match_pose(labels, alarms, sec)
        assert r["hands_up"] == {"labels": 2, "caught": 2} and r["false"] == 0


def write(tmp: pathlib.Path, name: str, data: Any) -> str:
    p = tmp / name
    p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return str(p)


@pytest.mark.parametrize("labels", [
    [{"t": 5.0, "type": "running"}],                              # bilinmeyen tür
    [{"t": 5.0, "type": "hands_up"}, {"t": 9.0, "type": "Lying"}],
    [{"t": 5.0}],                                                 # tür yok
    [{"type": "lying"}],                                          # zaman yok
    [{"t": "5", "type": "lying"}],                                # zaman sayı değil
    [{"t": True, "type": "lying"}],
    [{"t": -1.0, "type": "lying"}],
    [{"t": float("nan"), "type": "lying"}],
    [{"t": 1.0, "type": ["lying"]}],                              # tür metin değil (hash'lenemez)
    ["hands_up"],                                                 # kayıt nesne değil
    {"t": 5.0, "type": "lying"},                                  # liste değil
    "not json {",                                                 # JSON değil
])
def test_main_rejects_bad_labels_in_turkish_with_exit_2(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str],
                                                         labels: Any) -> None:
    lp = write(tmp_path, "l.json", labels)
    assert ev.main(["yok.mp4", "--profile", str(tmp_path / "p.json"), "--labels", lp]) == 2
    err = capsys.readouterr().err
    assert err.startswith("HATA: Etiket dosyası")
    assert "KeyError" not in err and "Traceback" not in err


def test_main_rejects_missing_labels_file(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert ev.main(["yok.mp4", "--profile", str(tmp_path / "p.json"), "--labels", str(tmp_path / "yok.json")]) == 2
    assert "Etiket dosyası okunamadı" in capsys.readouterr().err


@needs_edge
def test_main_rejects_non_safety_or_bad_profile_and_missing_video(tmp_path: pathlib.Path,
                                                                    capsys: pytest.CaptureFixture[str]) -> None:
    from bantvision.core import Profile

    labels = write(tmp_path, "l.json", [{"t": 5.0, "type": "lying"}])
    people = write(tmp_path, "p.json", Profile.people().to_dict())              # güvenlik yöntemi değil
    assert ev.main([str(tmp_path / "yok.mp4"), "--profile", people, "--labels", labels]) == 2
    assert "güvenlik (safety)" in capsys.readouterr().err
    assert ev.main([str(tmp_path / "yok.mp4"), "--profile", str(tmp_path / "yok.json"), "--labels", labels]) == 2
    assert "Profil dosyası okunamadı" in capsys.readouterr().err
    view = write(tmp_path, "s.json", {"id": "x", "profile": Profile.jeweler().to_dict()})   # GET /sessions/{id} yanıtı
    assert ev.load_profile(view).countMode == "safety"
    assert ev.main([str(tmp_path / "yok.mp4"), "--profile", view, "--labels", labels]) == 2
    assert "Video açılamadı" in capsys.readouterr().err


@needs_edge
def test_run_collects_alarms_hours_and_seconds_and_releases(monkeypatch: pytest.MonkeyPatch) -> None:
    import cv2

    import bantvision.core
    from bantvision.core import Profile

    seen: list[float] = []

    class FakePipeline:
        def __init__(self, _p: Any) -> None:
            pass

        def process(self, _frame: Any, ts: float) -> Any:
            seen.append(ts)
            fired = [types.SimpleNamespace(ts=ts, kind="lying")] if len(seen) == 2 else []
            return types.SimpleNamespace(safety=types.SimpleNamespace(fired=fired))

    released: list[bool] = []
    real = cv2.VideoCapture

    class Cap:
        def __init__(self, path: str) -> None:
            self._c = real(path)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._c, name)

        def release(self) -> None:
            released.append(True)
            self._c.release()

    monkeypatch.setattr(bantvision.core, "Pipeline", FakePipeline)
    monkeypatch.setattr(cv2, "VideoCapture", Cap)
    p = Profile.jeweler()
    p.safety.handsUp.seconds, p.safety.lying.seconds = 4.0, 12.0
    alarms, hours, seconds = ev.run(str(CLIP), p, every=3)
    c = real(str(CLIP))
    fps, n = c.get(cv2.CAP_PROP_FPS), 0
    while c.read()[0]:
        n += 1
    c.release()
    assert len(seen) == (n + 2) // 3 and seen[:3] == pytest.approx([0.0, 3 / fps, 6 / fps])     # her 3. kare, video zamanı
    assert alarms == [(seen[1], "lying")]
    assert hours == pytest.approx(n / fps / 3600)                  # süre atlanan kareler dahil tüm videodan
    assert seconds == {"hands_up": 4.0, "lying": 12.0} and released == [True]
