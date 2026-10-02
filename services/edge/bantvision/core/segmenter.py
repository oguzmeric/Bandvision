"""Arka plan farkı segmentasyonu — docs/03-algorithm.md §1–§2."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np

from .profile import Roi

_K3 = np.ones((3, 3), np.uint8)
# §2.4: ürün altındaki arka plan güncelleme katsayısı (yoğun akışta kaymayı önlemek için çok küçük)
FG_RATE_FACTOR = 0.002


@dataclass
class Blob:
    cx: float
    cy: float
    bbox: tuple[float, float, float, float]  # x, y, w, h (normalize)
    area: float                               # normalize
    label: int                                # bileşen etiketi (QC için)
    multiplicity: int = 1


def downsample(gray: np.ndarray, processing_width: int) -> tuple[np.ndarray, int]:
    """Kutu-ortalama ile tam sayı faktörlü küçültme. (küçük kare, faktör) döner."""
    h, w = gray.shape[:2]
    f = max(1, w // max(64, processing_width))
    ow, oh = w // f, h // f
    if f == 1:
        return gray[:oh, :ow].copy(), 1
    small = gray[: oh * f, : ow * f].reshape(oh, f, ow, f).mean(axis=(1, 3))
    return small.astype(np.uint8), f


def roi_pixels(roi: Roi, w: int, h: int) -> tuple[int, int, int, int]:
    x0 = max(0, min(w - 1, int(roi.x * w)))
    y0 = max(0, min(h - 1, int(roi.y * h)))
    x1 = max(x0 + 1, min(w, int((roi.x + roi.width) * w)))
    y1 = max(y0 + 1, min(h, int((roi.y + roi.height) * h)))
    return x0, y0, x1, y1


Polygon = Sequence[tuple[float, float]]


def roi_mask(roi: Roi, polygon: Polygon | None, w: int, h: int) -> np.ndarray:
    """§2.0 ROI maskesi (bool, h×w): dikdörtgen ∩ çokgen. Çokgen: piksel merkezi, çift-tek kuralı.

    İşlem sırası dokümandakiyle aynıdır; Swift `BackgroundSegmenter.roiMask` aynı pikselleri seçer.
    """
    mask = np.zeros((h, w), bool)
    x0, y0, x1, y1 = roi_pixels(roi, w, h)
    mask[y0:y1, x0:x1] = True
    if not polygon:
        return mask
    px = (np.arange(w, dtype=np.float64) + 0.5) / w
    py = (np.arange(h, dtype=np.float64) + 0.5) / h
    gx, gy = np.meshgrid(px, py)
    inside = np.zeros((h, w), bool)
    n = len(polygon)
    for k in range(n):
        xa, ya = polygon[k]
        xb, yb = polygon[k - 1]
        crosses = (ya > gy) != (yb > gy)
        if not crosses.any():
            continue
        with np.errstate(divide="ignore", invalid="ignore"):
            xc = (xb - xa) * (gy - ya) / (yb - ya) + xa
        inside ^= crosses & (gx < xc)
    return mask & inside


class BackgroundSegmenter:
    def __init__(self) -> None:
        self.bg: np.ndarray | None = None
        self.mask: np.ndarray | None = None
        self.labels: np.ndarray | None = None
        self._roi_key: tuple | None = None
        self._roi_mask: np.ndarray | None = None

    def roi_mask(self, roi: Roi, polygon: Polygon | None, w: int, h: int) -> np.ndarray:
        """Önbellekli §2.0 maskesi (ROI ya da boyut değişince yeniden)."""
        key = (w, h, roi.x, roi.y, roi.width, roi.height, tuple(polygon) if polygon else None)
        if key != self._roi_key or self._roi_mask is None:
            self._roi_key, self._roi_mask = key, roi_mask(roi, polygon, w, h)
        return self._roi_mask

    @property
    def has_background(self) -> bool:
        return self.bg is not None

    def reset(self) -> None:
        self.bg = None

    def _ensure(self, gray: np.ndarray) -> None:
        if self.bg is not None and self.bg.shape != gray.shape:
            self.bg = None

    def learn(self, gray: np.ndarray, rate: float) -> None:
        self._ensure(gray)
        if self.bg is None or rate >= 1:
            self.bg = gray.astype(np.float32)
            return
        self.bg += rate * (gray.astype(np.float32) - self.bg)

    def diff_percentile(self, gray: np.ndarray, roi: Roi, p: float, polygon: Polygon | None = None) -> int:
        if self.bg is None or self.bg.shape != gray.shape:
            return 0
        h, w = gray.shape
        x0, y0, x1, y1 = roi_pixels(roi, w, h)
        inside = self.roi_mask(roi, polygon, w, h)[y0:y1, x0:x1]
        d = np.abs(gray[y0:y1, x0:x1].astype(np.float32) - self.bg[y0:y1, x0:x1])[inside]
        if d.size == 0:
            return 0
        d = np.minimum(d.astype(np.int32), 255)
        hist = np.bincount(d.ravel(), minlength=256)
        target = int(d.size * p)
        cum = np.cumsum(hist)
        return int(np.searchsorted(cum, target))

    def segment(self, gray: np.ndarray, roi: Roi, threshold: int, close_iterations: int,
                rate: float, polygon: Polygon | None = None) -> list[Blob]:
        self._ensure(gray)
        if self.bg is None:
            self.bg = gray.astype(np.float32)
            self.mask = np.zeros_like(gray, np.uint8)
            self.labels = np.zeros(gray.shape, np.int32)
            return []
        h, w = gray.shape
        x0, y0, x1, y1 = roi_pixels(roi, w, h)
        g = gray.astype(np.float32)
        mask = np.zeros((h, w), np.uint8)
        inside = self.roi_mask(roi, polygon, w, h)[y0:y1, x0:x1]
        mask[y0:y1, x0:x1] = ((np.abs(g[y0:y1, x0:x1] - self.bg[y0:y1, x0:x1]) > threshold) & inside).astype(np.uint8)

        # açma + kapama (OpenCV varsayılan kenar değerleri §2.2 ile uyumlu)
        mask = cv2.dilate(cv2.erode(mask, _K3), _K3)
        for _ in range(max(0, close_iterations)):
            mask = cv2.erode(cv2.dilate(mask, _K3), _K3)

        # seçici arka plan güncellemesi
        r = np.where(mask == 0, rate, rate * FG_RATE_FACTOR).astype(np.float32)
        self.bg += r * (g - self.bg)

        n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
        self.mask, self.labels = mask, labels
        total = float(w * h)
        blobs: list[Blob] = []
        for i in range(1, n):
            bx, by, bw, bh, area = stats[i]
            blobs.append(Blob(cx=float(cents[i][0]) / w, cy=float(cents[i][1]) / h,
                              bbox=(bx / w, by / h, bw / w, bh / h), area=area / total, label=i))
        return blobs
