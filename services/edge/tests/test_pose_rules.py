"""Poz güvenlik kuralları (tasarım: docs/superpowers/specs/2026-10-06-poz-guvenlik-design.md)."""
from __future__ import annotations

import numpy as np

from bantvision.core.pose_rules import EpisodeTracker, hands_up, lying, scale


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
    ep = EpisodeTracker()
    for t in range(40):
        ep.update((7, "hands_up"), True, t / 10, 3.0)
    assert ep.sweep(4.0, set()) == [((7, "hands_up"), True)]
    assert ep.active() == []
    assert not ep.update((7, "hands_up"), True, 4.1, 3.0)                    # yeni bölüm baştan sayar
    assert ep.active() == [(7, "hands_up", 0.0, False)]
    # Episode fires again when threshold is reached (use large grace to keep episode open)
    assert ep.update((7, "hands_up"), True, 7.1, 3.0, grace_s=10.0)            # 7.1 - 4.1 = 3.0 >= 3.0


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
