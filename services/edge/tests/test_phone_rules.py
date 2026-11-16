"""Telefon kullanımı kuralları: kişi kırpıntısında telefon araması, el/baş yakınlığı, dilimli kanıt penceresi
(tasarım docs/superpowers/specs/2026-11-16-telefon-alarmi-design.md "Algılama (çekirdek)")."""
from __future__ import annotations

from collections.abc import Callable

import numpy as np
from fakes_safety import FakePhoneDetector, phone_kp

from bantvision.core.phone_rules import (
    PHONE_CONF,
    PHONE_END_S,
    PhoneEvidence,
    find_phones,
    phone_hit,
    phone_possible,
)

FRAME = np.zeros((300, 400, 3), np.uint8)


# ---------------------------------------------------------------- kırpıntıda arama

def test_find_phones_crops_with_pad_and_maps_to_frame_pixels() -> None:
    det = FakePhoneDetector([(0, 0, 50, 50)], phones=[(10, 20, 30, 40, 0.5)])     # telefon kırpıntıya göre
    out = find_phones(det, FRAME, (100, 50, 200, 250))
    assert out == [(100 - 20 + 10, 50 - 40 + 20, 100 - 20 + 30, 50 - 40 + 40, 0.5)]  # pay %20: 20 px, 40 px
    assert det.calls == [["cell phone"]] and det.confs == [PHONE_CONF]
    assert det.shapes == [(280, 140, 3)]


def test_find_phones_ignores_other_classes() -> None:
    class Mixed(FakePhoneDetector):
        def detect(self, crop: np.ndarray, classes: list[str], conf: float = 0.15) -> list[object]:
            from types import SimpleNamespace
            return [SimpleNamespace(x1=1, y1=1, x2=5, y2=5, score=0.9, cls="person"),
                    *super().detect(crop, classes, conf)]

    det = Mixed([], phones=[(10, 20, 30, 40, 0.5)])
    assert [p[4] for p in find_phones(det, FRAME, (100, 50, 200, 250))] == [0.5]


def test_find_phones_clamps_box_at_frame_edge_and_skips_empty_crop() -> None:
    det = FakePhoneDetector([], phones=[(2, 3, 6, 9, 0.4)])
    out = find_phones(det, FRAME, (-50, -50, 30, 30))                 # pay 16 px: kırpıntı (0, 0)–(46, 46)
    assert det.shapes == [(46, 46, 3)]
    assert out == [(2.0, 3.0, 6.0, 9.0, 0.4)]                          # kırpıntı (0, 0)'dan başlar: kaydırma yok
    det2 = FakePhoneDetector([], phones=[(2, 3, 6, 9, 0.4)])
    assert find_phones(det2, FRAME, (500, 500, 600, 600)) == []        # tamamen dışarıda
    assert det2.calls == []                                            # dedektör çağrılmaz


# ---------------------------------------------------------------- isabet kararı

def _phone_at(x: float, y: float) -> list[tuple[float, float, float, float, float]]:
    return [(x - 10, y - 10, x + 10, y + 10, 0.4)]


def test_phone_hit_near_wrist_or_head() -> None:
    kp = phone_kp()                                                    # ölçek 160 px, sol bilek (290, 260)
    assert phone_hit(_phone_at(290 - 0.5 * 160, 260), kp) is True
    assert phone_hit(_phone_at(290 - 0.7 * 160, 260), kp) is False
    assert phone_hit(_phone_at(320 + 40, 120), kp) is True             # başın (burun 320, 120) yanında
    assert phone_hit([], kp) is False                                  # telefon yok
    hidden = kp.copy()
    hidden[[5, 6], 2] = 0.0                                            # omuzlar görünmez: ölçek yok
    assert phone_hit(_phone_at(290, 260), hidden) is None


def test_phone_hit_uses_only_visible_wrist_and_head() -> None:
    kp = phone_kp()
    assert phone_hit(_phone_at(200, 260), kp) is True                  # sol bilekten 90 px (< 0,6·160 = 96)
    kp[9, 2] = 0.0                                                     # sol bilek görünmez: sağ bilek 150 px, baş uzak
    assert phone_hit(_phone_at(200, 260), kp) is False
    kp2 = phone_kp()
    kp2[[0, 1, 2, 3, 4, 9, 10], 2] = 0.0                               # bilek ve baş yok (kalça ölçeği var)
    assert phone_hit(_phone_at(290, 260), kp2) is None


def test_phone_possible_matches_when_phone_hit_can_decide() -> None:
    """Aramadan önce eklemlerden: ölçek ve en az bir görünen bilek/baş varsa True (o zaman `phone_hit` None değildir)."""
    kp = phone_kp()
    assert phone_possible(kp) is True
    no_anchor = kp.copy()
    no_anchor[[0, 1, 2, 3, 4, 9, 10], 2] = 0.0                         # bilek ve baş yok
    assert phone_possible(no_anchor) is False
    no_scale = kp.copy()
    no_scale[[5, 6], 2] = 0.0                                          # omuzlar yok: ölçek yok
    assert phone_possible(no_scale) is False
    one_wrist = kp.copy()
    one_wrist[[0, 1, 2, 3, 4, 9], 2] = 0.0                             # yalnız sağ bilek
    assert phone_possible(one_wrist) is True
    for k in (kp, no_anchor, no_scale, one_wrist):
        assert (phone_hit([], k) is not None) == phone_possible(k)


# ---------------------------------------------------------------- kanıt penceresi

def _drive(ev: PhoneEvidence, start: float, stop: float, hit_at: Callable[[float], bool | None],
           seconds: float = 60.0, observe_from: float = 0.0, tid: int = 1, step: float = 0.5) -> list[float]:
    """`start`–`stop` arası `step` adımla: gözlem (`observe_from`'dan itibaren) ve karar; `hit_at(ts)` → bool | None.
    Alarm doğan zamanlar döner."""
    fired = []
    n = round((stop - start) / step)
    for k in range(n + 1):
        ts = start + k * step
        if ts >= observe_from:
            ev.observe(tid, ts)
        if ev.update(tid, ts, hit_at(ts), seconds):
            fired.append(ts)
    return fired


def _every_slot(ts: float) -> bool:
    return ts % 5.0 == 0.0                                             # her 5 sn'lik dilimde bir isabet


def test_evidence_fires_when_enough_slots_have_hits() -> None:
    ev = PhoneEvidence()
    fired = _drive(ev, 0.0, 70.0, _every_slot)
    assert fired == [60.0]                                             # tam bir kez, gözlem 60 sn'ye ulaşınca
    (tid, kind, dur, was_fired), = ev.active()
    assert (tid, kind, was_fired) == (1, "phone", True)
    assert dur == 70.0                                                 # ilk isabetten (0) son isabete (70)


def test_active_duration_is_last_hit_minus_start_and_frozen_during_misses() -> None:
    """Süre = son isabet − ilk isabet (eller yukarıdaki son olumlu kare gibi): ıskalar ve kararsız kareler süreyi
    uzatmaz, bu yüzden video işinde alarm bitişi son isabete oturur (PHONE_END_S kadar geç değil)."""
    ev = PhoneEvidence()
    for k in range(29):                                                # 0–14 sn; isabet 2–6 sn, 10 sn'den sonra karar yok
        ts = k * 0.5
        ev.observe(1, ts)
        ev.update(1, ts, (2.0 <= ts <= 6.0) if ts < 10.0 else None, 60.0)
        if ts >= 6.0:
            assert ev.active()[0][2] == 4.0                            # 6 − 2, ıskada ve None'da donuk
    assert ev.started(1) == 2.0 and ev.started(2) is None


def test_evidence_does_not_fire_below_slot_ratio() -> None:
    def hits_in(slots: set[int]) -> Callable[[float], bool | None]:
        return lambda ts: ts % 5.0 == 0.0 and ts < 60.0 and int(ts // 5) in slots

    # Dilimler dağınık: isabetsiz aralık en çok 10 sn (< PHONE_END_S), bölüm kopmaz.
    ev = PhoneEvidence()                                               # 12 dilimin 7'si: 0,58 < 0,6
    assert _drive(ev, 0.0, 60.0, hits_in({0, 2, 4, 5, 7, 9, 11})) == []
    assert ev.active() and not ev.active()[0][3]
    ev = PhoneEvidence()                                               # 12 dilimin 8'i: 0,67 ≥ 0,6
    assert _drive(ev, 0.0, 60.0, hits_in({0, 2, 3, 5, 6, 8, 9, 11})) == [60.0]


def test_evidence_needs_track_observed_for_whole_window() -> None:
    ev = PhoneEvidence()
    fired = _drive(ev, 0.0, 100.0, _every_slot, observe_from=20.0)
    assert fired == [80.0]                                             # 60. sn'de yalnız 40 sn gözlem: alarm yok


def test_evidence_without_observation_never_fires() -> None:
    ev = PhoneEvidence()
    assert _drive(ev, 0.0, 100.0, _every_slot, observe_from=1e9) == []


def test_evidence_ends_after_end_s_without_hits_and_on_track_loss() -> None:
    ev = PhoneEvidence()
    ev.observe(1, 0.0)
    ev.update(1, 0.0, True, 60.0)                                      # alarmsız bölüm
    assert ev.sweep(PHONE_END_S, {1}) == []
    assert ev.sweep(PHONE_END_S + 0.1, {1}) == [((1, "phone"), False)]
    assert ev.active() == []

    ev = PhoneEvidence()
    ev.observe(2, 0.0)
    ev.update(2, 0.0, True, 60.0)
    assert ev.sweep(0.5, set()) == [((2, "phone"), False)]             # alarmsız: iz kaybı hemen bitirir

    ev = PhoneEvidence()
    assert _drive(ev, 0.0, 60.0, _every_slot, tid=3) == [60.0]
    assert ev.sweep(60.5, set()) == []                                 # alarmlı: iz kaybında bekler
    assert ev.sweep(60.0 + PHONE_END_S, set()) == []
    assert ev.sweep(60.0 + PHONE_END_S + 0.1, set()) == [((3, "phone"), True)]
    assert ev.active() == []


def test_evidence_hit_none_is_not_a_miss() -> None:
    ev = PhoneEvidence()
    ev.observe(1, 0.0)
    ev.update(1, 0.0, True, 60.0)
    for k in range(1, 30):                                             # 14,5 sn boyunca karar yok
        ev.observe(1, k * 0.5)
        assert ev.update(1, k * 0.5, None, 60.0) is False
    assert ev.sweep(14.5, {1}) == []                                   # None bitirmedi
    ev.update(1, 15.1, None, 60.0)
    assert ev.sweep(15.1, {1}) == [((1, "phone"), False)]             # None uzatmadı: son isabetten 15,1 sn

    ev = PhoneEvidence()                                               # None'lar isabet sayılmaz
    assert _drive(ev, 0.0, 70.0, lambda ts: True if ts == 0.0 else None) == []


def test_evidence_false_is_a_miss_but_does_not_end_by_itself() -> None:
    ev = PhoneEvidence()
    ev.observe(1, 0.0)
    ev.update(1, 0.0, True, 60.0)
    ev.update(1, 1.0, False, 60.0)
    assert ev.sweep(1.0, {1}) == [] and ev.active()[0][1] == "phone"


def test_evidence_restarts_on_backwards_time_and_stale_episode() -> None:
    ev = PhoneEvidence()
    ev.observe(1, 10.0)
    ev.update(1, 10.0, True, 60.0)
    ev.observe(1, 0.0)                                                 # video başa sardı
    ev.update(1, 0.0, True, 60.0)
    assert ev.sweep(0.0, {1}) == [((1, "phone"), False)]               # eski bölüm bitti, yenisi başladı
    assert [(a[0], a[2]) for a in ev.active()] == [(1, 0.0)]


def test_close_all_reports_fired_and_unfired() -> None:
    ev = PhoneEvidence()
    assert _drive(ev, 0.0, 60.0, _every_slot, tid=1) == [60.0]
    ev.observe(2, 60.0)
    ev.update(2, 60.0, True, 60.0)
    assert sorted(ev.close_all()) == [((1, "phone"), True), ((2, "phone"), False)]
    assert ev.active() == [] and ev.close_all() == [] and ev.sweep(61.0, {1, 2}) == []


def test_ended_last_is_last_hit_of_every_reported_end() -> None:
    """Biten bölümün son isabeti `ended_last`'ta (canlı alarm kaydının `endedAt`'i son isabete oturur, `PHONE_END_S`
    sonraki bildirime değil): sweep, ertelenmiş son ve close_all; her çağrı öncekinin yerine geçer."""
    ev, key = PhoneEvidence(), (3, "phone")
    assert _drive(ev, 0.0, 60.0, _every_slot, tid=3) == [60.0]            # son isabet 60
    for k in range(121, 151):                                          # 60,5–75: ıska
        ev.observe(3, k * 0.5)
        ev.update(3, k * 0.5, False, 60.0)
        if k * 0.5 <= 60.0 + PHONE_END_S:
            assert ev.sweep(k * 0.5, {3}) == [] and ev.ended_last == {}
    assert ev.sweep(75.5, {3}) == [(key, True)] and ev.ended_last == {key: 60.0}
    assert ev.sweep(76.0, {3}) == [] and ev.ended_last == {}

    ev = PhoneEvidence()
    ev.observe(4, 0.0)
    ev.update(4, 0.0, True, 60.0)
    ev.observe(4, 20.0)
    ev.update(4, 20.0, True, 60.0)                                     # bayat: eskisi ertelenmiş son, yenisi başladı
    assert ev.sweep(20.0, {4}) == [((4, "phone"), False)] and ev.ended_last == {(4, "phone"): 0.0}
    ev.update(4, 21.0, False, 60.0)                                    # ıska son isabeti ilerletmez
    assert ev.close_all() == [((4, "phone"), False)] and ev.ended_last == {(4, "phone"): 20.0}
    assert ev.close_all() == [] and ev.ended_last == {}


def test_slot_ratio_window_edges() -> None:
    from bantvision.core.phone_rules import _slot_ratio

    assert _slot_ratio([0.0, 60.0], 60.0, 60.0) == 2 / 12               # pencere başı ilk, sonu son dilim
    assert _slot_ratio([-1e-12], 60.0 - 1e-12, 60.0) == 1 / 12          # kayan nokta gürültüsü dilim −1 üretmez
    assert _slot_ratio([10.0, 20.0], 12.0, 12.0) == 1 / 3               # 12 sn: ⌈12/5⌉ = 3 dilim; 20 pencere dışı
    assert _slot_ratio([-0.5], 12.0, 12.0) == 0.0                       # pencere dışı sayılmaz


def test_slot_ratio_uses_equal_slots_when_seconds_is_not_a_multiple_of_slot() -> None:
    from bantvision.core.phone_rules import _slot_ratio

    # 11 sn: 3 eşit dilim (3,67 sn); 5 sn'lik dilimler + 1 sn'lik kısa son dilim değil
    assert _slot_ratio([0.0, 4.0], 11.0, 11.0) == 2 / 3                 # 4,0 ikinci dilimde (5 sn dilimde ilkindeydi)
    assert _slot_ratio([10.5], 11.0, 11.0) == 1 / 3
    assert _slot_ratio([11.0], 11.0, 11.0) == 1 / 3                     # pencere sonu son dilimde
    assert _slot_ratio([0.0, 5.0, 10.0], 15.0, 15.0) == 1.0             # S % 5 == 0: değişmez
