from __future__ import annotations

import numpy as np
import pytest
from fakes_safety import FakeDetector, FakePhoneDetector, FakePose, hands_up_kp, phone_kp

from bantvision.core import Pipeline, Profile
from bantvision.core.profile import Roi
from bantvision.core.safety import SafetyAnalyzer, SafetyResult

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


def test_disabled_rule_does_not_fire() -> None:
    p = Profile.jeweler()
    p.safety.handsUp.enabled = False
    assert not any(r.fired for r in run(hands_up_kp(), 5.0, profile=p))


def test_person_outside_drawn_area_still_fires() -> None:
    """Kullanıcı kararı (2026-10-07): güvenlikte alan kısıtı yok; eski profilde çizili alan yok sayılır."""
    q = Profile.jeweler()
    q.set_polygon([(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])  # kişi alanın dışında
    fired = [a for r in run(hands_up_kp(), 5.0, profile=q) for a in r.fired]
    assert len(fired) == 1 and fired[0].kind == "hands_up"
    r = Profile.jeweler()
    r.roi = Roi(0.0, 0.0, 0.2, 0.2)                                   # dikdörtgen alan da yok sayılır
    assert sum(len(x.fired) for x in run(hands_up_kp(), 5.0, profile=r)) == 1


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


# ---------------------------------------------------------------- alan yok sayılır; poz çağrıları

def test_person_touching_frame_bottom_is_analysed() -> None:
    """Tanıma kutusu kareye kırpılır (y2 = 1,0); yarı açık ROI bunu dışarıda saymamalı (tezgah kamerası, bel üstü)."""
    an, _, pose, p = make([(280, 100, 360, 480)])
    fired = [a for r in feed(an, p, 0, 50) for a in r.fired]
    assert len(fired) == 1 and fired[0].kind == "hands_up" and pose.calls > 0
    assert fired[0].box[3] >= 0.999


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


def test_area_is_ignored_and_callers_profile_unchanged() -> None:
    """Alan kısıtı yok: kutu merkezi ve ayak noktası alanın dışında olsa da poz çağrılır, alarm doğar; çağıranın profili
    değişmez (tanıma ve izleme tam karede)."""
    p = Profile.jeweler()
    p.roiPolygon = [(0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2)]    # kişi (x ≈ 0,44–0,56) tamamen dışarıda
    roi, poly = p.roi, list(p.roiPolygon)
    an, _, pose, p = make([BOX], p)
    fired = [a for r in feed(an, p, 0, 50) for a in r.fired]
    assert len(fired) == 1 and fired[0].kind == "hands_up" and pose.calls > 0
    assert p.roi == roi and p.roiPolygon == poly                       # çağıranın profili değişmedi


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


def test_missing_pose_skips_track_without_verdict_or_episode() -> None:
    """Poz modeli hazır değil (estimate → None): o karede izin pozu yok, karar ve bölüm güncellemesi yok."""
    an, _det, pose, p = make([BOX])
    pose.kp = None
    res = feed(an, p, 0, 60)                                           # 6 sn model yok
    assert pose.calls > 0 and all(not r.poses and not r.active and not r.fired and not r.ended for r in res)
    pose.kp = hands_up_kp()                                            # model geldi: sayım şimdi başlar
    res = feed(an, p, 60, 120)
    assert sum(len(r.fired) for r in res) == 1 and res[-1].active


def test_end_all_reports_open_alarmed_episodes_and_pending_reset_ends() -> None:
    an, _det, _pose, p = make([BOX])
    tid = next(a.track_id for r in feed(an, p, 0, 50) for a in r.fired)
    assert an.end_all() == [(tid, "hands_up", True)]
    assert an.end_all() == [] and not an.episodes.active()             # ikinci çağrı boş

    an2, _det2, _pose2, p2 = make([BOX])
    tid2 = next(a.track_id for r in feed(an2, p2, 0, 50) for a in r.fired)
    an2.reset()                                                        # sonu henüz bir sonuçta bildirilmedi
    assert not an2.episodes.active() and an2.end_all() == [(tid2, "hands_up", True)]

    an3, _det3, _pose3, p3 = make([BOX])
    feed(an3, p3, 0, 20)                                               # alarm vermemiş bölüm bildirilmez
    assert an3.episodes.active() and an3.end_all() == []


def test_pose_is_skipped_when_both_rules_are_disabled() -> None:
    """İki kural da kapalıysa poz modeli hiç çalışmaz (işlemci boşa harcanmaz); kişi izlenmeye devam eder."""
    p = Profile.jeweler()
    p.safety.handsUp.enabled = False
    p.safety.lying.enabled = False
    an, _, pose, p = make([BOX], p)
    res = feed(an, p, 0, 50)
    assert pose.calls == 0 and any(r.tracks for r in res)
    assert not any(r.fired or r.poses or r.active for r in res)
    p.safety.lying.enabled = True                                      # biri açılınca poz yine çalışır
    feed(an, p, 50, 60)
    assert pose.calls > 0


# ---------------------------------------------------------------- telefon kullanımı (üçüncü kural)

# BOX (280, 80, 360, 440) kırpıntısı %20 payla (264, 8)'den başlar; phone_kp sol bileği (290, 260) kırpıntıda
# ≈ (26, 252). FakePhoneDetector telefon kutularını kırpıntıya göre verir.
PHONE_NEAR_WRIST = (16.0, 242.0, 36.0, 262.0, 0.4)


def make_phone(profile: Profile, phones: list[tuple[float, float, float, float, float]] | None = None
               ) -> tuple[SafetyAnalyzer, FakePhoneDetector, FakePose]:
    det, pose = FakePhoneDetector([BOX], phones=[PHONE_NEAR_WRIST] if phones is None else phones), FakePose(phone_kp())
    return SafetyAnalyzer(detector=det, pose=pose), det, pose


def phone_only(seconds: float = 10.0) -> Profile:
    p = Profile.jeweler()
    p.safety.handsUp.enabled = False
    p.safety.lying.enabled = False
    p.safety.phone.enabled = True
    p.safety.phone.seconds = seconds
    return p


def test_phone_rule_off_by_default_never_searches_crops() -> None:
    p = Profile.jeweler()
    assert not p.safety.phone.enabled
    an, det, pose = make_phone(p)
    pose.kp = hands_up_kp()
    res = feed(an, p, 0, 50)
    assert det.phone_calls == 0 and det.calls == [["person"]] * 50     # kişi tanıma sayısı değişmez (kare başına 1)
    fired = [a.kind for r in res for a in r.fired]
    assert fired == ["hands_up"]                                       # mevcut kurallar aynen
    assert not any(a[1] == "phone" for r in res for a in r.active)


def test_phone_only_rule_fires_phone_alarm() -> None:
    p = phone_only(10.0)
    an, _det, pose = make_phone(p)
    res = feed(an, p, 0, 120)                                          # 10 kare/sn, 12 sn
    fired = [(k, a) for k, r in enumerate(res) for a in r.fired]
    assert len(fired) == 1 and fired[0][1].kind == "phone" and pose.calls > 0
    k, alarm = fired[0]
    first = next(j for j, r in enumerate(res) if r.tracks)             # onaylı iz: ilk arama ve ilk isabet
    assert alarm.ts == k / 10 and 10.0 <= alarm.ts <= 11.0             # 10 sn gözlem (+ onay gecikmesi)
    assert abs(alarm.started - first / 10) < 1e-9                       # başlangıç = ilk isabet
    assert alarm.track_id == res[-1].tracks[0].id
    assert any(a[1] == "phone" and a[3] for a in res[-1].active)
    x1, y1, x2, y2 = alarm.box
    assert abs(x1 - 280 / 640) < 0.02 and abs(y1 - 80 / 480) < 0.02
    assert abs(x2 - 360 / 640) < 0.02 and abs(y2 - 440 / 480) < 0.02


def test_phone_rule_without_phone_never_fires() -> None:
    p = phone_only(10.0)
    an, det, _pose = make_phone(p, phones=[])
    res = feed(an, p, 0, 150)
    assert det.phone_calls > 0 and not any(r.fired or r.active for r in res)


def test_phone_far_from_hands_and_head_never_fires() -> None:
    p = phone_only(10.0)
    an, _det, _pose = make_phone(p, phones=[(60.0, 400.0, 76.0, 412.0, 0.9)])   # dizde (≈ 332, 414)
    assert not any(r.fired for r in feed(an, p, 0, 150))


def test_phone_search_rate_limited_to_phone_fps() -> None:
    p = phone_only(60.0)
    an, det, _pose = make_phone(p)
    feed(an, p, 0, 50)                                                 # 10 kare/sn 5 sn
    assert 9 <= det.phone_calls <= 11
    assert all(c in (["person"], ["cell phone"]) for c in det.calls)


def test_phone_search_resumes_after_time_goes_backwards() -> None:
    p = phone_only(60.0)
    an, det, _pose = make_phone(p)
    feed(an, p, 0, 20)
    before = det.phone_calls
    an.process(FRAME, p, 10.0, 0.0)                                    # video başa sardı
    assert det.phone_calls == before + 1


def test_reset_and_end_all_report_fired_phone_episode() -> None:
    p = phone_only(10.0)
    an, _det, _pose = make_phone(p)
    tid = next(a.track_id for r in feed(an, p, 0, 120) for a in r.fired)
    an.reset()
    assert an._phone_last == {}                                        # arama zamanları temizlendi
    r = an.process(FRAME, p, 10.0, 12.0)
    assert r.ended == [(tid, "phone", True)] and r.active == []
    assert an.process(FRAME, p, 10.0, 12.1).ended == []                # yalnızca bir kez

    an2, _det2, _pose2 = make_phone(p)
    tid2 = next(a.track_id for r in feed(an2, p, 0, 120) for a in r.fired)
    assert an2.end_all() == [(tid2, "phone", True)]
    assert an2.end_all() == [] and not an2.phone.active()

    an3, _det3, _pose3 = make_phone(p)
    feed(an3, p, 0, 30)                                                # alarm vermemiş bölüm bildirilmez
    assert an3.phone.active() and an3.end_all() == []


def test_phone_episode_ends_after_person_leaves() -> None:
    p = phone_only(10.0)
    an, det, _pose = make_phone(p)
    tid = next(a.track_id for r in feed(an, p, 0, 120) for a in r.fired)
    det.boxes = []
    ends = [e for r in feed(an, p, 120, 300) for e in r.ended]
    assert ends == [(tid, "phone", True)]


def test_draw_safety_labels_phone() -> None:
    from bantvision.overlay import _SAFETY_LABELS, RED, draw_safety

    assert _SAFETY_LABELS["phone"] == "TELEFON"
    r = SafetyResult(active=[(7, "phone", 61.0, True)], boxes={7: (0.4, 0.2, 0.6, 0.9)})
    assert (draw_safety(FRAME.copy(), Profile.jeweler(), r) == np.array(RED, np.uint8)).all(axis=2).any()


def test_analyzer_active_includes_phone_and_pose_episodes() -> None:
    """`SafetyAnalyzer.active()`: eller yukarı/yatma ve telefon bölümleri aynı biçimde (canlı durum bunu okur)."""
    p = phone_only(10.0)
    p.safety.handsUp.enabled = True
    an, _det, pose = make_phone(p)
    res = feed(an, p, 0, 30)
    assert any(a[1] == "phone" for a in an.active()) and an.active() == res[-1].active
    pose.kp = hands_up_kp()                                            # eller yukarı da başlar
    res = feed(an, p, 30, 40)
    kinds = {a[1] for a in an.active()}
    assert kinds == {"phone", "hands_up"} and an.active() == res[-1].active


def test_phone_alarm_started_is_episode_start_even_when_firing_frame_is_a_miss() -> None:
    """Alarm ıska karesinde doğsa da başlangıç ilk isabettir (ts − süre değil: süre son isabette durur)."""
    p = phone_only(10.0)
    an, det, _pose = make_phone(p)
    res = feed(an, p, 0, 10)
    k0 = next(j for j, r in enumerate(res) if r.tracks)                # ilk arama ve ilk isabet
    feed(an, p, 10, k0 + 61)                                           # 6 sn telefon elde: iki dilimde de isabet
    det.phones = []                                                    # sonra hep ıska
    fired = [(k, a) for k, r in enumerate(feed(an, p, k0 + 61, 150), k0 + 61) for a in r.fired]
    assert len(fired) == 1
    k, alarm = fired[0]
    assert k >= k0 + 100                                               # 10 sn gözlemde, ıska karesinde doğdu
    assert abs(alarm.started - k0 / 10) < 1e-9                         # ts − süre olsaydı ≈ 4 sn geç


FIVE = [(20 + 120 * i, 80, 100 + 120 * i, 440) for i in range(5)]     # yan yana beş kişi


def _spy_searches(monkeypatch: pytest.MonkeyPatch) -> list[tuple[float, float]]:
    """`safety.find_phones` sarılır: her aramanın kişi kutusunun sol üstü (piksel) kaydedilir."""
    import bantvision.core.safety as safety_mod

    seen: list[tuple[float, float]] = []
    real = safety_mod.find_phones

    def spy(detector: object, bgr: np.ndarray, box_px: tuple[float, float, float, float]) -> list[object]:
        seen.append((round(box_px[0]), round(box_px[1])))
        return real(detector, bgr, box_px)

    monkeypatch.setattr(safety_mod, "find_phones", spy)
    return seen


def test_phone_search_budget_per_frame_and_every_person_is_searched(monkeypatch: pytest.MonkeyPatch) -> None:
    from bantvision.core.phone_rules import PHONE_FPS, PHONE_MAX_PER_FRAME

    assert PHONE_MAX_PER_FRAME == 2
    seen = _spy_searches(monkeypatch)
    p = phone_only(60.0)
    det, pose = FakePhoneDetector(FIVE, phones=[]), FakePose(phone_kp())
    an = SafetyAnalyzer(detector=det, pose=pose)
    per_frame: list[int] = []
    first = None
    for k in range(100):                                              # 10 kare/sn, 10 sn
        before = len(seen)
        r = an.process(FRAME, p, 10.0, k / 10)
        per_frame.append(len(seen) - before)
        if first is None and len(r.tracks) == 5:
            first = k
            searched_from = before
    assert first is not None and max(per_frame) <= PHONE_MAX_PER_FRAME
    assert det.phone_calls == len(seen)
    # beş kişi 3 karede (2 + 2 + 1) en az bir kez aranır: hiç aranmamış iz önce gelir
    assert len({x for x, _ in seen[searched_from:searched_from + 5]}) == 5
    # her kişi kendi hızında (≤ PHONE_FPS/sn) aranmaya devam eder; bütçe (20/sn) beş kişiye (10/sn) yeter
    span = (100 - first) / 10
    for x in {b[0] for b in FIVE}:
        n = sum(1 for sx, _ in seen if sx == x)
        assert PHONE_FPS * span - 2 <= n <= PHONE_FPS * span + 1


def test_phone_budget_is_shared_fairly_when_people_exceed_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """1 kare/sn akışta beş kişi her kare aranmak ister ama kare başına 2: en uzun süredir aranmamış olan önce."""
    seen = _spy_searches(monkeypatch)
    p = phone_only(60.0)
    an = SafetyAnalyzer(detector=FakePhoneDetector(FIVE, phones=[]), pose=FakePose(phone_kp()))
    counts: list[int] = []
    for k in range(30):
        before = len(seen)
        r = an.process(FRAME, p, 1.0, float(k))
        counts.append(len(seen) - before)
        if len(an._phone_last) == 5:                                   # herkes en az bir kez arandıktan sonra:
            assert max(k - v for v in an._phone_last.values()) <= 2    # kimse 3 kareden uzun beklemez
    assert max(counts) == 2 and len(r.tracks) == 5 and len(an._phone_last) == 5
    assert sorted({x for x, _ in seen[-10:]}) == sorted(b[0] for b in FIVE)


def test_no_visible_wrist_or_head_makes_no_phone_search(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _spy_searches(monkeypatch)
    p = phone_only(10.0)
    an, det, pose = make_phone(p)
    kp = phone_kp()
    kp[[0, 1, 2, 3, 4, 9, 10], 2] = 0.0                                # bilek ve baş yok (ölçek var)
    pose.kp = kp
    res = feed(an, p, 0, 50)
    assert any(r.tracks for r in res) and pose.calls > 0
    assert seen == [] and det.phone_calls == 0 and an._phone_last == {}
    pose.kp = phone_kp()                                               # bilekler görünür olunca hemen aranır
    an.process(FRAME, p, 10.0, 5.0)
    assert det.phone_calls == 1


def test_person_touching_frame_edge_is_phone_searched_and_can_fire() -> None:
    """Kutu sol kenarda: kırpıntı kareye sınırlanır (çökmez), telefon tam kareye doğru taşınır ve alarm doğar."""
    p = phone_only(10.0)
    kp = phone_kp()
    kp[:, 0] -= 280                                                    # eklemler kutuyla birlikte sola: bilek (10, 260)
    det = FakePhoneDetector([(0, 80, 80, 440)], phones=[(0.0, 242.0, 20.0, 262.0, 0.4)])   # kırpıntı (0, 8)'den
    an = SafetyAnalyzer(detector=det, pose=FakePose(kp))
    fired = [a for r in feed(an, p, 0, 120) for a in r.fired]
    shapes = [sh for c, sh in zip(det.calls, det.shapes) if c == ["cell phone"]]
    assert shapes and all(sh[1] == 96 for sh in shapes)                # x 0–96 (sol pay kareye kırpıldı)
    assert len(fired) == 1 and fired[0].kind == "phone" and fired[0].box[0] < 0.01
