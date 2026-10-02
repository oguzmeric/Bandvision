"""Uçtan uca çekirdek: ön işleme → segmentasyon → izleme → sayım → QC.
Kaynaktan bağımsızdır: process(frame, ts) alır. docs/03-algorithm.md"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

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
        self.counting = True
        self.total = 0
        self._calib: str | None = None          # "background" | "sample"
        self._calib_n = 0
        self._calib_max = 0
        self._calib_areas: list[float] = []
        self._calib_target = 8
        self._ts: deque[float] = deque()
        self._last_activity: float | None = None
        self.running = False
        self.factor = 1

    # ---- kontrol ----
    def set_profile(self, profile: Profile, reset_background: bool = False) -> None:
        self.profile = profile
        self.tracker.reset()
        if reset_background:
            self.segmenter.reset()

    def start_background_learning(self) -> None:
        self.tracker.reset()
        self._calib, self._calib_n, self._calib_max = "background", 0, 0

    def start_sample_learning(self, target: int = 8) -> None:
        self.tracker.reset()
        self._calib, self._calib_areas, self._calib_target = "sample", [], target

    def cancel_calibration(self) -> None:
        self._calib = None

    def reset_count(self) -> None:
        self.total = 0
        self.tracker.reset()

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
        speeds = self.tracker.axis_speeds(p.vertical)
        if not speeds:
            return None
        span = full_size[1] if p.vertical else full_size[0]
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
                p.diffThreshold = th
                self._calib = None
                self.tracker.reset()
                calib_events.append(("background_done", th))
            else:
                calib_events.append(("background_progress", self._calib_n / n_total))
            return FrameResult(ts, [], [], [], [], calib_events, None, fps, self.total, full_size, small)

        sampling = self._calib == "sample"
        expected = 0.0 if sampling else p.expectedArea
        raw = self.segmenter.segment(small, p.roi, p.diffThreshold, p.closeIterations, rate, p.roiPolygon)
        min_area = expected * p.minAreaFactor if expected > 0 else p.minAreaAbs
        blobs = [b for b in raw if b.area >= min_area]
        if p.splitTouching and expected > 0:
            for b in blobs:
                r = b.area / expected
                b.multiplicity = 1 if r < 1.5 else min(p.maxMultiplicity, max(1, round(r)))

        events = self.tracker.update(blobs, p.vertical, p.sign, p.linePosition, max_dist, p.minHits, max_missed)

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

        return FrameResult(ts, blobs, self.tracker.markers, counts, inspections, calib_events, change,
                           fps, self.total, full_size, small)
