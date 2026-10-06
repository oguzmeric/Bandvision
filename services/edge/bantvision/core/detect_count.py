"""Tanıma tabanlı iki yönlü geçiş sayımı (kişi, araç, hayvan) — docs/03-algorithm.md §4.10.

Her karede nesne tanıma (core/detector.py) kutuları verir; kişi izleyicisi (core/people_track.py) kimlikleri korur
ve tampon bantlı çizgiyi bir yönde geçeni giriş, öbür yönde geçeni çıkış sayar.

Doğruluk için:
- Tanıma yalnızca ROI'nin (sınır kutusu + %5 pay) kesitinde yapılır: model girdisi sabit (640) olduğundan alan
  küçüldükçe kişiler büyür, kapıdaki uzak/küçük kişiler daha iyi bulunur.
- Düşük güvenli tespitler de istenir (izleyici yalnızca mevcut izi sürdürmekte kullanır).
- İsteğe bağlı döşeme (`tiles`): kare örtüşen parçalara bölünüp ayrıca taranır (küçük kişiler büyür).
- Hareket desteği (`MotionDetector`): tepeden kamerada tanımanın kaçırdığı kişiyi hareket lekesi taşır; sayım
  yine en az bir gerçek tanımayla doğrulanan izlerle yapılır (bkz. people_track).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import cv2
import numpy as np

from .detector import ObjectDetector
from .lineframe import LineFrame
from .people_track import MotTrack, MotTracker, iou
from .profile import Profile
from .staff_color import vote_bgr

NormBox = tuple[float, float, float, float]


@dataclass
class DetectResult:
    tracks: list[MotTrack]                          # bu karede gözlenen onaylı izler (çizim)
    detections: list[tuple[NormBox, float]]         # normalize kutu, güven
    entries: list[MotTrack]
    exits: list[MotTrack]
    line: tuple[tuple[float, float], tuple[float, float]] = field(default=((0.0, 0.5), (1.0, 0.5)))
    motion: list[NormBox] = field(default_factory=list)  # hareket lekeleri (çizim/teşhis)
    staff_entries: list[MotTrack] = field(default_factory=list)     # §4.10 eki: personel geçişleri
    staff_exits: list[MotTrack] = field(default_factory=list)


def inside_roi(profile: Profile, x: float, y: float) -> bool:
    r = profile.roi
    if not (r.x <= x < r.x + r.width and r.y <= y < r.y + r.height):
        return False
    poly = profile.roiPolygon
    if not poly:
        return True
    inside = False
    n = len(poly)
    for k in range(n):                        # §2.0 çift-tek kuralı (aynı işlem sırası)
        xa, ya = poly[k]
        xb, yb = poly[k - 1]
        if (ya > y) != (yb > y) and x < (xb - xa) * (y - ya) / (yb - ya) + xa:
            inside = not inside
    return inside


def side_function(profile: Profile, w: int, h: int
                  ) -> tuple[Callable[[float, float], float], tuple[tuple[float, float], tuple[float, float]]]:
    """Çapa noktasının çizgiye işaretli uzaklığı (giriş yönü pozitif) ve çizimlik çizgi uçları."""
    if profile.countLine:
        a, b = profile.countLine
        lf = LineFrame.build(a, b, w, h)
        if lf is not None:
            return (lambda x, y: lf.to_frame(x, y)[1]), (a, b)
    lp, r = profile.linePosition, profile.roi
    if profile.vertical:
        return (lambda x, y: profile.sign * (y - lp)), ((r.x, lp), (r.x + r.width, lp))
    return (lambda x, y: profile.sign * (x - lp)), ((lp, r.y), (lp, r.y + r.height))


TILE_OVERLAP = 0.3


def nms(boxes: list[tuple[NormBox, float]], thr: float) -> list[tuple[NormBox, float]]:
    """Sınıftan bağımsız NMS (tam kare + döşeme sonuçlarını birleştirir); yüksek güvenli kalır."""
    kept: list[tuple[NormBox, float]] = []
    for b, s in sorted(boxes, key=lambda x: -x[1]):
        if all(iou(np.asarray(b), np.asarray(k)) < thr for k, _ in kept):
            kept.append((b, s))
    return kept


class MotionDetector:
    """Hareket lekeleri: küçük gri karede, yalnızca hareketsiz yerlerde güncellenen arka plana göre fark.

    Arka plan hareketli piksellerde güncellenmez (yavaş yürüyen kişi arka plana karışmaz); her yerde çok yavaş
    güncellenir (ışık değişimi, yer değiştiren eşya zamanla emilir).
    """

    def __init__(self, width: int = 160, threshold: float = 22.0, min_area: float = 0.002) -> None:
        self.width = width
        self.threshold = threshold
        self.min_area = min_area                 # kare alanına oranla en küçük leke
        self.bg: np.ndarray | None = None

    def reset(self) -> None:
        self.bg = None

    def __call__(self, bgr: np.ndarray, profile: Profile) -> list[NormBox]:
        h0, w0 = bgr.shape[:2]
        w = self.width
        h = max(1, round(h0 * w / w0))
        g = cv2.cvtColor(cv2.resize(bgr, (w, h), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        g = cv2.GaussianBlur(g, (5, 5), 0).astype(np.float32)
        if self.bg is None or self.bg.shape != g.shape:
            self.bg = g
            return []
        fg = (np.abs(g - self.bg) > self.threshold).astype(np.uint8)
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        still = fg == 0
        self.bg[still] += 0.05 * (g[still] - self.bg[still])
        self.bg += 0.002 * (g - self.bg)
        n, _, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
        out: list[NormBox] = []
        for k in range(1, n):
            x, y, bw, bh, area = (int(v) for v in stats[k])
            if area < self.min_area * w * h:
                continue
            b = (x / w, y / h, (x + bw) / w, (y + bh) / h)
            if inside_roi(profile, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2):
                out.append(b)
        return out


GATE_RECHECK_S = 1.0                            # hareket yokken de en geç bu aralıkla tanıma


class DetectCounter:
    def __init__(self, detector: ObjectDetector | None = None, tiles: int = 0, motion: bool = True) -> None:
        self._detector = detector
        self.tiles = tiles
        self.motion = MotionDetector() if motion else None
        self.tracker = MotTracker()
        self._gate: MotionDetector | None = None
        self._idle_frames = 0

    def enable_gate(self) -> None:
        """Canlı (çok kamera): alanda hareket ve iz yokken kişi tanıma atlanır (saniyede bir yine çalışır).
        Boş giriş/koridorda işlemci kişinin olduğu kameraya kalır. Hassas eşik: kaçırmak yerine boşuna çalışsın."""
        self._gate = MotionDetector(threshold=12.0)

    @property
    def detector(self) -> ObjectDetector:
        if self._detector is None:
            self._detector = ObjectDetector()
        return self._detector

    def reset(self) -> None:
        self.tracker.reset()
        if self.motion is not None:
            self.motion.reset()
        if self._gate is not None:
            self._gate.reset()
        self._idle_frames = 0

    def detect(self, bgr: np.ndarray, profile: Profile, low: float) -> list[tuple[NormBox, float]]:
        h, w = bgr.shape[:2]
        r = profile.roi
        mx, my = 0.05 * r.width, 0.05 * r.height
        x0, y0 = max(0, int((r.x - mx) * w)), max(0, int((r.y - my) * h))
        x1 = min(w, int(np.ceil((r.x + r.width + mx) * w)))
        y1 = min(h, int(np.ceil((r.y + r.height + my) * h)))
        regions = [(x0, y0, x1, y1)]
        if self.tiles > 1:                      # örtüşen döşemeler: küçük/tepeden görünen kişi büyütülerek bulunur
            n = self.tiles
            tw, th = (x1 - x0) / (n - (n - 1) * TILE_OVERLAP), (y1 - y0) / (n - (n - 1) * TILE_OVERLAP)
            for i in range(n):
                for j in range(n):
                    tx, ty = x0 + i * tw * (1 - TILE_OVERLAP), y0 + j * th * (1 - TILE_OVERLAP)
                    regions.append((int(tx), int(ty), int(min(x1, tx + tw)), int(min(y1, ty + th))))
        boxes: list[tuple[NormBox, float]] = []
        for rx0, ry0, rx1, ry1 in regions:
            for d in self.detector.detect(bgr[ry0:ry1, rx0:rx1], profile.detectClasses, conf=low):
                boxes.append((((d.x1 + rx0) / w, (d.y1 + ry0) / h, (d.x2 + rx0) / w, (d.y2 + ry0) / h), d.score))
        if len(regions) > 1:
            boxes = nms(boxes, 0.5)
        return [(b, s) for b, s in boxes if inside_roi(profile, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2)]

    def process(self, bgr: np.ndarray, profile: Profile, fps: float) -> DetectResult:
        h, w = bgr.shape[:2]
        p = self.tracker.p
        p.min_hits = max(1, profile.minHits)
        p.max_age = max(5, round(fps * 1.0))
        p.high = max(profile.detectConfidence, p.low + 0.05)
        idle = (self._gate is not None and not self.tracker.tracks and not self._gate(bgr, profile)
                and self._idle_frames < max(1, round(fps * GATE_RECHECK_S)))
        if idle:
            self._idle_frames += 1
            dets: list[tuple[NormBox, float]] = []
        else:
            if self._gate is not None and self.tracker.tracks:
                self._gate(bgr, profile)                # arka plan güncel kalsın
            self._idle_frames = 0
            dets = self.detect(bgr, profile, p.low)
        side_of, line = side_function(profile, w, h)
        # Hareket desteği yalnızca tepeden kamerada (konum noktası merkez): yatık/yandan kamerada tanıyıcı kişiyi
        # zaten bulur; kapı, ekran, gölge hareketi ise hayalet iz üretir.
        blobs = self.motion(bgr, profile) if self.motion is not None and profile.countAnchor == "center" else None
        r = profile.roi
        colors = profile.staffColors
        anchor_mode = profile.countAnchor

        def staff_vote(box: np.ndarray, others: list[np.ndarray]) -> bool | None:
            return vote_bgr(bgr, tuple(float(v) for v in box), [tuple(float(v) for v in o) for o in others],
                            anchor_mode, colors)

        ins, outs = self.tracker.update(dets, side_of, profile.countAnchor, blobs,
                                        (r.x, r.y, r.x + r.width, r.y + r.height),
                                        staff_vote if colors else None)
        seen = [t for t in self.tracker.tracks if t.confirmed and t.misses == 0]
        return DetectResult(seen, dets, ins, outs, line, blobs or [],
                            list(self.tracker.staff_entered), list(self.tracker.staff_exited))
