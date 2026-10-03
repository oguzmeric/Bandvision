"""Hacimli, tek sıra ürünler için sentetik bant videosu (şerit tarama sayımı §4.9 testleri).

Bant ve ürünler uzun bir "şerit" görüntüye boyanır; her kare bu şeridin bant hızına göre kaydırılmış penceresidir
(akış aşağı). Torba: parlak, uçları gölgeli yastık, iç kıvrımlar. Koli: düz renk, koyu kenar, bant ve etiket.
Doğru sayı: merkezi klip boyunca sayım çizgisini geçen ürünler.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class Bulk:
    z: float                 # şeritte öndeki (akış yönünde ilk) ucun konumu
    length: float
    kind: str = "bag"        # "bag" | "box"
    width_frac: float = 0.8
    seed: int = 0

    @property
    def center(self) -> float:
        return self.z + self.length / 2


@dataclass
class BulkScenario:
    name: str
    items: list[Bulk]
    width: int = 240
    height: int = 400
    belt_x: tuple[int, int] = (50, 190)
    belt_level: float = 90.0
    bag_level: float = 220.0
    box_level: float = 150.0
    outside_level: float = 40.0
    noise: float = 2.5
    frames_n: int = 300
    speed: Callable[[int], float] = field(default=lambda k: 2.4)     # piksel/kare
    dup_pattern: tuple[int, ...] = (1,)       # her kare kaç kez tekrarlanır (döngüsel); ekran kaydı taklidi
    start_travel: float = 0.0
    belt_joint_every: float = 0.0             # banttaki enine ek yerleri (0 = yok)
    seed: int = 7

    def travels(self) -> list[float]:
        """Her çıktı karesinin toplam bant kayması (tekrarlanan karelerde aynı)."""
        out: list[float] = []
        d = self.start_travel
        k = 0
        i = 0
        while len(out) < self.frames_n:
            rep = self.dup_pattern[i % len(self.dup_pattern)]
            for _ in range(rep):
                if len(out) < self.frames_n:
                    out.append(d)
            d += self.speed(k) * rep
            k += rep
            i += 1
        return out

    def truth(self, line_pos: float) -> int:
        """Merkezi [ilk kare, son kare] arasında çizgiyi geçen ürün sayısı. Çizgi: satır ≥ b geçmiş (§4.9)."""
        b = math.floor(line_pos * self.height + 0.5)
        tr = self.travels()
        d0, d1 = tr[0], tr[-1]

        def row(z: float, d: float) -> float:
            return self.height - 1 - (z - d)

        return sum(1 for it in self.items if row(it.center, d0) + 0.5 < b <= row(it.center, d1) + 0.5)

    def _strip(self) -> tuple[np.ndarray, float]:
        rng = np.random.default_rng(self.seed)
        z_max = max(it.z + it.length for it in self.items) + self.height + 50
        travel_max = self.travels()[-1] + self.height + 50
        n = int(max(z_max, travel_max)) + 10
        w = self.width
        strip = np.full((n, w), self.outside_level, np.float32)
        bx0, bx1 = self.belt_x
        tex = rng.normal(0, 6, (n, bx1 - bx0)).astype(np.float32)
        tex = cv2.GaussianBlur(tex, (0, 0), 2.0)
        strip[:, bx0:bx1] = self.belt_level + tex
        if self.belt_joint_every > 0:
            z = self.belt_joint_every
            while z < n - 2:
                strip[int(z):int(z) + 2, bx0:bx1] -= 25
                z += self.belt_joint_every
        for it in self.items:
            self._paint(strip, it)
        return strip, 0.0

    def _paint(self, strip: np.ndarray, it: Bulk) -> None:
        rng = np.random.default_rng(self.seed * 1000 + it.seed)
        bx0, bx1 = self.belt_x
        bw = bx1 - bx0
        iw = int(bw * it.width_frac)
        x0 = bx0 + (bw - iw) // 2 + int(rng.integers(-3, 4))
        x0 = max(bx0, min(bx1 - iw, x0))
        z0, z1 = round(it.z), round(it.z + it.length)
        n = z1 - z0
        if n <= 2:
            return
        zz = np.arange(n, dtype=np.float32)[:, None]
        xx = np.arange(iw, dtype=np.float32)[None, :]
        if it.kind == "bag":
            e = 0.18 * n
            end = np.minimum(zz, n - 1 - zz) / e
            pillow = 0.62 + 0.38 * np.clip(end, 0, 1) ** 0.6
            side = 0.85 + 0.15 * np.sin(np.pi * (xx + 0.5) / iw)
            img = self.bag_level * pillow * side
            for _ in range(int(rng.integers(1, 4))):             # iç kıvrımlar
                zc = rng.uniform(0.25, 0.75) * n
                slope = rng.uniform(-0.3, 0.3)
                d = np.abs(zz - (zc + slope * (xx - iw / 2)))
                img -= 28 * np.exp(-(d / 2.0) ** 2) * (rng.uniform(0.3, 0.9) > xx / iw)
            # arka uçta banda düşen gölge
            sh0, sh1 = z1, min(strip.shape[0], z1 + 5)
            strip[sh0:sh1, x0:x0 + iw] = np.minimum(strip[sh0:sh1, x0:x0 + iw], self.belt_level - 45)
        else:
            img = np.full((n, iw), self.box_level, np.float32)
            img[:, iw // 2 - iw // 20: iw // 2 + iw // 20] += 30            # koli bandı (akış boyunca)
            lz, lx = int(rng.uniform(0.15, 0.55) * n), int(rng.uniform(0.05, 0.4) * iw)
            img[lz:lz + int(0.25 * n), lx:lx + int(0.4 * iw)] = 230             # etiket
            img[:2, :] -= 40
            img[-2:, :] -= 40
            img[:, :2] -= 40
            img[:, -2:] -= 40
        strip[z0:z1, x0:x0 + iw] = img

    def frames(self) -> Iterator[tuple[np.ndarray, float]]:
        strip, _ = self._strip()
        rng = np.random.default_rng(self.seed + 1)
        h = self.height
        for k, d in enumerate(self.travels()):
            # Satır y, şeritte z = d + (h − 1 − y) konumunu gösterir (alt piksel: doğrusal karışım)
            zi = math.floor(d)
            fr = d - zi
            a = strip[zi:zi + h][::-1]
            b = strip[zi + 1:zi + 1 + h][::-1]
            img = (1 - fr) * a + fr * b
            img = img + rng.normal(0, self.noise, img.shape).astype(np.float32)
            yield np.clip(img, 0, 255).astype(np.uint8), k / 25.0


def sequence(n: int, length: float, gap: float, kind: str = "bag", jitter: float = 0.08,
             z0: float = 80.0, seed: int = 3, gaps: list[float] | None = None) -> list[Bulk]:
    """n ürün art arda; gap < 0 üst üste binme (torbalar), gaps verilirse her aralık ayrı."""
    rng = np.random.default_rng(seed)
    out: list[Bulk] = []
    z = z0
    for i in range(n):
        ln = length * (1 + rng.uniform(-jitter, jitter))
        out.append(Bulk(z, ln, kind, width_frac=float(rng.uniform(0.72, 0.85)), seed=i))
        g = gaps[i % len(gaps)] if gaps else gap
        z += ln + g
    return out
