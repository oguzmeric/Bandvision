"""Çokgen ROI (algoritma §2.0). Eşdeğerlik vektörleri Swift'te de aynıdır (BantSayacTests/RoiPolygonTests)."""
import json
import pathlib

import numpy as np
import pytest
from test_synthetic import calibrated_egg_profile, run

from bantvision import sim
from bantvision.core import Pipeline, Profile
from bantvision.core.profile import Roi
from bantvision.core.segmenter import BackgroundSegmenter, roi_mask, roi_pixels

EXAMPLE = pathlib.Path(__file__).resolve().parents[3] / "contracts" / "examples" / "profile-box-polygon.json"
# Orta şerit (x = 360/720 = 0.5) içeride; yan şeritler (150 ve 570) dışarıda. Eğik dörtgen.
MIDDLE_LANE = [(0.36, 0.1), (0.66, 0.1), (0.64, 0.9), (0.34, 0.9)]


def test_without_polygon_mask_is_the_rectangle() -> None:
    roi = Roi(0.05, 0.1, 0.9, 0.8)
    m = roi_mask(roi, None, 240, 426)
    x0, y0, x1, y1 = roi_pixels(roi, 240, 426)
    expected = np.zeros((426, 240), bool)
    expected[y0:y1, x0:x1] = True
    assert np.array_equal(m, expected)


@pytest.mark.parametrize(("w", "h", "inside", "sum_i", "sum_j", "rows"), [
    (240, 426, 47797, 5369916, 10133596, {106: (62, 186), 213: (50, 174), 319: (38, 162)}),
    (160, 90, 6738, 504548, 296505, {22: (42, 124), 45: (33, 116), 67: (26, 108)}),
])
def test_parity_vectors(w: int, h: int, inside: int, sum_i: int, sum_j: int, rows: dict[int, tuple[int, int]]) -> None:
    """Swift aynı sayıları vermeli (aynı kural, aynı işlem sırası)."""
    p = Profile.from_dict(json.loads(EXAMPLE.read_text(encoding="utf-8")))
    m = roi_mask(p.roi, p.roiPolygon, w, h)
    ys, xs = np.nonzero(m)
    assert (int(m.sum()), int(xs.sum()), int(ys.sum())) == (inside, sum_i, sum_j)
    for j, (first, last) in rows.items():
        row = np.nonzero(m[j])[0]
        assert (int(row[0]), int(row[-1])) == (first, last)
    assert not m[0].any() and not m[h - 1].any()


def test_concave_polygon() -> None:
    l_shape = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.4), (0.4, 0.4), (0.4, 0.9), (0.1, 0.9)]
    m = roi_mask(Roi(0, 0, 1, 1), l_shape, 100, 100)
    assert int(m.sum()) == 3900                      # alan 0,39
    assert m[20, 80] and m[80, 20] and not m[80, 80]  # kolların içi, iç köşenin dışı


def test_mask_is_rectangle_intersect_polygon() -> None:
    m = roi_mask(Roi(0.5, 0.0, 0.5, 1.0), [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)], 100, 100)
    assert int(m.sum()) == 5000 and not m[:, :50].any()


def test_profile_round_trip_and_bbox() -> None:
    p = Profile.egg()
    p.set_polygon(MIDDLE_LANE)
    assert (p.roi.x, p.roi.y) == (0.34, 0.1)
    assert p.roi.width == pytest.approx(0.32) and p.roi.height == pytest.approx(0.8)
    back = Profile.from_dict(p.to_dict())
    assert back.roiPolygon == MIDDLE_LANE and back.roi == p.roi
    with pytest.raises(ValueError):
        p.set_polygon([(0.1, 0.1), (0.2, 0.2)])
    p.set_polygon(None)
    assert p.roiPolygon is None and "roiPolygon" not in p.to_dict()


@pytest.fixture(scope="module")
def egg_profile() -> Profile:
    return calibrated_egg_profile()


def test_only_products_inside_polygon_are_counted(egg_profile: Profile) -> None:
    sc = sim.three_lanes()
    assert run(egg_profile, sc) == sc.expected_count               # dikdörtgen: üç şerit
    p = Profile.from_dict(egg_profile.to_dict())
    p.set_polygon(MIDDLE_LANE)
    p.linePosition = 0.5
    assert run(p, sc) == sc.expected_count // 3                    # çokgen: yalnızca orta şerit


def test_background_learning_ignores_motion_outside_polygon() -> None:
    """Kenarda (çokgen dışında) hareket varken boş bant öğrenmesi eşiği şişirmemeli."""
    busy = sim.Scenario("kenar", [sim.Item(-120 - i * 260, x) for i in range(8) for x in (150, 570)])

    def learned_threshold(polygon: list[tuple[float, float]] | None) -> int:
        p = Profile.egg()
        p.set_polygon(polygon)
        pipe = Pipeline(p)
        pipe.start_background_learning()
        for img, ts in busy.frames():
            r = pipe.process(img, ts)
            if any(e[0] == "background_done" for e in r.calibration):
                return p.diffThreshold
        raise AssertionError("öğrenme bitmedi")

    with_polygon = learned_threshold(MIDDLE_LANE)
    with_rect = learned_threshold(None)
    assert with_polygon <= 20, with_polygon       # yalnızca bant gürültüsü (σ=3)
    assert with_rect > 2 * with_polygon, (with_rect, with_polygon)


def test_segmenter_percentile_only_inside_polygon() -> None:
    seg = BackgroundSegmenter()
    bg = np.zeros((100, 100), np.uint8)
    seg.learn(bg, 1.0)
    frame = bg.copy()
    frame[:, :40] = 200                            # çokgenin dışında büyük fark
    poly = [(0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0)]
    assert seg.diff_percentile(frame, Roi(0, 0, 1, 1), 0.995, poly) == 0
    assert seg.diff_percentile(frame, Roi(0, 0, 1, 1), 0.995) == 200
