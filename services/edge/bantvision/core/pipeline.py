"""Uçtan uca çekirdek: ön işleme → segmentasyon → izleme → sayım → QC.
Kaynaktan bağımsızdır: process(frame, ts) alır. docs/03-algorithm.md"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from .lineframe import LineFrame
from .linescan import LineScanCounter
from .profile import Profile
from .qc import InspectionResult, inspect
from .segmenter import BackgroundSegmenter, Blob, downsample
from .tracker import BlobTracker, CountEvent, TrackMarker, median

_ROT = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}


@dataclass
class FrameResult:
    ts: float
    blobs: list[Blob]
    tracks: list[TrackMarker]
    counts: list[CountEvent]
    inspections: list[InspectionResult]
    calibration: list[tuple[str, Any]]
    state_change: bool | None
    fps: float
    total: int
    frame_size: tuple[int, int]
    gray_small: np.ndarray | None = field(default=None, repr=False)


class Pipeline:
    def __init__(self, profile: Profile, idle_seconds: float = 30.0) -> None:
        self.profile = profile
        self.idle_seconds = idle_seconds
        self.segmenter = BackgroundSegmenter()
        self.tracker = BlobTracker()
        self.linescan = LineScanCounter()       # §4.9 (countMode = "linescan")
        self.counting = True
        self.total = 0
        self._calib: str | None = None          # "background" | "sample"
        self._calib_n = 0
        self._calib_max = 0
        self._calib_areas: list[float] = []
        self._calib_target = 8
        self._calib_update = True
        self._ts: deque[float] = deque()
        self._last_activity: float | None = None
        self.running = False
        self.factor = 1
        self._frame: LineFrame | None = None

    # ---- kontrol ----
    def set_profile(self, profile: Profile, reset_background: bool = False) -> None:
        self.profile = profile
        self.tracker.reset()
        self.linescan.reset()
        if reset_background:
            self.segmenter.reset()

    def start_background_learning(self, update_threshold: bool = True) -> None:
        """§5. `update_threshold=False` (video başında otomatik): yalnızca arka plan görüntüsü öğrenilir,
        kaydedilmiş eşik korunur."""
        self.tracker.reset()
        self.linescan.reset()
        self._calib, self._calib_n, self._calib_max = "background", 0, 0
        self._calib_update = update_threshold

    def start_sample_learning(self, target: int = 8) -> None:
        self.tracker.reset()
        self.linescan.reset()               # şerit taramada: ürün boyu baştan öğrenilir
        self._calib, self._calib_areas, self._calib_target = "sample", [], target

    def cancel_calibration(self) -> None:
        self._calib = None

    def reset_count(self) -> None:
        self.total = 0
        self.tracker.reset()
        self.linescan.reset()

    def finish(self, ts: float) -> list[CountEvent]:
        """Video sonu (§4.9): şerit taramada çizgiye yarım binmiş son ürünler merkezlerine göre sayılır."""
        p = self.profile
        if p.countMode != "linescan" or self._calib is not None or not self.counting:
            return []
        out = [CountEvent(e.seg_id, e.delta, True, 0.0, None) for e in self.linescan.flush(p)]
        self.total += sum(e.delta for e in out)
        return out

    # ---- fps ----
    def _update_fps(self, ts: float) -> float:
        self._ts.append(ts)
        while len(self._ts) > 2 and ts - self._ts[0] > 2.0:
            self._ts.popleft()
        if len(self._ts) >= 3 and self._ts[-1] > self._ts[0]:
            return (len(self._ts) - 1) / (self._ts[-1] - self._ts[0])
        return self.profile.referenceFps

    def belt_speed_mm_s(self, fps: float, full_size: tuple[int, int]) -> float | None:
        """§9: sayılmış izlerin eksen hızlarının medyanı → mm/sn."""
        p = self.profile
        if not p.mmPerPixel:
            return None
        # §4.8: açılı çizgide izler çizgi çerçevesinde (u akış ekseni, birim kare yüksekliği)
        speeds = self.tracker.axis_speeds(True if p.countLine else p.vertical)
        if not speeds:
            return None
        span = full_size[1] if p.vertical else full_size[0]
        if p.countLine:
            span = full_size[1]
        return median(speeds) * span * p.mmPerPixel * fps

    # ---- ana döngü ----
    def process(self, frame: np.ndarray, ts: float) -> FrameResult:
        p = self.profile
        if p.rotation in _ROT:
            frame = cv2.rotate(frame, _ROT[p.rotation])
        full = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        small, self.factor = downsample(full, p.processingWidth)
        fps = self._update_fps(ts)
        k = p.referenceFps / max(1.0, fps)
        max_dist = min(0.5, p.maxMatchDistance * k)
        rate = 1 - (1 - p.backgroundRate) ** k
        max_missed = max(2, round(6 / k))
        calib_events: list[tuple[str, Any]] = []
        full_size = (full.shape[1], full.shape[0])

        if p.countMode == "linescan":
            return self._process_linescan(small, ts, fps, full_size, calib_events)

        # §5 boş bant öğrenme
        if self._calib == "background":
            n_total = max(15, round(fps * 1.0))
            n = self._calib_n
            self.segmenter.learn(small, 1.0 if n == 0 else 0.15)
            if n >= int(0.4 * n_total):
                self._calib_max = max(self._calib_max, self.segmenter.diff_percentile(small, p.roi, 0.995, p.roiPolygon))
            self._calib_n = n + 1
            if self._calib_n >= n_total:
                th = int(min(100, max(12, int(self._calib_max * 1.5) + 8)))
                self._calib = None
                self.tracker.reset()
                if not self._calib_update:
                    calib_events.append(("background_done", p.diffThreshold))
                elif th >= 100:
                    # Gürültü üst sınıra dayandı: öğrenirken bantta ürün/hareket vardı; eşiği bozma
                    calib_events.append(("background_rejected", th))
                else:
                    p.diffThreshold = th
                    calib_events.append(("background_done", th))
            else:
                calib_events.append(("background_progress", self._calib_n / n_total))
            return FrameResult(ts, [], [], [], [], calib_events, None, fps, self.total, full_size, small)

        sampling = self._calib == "sample"
        expected = 0.0 if sampling else p.expectedArea
        frame_lf = LineFrame.build(*p.countLine, small.shape[1], small.shape[0]) if p.countLine else None
        raw = self.segmenter.segment(small, p.roi, p.diffThreshold, p.closeIterations, rate, p.roiPolygon, frame_lf)
        min_area = expected * p.minAreaFactor if expected > 0 else p.minAreaAbs
        blobs = [b for b in raw if b.area >= min_area]
        if p.splitTouching and expected > 0:
            for b in blobs:
                r = b.area / expected
                b.multiplicity = 1 if r < 1.5 else min(p.maxMultiplicity, max(1, round(r)))

        if frame_lf is not None:
            # §4.8: lekeler çizgi çerçevesine; izleyici "aşağı akış, çizgi 0" ile aynen çalışır
            events = self.tracker.update([frame_lf.blob(b) for b in blobs], True, 1.0, 0.0, max_dist,
                                         p.minHits, max_missed, frame_lf.bounds)
        else:
            events = self.tracker.update(blobs, p.vertical, p.sign, p.linePosition, max_dist, p.minHits, max_missed)
        self._frame = frame_lf

        counts: list[CountEvent] = []
        inspections: list[InspectionResult] = []
        if sampling:
            for e in events:
                if e.is_first_crossing and e.median_area > 0:
                    self._calib_areas.append(e.median_area)
            if events:
                if len(self._calib_areas) >= self._calib_target:
                    p.expectedArea = median(self._calib_areas)
                    self._calib = None
                    calib_events.append(("sample_done", p.expectedArea))
                else:
                    calib_events.append(("sample_progress", (len(self._calib_areas), self._calib_target)))
        elif self.counting and events:
            for e in events:
                self.total += e.delta
                counts.append(e)
                if (p.qc.enabled and e.is_first_crossing and e.delta == 1 and p.expectedArea > 0
                        and e.blob_index is not None and self.segmenter.labels is not None):
                    inspections.append(inspect(full, self.segmenter.labels, blobs[e.blob_index],
                                               e.track_id, p, self.factor))

        # §8 çalışıyor/durdu
        if blobs or events:
            self._last_activity = ts
        now_running = self._last_activity is not None and ts - self._last_activity <= self.idle_seconds
        change = None
        if now_running != self.running:
            self.running = now_running
            change = now_running

        markers = self.tracker.markers
        if frame_lf is not None:                      # iz işaretleri görüntü koordinatına (ekran/çizim)
            markers = [TrackMarker(m.id, *frame_lf.to_image(m.x, m.y), m.counted) for m in markers]
        return FrameResult(ts, blobs, markers, counts, inspections, calib_events, change,
                           fps, self.total, full_size, small)

    def _process_linescan(self, small: np.ndarray, ts: float, fps: float, full_size: tuple[int, int],
                          calib_events: list[tuple[str, Any]]) -> FrameResult:
        """§4.9 Şerit tarama: arka plan ve leke yok. Boş bant öğrenme gerekmez (hemen biter, eşik değişmez);
        örnek öğrenme ürün boyunu öğrenir (`productLength`)."""
        p = self.profile
        if self._calib == "background":
            self._calib = None
            calib_events.append(("background_done", p.diffThreshold))
        sampling = self._calib == "sample"
        if sampling:
            saved, p.productLength = p.productLength, 0.0
            events = self.linescan.process(small, p)
            p.productLength = saved
            if self.linescan.product_length > 0:
                p.productLength = self.linescan.product_length
                self._calib = None
                calib_events.append(("sample_done", p.productLength))
            events = []
        else:
            events = self.linescan.process(small, p)
        counts: list[CountEvent] = []
        if self.counting and not sampling:
            for e in events:
                self.total += e.delta
                counts.append(CountEvent(e.seg_id, e.delta, True, 0.0, None))
        if counts or self.linescan.moving:
            self._last_activity = ts
        now_running = self._last_activity is not None and ts - self._last_activity <= self.idle_seconds
        change = None
        if now_running != self.running:
            self.running = now_running
            change = now_running
        markers = [TrackMarker(m.id, m.x, m.y, m.counted) for m in self.linescan.markers(small.shape, p)]
        return FrameResult(ts, [], markers, counts, [], calib_events, change, fps, self.total, full_size, small)
