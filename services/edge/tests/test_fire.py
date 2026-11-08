"""FireAnalyzer (core/fire.py): sahte dedektör + sentetik kareyle karar katmanı (R4–R6, Review Focus 1–4)."""
from __future__ import annotations

import numpy as np
import pytest
from fakes_fire import FakeFireDetector, H, Item, W, ended, fired, make, run

from bantvision.core import Pipeline, Profile
from bantvision.core.fire import FireAlarm, FireAnalyzer, FireResult
from bantvision.core.fire_model import FireModelMissing
from bantvision.core.fire_rules import END_S, THRESHOLDS

FLAME = (280.0, 200.0, 360.0, 280.0)                                   # 640×480 ortasında 80×80 alev
SMOKE = (60.0, 60.0, 180.0, 140.0)


def flame_from(t0: float, box: tuple[float, float, float, float] = FLAME, moving: bool = True, score: float = 0.9,
               cls: str = "fire", until: float = 1e9):
    def script(ts: float) -> list[Item]:
        return [(cls, box, score, moving)] if t0 <= ts < until else []
    return script


# ---------------------------------------------------------------- temel alarm

def test_moving_fire_alarms_once_after_rule_seconds_with_normalised_box() -> None:
    an, det, p = make(flame_from(2.0))
    res = run(an, det, p, 25.0, 0.0, 12.0)
    alarms = fired(res)
    assert len(alarms) == 1                                            # bölüm başına tek alarm
    ts, a = alarms[0]
    assert isinstance(a, FireAlarm) and (a.kind, a.track_id) == ("fire", 0)
    assert a.started == pytest.approx(2.0) and 3.0 - 1e-9 <= ts - 2.0 <= 3.0 + 1 / 25 + 1e-9 and a.ts == ts
    assert a.box == pytest.approx((280 / W, 200 / H, 360 / W, 280 / H))
    last = res[-1][1]
    assert last.active == [(0, "fire", pytest.approx(12.0 - 1 / 25 - 2.0), True)]
    assert last.boxes == {0: pytest.approx((280 / W, 200 / H, 360 / W, 280 / H))}
    kind, box, score, moved = last.detections[0]
    assert (kind, score, moved) == ("fire", 0.9, True) and box == pytest.approx(a.box)


def test_no_alarm_before_rule_seconds_and_active_episode_reports_duration() -> None:
    an, det, p = make(flame_from(2.0))
    res = run(an, det, p, 5.0, 0.0, 5.0)
    assert fired(res) == [] and res[-1][1].boxes == {}
    assert res[-1][1].active == [(0, "fire", pytest.approx(2.8), False)]


def test_first_frame_has_no_motion_reference_and_does_not_vote() -> None:
    an, det, p = make(flame_from(0.0))
    res = run(an, det, p, 25.0, 0.0, 0.08)
    first, second = res[0][1], res[1][1]
    assert first.detections[0][3] is False and first.active == []
    assert second.detections[0][3] is True and second.active == [(0, "fire", 0.0, False)]


# ---------------------------------------------------------------- Review Focus 1: durağan alev resmi / kırmızı lamba

def test_static_flame_picture_never_alarms() -> None:
    an, det, p = make(flame_from(0.0, moving=False, score=0.95))
    res = run(an, det, p, 5.0, 0.0, 30.0)
    assert fired(res) == [] and all(r.active == [] for _, r in res)
    assert all(r.detections and r.detections[0][3] is False for _, r in res)   # kutu geçerli ama durağan


# ---------------------------------------------------------------- Review Focus 2: ışık patlaması / IR geçişi

def test_ir_flicker_frames_do_not_vote_and_cannot_alarm_alone() -> None:
    """Kare geneli her karede değişiyor (IR aç/kapa): durağan alev resmi içi de değişir ama kareler oy dışıdır."""
    an, det, p = make(flame_from(0.0, moving=False, score=0.95))
    res = run(an, det, p, 5.0, 0.0, 20.0, flash=lambda ts: 70 if round(ts * 5) % 2 else 0)
    assert fired(res) == [] and all(r.active == [] for _, r in res)
    assert all(not d[3] for _, r in res for d in r.detections)


def test_light_step_is_not_motion() -> None:
    an, det, p = make(flame_from(0.0, moving=False, score=0.95))
    res = run(an, det, p, 5.0, 0.0, 20.0, flash=lambda ts: 70 if ts >= 5.0 else 0)
    assert fired(res) == [] and all(r.active == [] for _, r in res)


def test_flash_frames_are_left_out_of_the_window_not_counted_against_fire() -> None:
    """Gerçek alev sürerken 1 sn ışık patlaması: patlama kareleri ve onlarla kıyaslanan sonraki 1 sn oy dışı (10/16
    kare). Olumsuz sayılsalardı oran 6/16 < 0,6 olur, alarm gecikirdi; pencere dışı oldukları için alarm zamanında."""
    an, det, p = make(flame_from(2.0))
    res = run(an, det, p, 5.0, 0.0, 8.0, flash=lambda ts: 70 if 3.0 <= ts < 4.0 else 0)
    alarms = fired(res)
    assert len(alarms) == 1 and alarms[0][0] == pytest.approx(5.0)


def test_flash_frames_do_not_extend_an_episode() -> None:
    """Alev 3,4 sn'de durağan bir resme döner ve kare titremeye başlar: titreyen kareler kutu içini de değiştirir ama
    oy dışıdır, bölümü uzatmaz; END_S son olumlu kareden (geçiş kareleri dahil en geç 4,0) sayılır."""
    def script(ts: float) -> list[Item]:
        return [("fire", FLAME, 0.9, ts < 3.4)] if ts >= 2.0 else []

    an, det, p = make(script)
    res = run(an, det, p, 5.0, 0.0, 20.0, flash=lambda ts: (70 if round(ts * 5) % 2 else 0) if ts >= 3.4 else 0)
    ends = ended(res)
    assert len(ends) == 1 and ends[0][1][:2] == (0, "fire")
    assert 3.2 + END_S - 1e-9 <= ends[0][0] <= 4.0 + END_S + 1e-9          # titreme 20. sn'ye dek sürse de bitti


# ---------------------------------------------------------------- Review Focus 3: 1 kare/sn ve 25 kare/sn

@pytest.mark.parametrize("fps", [1.0, 5.0, 25.0])
@pytest.mark.parametrize("kind,seconds", [("fire", 3.0), ("smoke", 8.0), ("fire", 2.0)])
def test_alarm_time_is_rule_seconds_at_any_frame_rate(fps: float, kind: str, seconds: float) -> None:
    p = Profile.fire_watch()
    getattr(p.fire, kind).seconds = seconds
    an, det, _ = make(flame_from(4.0, cls=kind), p)
    res = run(an, det, p, fps, 0.0, 4.0 + seconds + 3.0)
    alarms = fired(res)
    assert len(alarms) == 1
    ts, a = alarms[0]
    assert a.kind == kind and a.started == pytest.approx(4.0)
    assert seconds - 1e-9 <= ts - 4.0 <= seconds + 1 / fps + 1e-9


# ---------------------------------------------------------------- Review Focus 4: hariç bölge

ZONE = [(0.1, 0.5), (0.4, 0.5), (0.4, 0.9), (0.1, 0.9)]                 # x 64–256, y 240–432 (ocak)


def test_flame_inside_ignore_zone_never_alarms_but_spill_outside_does() -> None:
    stove = (100.0, 300.0, 200.0, 400.0)
    overflow = (100.0, 200.0, 250.0, 420.0)                             # bölgeden taşıyor ama merkezi içeride
    spill = (180.0, 150.0, 420.0, 330.0)                                # merkezi (300, 240) bölge dışında

    def script(ts: float) -> list[Item]:
        if ts < 10.0:
            return [("fire", stove, 0.9, True)]
        if ts < 20.0:
            return [("fire", overflow, 0.9, True)]
        return [("fire", spill, 0.9, True)]

    p = Profile.fire_watch()
    p.fire.ignoreZones = [ZONE]
    an, det, _ = make(script, p)
    res = run(an, det, p, 5.0, 0.0, 26.0)
    assert all(r.detections == [] for ts, r in res if ts < 20.0)        # bölgedeki kutu hiç geçerli sayılmaz
    alarms = fired(res)
    assert len(alarms) == 1 and 23.0 - 1e-9 <= alarms[0][0] <= 23.2 + 1e-9
    assert alarms[0][1].box == pytest.approx((180 / W, 150 / H, 420 / W, 330 / H))


# ---------------------------------------------------------------- kurallar, eşik, en küçük kutu

def test_disabled_class_is_never_processed() -> None:
    def script(ts: float) -> list[Item]:
        return [("fire", FLAME, 0.9, True), ("smoke", SMOKE, 0.9, True)]

    p = Profile.fire_watch()
    p.fire.smoke.enabled = False
    an, det, _ = make(script, p)
    res = run(an, det, p, 5.0, 0.0, 15.0)
    assert {a.kind for _, a in fired(res)} == {"fire"}
    assert all(set(c) == {"fire"} for c in det.calls)                   # dedektöre duman eşiği hiç gitmez
    assert all(d[0] == "fire" for _, r in res for d in r.detections)
    assert all(a[1] == "fire" for _, r in res for a in r.active)

    q = Profile.fire_watch()
    q.fire.fire.enabled = q.fire.smoke.enabled = False
    an2, det2, _ = make(script, q)
    res2 = run(an2, det2, q, 5.0, 0.0, 15.0)
    assert det2.calls == [] and fired(res2) == [] and all(r.detections == [] for _, r in res2)


@pytest.mark.parametrize("sens", ["low", "normal", "high"])
def test_detector_gets_sensitivity_thresholds(sens: str) -> None:
    p = Profile.fire_watch()
    p.fire.sensitivity = sens
    an, det, _ = make(flame_from(0.0, score=0.50), p)
    res = run(an, det, p, 5.0, 0.0, 1.0)
    assert det.calls and all(c == THRESHOLDS[sens] for c in det.calls)
    assert bool(res[-1][1].detections) == (0.50 >= THRESHOLDS[sens]["fire"])


def test_analyzer_drops_scores_below_threshold_even_if_detector_returns_them() -> None:
    class Loose(FakeFireDetector):
        def detect(self, _bgr: np.ndarray, conf: dict[str, float]):
            self.calls.append(dict(conf))
            from bantvision.core.detector import Detection
            return [Detection(*FLAME, 0.2, "fire"), Detection(*SMOKE, 0.9, "unknown")]

    det = Loose(flame_from(0.0))
    an, p = FireAnalyzer(detector=det), Profile.fire_watch()
    res = run(an, det, p, 5.0, 0.0, 6.0)
    assert all(r.detections == [] for _, r in res) and fired(res) == []


def test_tiny_boxes_are_dropped() -> None:
    def script(ts: float) -> list[Item]:
        return [("fire", (100.0, 100.0, 300.0, 107.0), 0.9, True),     # kısa kenar 7 px < 7,2 px
                ("smoke", (400.0, 100.0, 408.0, 300.0), 0.9, True)]     # 8 px: kalır

    an, det, p = make(script)
    res = run(an, det, p, 5.0, 0.0, 1.0)
    assert [d[0] for d in res[-1][1].detections] == ["smoke"]


# ---------------------------------------------------------------- bölüm yaşam döngüsü

def test_episode_ends_end_s_after_last_positive_and_a_new_episode_alarms_again() -> None:
    an, det, p = make(lambda ts: [("fire", FLAME, 0.9, True)] if 2.0 <= ts < 8.0 or 30.0 <= ts else [])
    res = run(an, det, p, 5.0, 0.0, 40.0)
    ends = ended(res)
    assert len(ends) == 1 and ends[0][1] == (0, "fire", True)
    assert ends[0][0] == pytest.approx(7.8 + END_S)                     # son olumlu kare 7,8
    assert all(r.active == [] and r.boxes == {} for ts, r in res if ends[0][0] <= ts < 30.0)
    alarms = fired(res)
    assert [round(ts, 1) for ts, _ in alarms] == [5.0, 33.0]            # yeni bölüm yeniden alarm verir
    assert alarms[1][1].started == pytest.approx(30.0)


def test_episode_survives_short_gaps_shorter_than_end_s() -> None:
    an, det, p = make(lambda ts: [("fire", FLAME, 0.9, True)] if 2.0 <= ts < 6.0 or 12.0 <= ts else [])
    res = run(an, det, p, 5.0, 0.0, 20.0)
    assert len(fired(res)) == 1 and ended(res) == []


def test_episode_without_alarm_ends_with_false() -> None:
    an, det, p = make(flame_from(2.0, until=3.0))
    res = run(an, det, p, 5.0, 0.0, 15.0)
    assert fired(res) == [] and [e for _, e in ended(res)] == [(0, "fire", False)]


def test_fire_and_smoke_at_the_same_time() -> None:
    def script(ts: float) -> list[Item]:
        return [("fire", FLAME, 0.9, True), ("smoke", SMOKE, 0.8, True)] if ts >= 1.0 else []

    an, det, p = make(script)
    res = run(an, det, p, 5.0, 0.0, 12.0)
    alarms = {a.kind: (ts, a) for ts, a in fired(res)}
    assert set(alarms) == {"fire", "smoke"} and len(fired(res)) == 2
    assert alarms["fire"][1].track_id == 0 and alarms["smoke"][1].track_id == 1
    assert alarms["fire"][0] == pytest.approx(4.0) and alarms["smoke"][0] == pytest.approx(9.0)
    last = res[-1][1]
    assert sorted(a[:2] for a in last.active) == [(0, "fire"), (1, "smoke")]
    assert last.boxes[1] == pytest.approx((60 / W, 60 / H, 180 / W, 140 / H))


def test_alarm_box_is_union_of_last_frame_boxes_touching_trigger_cell() -> None:
    a, b = (280.0, 200.0, 330.0, 260.0), (335.0, 210.0, 380.0, 280.0)
    far = (560.0, 400.0, 620.0, 460.0)

    def script(ts: float) -> list[Item]:
        if ts < 1.0:
            return []
        boxes = [("fire", a, 0.9, True), ("fire", b, 0.9, True)]
        return boxes + ([("fire", far, 0.9, True)] if ts >= 3.5 else [])

    an, det, p = make(script)
    _ts, alarm = fired(run(an, det, p, 5.0, 0.0, 6.0))[0]
    assert alarm.box == pytest.approx((280 / W, 200 / H, 380 / W, 280 / H))


# ---------------------------------------------------------------- mekânsal oy: dağınık vs kayan

def test_scattered_single_frame_boxes_never_alarm() -> None:
    """Her kare başka, komşu olmayan bir hücrede tek kare kutu (yansıma/parıltı): oran hiçbir hücrede 0,6'ya ulaşmaz."""
    cells = [(0, 0), (3, 0), (6, 0), (1, 4), (5, 4)]                    # (sütun, satır); komşulukları ayrık
    rng = np.random.default_rng(7)
    order: list[tuple[int, int]] = []
    for _ in range(100):
        order += [cells[i] for i in rng.permutation(len(cells))]
    cw, ch = W / 8, H / 6

    def script(ts: float) -> list[Item]:
        c, r = order[round(ts * 5)]
        return [("fire", (c * cw + 10, r * ch + 10, c * cw + 60, r * ch + 60), 0.9, True)]

    an, det, p = make(script)
    res = run(an, det, p, 5.0, 0.0, 60.0)
    assert fired(res) == []
    assert any(r.active for _, r in res)                                # bölüm açıldı ama oy tutmadı


def test_slowly_drifting_smoke_alarms() -> None:
    """30 px duman kutusu saniyede 25 px kayar (8 sn'de 2,5 hücre): hiçbir hücreyi kendisi pencerenin %60'ında kaplamaz
    (en çok 4,4/8 sn), komşuluk kabulüyle 1. sütun 8 sn boyunca olumlu kalır."""
    def script(ts: float) -> list[Item]:
        x = 20.0 + ts * 25.0
        return [("smoke", (x, 150.0, x + 30.0, 180.0), 0.9, True)]

    an, det, p = make(script)
    alarms = fired(run(an, det, p, 5.0, 0.0, 20.0))
    assert len(alarms) == 1 and alarms[0][1].kind == "smoke"
    assert 8.2 - 1e-9 <= alarms[0][0] <= 8.4 + 1e-9                     # ilk olumlu kare 0,2; kural 8 sn


# ---------------------------------------------------------------- reset / end_all / zaman geri gider

def test_reset_reports_alarmed_episode_as_ended_on_next_process() -> None:
    an, det, p = make(flame_from(1.0))
    run(an, det, p, 5.0, 0.0, 6.0)
    an.reset()
    res = run(an, det, p, 5.0, 6.0, 6.4)
    assert res[0][1].ended == [(0, "fire", True)] and res[0][1].boxes == {}
    assert res[1][1].ended == []                                        # yalnızca bir kez
    assert res[0][1].detections[0][3] is False                          # hareket geçmişi de sıfırlandı


def test_reset_does_not_report_episode_that_never_fired() -> None:
    an, det, p = make(flame_from(1.0))
    run(an, det, p, 5.0, 0.0, 2.0)
    an.reset()
    assert run(an, det, p, 5.0, 2.0, 2.2)[0][1].ended == []


def test_end_all_returns_open_alarmed_episodes_and_pending_reset_ends() -> None:
    def script(ts: float) -> list[Item]:
        return [("fire", FLAME, 0.9, True), ("smoke", SMOKE, 0.9, True)] if ts >= 1.0 else []

    an, det, p = make(script)
    run(an, det, p, 5.0, 0.0, 6.0)                                      # alev alarmlı, duman henüz değil
    assert an.end_all() == [(0, "fire", True)]
    assert an.end_all() == []

    an2, det2, p2 = make(flame_from(1.0))
    run(an2, det2, p2, 5.0, 0.0, 6.0)
    an2.reset()
    assert an2.end_all() == [(0, "fire", True)] and an2.end_all() == []


def test_time_going_backwards_ends_episodes_and_restarts_cleanly() -> None:
    an, det, p = make(flame_from(1.0))
    run(an, det, p, 5.0, 0.0, 6.0)
    res = run(an, det, p, 5.0, 0.0, 6.0)                                # video başa sardı
    assert res[0][1].ended == [(0, "fire", True)]
    assert [round(ts, 1) for ts, _ in fired(res)] == [4.0]              # geçmiş atıldı; alev yine 1,0'da başlar


# ---------------------------------------------------------------- hata, varsayılan, pipeline

def test_detector_errors_propagate() -> None:
    class Missing:
        def detect(self, _bgr: np.ndarray, _conf: dict[str, float]) -> list[object]:
            raise FireModelMissing("Yangın/duman modeli kurulu değil.")

    an = FireAnalyzer(detector=Missing())
    with pytest.raises(FireModelMissing):
        an.process(np.zeros((H, W, 3), np.uint8), 0.0, Profile.fire_watch())


def test_detector_error_after_reset_keeps_pending_ended() -> None:
    """reset() ile kesilen alarmlı bölüm, dedektör bir kez hata verse de kaybolmaz: sonraki başarılı `process` ya da
    `end_all` bildirir (alarm günlüğü sonsuza dek açık kalmaz)."""
    class Flaky(FakeFireDetector):
        fail = False

        def detect(self, bgr: np.ndarray, conf: dict[str, float]) -> list:  # type: ignore[override]
            if self.fail:
                self.fail = False
                raise FireModelMissing("Yangın/duman modeli kurulu değil.")
            return super().detect(bgr, conf)

    for finish in ("process", "end_all"):
        det = Flaky(flame_from(1.0))
        an, p = FireAnalyzer(detector=det), Profile.fire_watch()
        assert fired(run(an, det, p, 5.0, 0.0, 6.0))                   # alarm doğdu
        an.reset()
        det.fail = True
        with pytest.raises(FireModelMissing):
            run(an, det, p, 5.0, 6.0, 6.2)
        if finish == "process":
            res = run(an, det, p, 5.0, 6.2, 6.6)
            assert res[0][1].ended == [(0, "fire", True)] and res[1][1].ended == []
            assert an.end_all() == []
        else:
            assert an.end_all() == [(0, "fire", True)] and an.end_all() == []


def test_detector_error_after_time_went_backwards_keeps_pending_ended() -> None:
    det = type("Once", (FakeFireDetector,), {})(flame_from(1.0))
    an, p = FireAnalyzer(detector=det), Profile.fire_watch()
    run(an, det, p, 5.0, 0.0, 6.0)
    orig = det.detect

    def boom(_bgr: np.ndarray, _conf: dict[str, float]) -> list:
        det.detect = orig  # type: ignore[method-assign]
        raise FireModelMissing("Yangın/duman modeli kurulu değil.")

    det.detect = boom  # type: ignore[method-assign]
    with pytest.raises(FireModelMissing):
        run(an, det, p, 5.0, 0.0, 0.2)                                  # video başa sardı, tanıma hata verdi
    res = run(an, det, p, 5.0, 0.2, 0.6)
    assert res[0][1].ended == [(0, "fire", True)]


def test_profile_without_fire_block_uses_defaults() -> None:
    p = Profile.fire_watch()
    p.fire = None  # type: ignore[assignment]
    an, det, _ = make(flame_from(1.0), p)
    res = run(an, det, p, 5.0, 0.0, 6.0)
    assert det.calls[-1] == THRESHOLDS["normal"] and len(fired(res)) == 1


def test_pipeline_routes_fire_mode_and_resets_analyzer() -> None:
    p = Profile.fire_watch()
    pipe = Pipeline(p)
    det = FakeFireDetector(flame_from(1.0))
    pipe.fire = FireAnalyzer(detector=det)
    rng = np.random.default_rng(0)
    from fakes_fire import scene

    r = None
    for k in range(30):
        det.ts = k / 5
        r = pipe.process(scene(det.script(det.ts), rng), det.ts)
    assert r is not None and isinstance(r.fire, FireResult) and r.safety is None
    assert r.counts == [] and pipe.total == 0 and r.frame_size == (W, H)
    assert r.fire.boxes                                                 # 6. sn: alarm verdi
    pipe.reset_count()
    det.ts = 6.0
    r = pipe.process(scene(det.script(6.0), rng), 6.0)
    assert r.fire is not None and r.fire.ended == [(0, "fire", True)]
    pipe.set_profile(Profile.fire_watch())
    assert pipe.fire.end_all() == []
