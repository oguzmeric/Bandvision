"""Açılı sayım çizgisi çerçevesi — docs/03-algorithm.md §4.8.

Lekeler çizgiye göre döndürülmüş bir çerçeveye taşınır: `v` çizgi boyunca, `u` akış yönünde (çizgi `u = 0`).
İzleyici bu çerçevede "aşağı akış, çizgi 0" ile değişmeden çalışır. Swift `LineFrame` ile birebir aynı işlem sırası.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .segmenter import Blob

Point = tuple[float, float]


@dataclass(frozen=True)
class LineFrame:
    alpha: float   # w / h: normalize x → kare yüksekliği birimi
    ax: float      # A (eş ölçekli)
    ay: float
    dx: float      # çizgi yönü (birim)
    dy: float
    bounds: tuple[float, float, float, float]   # v0, v1, u0, u1 (silme sınırı, ±0.1 dahil)

    @classmethod
    def build(cls, a: Point, b: Point, w: int, h: int) -> LineFrame | None:
        alpha = w / h
        ax, ay = a[0] * alpha, a[1]
        bx, by = b[0] * alpha, b[1]
        length = math.hypot(bx - ax, by - ay)
        if length < 1e-6:
            return None
        dx, dy = (bx - ax) / length, (by - ay) / length
        partial = cls(alpha, ax, ay, dx, dy, (0.0, 0.0, 0.0, 0.0))
        corners = [partial.to_frame(x, y) for x, y in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))]
        vs, us = [c[0] for c in corners], [c[1] for c in corners]
        return cls(alpha, ax, ay, dx, dy, (min(vs) - 0.1, max(vs) + 0.1, min(us) - 0.1, max(us) + 0.1))

    @property
    def nx(self) -> float:
        return -self.dy

    @property
    def ny(self) -> float:
        return self.dx

    def to_frame(self, x: float, y: float) -> Point:
        rx, ry = x * self.alpha - self.ax, y - self.ay
        return rx * self.dx + ry * self.dy, rx * self.nx + ry * self.ny

    def to_image(self, v: float, u: float) -> Point:
        qx = self.ax + v * self.dx + u * self.nx
        qy = self.ay + v * self.dy + u * self.ny
        return qx / self.alpha, qy

    def blob(self, b: Blob) -> Blob:
        """Leke çerçeveye: merkez (v, u); kutu piksellerden (`frame_bbox`), yoksa görüntü kutusunun köşelerinden."""
        v, u = self.to_frame(b.cx, b.cy)
        if b.frame_bbox is not None:                     # piksellerden (segmentasyon), doğru kapsam
            return Blob(cx=v, cy=u, bbox=b.frame_bbox, area=b.area, label=b.label, multiplicity=b.multiplicity)
        x, y, bw, bh = b.bbox                            # yedek: kutu köşelerinden (testlerde elle kurulan lekeler)
        pts = [self.to_frame(px, py) for px, py in ((x, y), (x + bw, y), (x, y + bh), (x + bw, y + bh))]
        v0, v1 = min(p[0] for p in pts), max(p[0] for p in pts)
        u0, u1 = min(p[1] for p in pts), max(p[1] for p in pts)
        return Blob(cx=v, cy=u, bbox=(v0, u0, v1 - v0, u1 - u0), area=b.area, label=b.label,
                    multiplicity=b.multiplicity)


def nearest_direction(a: Point, b: Point, aspect: float) -> str:
    """Akış vektörüne (a→b'nin sağ eli) en yakın eksen yönü; uyumluluk için `direction` alanına yazılır."""
    dx, dy = (b[0] - a[0]) * aspect, b[1] - a[1]
    fx, fy = -dy, dx
    if abs(fy) >= abs(fx):
        return "down" if fy > 0 else "up"
    return "right" if fx > 0 else "left"
