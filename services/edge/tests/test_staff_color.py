"""Personel rengi (§4.10 eki): renk çevirisi, gövde bölgesi, kare oyu, öğretme."""
from __future__ import annotations

import numpy as np
import pytest

from bantvision.core import staff_color as sc

ORANGE = (240, 120, 20)          # RGB yelek
NAVY = (25, 35, 80)


def frame_with(person_rgb: tuple[int, int, int], box: tuple[float, float, float, float], vest: float = 1.0,
               shirt: tuple[int, int, int] = (200, 200, 200), size: tuple[int, int] = (640, 360),
               shade: float = 1.0) -> np.ndarray:
    """Gri zemin; kutuda kişi: gövdenin `vest` kadarlık orta şeridi `person_rgb`, kalan gövde `shirt`."""
    w, h = size
    img = np.full((h, w, 3), 128, np.uint8)
    x1, y1, x2, y2 = (int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h))
    img[y1:y2, x1:x2] = np.array(shirt[::-1], np.uint8)
    bw = x2 - x1
    vx1, vx2 = x1 + int(bw * (0.5 - vest / 2)), x1 + int(bw * (0.5 + vest / 2))
    img[y1:y2, vx1:vx2] = np.array(person_rgb[::-1], np.uint8)
    return np.clip(img.astype(np.float64) * shade, 0, 255).astype(np.uint8)


def lab_of(rgb: tuple[int, int, int]) -> sc.LabColor:
    return sc.srgb_to_lab(*rgb)


def test_srgb_to_lab_reference_values() -> None:
    for rgb, ref in [((255, 255, 255), (100.0, 0.0, 0.0)), ((0, 0, 0), (0.0, 0.0, 0.0)),
                     ((255, 0, 0), (53.24, 80.09, 67.20)), ((0, 255, 0), (87.73, -86.18, 83.18)),
                     ((0, 0, 255), (32.30, 79.19, -107.86)), ((128, 128, 128), (53.59, 0.0, 0.0))]:
        got = sc.srgb_to_lab(*rgb)
        assert got == pytest.approx(ref, abs=0.02), rgb


def test_torso_region_depends_on_camera_mount() -> None:
    box = (0.2, 0.1, 0.4, 0.9)
    assert sc.torso_region(box, "bottom") == pytest.approx((0.26, 0.22, 0.34, 0.46))
    assert sc.torso_region(box, "center") == pytest.approx((0.26, 0.34, 0.34, 0.66))


def test_grid_points_row_major_and_pixel_clamp() -> None:
    pts = sc.grid_points((0.0, 0.0, 1.0, 1.0))
    assert len(pts) == 144 and pts[0] == pytest.approx((1 / 24, 1 / 24)) and pts[1][1] == pts[0][1]
    assert sc.to_pixel(1.0, 1.0, 640, 360) == (639, 359) and sc.to_pixel(-0.1, 0.5, 640, 360) == (0, 180)


def test_vote_full_uniform_partial_vest_shade_and_other_colour() -> None:
    box = (0.4, 0.1, 0.5, 0.9)
    colors = [lab_of(ORANGE)]
    assert sc.vote_bgr(frame_with(ORANGE, box), box, [], "bottom", colors) is True
    assert sc.vote_bgr(frame_with(ORANGE, box, vest=0.35), box, [], "bottom", colors) is True      # yelek
    assert sc.vote_bgr(frame_with(ORANGE, box, shade=0.85), box, [], "bottom", colors) is True     # hafif gölge
    assert sc.vote_bgr(frame_with(NAVY, box), box, [], "bottom", colors) is False


def test_vote_ignores_points_inside_neighbour_box() -> None:
    """Yan yana grup: müşterinin gövdesine giren personel kutusunun noktaları sayılmaz."""
    w, h = 640, 360
    img = np.full((h, w, 3), 128, np.uint8)
    cust, staff = (0.40, 0.1, 0.50, 0.9), (0.45, 0.1, 0.55, 0.9)
    img[int(0.1 * h):int(0.9 * h), int(0.40 * w):int(0.50 * w)] = NAVY[::-1]
    img[int(0.1 * h):int(0.9 * h), int(0.45 * w):int(0.55 * w)] = ORANGE[::-1]     # öndeki personel örtüyor
    colors = [lab_of(ORANGE)]
    assert sc.vote_bgr(img, cust, [], "bottom", colors) is True                     # dışlamasız: karışır
    assert sc.vote_bgr(img, cust, [staff], "bottom", colors) is False               # komşunun noktaları dışlandı


def test_vote_none_for_tiny_box_and_dark_points_never_match() -> None:
    colors = [lab_of(ORANGE)]
    assert sc.vote_bgr(frame_with(ORANGE, (0.5, 0.5, 0.505, 0.52)), (0.5, 0.5, 0.505, 0.52), [], "bottom",
                       colors) is None
    dark = sc.labs_from_rgb(np.array([[3, 3, 3]] * 144, np.uint8))
    assert sc.vote_labs(dark, [(2.0, 0.0, 0.0)]) is False


def test_is_staff_needs_three_votes_and_majority() -> None:
    assert not sc.is_staff(2, 2)
    assert sc.is_staff(3, 2) and sc.is_staff(4, 2) and not sc.is_staff(5, 2)


def test_achromatic_warning() -> None:
    assert sc.is_achromatic(lab_of((20, 20, 20))) and sc.is_achromatic(lab_of(NAVY))
    assert not sc.is_achromatic(lab_of(ORANGE))


def test_teach_from_box_patch_and_dark() -> None:
    box = (0.4, 0.1, 0.5, 0.9)
    img = frame_with(ORANGE, box, vest=0.6)
    c = sc.teach_bgr(img, [box], (0.45, 0.4), "bottom")
    assert c is not None and sc.color_distance(c, lab_of(ORANGE)) < 3
    c2 = sc.teach_bgr(img, [], (0.45, 0.3), "bottom")                     # kutusuz: tıklanan yerin çevresi
    assert c2 is not None and sc.color_distance(c2, lab_of(ORANGE)) < 3
    black = np.zeros((360, 640, 3), np.uint8)
    assert sc.teach_bgr(black, [], (0.5, 0.5), "bottom") is None


class _FakeDetector:
    """Karedeki renkli dikdörtgenleri kişi kutusu olarak döndürür (tanıma modeli gerekmez)."""

    def __init__(self, boxes_per_frame: list[list[tuple[float, float, float, float]]]) -> None:
        self.frames = boxes_per_frame
        self.k = 0

    def detect(self, crop: np.ndarray, _classes: object, conf: float = 0.15) -> list[object]:
        from types import SimpleNamespace

        h, w = crop.shape[:2]
        out = [SimpleNamespace(x1=b[0] * w, y1=b[1] * h, x2=b[2] * w, y2=b[3] * h, score=0.9)
               for b in self.frames[self.k]]
        self.k += 1
        return out


def _run(people: list[tuple[tuple[int, int, int], float]], colors: list[sc.LabColor]) -> tuple[int, int, int]:
    """Yan yana kişiler (renk, x merkezi) yukarıdan aşağı geçer; (giriş, personel giriş, personel çıkış)."""
    from bantvision.core import Pipeline, Profile

    p = Profile.people()
    p.direction, p.linePosition, p.countAnchor, p.staffColors = "down", 0.55, "bottom", colors
    n = 40
    frames, boxes = [], []
    for k in range(n):
        y = 0.05 + 0.6 * k / (n - 1)
        img = np.full((360, 640, 3), 128, np.uint8)
        fb = []
        for rgb, cx in people:
            b = (cx - 0.04, y, cx + 0.04, y + 0.33)
            img[int(b[1] * 360):int(b[3] * 360), int(b[0] * 640):int(b[2] * 640)] = rgb[::-1]
            fb.append(b)
        frames.append(img)
        boxes.append(fb)
    pipe = Pipeline(p)
    pipe.detect._detector = _FakeDetector(boxes)            # type: ignore[assignment]
    pipe.detect.motion = None
    pipe.counting = True
    for k, img in enumerate(frames):
        pipe.process(img, k / 10)
    return pipe.total, pipe.total_staff_in, pipe.total_staff_out


def test_pipeline_counts_staff_separately_in_group() -> None:
    staff = [lab_of(ORANGE)]
    assert _run([(ORANGE, 0.40)], staff) == (0, 1, 0)
    assert _run([(NAVY, 0.40)], staff) == (1, 0, 0)
    assert _run([(ORANGE, 0.40), (NAVY, 0.52)], staff) == (1, 1, 0)       # yan yana: personel + müşteri
    assert _run([(ORANGE, 0.40), (NAVY, 0.52)], []) == (2, 0, 0)          # renk yok: bugünkü davranış
