"""Yan yana geçen gruplar (§4.10): mükerrer sayım olmamalı, eksik sayım çok küçük kalmalı.

Mağazada 2–3 kişi yan yana geçer; tanıyıcı kişileri kaçırır, üst üste binenleri birleştirir, aynı kişiye yarım kutu
verir. Sayı her kişi için tam bir kez artmalıdır.
"""
from __future__ import annotations

from bantvision.core.people_track import MotParams, MotTracker
from bantvision.core.sim_people import Faults, scenario, side


def count(frames: list, params: MotParams | None = None) -> tuple[int, int]:
    t = MotTracker(params or MotParams(max_age=25))
    ins = outs = 0
    for d in frames:
        a, b = t.update(d, side)
        ins += len(a)
        outs += len(b)
    return ins, outs


def run_suite(seeds: range, faults: Faults) -> tuple[int, int, int]:
    over = under = people = 0
    for s in seeds:
        frames, down, up = scenario(s, faults)
        i, o = count(frames)
        over += max(0, i - down) + max(0, o - up)
        under += max(0, down - i) + max(0, up - o)
        people += down + up
    return over, under, people


def test_groups_perfect_detection_exact() -> None:
    over, under, _ = run_suite(range(60), Faults(miss=0, part=0, merge=0))
    assert (over, under) == (0, 0)


def test_groups_typical_faults_no_double_count() -> None:
    over, under, people = run_suite(range(60), Faults())
    assert over == 0
    assert under <= 0.005 * people


def test_groups_heavy_faults_stay_accurate() -> None:
    over, under, people = run_suite(range(60), Faults(miss=0.25, part=0.1, merge=0.1))
    assert over <= 0.003 * people
    assert under <= 0.01 * people


def test_part_box_does_not_create_second_person() -> None:
    # her karede aynı kişiye üst gövde kutusu da gelir (yüksek güvenle): tek kişi sayılır
    frames = []
    for k in range(40):
        y = 0.2 + 0.7 * k / 39
        full = (0.46, y - 0.08, 0.54, y + 0.08)
        part = (0.468, y - 0.08, 0.532, y + 0.008)
        frames.append([(full, 0.5), (part, 0.9)])
    assert count(frames) == (1, 0)


def test_two_people_overlapping_side_by_side_both_counted() -> None:
    # kutuları %40 üst üste binen iki kişi (eş boy): ikisi de ayrı kişi
    frames = [[((0.40, y - 0.08, 0.48, y + 0.08), 0.8), ((0.45, y - 0.08, 0.53, y + 0.08), 0.8)]
              for y in (0.2 + 0.7 * k / 39 for k in range(40))]
    assert count(frames) == (2, 0)


def test_neighbor_strong_detection_does_not_steal_track() -> None:
    # sağdaki kişinin tespiti çizgi civarında hep silik gelir; soldakinin güçlü tespiti onu kapmamalı
    frames = []
    for k in range(40):
        y = 0.2 + 0.7 * k / 39
        weak = 0.3 if 12 <= k <= 28 else 0.8
        frames.append([((0.40, y - 0.08, 0.48, y + 0.08), 0.9), ((0.485, y - 0.08, 0.565, y + 0.08), weak)])
    assert count(frames) == (2, 0)
