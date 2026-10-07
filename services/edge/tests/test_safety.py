from __future__ import annotations

import numpy as np
from fakes_safety import FakeDetector, FakePose, hands_up_kp

from bantvision.core import Pipeline, Profile
from bantvision.core.safety import SafetyAnalyzer


def run(kp: np.ndarray, seconds: float, fps: float = 10.0, profile: Profile | None = None) -> list[object]:
    p = profile or Profile.jeweler()
    an = SafetyAnalyzer(detector=FakeDetector([(280, 80, 360, 440)]), pose=FakePose(kp))
    frame = np.zeros((480, 640, 3), np.uint8)
    out = []
    for k in range(int(seconds * fps)):
        out.append(an.process(frame, p, fps, k / fps))
    return out


def test_hands_up_alarm_after_three_seconds_once() -> None:
    res = run(hands_up_kp(), 5.0)
    fired = [(k, a.kind) for k, r in enumerate(res) for a in r.fired]
    assert len(fired) == 1 and fired[0][1] == "hands_up"
    assert 30 <= fired[0][0] <= 36                                     # 3 sn + onay (minHits) gecikmesi


def test_alarm_carries_normalised_box_and_start_time() -> None:
    res = run(hands_up_kp(), 5.0)
    alarm = next(a for r in res for a in r.fired)
    x1, y1, x2, y2 = alarm.box
    assert abs(x1 - 280 / 640) < 0.02 and abs(y1 - 80 / 480) < 0.02
    assert abs(x2 - 360 / 640) < 0.02 and abs(y2 - 440 / 480) < 0.02
    assert abs((alarm.ts - alarm.started) - 3.0) < 0.15                # süre eşiği kadar önce başladı


def test_alarm_fires_once_at_one_fps_with_adaptive_grace() -> None:
    """1 kare/sn: kare aralığı (1 sn) sabit 0,5 sn toleransı aşar; tolerans kare hızına uyar."""
    res = run(hands_up_kp(), 6.0, fps=1.0)
    fired = [(k, a.kind) for k, r in enumerate(res) for a in r.fired]
    assert len(fired) == 1 and fired[0][1] == "hands_up"


def test_disabled_rule_and_area_outside_do_not_fire() -> None:
    p = Profile.jeweler()
    p.safety.handsUp.enabled = False
    assert not any(r.fired for r in run(hands_up_kp(), 5.0, profile=p))
    q = Profile.jeweler()
    q.set_polygon([(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])  # kişi alanın dışında
    assert not any(r.fired for r in run(hands_up_kp(), 5.0, profile=q))


def test_hidden_hips_never_lying() -> None:
    kp = hands_up_kp()
    kp[[9, 10], 1] = 300                                               # eller aşağıda
    kp[[11, 12], 2] = 0.0                                              # kalça tezgah arkasında
    assert not any(r.fired for r in run(kp, 15.0))


def test_ended_reported_when_person_leaves() -> None:
    det = FakeDetector([(280, 80, 360, 440)])
    an = SafetyAnalyzer(detector=det, pose=FakePose(hands_up_kp()))
    p = Profile.jeweler()
    frame = np.zeros((480, 640, 3), np.uint8)
    fired = 0
    for k in range(40):                                                # 4 sn el kaldırma: alarm
        r = an.process(frame, p, 10.0, k / 10)
        fired += len(r.fired)
    assert fired == 1 and any(a[3] for a in r.active)
    det.boxes = []                                                     # kişi çıktı
    ends = []
    for k in range(40, 80):
        r = an.process(frame, p, 10.0, k / 10)
        ends += r.ended
    assert len(ends) == 1 and ends[0][1:] == ("hands_up", True)
    assert not r.active


def test_pipeline_routes_safety_mode_and_draws() -> None:
    from bantvision.overlay import draw_safety

    pipe = Pipeline(Profile.jeweler())
    pipe.safety = SafetyAnalyzer(detector=FakeDetector([(280, 80, 360, 440)]), pose=FakePose(hands_up_kp()))
    frame = np.zeros((480, 640, 3), np.uint8)
    r = None
    for k in range(40):
        r = pipe.process(frame, k / 10)
    assert r is not None and r.safety is not None and r.counts == [] and pipe.total == 0
    img = draw_safety(frame.copy(), pipe.profile, r.safety)
    assert img.shape == frame.shape and img.any()                     # iskelet ve kırmızı kutu çizildi


def test_draw_safety_none_is_noop_and_red_box_only_when_alarming() -> None:
    from bantvision.overlay import RED, draw_safety

    frame = np.zeros((480, 640, 3), np.uint8)
    assert draw_safety(frame.copy(), Profile.jeweler(), None).sum() == 0
    an = SafetyAnalyzer(detector=FakeDetector([(280, 80, 360, 440)]), pose=FakePose(hands_up_kp()))
    p = Profile.jeweler()
    early = late = None
    for k in range(40):
        r = an.process(frame, p, 10.0, k / 10)
        if k == 10:
            early = draw_safety(frame.copy(), p, r)
        late = draw_safety(frame.copy(), p, r)
    red = np.array(RED, np.uint8)
    assert early is not None and late is not None
    assert not (early == red).all(axis=2).any()                        # henüz alarm yok: kırmızı yok
    assert (late == red).all(axis=2).any()                             # alarm: kırmızı kutu


def test_pipeline_reset_resets_safety_analyzer() -> None:
    pipe = Pipeline(Profile.jeweler())
    pipe.safety = SafetyAnalyzer(detector=FakeDetector([(280, 80, 360, 440)]), pose=FakePose(hands_up_kp()))
    frame = np.zeros((480, 640, 3), np.uint8)
    for k in range(5):
        pipe.process(frame, k / 10)
    assert pipe.safety.dc.tracker.tracks
    pipe.reset_count()
    assert not pipe.safety.dc.tracker.tracks
    pipe.process(frame, 1.0)
    pipe.set_profile(Profile.jeweler())
    assert not pipe.safety.dc.tracker.tracks
