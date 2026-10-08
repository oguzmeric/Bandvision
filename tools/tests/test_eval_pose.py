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


# ---------------------------------------------------------------- olay içi tekrar (`end`, `tekrar`)
SEC = {"hands_up": 3.0, "lying": 10.0}
TEKRAR = "Tekrar (aynı olayın içinde, yanlış alarm sayılmaz)"


def test_repeat_alarms_inside_a_caught_event_are_tekrar_not_false() -> None:
    # t=10: yakalama penceresi [10, 15]; olay (end yok) t + süre + 2 + 10 = 25'e kadar sürer
    alarms = [(13.0, "hands_up"), (16.0, "hands_up"), (25.0, "hands_up"), (25.1, "hands_up")]
    r = ev.match_pose([{"t": 10.0, "type": "hands_up"}], alarms, SEC)
    assert r["hands_up"] == {"labels": 1, "caught": 1}
    assert r["repeat"] == 2 and r["false"] == 1                    # 16 ve 25 (sınır dahil) tekrar; 25,1 olay dışı: yanlış


def test_event_with_end_lasts_until_end_plus_tolerance() -> None:
    alarms = [(21.0, "lying"), (40.0, "lying"), (62.0, "lying"), (62.1, "lying")]
    r = ev.match_pose([{"t": 10.0, "type": "lying", "end": 60.0}], alarms, SEC)
    assert r["lying"] == {"labels": 1, "caught": 1}
    assert r["repeat"] == 2 and r["false"] == 1                    # 40 ve 62 (end + 2 sınırı) tekrar; 62,1 yanlış
    no_end = ev.match_pose([{"t": 10.0, "type": "lying"}], alarms, SEC)    # end yok: olay 10 + 10 + 2 + 10 = 32'ye kadar
    assert no_end["lying"]["caught"] == 1 and no_end["repeat"] == 0 and no_end["false"] == 3


def test_alarm_after_a_missed_label_is_false_not_tekrar() -> None:
    # 15 < 20 ≤ 25: olay penceresinde ama etiket yakalanmadı (alarm geç geldi) → tekrar sayılmaz, yanlış alarmdır
    r = ev.match_pose([{"t": 10.0, "type": "hands_up"}], [(20.0, "hands_up")], SEC)
    assert r["hands_up"] == {"labels": 1, "caught": 0}
    assert r["repeat"] == 0 and r["false"] == 1


def test_repeat_must_be_the_same_type_as_the_caught_label() -> None:
    r = ev.match_pose([{"t": 10.0, "type": "hands_up"}], [(12.0, "hands_up"), (14.0, "lying")], SEC)
    assert r["hands_up"]["caught"] == 1 and r["repeat"] == 0 and r["false"] == 1


def test_event_window_does_not_starve_a_later_label() -> None:
    # 17 hem 1. etiketin olay penceresinde (10–25) hem 2. etiketin yakalama penceresinde (16–21): önce yakalamalar
    labels = [{"t": 10.0, "type": "hands_up"}, {"t": 16.0, "type": "hands_up"}]
    r = ev.match_pose(labels, [(12.0, "hands_up"), (17.0, "hands_up")], SEC)
    assert r["hands_up"] == {"labels": 2, "caught": 2} and r["repeat"] == 0 and r["false"] == 0


def test_repeat_counting_does_not_depend_on_alarm_order() -> None:
    alarms = [(16.0, "hands_up"), (13.0, "hands_up"), (30.0, "hands_up")]
    r = ev.match_pose([{"t": 10.0, "type": "hands_up"}], alarms, SEC)
    assert r["hands_up"]["caught"] == 1 and r["repeat"] == 1 and r["false"] == 1


def test_labels_accept_an_optional_end_and_reject_a_bad_one() -> None:
    ok = [{"t": 10.0, "type": "lying", "end": 40}, {"t": 5, "type": "hands_up", "end": 5},
          {"t": 1, "type": "lying", "end": None}]
    assert ev.check_labels(ok) == ok                               # end == t ve null (yok) geçerli
    for bad in (5.0, "20", True, float("nan"), float("inf"), [30]):
        with pytest.raises(ev.InputError) as e:
            ev.check_labels([{"t": 10.0, "type": "lying", "end": bad}])
        assert "1. kaydın bitişi (end)" in str(e.value)


# ---------------------------------------------------------------- manifest: toplama ve kamera başına kapı
def multi(cams: dict[str, tuple[int, float]], hu: tuple[int, int] = GOOD, ly: tuple[int, int] = GOOD) -> dict[str, Any]:
    """`aggregate` sonucu biçiminde: kamera → (yanlış alarm, saat)."""
    r = result(hu, ly, sum(f for f, _ in cams.values()), sum(h for _, h in cams.values()))
    r["cameras"] = {name: {"false": f, "hours": h} for name, (f, h) in cams.items()}
    return r


def test_aggregate_sums_capture_across_entries_and_false_alarms_per_camera() -> None:
    parts = [("Tezgah", {**result((10, 9), (5, 5), 1, 4.0), "repeat": 2}),
             ("Giriş", result((10, 10), (15, 14), 0, 2.0)),
             ("Tezgah", result((0, 0), (0, 0), 2, 4.0))]
    r = ev.aggregate(parts)
    assert r["hands_up"] == {"labels": 20, "caught": 19} and r["lying"] == {"labels": 20, "caught": 19}
    assert r["repeat"] == 2 and r["false"] == 3 and r["hours"] == pytest.approx(10.0)
    assert r["cameras"] == {"Tezgah": {"false": 3, "hours": 8.0}, "Giriş": {"false": 0, "hours": 2.0}}
    assert list(r["cameras"]) == ["Tezgah", "Giriş"]              # ilk görülme sırası


def test_report_gates_every_camera_with_an_hour_or_more(capsys: pytest.CaptureFixture[str]) -> None:
    assert ev.report(multi({"Tezgah": (1, 8.0), "Giriş": (0, 2.0)})) is True      # Tezgah tam sınırda (1 / 8 saat)
    out = capsys.readouterr().out
    assert "Tezgah" in out and "Giriş" in out and "(1.00 / 8 saat)" in out and out.splitlines()[-1] == "GEÇTİ"
    # toplamda 1 yanlış alarm / 10 saat = 0,8 / 8 saat (tek video gibi bakılsa geçerdi); ama Giriş tek başına 4 / 8 saat
    assert ev.report(multi({"Tezgah": (0, 8.0), "Giriş": (1, 2.0)})) is False
    out = capsys.readouterr().out
    assert "(4.00 / 8 saat)" in out and out.splitlines()[-1] == "KALDI"
    assert ev.report(multi({"Tezgah": (0, 8.0), "Giriş": (2, 1.0)})) is False     # tam 1 saat: o kamera da sınanır
    assert "(16.00 / 8 saat)" in capsys.readouterr().out


def test_report_every_camera_needs_an_hour_of_video(capsys: pytest.CaptureFixture[str]) -> None:
    # Tezgah 8 saat ve temiz; Depo 50 dk: toplam 8,8 saat yetse de Depo'nun süresi yetmez → KALDI
    assert ev.report(multi({"Tezgah": (0, 8.0), "Depo": (0, 50 / 60)})) is False
    out = capsys.readouterr().out
    assert "yetersiz süre: Depo 50 dk (en az 60 dk)" in out and out.splitlines()[-1] == "KALDI"
    assert "Tezgah" in out and "yetersiz süre: Tezgah" not in out        # yeterli kamera için bu ileti yok
    assert ev.report(multi({"Tezgah": (0, 8.0), "Depo": (5, 59.6 / 60)})) is False   # 59,6 dk "60 dk" diye yuvarlanmaz
    assert "yetersiz süre: Depo 59 dk (en az 60 dk)" in capsys.readouterr().out
    assert ev.report(multi({"A": (0, 0.2), "B": (0, 0.3), "C": (0, 8.0)})) is False   # kısa her kamera ayrı yazılır
    out = capsys.readouterr().out
    assert "yetersiz süre: A 12 dk (en az 60 dk)" in out and "yetersiz süre: B 18 dk (en az 60 dk)" in out
    assert "Not:" not in out


def test_report_passes_when_every_camera_has_an_hour_and_is_within_the_limit(
        capsys: pytest.CaptureFixture[str]) -> None:
    assert ev.report(multi({"Tezgah": (1, 8.0), "Giriş": (0, 1.0), "Depo": (0, 2.5)})) is True
    out = capsys.readouterr().out
    assert "yetersiz süre" not in out and "Not:" not in out and out.splitlines()[-1] == "GEÇTİ"


def test_report_two_half_hour_cameras_do_not_add_up_to_an_hour(capsys: pytest.CaptureFixture[str]) -> None:
    # toplam tam 1 saat ama hiçbir kamera tek başına 1 saat değil: eskiden "Not:" ile geçerdi, artık KALDI
    assert ev.report(multi({"A": (0, 0.5), "B": (0, 0.5)})) is False
    out = capsys.readouterr().out
    assert "yetersiz süre: A 30 dk (en az 60 dk)" in out and "yetersiz süre: B 30 dk (en az 60 dk)" in out
    assert "Not:" not in out and out.splitlines()[-1] == "KALDI"


def test_report_capture_gate_still_applies_in_manifest_mode(capsys: pytest.CaptureFixture[str]) -> None:
    assert ev.report(multi({"Tezgah": (0, 8.0)}, hu=(20, 18))) is False
    out = capsys.readouterr().out
    assert "%90.0 (18/20)" in out and out.splitlines()[-1] == "KALDI"


def test_report_prints_tekrar_without_affecting_the_gate(capsys: pytest.CaptureFixture[str]) -> None:
    r = result(GOOD, GOOD, 0, 8.0)
    r["repeat"] = 7
    assert ev.report(r) is True
    out = capsys.readouterr().out
    assert f"{TEKRAR}: 7" in out and "Yanlış alarm: 0 (0.00 / 8 saat)" in out and out.splitlines()[-1] == "GEÇTİ"
    m = multi({"Tezgah": (0, 8.0)})
    m["repeat"] = 3
    assert ev.report(m) is True
    assert f"{TEKRAR}: 3" in capsys.readouterr().out


def test_report_single_video_output_is_unchanged(capsys: pytest.CaptureFixture[str]) -> None:
    assert ev.report(result(GOOD, GOOD, 1, 8.0)) is True
    assert capsys.readouterr().out == ("Eller yukarı: %100.0 (20/20)\nYerde yatan kişi: %100.0 (20/20)\n"
                                       "Yanlış alarm: 1 (1.00 / 8 saat)\nGEÇTİ\n")    # tekrar yok → tekrar satırı, tablo yok


# ---------------------------------------------------------------- manifest: komut satırı
def make_manifest(tmp: pathlib.Path, spec: list[dict[str, Any]]) -> str:
    """`tmp/kayit/manifest.json` + yolları manifeste göre verilen dosyalar. spec: {"video": "a.mp4"|"alt/c.mp4", "labels": [...],
    "camera"?}. Dönen: manifest yolu."""
    base = tmp / "kayit"
    entries = []
    for i, s in enumerate(spec):
        video = base / s["video"]
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"")                                     # run sahte; yalnızca dosyanın var olması denetlenir
        (base / f"l{i}.json").write_text(json.dumps(s["labels"]), encoding="utf-8")
        (base / f"p{i}.json").write_text("{}", encoding="utf-8")
        e: dict[str, Any] = {"video": s["video"], "labels": f"l{i}.json", "profile": f"p{i}.json"}
        if "camera" in s:
            e["camera"] = s["camera"]
        entries.append(e)
    m = base / "manifest.json"
    m.write_text(json.dumps(entries), encoding="utf-8")
    return str(m)


def patch_manifest_run(monkeypatch: pytest.MonkeyPatch, by_video: dict[str, tuple[list[tuple[float, str]], float]],
                       profile: Any = None) -> list[tuple[str, int]]:
    """`run` video dosya adına göre (alarmlar, saat) döndürür; `load_profile` sahte. Dönen liste (video yolu, every)."""
    calls: list[tuple[str, int]] = []

    def fake_run(video: str, _profile: Any, every: int = 1) -> tuple[list[tuple[float, str]], float, dict[str, float]]:
        calls.append((video, every))
        alarms, hours = by_video[pathlib.Path(video).name]
        return alarms, hours, {"hands_up": 3.0, "lying": 10.0}

    monkeypatch.setattr(ev, "load_profile", lambda _path: profile or fake_profile())
    monkeypatch.setattr(ev, "run", fake_run)
    return calls


def halves() -> tuple[list[list[dict[str, Any]]], list[list[tuple[float, str]]]]:
    """Etiketler ve alarmlar iki yarıya bölünür (t < 1000 ve ≥ 1000); toplamda 20 + 20 etiket, hepsi yakalanır."""
    labels, alarms = full_labels_and_alarms()
    return ([[lab for lab in labels if lab["t"] < 1000], [lab for lab in labels if lab["t"] >= 1000]],
            [[a for a in alarms if a[0] < 1000], [a for a in alarms if a[0] >= 1000]])


def test_main_manifest_aggregates_capture_and_resolves_paths_relative_to_the_manifest(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    (l1, l2), (a1, a2) = halves()
    m = make_manifest(tmp_path, [{"video": "a.mp4", "labels": l1, "camera": "Tezgah"},
                                 {"video": "b.mp4", "labels": l2, "camera": "Tezgah"},
                                 {"video": "alt/c.mp4", "labels": []}])           # kamera adı yok → dosya adı
    calls = patch_manifest_run(monkeypatch, {"a.mp4": (a1, 4.0), "b.mp4": (a2 + [(1.0e6, "lying")], 4.0),
                                             "c.mp4": ([], 2.0)})
    assert ev.main(["--manifest", m, "--every", "2"]) == 0
    out = capsys.readouterr()
    assert "Eller yukarı: %100.0 (20/20)" in out.out and "Yerde yatan kişi: %100.0 (20/20)" in out.out   # girdiler toplanır
    assert "Tezgah" in out.out and "c.mp4" in out.out and out.out.splitlines()[-1] == "GEÇTİ"
    assert "(1.00 / 8 saat)" in out.out and "(0.00 / 8 saat)" in out.out    # Tezgah: 8 saatte 1; c.mp4: 0
    base = tmp_path / "kayit"
    assert [(pathlib.Path(v).resolve(), e) for v, e in calls] == [
        ((base / "a.mp4").resolve(), 2), ((base / "b.mp4").resolve(), 2), ((base / "alt" / "c.mp4").resolve(), 2)]


def test_main_manifest_fails_when_a_single_camera_exceeds_the_false_alarm_limit(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    (l1, l2), (a1, a2) = halves()
    m = make_manifest(tmp_path, [{"video": "a.mp4", "labels": l1, "camera": "Tezgah"},
                                 {"video": "b.mp4", "labels": l2, "camera": "Tezgah"},
                                 {"video": "c.mp4", "labels": [], "camera": "Giriş"}])
    # Tezgah 8 saatte 0; Giriş 2 saatte 1 (4 / 8 saat). Toplamda 1 / 10 saat = 0,8 / 8 saat: tek kapı olsaydı geçerdi
    patch_manifest_run(monkeypatch, {"a.mp4": (a1, 4.0), "b.mp4": (a2, 4.0), "c.mp4": ([(5.0, "lying")], 2.0)})
    assert ev.main(["--manifest", m]) == 1
    out = capsys.readouterr().out
    assert "Giriş" in out and "(4.00 / 8 saat)" in out and out.splitlines()[-1] == "KALDI"
    assert "Eller yukarı: %100.0 (20/20)" in out                    # yakalama tamam; yalnızca Giriş kamerası kaldı


def test_main_manifest_counts_tekrar_separately_and_warns_for_disabled_rules(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    labels, alarms = full_labels_and_alarms()
    labels = [{**lab, "end": lab["t"] + 30} for lab in labels]      # her olay 30 sn sürer
    again = [(t + 8, k) for t, k in alarms]                        # her alarmın 8 sn sonra tekrarı (olayın içinde)
    m = make_manifest(tmp_path, [{"video": "a.mp4", "labels": labels, "camera": "Tezgah"}])
    patch_manifest_run(monkeypatch, {"a.mp4": (alarms + again, 8.0)}, profile=fake_profile(False))
    assert ev.main(["--manifest", m]) == 0
    out = capsys.readouterr()
    assert f"{TEKRAR}: 40" in out.out and "(0.00 / 8 saat)" in out.out
    assert "UYARI" in out.err and "a.mp4" in out.err and "Eller yukarı kuralı kapalı" in out.err


@pytest.mark.parametrize(("manifest", "needle"), [
    ("not json {", "Manifest dosyası okunamadı"),
    ({"video": "a.mp4"}, "liste"),                                 # liste değil
    ([], "liste"),                                                 # boş liste
    (["a.mp4"], "1. kayıt bir nesne değil"),
    ([{"video": "a.mp4", "labels": "l.json"}], "1. kayıtta \"profile\""),                       # alan eksik
    ([{"video": "a.mp4", "labels": "l.json", "profile": 5}], "1. kayıtta \"profile\""),         # metin değil
    ([{"video": "a.mp4", "labels": "l.json", "profile": "  "}], "1. kayıtta \"profile\""),      # boş
    ([{"video": "a.mp4", "labels": "l.json", "profile": "p.json"}, {"video": "b.mp4"}], "2. kayıtta \"labels\""),
    ([{"video": "a.mp4", "labels": "l.json", "profile": "p.json", "kamera": "x"}], "1. kayıtta bilinmeyen alan: kamera"),
    ([{"video": "a.mp4", "labels": "l.json", "profile": "p.json", "camera": ""}], "1. kayıtta \"camera\""),
    ([{"video": "a.mp4", "labels": "l.json", "profile": "p.json", "camera": 3}], "1. kayıtta \"camera\""),
])
def test_main_manifest_rejects_malformed_entries_in_turkish(
        tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], manifest: Any, needle: str) -> None:
    assert ev.main(["--manifest", write(tmp_path, "m.json", manifest)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("HATA: Manifest") and needle in err
    assert "Traceback" not in err and "KeyError" not in err


def test_main_manifest_missing_file_is_a_turkish_input_error(tmp_path: pathlib.Path,
                                                             capsys: pytest.CaptureFixture[str]) -> None:
    assert ev.main(["--manifest", str(tmp_path / "yok.json")]) == 2
    assert capsys.readouterr().err.startswith("HATA: Manifest dosyası okunamadı")


def test_main_manifest_checks_every_entry_before_processing_any_video(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    good = [{"t": 5.0, "type": "lying"}]
    m = make_manifest(tmp_path, [{"video": "a.mp4", "labels": good}, {"video": "b.mp4", "labels": good}])
    base = tmp_path / "kayit"
    calls = patch_manifest_run(monkeypatch, {"a.mp4": ([], 1.0), "b.mp4": ([], 1.0)})
    (base / "l1.json").write_text("not json {", encoding="utf-8")                  # 2. kaydın etiketi bozuk
    assert ev.main(["--manifest", m]) == 2
    err = capsys.readouterr().err
    assert err.startswith("HATA: Manifest 2. kayıt (b.mp4): Etiket dosyası okunamadı") and calls == []   # hiç video işlenmedi
    (base / "l1.json").write_text(json.dumps(good), encoding="utf-8")
    (base / "b.mp4").unlink()                                                       # 2. kaydın videosu yok
    assert ev.main(["--manifest", m]) == 2
    assert "Manifest 2. kayıt (b.mp4): video bulunamadı" in capsys.readouterr().err and calls == []
    (base / "b.mp4").write_bytes(b"")

    def bad_profile(path: str) -> Any:
        if path.endswith("p0.json"):
            raise ev.InputError("Profil geçersiz: deneme")
        return fake_profile()

    monkeypatch.setattr(ev, "load_profile", bad_profile)
    assert ev.main(["--manifest", m]) == 2
    assert "Manifest 1. kayıt (a.mp4): Profil geçersiz: deneme" in capsys.readouterr().err and calls == []


def test_main_manifest_reports_a_video_that_cannot_be_opened_with_its_entry(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    m = make_manifest(tmp_path, [{"video": "a.mp4", "labels": [{"t": 5.0, "type": "lying"}]}])
    monkeypatch.setattr(ev, "load_profile", lambda _path: fake_profile())

    def broken(video: str, _profile: Any, every: int = 1) -> Any:
        raise ev.InputError(f"Video açılamadı: {video}")

    monkeypatch.setattr(ev, "run", broken)
    assert ev.main(["--manifest", m]) == 2
    assert "HATA: Manifest 1. kayıt (a.mp4): Video açılamadı" in capsys.readouterr().err


@pytest.mark.parametrize(("argv", "needle"), [
    (["v.mp4", "--manifest", "m.json"], "--manifest ile VIDEO"),
    (["--manifest", "m.json", "--labels", "l.json"], "--manifest ile VIDEO"),
    (["--manifest", "m.json", "--profile", "p.json"], "--manifest ile VIDEO"),
    ([], "VIDEO"),
    (["v.mp4", "--labels", "l.json"], "--profile"),
    (["v.mp4", "--profile", "p.json"], "--labels"),
])
def test_main_rejects_wrong_argument_combinations_in_turkish(capsys: pytest.CaptureFixture[str], argv: list[str],
                                                              needle: str) -> None:
    assert ev.main(argv) == 2
    err = capsys.readouterr().err
    assert err.startswith("HATA: ") and needle in err and "usage" not in err.lower()


def test_main_single_video_with_end_labels_prints_tekrar_and_keeps_the_gate(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    labels, alarms = full_labels_and_alarms()
    labels = [{**lab, "end": lab["t"] + 30} for lab in labels]
    patch_run(monkeypatch, alarms + [(t + 8, k) for t, k in alarms], hours=8.0)
    assert ev.main(["v.mp4", "--profile", "p.json", "--labels", write(tmp_path, "l.json", labels)]) == 0
    out = capsys.readouterr().out
    assert f"{TEKRAR}: 40" in out and "Yanlış alarm: 0 (0.00 / 8 saat)" in out
    assert "Kamera" not in out and out.splitlines()[-1] == "GEÇTİ"                   # tek video: kamera tablosu yok


def test_main_manifest_exits_1_when_one_camera_has_less_than_an_hour(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    (l1, l2), (a1, a2) = halves()
    m = make_manifest(tmp_path, [{"video": "a.mp4", "labels": l1, "camera": "Tezgah"},
                                 {"video": "b.mp4", "labels": l2, "camera": "Tezgah"},
                                 {"video": "c.mp4", "labels": [], "camera": "Depo"}])
    patch_manifest_run(monkeypatch, {"a.mp4": (a1, 4.0), "b.mp4": (a2, 4.0), "c.mp4": ([], 50 / 60)})
    assert ev.main(["--manifest", m]) == 1                        # yakalama tamam, yanlış alarm yok; ama Depo 50 dk
    out = capsys.readouterr().out
    assert "yetersiz süre: Depo 50 dk (en az 60 dk)" in out and out.splitlines()[-1] == "KALDI"
    patch_manifest_run(monkeypatch, {"a.mp4": (a1, 4.0), "b.mp4": (a2, 4.0), "c.mp4": ([], 1.0)})
    assert ev.main(["--manifest", m]) == 0                        # Depo tam 1 saat ve temiz: geçer
    assert capsys.readouterr().out.splitlines()[-1] == "GEÇTİ"
