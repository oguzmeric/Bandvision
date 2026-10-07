from __future__ import annotations

import numpy as np
from fakes_safety import FakeDetector, FakePose, hands_up_kp

from bantvision.core import Pipeline, Profile
from bantvision.core.detect_count import inside_roi
from bantvision.core.safety import SafetyAnalyzer, SafetyResult, anchor_point

BOX = (280, 80, 360, 440)                                              # 640×480'de ayakta kişi (alt orta ≈ 0,92)
FRAME = np.zeros((480, 640, 3), np.uint8)


def make(boxes: list[tuple[float, float, float, float]], profile: Profile | None = None
         ) -> tuple[SafetyAnalyzer, FakeDetector, FakePose, Profile]:
    det, pose = FakeDetector(list(boxes)), FakePose(hands_up_kp())
    return SafetyAnalyzer(detector=det, pose=pose), det, pose, profile or Profile.jeweler()


def feed(an: SafetyAnalyzer, p: Profile, start: int, stop: int, fps: float = 10.0) -> list[SafetyResult]:
    return [an.process(FRAME, p, fps, k / fps) for k in range(start, stop)]


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
    assert not r.active and r.boxes == {}


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


# ---------------------------------------------------------------- alan kuralı ve poz çağrıları

def test_person_touching_frame_bottom_is_analysed() -> None:
    """Tanıma kutusu kareye kırpılır (y2 = 1,0); yarı açık ROI bunu dışarıda saymamalı (tezgah kamerası, bel üstü)."""
    an, _, pose, p = make([(280, 100, 360, 480)])
    fired = [a for r in feed(an, p, 0, 50) for a in r.fired]
    assert len(fired) == 1 and fired[0].kind == "hands_up" and pose.calls > 0
    assert fired[0].box[3] >= 0.999


def test_anchor_point_is_clamped_inside_frame() -> None:
    ax, ay = anchor_point((0.4, 0.2, 0.6, 1.0))
    assert ay < 1.0 and inside_roi(Profile.jeweler(), ax, ay)
    ax, ay = anchor_point((0.95, 0.2, 1.3, 1.2))
    assert ax < 1.0 and ay < 1.0 and inside_roi(Profile.jeweler(), ax, ay)


def test_empty_scene_makes_no_pose_calls() -> None:
    an, _, pose, p = make([])
    for r in feed(an, p, 0, 30):
        assert r.tracks == [] and r.poses == {} and r.active == []
    assert pose.calls == 0


def test_unobserved_track_makes_no_pose_calls() -> None:
    an, det, pose, p = make([BOX])
    feed(an, p, 0, 10)
    assert pose.calls > 0 and an.dc.tracker.tracks
    before = pose.calls
    det.boxes = []                                                     # tanıma kişiyi kaçırdı; iz henüz ölmedi
    for r in feed(an, p, 10, 13):
        assert r.tracks == [] and r.poses == {}
    assert an.dc.tracker.tracks and pose.calls == before


def test_area_uses_bottom_centre_anchor_not_box_centre() -> None:
    """Kutu merkezi alanın içinde ama ayak noktası dışında: iz var, poz çağrısı ve alarm yok."""
    p = Profile.jeweler()
    p.roiPolygon = [(0.3, 0.2), (0.7, 0.2), (0.7, 0.7), (0.3, 0.7)]    # ROI tam kare kalır
    roi, poly = p.roi, list(p.roiPolygon)
    an, _, pose, p = make([BOX], p)
    res = feed(an, p, 0, 50)
    assert any(r.tracks for r in res) and an.dc.tracker.tracks         # izleyici kişiyi görüyor
    assert pose.calls == 0 and not any(r.fired or r.poses for r in res)
    assert p.roi == roi and p.roiPolygon == poly                       # çağıranın profili değişmedi


def test_person_standing_in_floor_polygon_is_analysed() -> None:
    """Ayak noktası zemindeki alanın içinde, kutu merkezi üstünde: izlenir, poz çağrılır, alarm doğar."""
    p = Profile.jeweler()
    p.roiPolygon = [(0.3, 0.8), (0.7, 0.8), (0.7, 1.0), (0.3, 1.0)]
    an, _, pose, p = make([BOX], p)
    fired = [a for r in feed(an, p, 0, 50) for a in r.fired]
    assert len(fired) == 1 and fired[0].kind == "hands_up" and pose.calls > 0


# ---------------------------------------------------------------- kutu sürekliliği ve reset()

def test_red_box_survives_one_missed_detection_frame() -> None:
    from bantvision.overlay import RED, draw_safety

    an, det, _, p = make([BOX])
    r = feed(an, p, 0, 40)[-1]
    tid = next(a[0] for a in r.active if a[3])
    det.boxes = []                                                     # alarmdan sonra tanıma bir kare kaçırdı
    r = an.process(FRAME, p, 10.0, 4.0)
    assert r.tracks == [] and any(a[3] for a in r.active) and tid in r.boxes
    img = draw_safety(FRAME.copy(), p, r)
    red = np.array(RED, np.uint8)
    assert (img[250, 270:290] == red).all(axis=1).any()                # kutunun sol kenarı (x ≈ 280)


def test_draw_safety_handles_both_kinds_and_box_without_track() -> None:
    from bantvision.overlay import RED, draw_safety

    r = SafetyResult(active=[(7, "hands_up", 4.0, True), (7, "lying", 12.0, True), (8, "lying", 1.0, False)],
                     boxes={7: (0.4, 0.2, 0.6, 0.9)})
    img = draw_safety(FRAME.copy(), Profile.jeweler(), r)
    assert (img == np.array(RED, np.uint8)).all(axis=2).any()
    assert draw_safety(FRAME.copy(), Profile.jeweler(), SafetyResult(active=[(9, "lying", 3.0, True)])).sum() == 0


def test_reset_reports_fired_episodes_as_ended_on_next_frame() -> None:
    an, _, _, p = make([BOX])
    r = feed(an, p, 0, 40)[-1]
    tid = next(a[0] for a in r.active if a[3])
    an.reset()
    r = an.process(FRAME, p, 10.0, 4.0)
    assert r.ended == [(tid, "hands_up", True)] and r.active == [] and r.boxes == {}
    assert an.process(FRAME, p, 10.0, 4.1).ended == []                 # yalnızca bir kez bildirilir


def test_reset_does_not_report_episode_that_never_fired() -> None:
    an, _, _, p = make([BOX])
    r = feed(an, p, 0, 15)[-1]
    assert r.active and not any(a[3] for a in r.active)                # bölüm var ama eşik dolmadı
    an.reset()
    assert an.process(FRAME, p, 10.0, 1.5).ended == []
