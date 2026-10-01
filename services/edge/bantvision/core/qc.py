"""Kalite kontrol aşama 1: geometri, leke, boy sınıfı — docs/03-algorithm.md §6.
Barkod/metin okuma asenkron olduğundan servis katmanında eklenir (reasons listesine)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from .profile import Profile
from .segmenter import Blob


@dataclass
class InspectionResult:
    track_id: int
    result: str                      # "ok" | "nok"
    reasons: list[str]
    metrics: dict[str, float]
    size_class: str | None = None
    crop: np.ndarray | None = field(default=None, repr=False)  # tam çözünürlüklü kırpıntı (gri)

    def finalize(self) -> None:
        self.result = "nok" if self.reasons else "ok"


_CORNERS = np.array([[0, 0], [1, 0], [0, 1], [1, 1]], np.float32)


def geometry_metrics(labels: np.ndarray, label: int) -> tuple[float, float, float, float]:
    """(aspect, solidity, major_px, minor_px) — işleme pikseli cinsinden."""
    ys, xs = np.nonzero(labels == label)
    n = len(xs)
    if n < 5:
        return 1.0, 1.0, 0.0, 0.0
    pts = np.stack([xs, ys], axis=1).astype(np.float32)
    cov = np.cov(pts.T)
    ev = np.sort(np.linalg.eigvalsh(cov))[::-1]
    l1, l2 = float(max(ev[0], 1e-6)), float(max(ev[1], 1e-6))
    aspect = math.sqrt(l1 / l2)
    corners = (pts[:, None, :] + _CORNERS[None, :, :]).reshape(-1, 2)
    hull = cv2.convexHull(corners)
    hull_area = float(cv2.contourArea(hull))
    solidity = min(1.0, n / hull_area) if hull_area > 0 else 1.0
    return aspect, solidity, 4 * math.sqrt(l1), 4 * math.sqrt(l2)


def inspect(full_gray: np.ndarray, labels: np.ndarray, blob: Blob, track_id: int,
            profile: Profile, factor: int) -> InspectionResult:
    qc = profile.qc
    reasons: list[str] = []
    metrics: dict[str, float] = {}

    # --- geometri ---
    area_ratio = blob.area / profile.expectedArea if profile.expectedArea > 0 else 1.0
    aspect, solidity, major_px, minor_px = geometry_metrics(labels, blob.label)
    metrics.update(areaRatio=round(float(area_ratio), 4), aspect=round(aspect, 4), solidity=round(solidity, 4))
    g = qc.geometry
    if area_ratio < g.areaMinFactor:
        reasons.append("area_low")
    elif area_ratio > g.areaMaxFactor:
        reasons.append("area_high")
    if not (g.aspectMin <= aspect <= g.aspectMax):
        reasons.append("aspect_out")
    if solidity < g.solidityMin:
        reasons.append("solidity_low")

    # --- boy ---
    size_class = None
    major_full, minor_full = major_px * factor, minor_px * factor
    if profile.mmPerPixel:
        minor_mm = minor_full * profile.mmPerPixel
        metrics.update(majorMm=round(major_full * profile.mmPerPixel, 2), minorMm=round(minor_mm, 2))
        for sc in qc.sizeClasses:
            if minor_mm <= sc.maxMm:
                size_class = sc.name
                break

    # --- tam çözünürlüklü kırpıntı ---
    lh, lw = labels.shape
    bx, by, bw, bh = blob.bbox
    x0, y0 = int(bx * lw), int(by * lh)
    x1, y1 = min(lw, x0 + max(1, round(bw * lw))), min(lh, y0 + max(1, round(bh * lh)))
    fx0, fy0, fx1, fy1 = x0 * factor, y0 * factor, x1 * factor, y1 * factor
    obj = full_gray[fy0:fy1, fx0:fx1]

    if qc.spots.enabled and obj.size > 0:
        m_small = (labels[y0:y1, x0:x1] == blob.label).astype(np.uint8)
        m_full = cv2.resize(m_small, (obj.shape[1], obj.shape[0]), interpolation=cv2.INTER_NEAREST)
        # büyütülmüş maskenin kenarındaki karışık bloklar + gölge payı (§6.3)
        k = factor + int(0.03 * minor_full)
        # kırpıntı kenarı da 'dışarı' sayılır (borderValue=0), yoksa kenar pikselleri aşınmaz
        m_full = cv2.erode(m_full, np.ones((2 * k + 1, 2 * k + 1), np.uint8),
                           borderType=cv2.BORDER_CONSTANT, borderValue=0)
        inside = obj[m_full > 0]
        if inside.size > 0:
            ref = float(np.median(inside))
            spot = int(np.count_nonzero(inside < ref - qc.spots.darkDelta))
            spot_ratio = spot / inside.size
            metrics["spotRatio"] = round(spot_ratio, 5)
            if spot_ratio > qc.spots.maxSpotAreaRatio:
                reasons.append("spots")

    # NOK görseli için %10 dolgulu kırpıntı
    fh, fw = full_gray.shape
    px, py = int(0.1 * (fx1 - fx0)), int(0.1 * (fy1 - fy0))
    crop = full_gray[max(0, fy0 - py):min(fh, fy1 + py), max(0, fx0 - px):min(fw, fx1 + px)].copy()

    res = InspectionResult(track_id=track_id, result="ok", reasons=reasons, metrics=metrics,
                           size_class=size_class, crop=crop)
    res.finalize()
    return res
