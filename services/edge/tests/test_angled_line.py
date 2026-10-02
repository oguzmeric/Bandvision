"""Açılı sayım çizgisi (algoritma §4.8). Eşdeğerlik vektörleri Swift'te de aynıdır (BantSayacTests/LineFrameTests)."""
import math

import numpy as np
import pytest
from test_synthetic import calibrated_egg_profile

from bantvision import sim
from bantvision.core import Pipeline, Profile
from bantvision.core.lineframe import LineFrame, nearest_direction
from bantvision.core.profile import Roi
from bantvision.core.segmenter import BackgroundSegmenter


def perpendicular_line(sc: sim.Scenario, half: float = 0.35) -> tuple[tuple[float, float], tuple[float, float]]:
    """Akışa dik, görüntü merkezinden geçen çizgi; a→b'nin sağ eli akış yönü."""
    th = math.radians(sc.angle_deg)
    fx, fy = math.cos(th), math.sin(th)
    dx, dy = fy, -fx
    cx, cy, ln = sc.width / 2, sc.height / 2, half * min(sc.width, sc.height)
    return (((cx - dx * ln) / sc.width, (cy - dy * ln) / sc.height),
            ((cx + dx * ln) / sc.width, (cy + dy * ln) / sc.height))


def run(profile: Profile, sc: sim.Scenario) -> int:
    pipe = Pipeline(profile)
    for img, ts in sc.empty_frames(0.5):
        pipe.process(img, ts)
    pipe.reset_count()
    for img, ts in sc.frames():
        pipe.process(img, ts)
    return pipe.total


# --- çerçeve matematiği ------------------------------------------------------------------------------------

def test_flow_is_right_hand_of_a_to_b() -> None:
    lf = LineFrame.build((0.1, 0.5), (0.9, 0.5), 100, 100)       # soldan sağa → akış aşağı
    assert lf is not None
    assert lf.to_frame(0.5, 0.6)[1] > 0 and lf.to_frame(0.5, 0.4)[1] < 0
    rev = LineFrame.build((0.9, 0.5), (0.1, 0.5), 100, 100)      # uçlar yer değiştirince akış yukarı
    assert rev is not None and rev.to_frame(0.5, 0.6)[1] < 0
    assert nearest_direction((0.1, 0.5), (0.9, 0.5), 1.0) == "down"
    assert nearest_direction((0.5, 0.9), (0.5, 0.1), 1.0) == "right"   # aşağıdan yukarı → sağ el sağ


def test_degenerate_line_is_ignored() -> None:
    assert LineFrame.build((0.4, 0.4), (0.4, 0.4), 100, 100) is None


def test_angles_survive_non_square_pixels() -> None:
    """Kare olmayan karede (720×1280) 45°'lik doğru, eş ölçekli birimde de 45°'dir; dikmesi gerçekten diktir."""
    w, h = 240, 426
    a = (0.5 - 0.2 * h / w, 0.5 - 0.2)                          # pikselde 45°
    b = (0.5 + 0.2 * h / w, 0.5 + 0.2)
    lf = LineFrame.build(a, b, w, h)
    assert lf is not None and lf.dx == pytest.approx(math.sqrt(0.5)) and lf.dy == pytest.approx(math.sqrt(0.5))


def test_round_trip() -> None:
    lf = LineFrame.build((0.12, 0.62), (0.78, 0.38), 240, 426)
    assert lf is not None
    for p in ((0.5, 0.5), (0.1, 0.9), (0.9, 0.05), (0.0, 0.0)):
        assert lf.to_image(*lf.to_frame(*p)) == pytest.approx(p, abs=1e-12)


def test_parity_vectors() -> None:
    """Swift `LineFrameTests` aynı sayıları doğrular."""
    lf = LineFrame.build((0.12, 0.62), (0.78, 0.38), 240, 426)
    assert lf is not None
    assert lf.alpha == pytest.approx(0.5633802816901409, abs=1e-15)
    assert (lf.dx, lf.dy) == pytest.approx((0.8401843886289171, -0.5423008326604828), abs=1e-15)
    assert lf.bounds == pytest.approx((-0.3628755145154736, 0.8527686356824272, -0.6575769124537358,
                                       0.6881290720402419), abs=1e-15)
    assert lf.to_frame(0.5, 0.5) == pytest.approx((0.2449465605834768, 0.015276079793253017), abs=1e-15)
    assert lf.to_frame(0.1, 0.9) == pytest.approx((-0.16131109949568356, 0.2291411968987956), abs=1e-15)


def test_segment_frame_boxes_parity() -> None:
    """Çerçeve kutusu piksellerden; Swift `testSegmentFrameBoxesParity` ile aynı giriş ve sayılar."""
    w, h = 60, 40
    img = np.zeros((h, w), np.uint8)
    for j in range(h):
        for i in range(w):
            if abs(i - 30) + abs(j - 20) <= 9 or (4 <= i <= 8 and 3 <= j <= 7):
                img[j, i] = 200
    seg = BackgroundSegmenter()
    seg.learn(np.zeros((h, w), np.uint8), 1.0)
    lf = LineFrame.build((0.1, 0.8), (0.9, 0.3), w, h)
    blobs = sorted(seg.segment(img, Roi(0, 0, 1, 1), 50, 0, 0.02, None, lf), key=lambda b: b.cx)
    assert [(b.cx, b.cy) for b in blobs] == [(0.1, 0.125), (0.5, 0.5)]
    assert blobs[0].frame_bbox == pytest.approx((0.1884615384615384, -0.6846153846153846,
                                                 0.15576923076923074, 0.15576923076923085), abs=1e-12)
    assert blobs[1].frame_bbox == pytest.approx((0.4692307692307692, -0.23653846153846164,
                                                 0.41346153846153855, 0.41346153846153855), abs=1e-12)


def test_profile_round_trip() -> None:
    p = Profile.egg()
    p.countLine = ((0.12, 0.62), (0.78, 0.38))
    back = Profile.from_dict(p.to_dict())
    assert back.countLine == p.countLine
    assert "countLine" not in Profile.egg().to_dict()


# --- sayım ------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def egg_profile() -> Profile:
    p = calibrated_egg_profile()
    p.roi = Roi(0.0, 0.0, 1.0, 1.0)           # döndürülmüş bant görüntünün her yerinden geçer
    return p


def with_line(p: Profile, sc: sim.Scenario) -> Profile:
    q = Profile.from_dict(p.to_dict())
    q.countLine = perpendicular_line(sc)
    return q


@pytest.mark.parametrize("angle", [30, 45, 60, 135, 160])
@pytest.mark.parametrize("make", [sim.single_file, sim.touching_vertical], ids=lambda f: f.__name__)
def test_angled_flow_counts(egg_profile: Profile, make, angle: int) -> None:
    sc = make(angle_deg=angle)
    assert run(with_line(egg_profile, sc), sc) == sc.expected_count


@pytest.mark.parametrize("angle", [45, 90, 135])
def test_angled_flicker_pairs(egg_profile: Profile, angle: int) -> None:
    """Değip ayrılan çiftler. 30° ve 60°'de ±1–4 sapma var; düz çizgide de aynı (izleyicinin genel sınırı,
    açılı çizgiden değil) — bkz. docs/03-algorithm.md §4.8 notu."""
    sc = sim.flicker_pairs(angle_deg=angle)
    assert run(with_line(egg_profile, sc), sc) == sc.expected_count


def test_straight_count_line_matches_axis_line(egg_profile: Profile) -> None:
    """Yatay `countLine` (soldan sağa, y = 0.5) eski "aşağı, 0.5" çizgisiyle aynı sayar."""
    for make in sim.ALL:
        sc = make()
        axis = Profile.from_dict(egg_profile.to_dict())
        axis.direction, axis.linePosition = "down", 0.5
        line = Profile.from_dict(egg_profile.to_dict())
        line.countLine = ((0.0, 0.5), (1.0, 0.5))
        assert run(line, sc) == run(axis, sc) == sc.expected_count, make.__name__
