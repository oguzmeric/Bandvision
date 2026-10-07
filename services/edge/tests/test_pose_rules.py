"""Poz güvenlik kuralları (tasarım: docs/superpowers/specs/2026-10-06-poz-guvenlik-design.md)."""
from __future__ import annotations

import numpy as np

from bantvision.core.pose_rules import (
    ELBOW_DOWN,
    FIRED_GRACE_S,
    WRIST_UP,
    EpisodeTracker,
    hands_up,
    lying,
    scale,
)


def person(**pts: tuple[float, float] | None) -> np.ndarray:
    """Ayakta kişi (y aşağı): baş 100, omuzlar 160, dirsekler 230, bilekler 290, kalça 330, diz 430, ayak 520.
    Anahtarla eklem taşınır; None verilen eklem görünmez (güven 0)."""
    base = {0: (200, 100), 1: (192, 92), 2: (208, 92), 3: (184, 98), 4: (216, 98), 5: (170, 160), 6: (230, 160),
            7: (160, 230), 8: (240, 230), 9: (158, 290), 10: (242, 290), 11: (180, 330), 12: (220, 330),
            13: (180, 430), 14: (220, 430), 15: (180, 520), 16: (220, 520)}
    names = {"nose": 0, "l_sh": 5, "r_sh": 6, "l_el": 7, "r_el": 8, "l_wr": 9, "r_wr": 10, "l_hip": 11, "r_hip": 12}
    kp = np.zeros((17, 3))
    for i, (x, y) in base.items():
        kp[i] = (x, y, 0.9)
    for k, v in pts.items():
        i = names[k]
        if v is None:
            kp[i, 2] = 0.0
        else:
            kp[i, :2] = v
    return kp


def test_scale_uses_torso_or_head() -> None:
    assert scale(person()) == 170.0                                         # omuz ortası 160 → kalça ortası 330
    s = scale(person(l_hip=None, r_hip=None))
    assert s is not None and abs(s - 2.5 * 60) < 1e-6                       # baş 100 → omuz 160
    assert scale(person(l_sh=None)) is None


def test_hands_up_surrender_and_overhead() -> None:
    assert hands_up(person()) is False
    up = person(l_el=(150, 150), r_el=(250, 150), l_wr=(150, 90), r_wr=(250, 90))       # teslim: dirsek omuz hizası
    assert hands_up(up) is True
    over = person(l_el=(165, 110), r_el=(235, 110), l_wr=(175, 40), r_wr=(225, 40))     # baş üstü
    assert hands_up(over) is True


def test_hands_up_needs_both_hands_and_handles_counter() -> None:
    one = person(l_el=(150, 150), l_wr=(150, 90))                            # tek el (rafa uzanma)
    assert hands_up(one) is False
    counter = person(l_hip=None, r_hip=None, l_el=(150, 150), r_el=(250, 150), l_wr=(150, 90), r_wr=(250, 90))
    assert hands_up(counter) is True                                         # kalça tezgah arkasında
    assert hands_up(person(l_wr=None)) is None                               # bilek görünmüyor


def test_hands_up_low_elbows_rejected() -> None:
    wave = person(l_el=(150, 260), r_el=(250, 260), l_wr=(150, 100), r_wr=(250, 100))  # dirsek aşağıda
    assert hands_up(wave) is False


def test_hands_up_thresholds_from_real_camera_measurement() -> None:
    """Gerçek kamera ölçümü (2026-10-07, yüksekten eğik bakan NVR kamerası): teslim duruşunda bilek omzun
    0,19–0,37·s üstünde, dirsek omzun 0,14·s altına kadar. Eşikler: bilek ≥ 0,20·s üstte, dirsek ≤ 0,30·s altta."""
    assert (WRIST_UP, ELBOW_DOWN) == (0.20, 0.30)
    s = 170.0                                                                # person(): omuz 160, kalça ortası 330

    def pose(wrist_up: float, elbow_down: float) -> np.ndarray:
        wy, ey = 160 - wrist_up * s, 160 + elbow_down * s
        return person(l_el=(150, ey), r_el=(250, ey), l_wr=(150, wy), r_wr=(250, wy))

    assert hands_up(pose(0.21, 0.14)) is True                                # eğik kamerada ölçülen teslim
    assert hands_up(pose(0.20, 0.29)) is True                                # sınırlar dahil
    assert hands_up(pose(0.19, 0.0)) is False                                # bilek yeterince yukarıda değil
    assert hands_up(pose(0.30, 0.31)) is False                               # dirsek çok aşağıda


def test_hands_at_chest_height_or_below_are_not_hands_up() -> None:
    for wy in (160, 200, 250, 290):                                          # omuz hizası, göğüs, bel, aşağıda
        assert hands_up(person(l_el=(150, 230), r_el=(250, 230), l_wr=(150, wy), r_wr=(250, wy))) is False, wy
    assert hands_up(person(l_wr=(150, 130), r_wr=(250, 130))) is False       # omzun 0,18·s üstü (çene hizası)


def lying_person(direction: str) -> np.ndarray:
    if direction == "side":                                                  # yatay: baş solda
        return person(nose=(100, 400), l_sh=(160, 390), r_sh=(160, 410), l_hip=(330, 390), r_hip=(330, 410))
    return person(nose=(200, 520), l_sh=(190, 470), r_sh=(210, 470), l_hip=(190, 420), r_hip=(210, 420))  # kameraya doğru


def test_lying_horizontal_and_toward_camera() -> None:
    assert lying(lying_person("side")) is True
    assert lying(lying_person("toward")) is True                             # baş kalçanın altında
    assert lying(person()) is False


def test_lying_rejects_bending_sitting_and_needs_hips() -> None:
    bend = person(nose=(250, 300), l_sh=(225, 280), r_sh=(255, 300))         # eğilme: ~45°, baş kalçanın üstünde
    assert lying(bend) is False
    sit = person(l_hip=(180, 260), r_hip=(220, 260))                          # oturma: gövde dik
    assert lying(sit) is False
    assert lying(person(l_hip=None, r_hip=None)) is None                     # tezgah arkasında ayakta


def test_lying_foreshortened_via_head_condition() -> None:
    # θ small but head.y >= hip.y - 0.1*s: True via head condition only
    foreshortenend = person(
        nose=(200, 440), l_sh=(190, 410), r_sh=(210, 410), l_hip=(190, 420), r_hip=(210, 420)
    )
    assert lying(foreshortenend) is True
    # Same pose with head well above hips: False (head branch fails)
    head_high = person(nose=(200, 300), l_sh=(190, 410), r_sh=(210, 410), l_hip=(190, 420), r_hip=(210, 420))
    assert lying(head_high) is False


def test_lying_rejects_crouch() -> None:
    # Crouch: shoulders above hips, head well above hips, θ small → lying False
    crouch = person(nose=(200, 250), l_sh=(180, 300), r_sh=(220, 300), l_hip=(175, 360), r_hip=(225, 360))
    assert lying(crouch) is False


def test_episode_fires_once_after_threshold() -> None:
    ep = EpisodeTracker()
    fired = [ep.update((1, "hands_up"), True, t / 10, 3.0) for t in range(50)]
    assert fired.index(True) == 30 and sum(fired) == 1


def test_episode_grace_and_end() -> None:
    ep = EpisodeTracker()
    for t in range(20):
        ep.update((1, "lying"), True, t / 10, 10.0)
    ep.update((1, "lying"), None, 2.2, 10.0)                                 # 0,3 sn kopma: affedilir
    assert ep.sweep(2.3, {1}) == []
    assert ep.active()[0][:2] == (1, "lying")
    assert ep.sweep(2.6, {1}) == [((1, "lying"), False)]                     # > 0,5 sn: biter, alarm yoktu
    assert ep.active() == []


def test_episode_ends_when_track_lost_and_reports_fired() -> None:
    """Alarm vermiş bölüm iz kaybolunca da ancak son True'dan FIRED_GRACE_S sonra biter (kısa kopma çift alarm vermesin)."""
    ep = EpisodeTracker()
    for t in range(40):
        ep.update((7, "hands_up"), True, t / 10, 3.0)                       # son True 3,9
    assert ep.sweep(4.0, set()) == [] and ep.sweep(6.8, set()) == []
    assert ep.sweep(7.0, set()) == [((7, "hands_up"), True)]                 # 3,1 sn > FIRED_GRACE_S
    assert ep.active() == []
    assert not ep.update((7, "hands_up"), True, 7.1, 3.0)                    # yeni bölüm baştan sayar
    assert ep.active() == [(7, "hands_up", 0.0, False)]
    # Episode fires again when threshold is reached (use large grace to keep episode open)
    assert ep.update((7, "hands_up"), True, 10.1, 3.0, grace_s=10.0)           # 10.1 - 7.1 = 3.0 >= 3.0
    ep2 = EpisodeTracker()
    for t in range(20):
        ep2.update((8, "hands_up"), True, t / 10, 3.0)                      # alarm yok
    assert ep2.sweep(2.0, set()) == [((8, "hands_up"), False)]              # alarmsız bölüm iz kaybında hemen biter


def test_fired_episode_survives_two_second_dropout_without_refiring() -> None:
    """Canlıda görülen: bölüm 15:52:44'te alarm verdi, bir saniye içinde koptu, 15:52:47'de yeniden alarm verdi (tek olaya
    iki kayıt). Alarm vermiş bölüm FIRED_GRACE_S (3 sn) boyunca sürer: 2 sn kopma aynı bölüm, yeniden alarm yok."""
    assert FIRED_GRACE_S == 3.0
    ep, key = EpisodeTracker(), (1, "hands_up")
    fired = [ep.update(key, True, t / 10, 3.0) for t in range(36)]           # 0–3,5 sn: 3,0'da alarm
    assert sum(fired) == 1
    for t in range(36, 56):                                                  # 3,6–5,5: 2 sn kopma (karar yok/yanlış)
        assert not ep.update(key, None if t % 2 else False, t / 10, 3.0)
        assert ep.sweep(t / 10, {1}) == []
    refired = [ep.update(key, True, t / 10, 3.0) for t in range(56, 100)]    # kişi yine eller yukarı
    assert not any(refired) and ep.sweep(9.9, {1}) == []
    (a,) = ep.active()
    assert a[3] is True and abs(a[2] - 9.9) < 1e-9                           # tek bölüm, başlangıç 0,0


def test_fired_episode_ends_after_more_than_three_seconds_of_false() -> None:
    ep, key = EpisodeTracker(), (1, "lying")
    for t in range(36):
        ep.update(key, True, t / 10, 3.0)                                    # son True 3,5
    for t in range(36, 65):
        ep.update(key, False, t / 10, 3.0)
        assert ep.sweep(t / 10, {1}) == [], t                               # 6,4'e kadar (2,9 sn) sürer
    assert ep.sweep(6.6, {1}) == [(key, True)] and ep.active() == []
    assert not ep.update(key, True, 6.7, 3.0)                               # yeni bölüm
    assert ep.active() == [(1, "lying", 0.0, False)]


def test_fired_grace_also_applies_in_update_and_takes_the_max_with_adaptive_grace() -> None:
    ep, key = EpisodeTracker(), (1, "hands_up")
    for t in range(31):
        ep.update(key, True, t / 10, 3.0)                                    # 3,0'da alarm
    assert not ep.update(key, True, 5.9, 3.0)                                # 2,9 sn sonra True: aynı bölüm sürer
    assert ep.sweep(5.9, {1}) == [] and ep.active()[0][2] == 5.9
    assert not ep.update(key, True, 10.0, 3.0, grace_s=5.0)                  # uyarlanmış tolerans daha büyükse o
    assert ep.sweep(10.0, {1}) == [] and ep.active()[0][3] is True
    assert not ep.update(key, True, 15.5, 3.0, grace_s=5.0)                  # 5,5 sn > max(3, 5): bölüm biter
    assert ep.sweep(15.5, {1}) == [(key, True)] and ep.active() == [(1, "hands_up", 0.0, False)]


def test_non_fired_episode_keeps_short_grace() -> None:
    ep, key = EpisodeTracker(), (1, "hands_up")
    for t in range(11):
        ep.update(key, True, t / 10, 3.0)                                    # 1 sn, alarm yok
    assert ep.sweep(1.4, {1}) == []
    assert ep.sweep(1.6, {1}) == [(key, False)]                              # > 0,5 sn: biter (eskisi gibi)
    for t in range(20, 31):
        ep.update(key, True, t / 10, 3.0)
    assert not ep.update(key, True, 3.7, 3.0)                                # 0,7 sn kopma: yeni bölüm
    assert ep.sweep(3.7, {1}) == [(key, False)] and ep.active() == [(1, "hands_up", 0.0, False)]


def test_close_all_reports_every_episode_and_pending_end() -> None:
    ep = EpisodeTracker()
    for t in range(31):
        ep.update((1, "hands_up"), True, t / 10, 3.0)
    ep.update((2, "lying"), True, 0.0, 10.0)
    assert not ep.update((1, "hands_up"), True, 20.0, 3.0)                   # eskisi ertelenmiş son
    assert sorted(ep.close_all()) == [((1, "hands_up"), False), ((1, "hands_up"), True), ((2, "lying"), False)]
    assert ep.active() == [] and ep.close_all() == []


def test_episode_grace_adapts_to_frame_rate() -> None:
    # With grace_s=1.25, True frames every 1.0s for 4s fires once (threshold 3)
    ep_loose = EpisodeTracker()
    for ts in [0.0, 1.0, 2.0, 3.0]:
        ep_loose.update((1, "test"), True, ts, 3.0, grace_s=1.25)
    assert ep_loose.active()[0][3] is True  # fired
    # With default grace_s=0.5, same sequence never fires (episode restarts at 1.0)
    ep_strict = EpisodeTracker()
    for ts in [0.0, 1.0, 2.0, 3.0]:
        ep_strict.update((1, "test"), True, ts, 3.0)  # default grace_s=0.5
    assert ep_strict.active()[0][3] is False  # never fired


def test_stale_restart_reports_end_and_keeps_new_episode() -> None:
    # Fire episode with 40 frames at 0.1s (threshold 3.0)
    ep = EpisodeTracker()
    for t in range(40):
        ep.update((7, "hands_up"), True, t / 10, 3.0)
    # Episode fires at t=30 (3.0s)
    assert ep.active()[0][3] is True
    # Long gap: update at ts=20.0 treats as stale
    assert not ep.update((7, "hands_up"), True, 20.0, 3.0)
    # sweep reports the old fired episode ending, but keeps new episode
    assert ep.sweep(20.1, {7}) == [((7, "hands_up"), True)]
    assert ep.active() == [(7, "hands_up", 0.0, False)]
    # New episode fires when threshold reached (20.0 + 3.0 = 23.0)
    for ts_frac in range(31):
        ts = 20.0 + ts_frac * 0.1
        if ts > 23.0:
            break
        fired = ep.update((7, "hands_up"), True, ts, 3.0)
        if ts >= 23.0:
            assert fired
        ep.sweep(ts, {7})
    # Verify final state
    assert ep.active()[0][3] is True  # new episode fired


def test_backwards_timestamp_restarts() -> None:
    # Episode with True frames at ts 5.0..6.0 (threshold 0.5)
    ep = EpisodeTracker()
    for ts in [5.0, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6]:
        ep.update((3, "lying"), True, ts, 0.5)
    # Should have fired (5.5 - 5.0 = 0.5 >= 0.5)
    assert ep.active()[0][3] is True
    # Backwards timestamp: ts=1.0
    assert not ep.update((3, "lying"), True, 1.0, 0.5)
    # Next sweep reports old fired episode and shows new one
    result = ep.sweep(1.0, {3})
    assert result == [((3, "lying"), True)]
    assert ep.active() == [(3, "lying", 0.0, False)]
