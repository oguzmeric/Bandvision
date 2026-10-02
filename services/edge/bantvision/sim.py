"""Sentetik bant videosu üretici (testler ve Swift eşdeğerlik vektörleri için)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class Item:
    start_y: float          # tam çözünürlük piksel, t=0 anındaki merkez (negatif = kadraj üstü)
    x: float
    rx: float = 54
    ry: float = 72
    spot: bool = False      # koyu leke
    bite: bool = False      # kenarından ısırılmış (kırık/ezik)
    wobble: float = 0.0     # akış ekseninde salınım genliği (px): bitişik ürünlerin değip ayrılması
    wobble_hz: float = 3.0


@dataclass
class Scenario:
    name: str
    items: list[Item]
    speed_px_s: float = 1080.0          # tam çözünürlükte bant hızı (px/sn)
    fps: float = 60.0
    width: int = 720
    height: int = 1280
    belt: int = 70
    product: int = 200
    noise: float = 3.0
    extra_seconds: float = 0.6
    seed: int = 1
    # Akış açısı (derece, görüntü koordinatı: 90 = aşağı, 0 = sağa). Bant görüntü merkezi etrafında döndürülür.
    angle_deg: float = 90.0
    expected_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.expected_count = len(self.items)

    @property
    def n_frames(self) -> int:
        far = max(-it.start_y for it in self.items) + self.height + 200
        return int((far / self.speed_px_s + self.extra_seconds) * self.fps)

    def _place(self, bx: float, by: float) -> tuple[int, int]:
        """Bant koordinatı (x, akış) → görüntü pikseli (merkez etrafında `angle_deg - 90` döndürülmüş)."""
        if self.angle_deg == 90.0:                       # döndürme yok: eski görüntülerle piksel piksel aynı
            return int(bx), int(by)
        phi = math.radians(self.angle_deg - 90.0)
        cx, cy = self.width / 2, self.height / 2
        dx, dy = bx - cx, by - cy
        return int(cx + dx * math.cos(phi) - dy * math.sin(phi)), int(cy + dx * math.sin(phi) + dy * math.cos(phi))

    def frames(self):
        """(gri kare, zaman damgası) üretir."""
        rng = np.random.default_rng(self.seed)
        tilt = self.angle_deg - 90.0
        for k in range(self.n_frames):
            t = k / self.fps
            img = np.full((self.height, self.width), float(self.belt), np.float32)
            img += rng.normal(0, self.noise, img.shape).astype(np.float32)
            for it in self.items:
                y = it.start_y + t * self.speed_px_s + it.wobble * math.sin(2 * math.pi * it.wobble_hz * t)
                reach = max(self.width, self.height) * 0.6 + it.ry * 1.2   # döndürülmüş bantta görünürlük payı
                if -reach < y < self.height + reach:
                    c = self._place(it.x, y)
                    cv2.ellipse(img, c, (int(it.rx), int(it.ry)), tilt, 0, 360, float(self.product), -1)
                    if it.spot:
                        cv2.circle(img, self._place(it.x + it.rx * 0.2, y - it.ry * 0.2), int(it.rx * 0.22),
                                   float(self.product - 90), -1)
                    if it.bite:
                        cv2.circle(img, self._place(it.x + it.rx * 0.95, y), int(it.rx * 0.55),
                                   float(self.belt), -1)
            yield np.clip(img, 0, 255).astype(np.uint8), t

    def empty_frames(self, seconds: float = 1.5):
        rng = np.random.default_rng(self.seed + 100)
        for k in range(int(seconds * self.fps)):
            img = np.full((self.height, self.width), float(self.belt), np.float32)
            img += rng.normal(0, self.noise, img.shape).astype(np.float32)
            yield np.clip(img, 0, 255).astype(np.uint8), -seconds + k / self.fps


def single_file(n: int = 10, gap: float = 270, **kw) -> Scenario:
    return Scenario("single", [Item(-120 - i * gap, 360) for i in range(n)], **kw)


def three_lanes(n: int = 15, **kw) -> Scenario:
    return Scenario("three_lanes", [Item(-120 - i * 210, x) for i in range(n) for x in (150, 360, 570)],
                    speed_px_s=1620, **kw)


def touching_vertical(n: int = 10, **kw) -> Scenario:
    items: list[Item] = []
    for i in range(n):
        y = -120 - i * 420
        items += [Item(y, 360), Item(y - 141, 360)]
    return Scenario("touching_vertical", items, **kw)


def touching_side(n: int = 10, **kw) -> Scenario:
    items: list[Item] = []
    for i in range(n):
        y = -120 - i * 300
        items += [Item(y, 300), Item(y, 405)]
    return Scenario("touching_side", items, **kw)


def flicker_pairs(n: int = 10, **kw) -> Scenario:
    """Arka arkaya çiftler; arkadaki öndekine bir değip bir ayrılır (gerçek yumurtada sık).

    Leke kareden kareye bir birleşik (×2) bir ayrık görünür; izleyici aynı çifti birden fazla saymamalı.
    """
    items: list[Item] = []
    for i in range(n):
        y = -120 - i * 430
        items += [Item(y, 360), Item(y - 146, 360, wobble=5.0, wobble_hz=4.0 + 0.37 * i)]
    return Scenario("flicker_pairs", items, **kw)


ALL = [single_file, three_lanes, touching_vertical, touching_side, flicker_pairs]
