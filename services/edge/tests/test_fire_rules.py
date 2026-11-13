"""core/fire_rules.py: R4 sabitleri ve saf yardımcılar (eşik, en küçük kutu, hariç bölge, hareket geçmişi, hücre oyu)."""
from __future__ import annotations

import numpy as np
import pytest

from bantvision.core import fire_rules as fr
from bantvision.core.profile import FireConfig, SafetyRule


def test_constants_are_the_ruling_values() -> None:
    assert fr.THRESHOLDS == {"low": {"fire": .60, "smoke": .65}, "normal": {"fire": .45, "smoke": .50},
                             "high": {"fire": .35, "smoke": .40}}
    assert (fr.MIN_SIDE, fr.MOTION_W, fr.MOTION_LAG_S, fr.MOTION_PIX, fr.MOTION_MIN) == (0.015, 160, 1.0, 15, 0.02)
    assert (fr.GLOBAL_CHANGE_MAX, fr.GRID, fr.RATIO, fr.MIN_HITS, fr.END_S, fr.MAX_FPS) == (
        0.80, (8, 6), 0.6, 3, 10.0, 5.0)
    assert fr.TRACK_IDS == {"fire": 0, "smoke": 1}


def test_class_conf_has_only_enabled_rules_at_sensitivity() -> None:
    assert fr.class_conf(FireConfig()) == {"fire": .45, "smoke": .50}
    assert fr.class_conf(FireConfig(sensitivity="high")) == {"fire": .35, "smoke": .40}
    assert fr.class_conf(FireConfig(smoke=SafetyRule(False, 8.0), sensitivity="low")) == {"fire": .60}
    assert fr.class_conf(FireConfig(fire=SafetyRule(False, 3.0), smoke=SafetyRule(False, 8.0))) == {}
    assert fr.class_conf(FireConfig(sensitivity="bogus")) == {"fire": .45, "smoke": .50}   # bozuk: normal


def test_big_enough_uses_short_side_over_frame_height() -> None:
    # 480 yükseklikte sınır 7,2 px; genişlikten bağımsız (kısa kenar / kare YÜKSEKLİĞİ)
    assert not fr.big_enough((0, 0, 100, 7), 480)
    assert fr.big_enough((0, 0, 100, 8), 480)
    assert not fr.big_enough((0, 0, 7, 100), 480)
    assert fr.big_enough((10, 10, 18, 18), 480)


def test_ignore_zone_drops_box_whose_centre_is_inside() -> None:
    zone = [(0.1, 0.5), (0.4, 0.5), (0.4, 0.9), (0.1, 0.9)]           # 640×480'de x 64–256, y 240–432
    assert fr.in_ignore_zone((100, 300, 200, 400), [zone], 640, 480)  # tamamen içeride
    assert fr.in_ignore_zone((100, 200, 250, 420), [zone], 640, 480)  # dışarı taşıyor ama merkez (175,310) içeride
    assert not fr.in_ignore_zone((180, 150, 420, 330), [zone], 640, 480)   # merkez (300,240) dışarıda
    assert not fr.in_ignore_zone((240, 400, 300, 470), [zone], 640, 480)   # kısmen içeride, merkez (270,435) dışarıda
    assert fr.in_ignore_zone((54, 230, 74, 250), [zone], 640, 480)     # merkez köşede (64,240): kenar içeride sayılır
    assert not fr.in_ignore_zone((100, 300, 200, 400), [], 640, 480)
    other = [(0.8, 0.0), (1.0, 0.0), (1.0, 0.2)]
    assert fr.in_ignore_zone((600, 10, 630, 20), [zone, other], 640, 480)   # ikinci bölge


def test_box_cells_marks_covered_cells() -> None:
    g = fr.box_cells((0.0, 0.0, 0.125, 1 / 6))                          # tam bir hücre
    assert g.shape == (6, 8) and g.sum() == 1 and g[0, 0]
    g = fr.box_cells((0.1, 0.1, 0.3, 0.2))                              # sütun 0–2, satır 0–1
    assert g.sum() == 6 and g[0:2, 0:3].all()
    g = fr.box_cells((0.9, 0.95, 1.0, 1.0))                             # sağ alt köşe
    assert g.sum() == 1 and g[5, 7]
    g = fr.box_cells((0.5, 0.5, 0.5, 0.5))                              # bozuk (sıfır alan): yine bir hücre
    assert g.sum() == 1 and g[3, 4]


def test_neighbourhood_is_eight_connected_and_clipped() -> None:
    g = np.zeros((6, 8), bool)
    g[3, 2] = True
    n = fr.neighbourhood(g)
    assert n.sum() == 9 and n[2:5, 1:4].all()
    g = np.zeros((6, 8), bool)
    g[0, 0] = True
    assert fr.neighbourhood(g).sum() == 4


def gray(v: int, shape: tuple[int, int] = (120, 160)) -> np.ndarray:
    return np.full(shape, v, np.uint8)


def test_small_gray_is_motion_width() -> None:
    s = fr.small_gray(np.zeros((480, 640, 3), np.uint8))
    assert s.shape == (120, 160) and s.dtype == np.uint8


def test_changed_ratio_whole_frame_and_box() -> None:
    a, b = gray(100), gray(100)
    b[:60, :] = 120                                                     # üst yarı değişti
    assert fr.changed_ratio(b, a) == pytest.approx(0.5)
    assert fr.changed_ratio(b, a, (0.0, 0.0, 1.0, 0.5)) == pytest.approx(1.0)
    assert fr.changed_ratio(b, a, (0.0, 0.5, 1.0, 1.0)) == pytest.approx(0.0)
    c = gray(115)                                                       # fark tam MOTION_PIX: değişmiş sayılmaz
    assert fr.changed_ratio(c, a) == 0.0


def test_motion_history_reference_selection() -> None:
    h = fr.MotionHistory()
    assert h.push(0.0, gray(0)) is None                                 # ilk kare: kıyas yok
    ref = h.push(0.2, gray(2))
    assert ref is not None and ref[0, 0] == 0                           # geçmiş < 1 sn: en eski kare
    ref = h.push(0.4, gray(4))
    assert ref is not None and ref[0, 0] == 0
    for k in range(3, 8):
        ref = h.push(k / 5, gray(k * 2))
    assert ref is not None and ref[0, 0] == 4                           # ts 1,4 → ≤ 0,4 olan en yakın: 0,4
    slow = fr.MotionHistory()
    slow.push(0.0, gray(10))
    ref = slow.push(2.0, gray(20))
    assert ref is not None and ref[0, 0] == 10                          # 1 kare/sn'den yavaş: bir önceki kare
    ref = slow.push(4.0, gray(30))
    assert ref is not None and ref[0, 0] == 20
    assert slow.push(4.5, gray(40, (100, 160))) is None                 # boyut değişti: geçmiş atılır
    assert slow.push(4.0, gray(50, (100, 160))) is None                 # zaman geri gitti: geçmiş atılır


def test_cell_votes_ratio_hits_neighbourhood_and_closed_window() -> None:
    box = (0.30, 0.30, 0.36, 0.36)                                      # sütun 2, satır 1
    near = (0.40, 0.30, 0.46, 0.36)                                     # komşu hücre (sütun 3)
    far = (0.80, 0.80, 0.86, 0.86)
    v = fr.CellVotes()
    v.add(0.0, [box])
    v.add(1.0, [box])
    assert v.trigger(1.0, 3.0) is None                                  # 2 olumlu < MIN_HITS
    v.add(2.0, [near])
    assert v.trigger(2.0, 3.0) is not None                              # komşuluk: kayan kutu aynı hücrede sayılır
    v2 = fr.CellVotes()
    for k in range(10):                                                 # 5/10 olumlu: oran 0,5 < 0,6
        v2.add(k * 0.1, [box] if k % 2 == 0 else [])
    assert v2.trigger(0.9, 3.0) is None
    v3 = fr.CellVotes()
    for k in range(10):                                                 # 6/10: oran 0,6 ≥ RATIO
        v3.add(k * 0.1, [box] if k < 6 else [])
    assert v3.trigger(0.9, 3.0) is not None
    v4 = fr.CellVotes()
    for k in range(6):                                                  # komşu olmayan hücreler arasında atlama
        v4.add(k * 0.1, [box] if k % 2 == 0 else [far])
    assert v4.trigger(0.5, 3.0) is None
    v5 = fr.CellVotes()
    for t in (0.0, 1.0, 2.0):                                           # pencere [now − s, now] kapalı: 1 kare/sn,
        v5.add(t, [box])                                                # 2 sn kuralda 3 kare sayılır
    assert v5.trigger(2.0, 2.0) is not None
    v5.add(3.0, [])
    v5.add(4.0, [])
    assert v5.trigger(4.0, 2.0) is None                                 # eski olumlular pencereden düştü


def test_cell_votes_box_is_union_of_last_frame_boxes_touching_cell() -> None:
    a, b = (0.30, 0.30, 0.36, 0.36), (0.37, 0.31, 0.43, 0.40)
    far = (0.80, 0.80, 0.86, 0.86)
    v = fr.CellVotes()
    v.add(0.0, [(0.29, 0.29, 0.35, 0.35)])
    v.add(1.0, [a])
    v.add(2.0, [a, b, far])
    cell = v.trigger(2.0, 3.0)
    assert cell is not None
    assert v.box_at(cell) == pytest.approx((0.30, 0.30, 0.43, 0.40))    # uzak kutu birleşime girmez
    v.add(3.0, [])                                                      # son kare boş: kutu en son değen kareden
    assert v.box_at(cell) == pytest.approx((0.30, 0.30, 0.43, 0.40))


def test_cell_votes_tie_prefers_cell_covered_by_the_boxes_themselves() -> None:
    """Komşuluk nedeniyle birçok hücre eşit sayıda olumlu: tetikleyen hücre kutuların kendisinin kapladığı hücredir,
    yalnız bir kutunun komşuluğuna giren kenar hücresi değil (alarm kutusu iki kutuyu da kapsar)."""
    a, b = (0.30, 0.30, 0.36, 0.36), (0.38, 0.30, 0.45, 0.36)           # sütun 2 ve 3, satır 1
    v = fr.CellVotes()
    for t in (0.0, 1.0, 2.0):
        v.add(t, [a, b])
    cell = v.trigger(2.0, 3.0)
    assert cell in {(1, 2), (1, 3)}
    assert v.box_at(cell) == pytest.approx((0.30, 0.30, 0.45, 0.36))
