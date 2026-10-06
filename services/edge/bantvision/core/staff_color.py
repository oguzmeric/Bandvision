"""Personel rengi (algoritma §4.10 eki): öğretilen üniforma rengini giyen kişinin geçişi müşteri sayılmaz.

Kişi kutusunun gövde bölgesinden 12×12 nokta örneklenir, sRGB → CIE Lab (D65) çevrilir; noktaların ≥ %25'i
öğretilen renge yakınsa (ΔL yarım ağırlıklı uzaklık < 20) o kare personel oyu verir. İz başına oylar birikir; geçiş
anında ≥ 3 oy ve çoğunluk personelse geçiş personel geçişidir. Swift: apps/ios/BantSayac/Vision/StaffColor.swift —
davranış birebir aynı (staff_parity.json). Görüntü saklanmaz; öğretilen renk yalnızca 3 sayıdır.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import median

import numpy as np

LabColor = tuple[float, float, float]
Box = tuple[float, float, float, float]

GRID = 12
MATCH_DIST = 20.0
MIN_FRACTION = 0.25
MIN_POINTS = 36                 # ızgaranın %25'i: komşu kutular çıkarıldıktan sonra kalan en az nokta
DARK_L = 8.0
MIN_VOTES = 3
ACHROMATIC_C = 15.0
TEACH_PATCH = 0.06              # kutusuz öğretmede kare kenarı (görüntü genişliğine oran)
MAX_COLORS = 3
MIN_BOX_PX = (8.0, 16.0)

_M = np.array([[0.4124564, 0.3575761, 0.1804375],
               [0.2126729, 0.7151522, 0.0721750],
               [0.0193339, 0.1191920, 0.9503041]])
_WHITE = np.array([0.95047, 1.0, 1.08883])


def labs_from_rgb(rgb: np.ndarray) -> np.ndarray:
    """N×3 sRGB (0–255) → N×3 Lab."""
    c = np.asarray(rgb, np.float64).reshape(-1, 3) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = (lin[:, 0:1] * _M[:, 0] + lin[:, 1:2] * _M[:, 1] + lin[:, 2:3] * _M[:, 2]) / _WHITE
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)
    return np.stack([116.0 * f[:, 1] - 16.0, 500.0 * (f[:, 0] - f[:, 1]), 200.0 * (f[:, 1] - f[:, 2])], axis=1)


def srgb_to_lab(r: int, g: int, b: int) -> LabColor:
    L, a, bb = labs_from_rgb(np.array([[r, g, b]]))[0]
    return float(L), float(a), float(bb)


def torso_region(box: Box, anchor: str) -> Box:
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    ty0, ty1 = (0.15, 0.45) if anchor == "bottom" else (0.30, 0.70)
    return (x1 + 0.30 * w, y1 + ty0 * h, x1 + 0.70 * w, y1 + ty1 * h)


def grid_points(region: Box) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = region
    rw, rh = x1 - x0, y1 - y0
    return [(x0 + (i + 0.5) / GRID * rw, y0 + (j + 0.5) / GRID * rh) for j in range(GRID) for i in range(GRID)]


def to_pixel(x: float, y: float, w: int, h: int) -> tuple[int, int]:
    return min(max(math.floor(x * w), 0), w - 1), min(max(math.floor(y * h), 0), h - 1)


def color_distance(p: LabColor, q: LabColor) -> float:
    return math.sqrt((0.5 * (p[0] - q[0])) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2)


def vote_labs(labs: np.ndarray, colors: Sequence[LabColor]) -> bool | None:
    """Kalan noktaların ≥ %25'i öğretilen renklerden birine yakınsa personel oyu; < 36 nokta: oy yok."""
    n = len(labs)
    if n < MIN_POINTS or not colors:
        return None
    c = np.asarray(colors, np.float64)
    d = np.sqrt((0.5 * (labs[:, None, 0] - c[None, :, 0])) ** 2 + (labs[:, None, 1] - c[None, :, 1]) ** 2
                + (labs[:, None, 2] - c[None, :, 2]) ** 2)
    hit = (d.min(axis=1) < MATCH_DIST) & (labs[:, 0] >= DARK_L)
    return bool(int(hit.sum()) >= MIN_FRACTION * n)


def _inside(o: Box, x: float, y: float) -> bool:
    return o[0] <= x <= o[2] and o[1] <= y <= o[3]


def vote_bgr(bgr: np.ndarray, box: Box, others: Sequence[Box], anchor: str,
             colors: Sequence[LabColor]) -> bool | None:
    """Bu karede tanımayla gözlenen kutunun oyu. `others`: aynı karedeki diğer tanıma kutuları (noktaları dışlanır)."""
    h, w = bgr.shape[:2]
    if (box[2] - box[0]) * w < MIN_BOX_PX[0] or (box[3] - box[1]) * h < MIN_BOX_PX[1]:
        return None
    pts = [to_pixel(x, y, w, h) for x, y in grid_points(torso_region(box, anchor))
           if not any(_inside(o, x, y) for o in others)]
    if len(pts) < MIN_POINTS:
        return None
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    return vote_labs(labs_from_rgb(bgr[ys, xs, ::-1]), colors)


def is_staff(votes: int, staff_votes: int) -> bool:
    return votes >= MIN_VOTES and 2 * staff_votes >= votes


def is_achromatic(c: LabColor) -> bool:
    return math.hypot(c[1], c[2]) < ACHROMATIC_C


def dominant_color(labs: np.ndarray) -> LabColor | None:
    """(⌊a/8⌋, ⌊b/8⌋) kutucuklarından en kalabalığı (eşitlikte ilk görülen); o kutucuğun L, a, b medyanı."""
    if len(labs) == 0:
        return None
    counts: dict[tuple[int, int], list[int]] = {}
    for k, (_, a, b) in enumerate(labs):
        counts.setdefault((math.floor(a / 8), math.floor(b / 8)), []).append(k)
    best = max(counts.values(), key=len)            # max ilk görünen en büyüğü verir (sözlük ekleme sırası)
    sel = labs[best]
    c = (float(median(sel[:, 0])), float(median(sel[:, 1])), float(median(sel[:, 2])))
    return None if c[0] < DARK_L else c


def teach_bgr(bgr: np.ndarray, boxes: Sequence[Box], point: tuple[float, float], anchor: str) -> LabColor | None:
    """Tıklanan noktayı içeren en küçük kutunun gövdesi; kutu yoksa tıklanan yer çevresi. Çok karanlıksa None."""
    h, w = bgr.shape[:2]
    x, y = point
    inside = [b for b in boxes if _inside(b, x, y)]
    if inside:
        region = torso_region(min(inside, key=lambda b: (b[2] - b[0]) * (b[3] - b[1])), anchor)
    else:
        hx, hy = TEACH_PATCH / 2, TEACH_PATCH / 2 * w / h
        region = (max(0.0, x - hx), max(0.0, y - hy), min(1.0, x + hx), min(1.0, y + hy))
    pts = [to_pixel(px, py, w, h) for px, py in grid_points(region)]
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    return dominant_color(labs_from_rgb(bgr[ys, xs, ::-1]))
