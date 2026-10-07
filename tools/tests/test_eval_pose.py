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

# Profil/video testleri edge bağımlılıkları (numpy, OpenCV) ister: CI'da edge-core işinde (ci.yml, `test_eval_pose.py`
# açıkça listelenir) koşar, contracts işinde atlanır; geri kalanı saf Python'dur ve ikisinde de koşar
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
    # pencereler: t=10 → [10, 15], t=12 → [12, 17]. Sıralı alarmlarda 11 → t=10, 14 → t=12 (2 yakalama); sıralanmamış
    # [14, 11] verilirse ilk etiket 14'ü alır, 11 ise t=12'nin penceresinde olmadığından 1 yakalama kalırdı.
    sec = {"hands_up": 3.0, "lying": 10.0}
    labels = [{"t": 10.0, "type": "hands_up"}, {"t": 12.0, "type": "hands_up"}]
    for alarms in ([(11.0, "hands_up"), (14.0, "hands_up")], [(14.0, "hands_up"), (11.0, "hands_up")]):
        r = ev.match_pose(labels, alarms, sec)
        assert r["hands_up"] == {"labels": 2, "caught": 2} and r["false"] == 0


def result(hu: tuple[int, int], ly: tuple[int, int], false: int, hours: float) -> dict[str, Any]:
    """`match_pose` sonucu biçiminde: tür başına (etiket, yakalanan), yanlış alarm, video süresi (saat)."""
    return {"hands_up": {"labels": hu[0], "caught": hu[1]}, "lying": {"labels": ly[0], "caught": ly[1]},
            "false": false, "hours": hours}


GOOD = (20, 20)


@pytest.mark.parametrize("kind", ["hands_up", "lying"])
def test_report_capture_rate_gate_is_95_percent(capsys: pytest.CaptureFixture[str], kind: str) -> None:
    def res(caught: int, labels: int = 20) -> dict[str, Any]:
        return result((labels, caught) if kind == "hands_up" else GOOD, (labels, caught) if kind == "lying" else GOOD,
                      0, 8.0)

    assert ev.report(res(19)) is True                              # 19/20 = %95: geçer
    out = capsys.readouterr().out
    assert "%95.0 (19/20)" in out and out.splitlines()[-1] == "GEÇTİ"
    assert ev.report(res(18)) is False                             # 18/20 = %90: kalır
    out = capsys.readouterr().out
    assert "%90.0 (18/20)" in out and out.splitlines()[-1] == "KALDI"
    assert ev.report(res(19, labels=19)) is False                  # %100 ama 20'den az etiket: yeterli değil
    out = capsys.readouterr().out
    assert "(19/19) — en az 20 etiket gerekli" in out and out.splitlines()[-1] == "KALDI"


def test_report_false_alarm_rate_and_minimum_duration(capsys: pytest.CaptureFixture[str]) -> None:
    assert ev.report(result(GOOD, GOOD, 0, 0.99)) is False         # 0 yanlış alarm olsa da video 1 saatten kısa
    out = capsys.readouterr().out
    assert "yetersiz süre: video 59 dk" in out and out.splitlines()[-1] == "KALDI"
    assert ev.report(result(GOOD, GOOD, 0, 59.6 / 60)) is False
    assert "video 59 dk" in capsys.readouterr().out                # 59,6 dk "60 dk" diye yuvarlanmaz
    assert ev.report(result(GOOD, GOOD, 1, 1.0)) is False          # 1 saatte 1 yanlış alarm = 8 / 8 saat
    out = capsys.readouterr().out
    assert "(8.00 / 8 saat)" in out and out.splitlines()[-1] == "KALDI"
    assert ev.report(result(GOOD, GOOD, 1, 8.0)) is True           # 8 saatte 1 yanlış alarm: sınır, geçer
    out = capsys.readouterr().out
    assert "(1.00 / 8 saat)" in out and out.splitlines()[-1] == "GEÇTİ"
    assert ev.report(result(GOOD, GOOD, 2, 8.0)) is False          # 8 saatte 2: kalır
    assert "(2.00 / 8 saat)" in capsys.readouterr().out
    assert ev.report(result(GOOD, GOOD, 0, 1.0)) is True           # tam 1 saat ve yanlış alarm yok: yeterli süre
    assert "Yanlış alarm: 0 (0.00 / 8 saat)" in capsys.readouterr().out


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


def fake_profile(hands_up_enabled: bool = True) -> Any:
    rule = types.SimpleNamespace
    return rule(safety=rule(handsUp=rule(enabled=hands_up_enabled, seconds=3.0), lying=rule(enabled=True, seconds=10.0)))


def patch_run(monkeypatch: pytest.MonkeyPatch, alarms: list[tuple[float, str]], hours: float,
              profile: Any = None) -> list[tuple[str, int]]:
    """`load_profile` ve `run` sahtelenir: cv2, model ve video gerekmez. Dönen liste `run`'a verilen (video, every)."""
    calls: list[tuple[str, int]] = []

    def fake_run(video: str, _profile: Any, every: int = 1) -> tuple[list[tuple[float, str]], float, dict[str, float]]:
        calls.append((video, every))
        return alarms, hours, {"hands_up": 3.0, "lying": 10.0}

    monkeypatch.setattr(ev, "load_profile", lambda _path: profile or fake_profile())
    monkeypatch.setattr(ev, "run", fake_run)
    return calls


def full_labels_and_alarms() -> tuple[list[dict[str, Any]], list[tuple[float, str]]]:
    """20 eller yukarı + 20 yerde yatma etiketi; her biri süre + 2 sn içinde alarm almış (3 + 2 ve 10 + 2 sınırı içinde)."""
    labels = ([{"t": 100.0 * i, "type": "hands_up"} for i in range(20)]
              + [{"t": 100.0 * i + 50, "type": "lying"} for i in range(20)])
    alarms = ([(100.0 * i + 4, "hands_up") for i in range(20)] + [(100.0 * i + 50 + 11, "lying") for i in range(20)])
    return labels, alarms


def test_main_exit_0_when_all_gates_pass(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    labels, alarms = full_labels_and_alarms()
    calls = patch_run(monkeypatch, alarms + [(1.0e6, "lying")], hours=8.0)          # 8 saatte 1 yanlış alarm: sınırda
    argv = ["v.mp4", "--profile", "p.json", "--labels", write(tmp_path, "l.json", labels)]
    assert ev.main([*argv, "--every", "2"]) == 0
    out = capsys.readouterr()
    assert "Eller yukarı: %100.0 (20/20)" in out.out and "(1.00 / 8 saat)" in out.out
    assert out.out.splitlines()[-1] == "GEÇTİ" and out.err == ""
    assert ev.main([*argv, "--every", "0"]) == 0                  # 0 ya da negatif: her kare
    assert calls == [("v.mp4", 2), ("v.mp4", 1)]


def test_main_exit_1_when_a_gate_fails(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    labels, alarms = full_labels_and_alarms()
    lp = write(tmp_path, "l.json", labels)
    argv = ["v.mp4", "--profile", "p.json", "--labels", lp]
    patch_run(monkeypatch, alarms[2:], hours=8.0)                                   # iki eller yukarı kaçtı: 18/20
    assert ev.main(argv) == 1
    out = capsys.readouterr().out
    assert "%90.0 (18/20)" in out and out.splitlines()[-1] == "KALDI"
    patch_run(monkeypatch, alarms + [(1.0e6, "lying"), (2.0e6, "lying")], hours=8.0)    # 8 saatte 2 yanlış alarm
    assert ev.main(argv) == 1
    assert "(2.00 / 8 saat)" in capsys.readouterr().out
    patch_run(monkeypatch, alarms, hours=0.5)                                       # yarım saatlik video
    assert ev.main(argv) == 1
    assert "yetersiz süre: video 30 dk" in capsys.readouterr().out
    short_labels = [lab for lab in labels if not (lab["type"] == "lying" and lab["t"] == 50.0)]   # yerde yatma: 19 etiket
    patch_run(monkeypatch, alarms, hours=8.0)
    assert ev.main(["v.mp4", "--profile", "p.json", "--labels", write(tmp_path, "k.json", short_labels)]) == 1
    assert "en az 20 etiket gerekli" in capsys.readouterr().out


def test_main_warns_when_a_labelled_rule_is_disabled(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                                      capsys: pytest.CaptureFixture[str]) -> None:
    labels, alarms = full_labels_and_alarms()
    patch_run(monkeypatch, [a for a in alarms if a[1] != "hands_up"], hours=8.0, profile=fake_profile(False))
    assert ev.main(["v.mp4", "--profile", "p.json", "--labels", write(tmp_path, "l.json", labels)]) == 1
    assert "UYARI: profilde Eller yukarı kuralı kapalı" in capsys.readouterr().err
