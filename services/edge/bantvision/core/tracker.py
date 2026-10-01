"""İzleme ve çizgi geçişinde sayım — docs/03-algorithm.md §4."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .segmenter import Blob


@dataclass
class CountEvent:
    track_id: int
    delta: int
    is_first_crossing: bool
    median_area: float
    blob_index: int | None  # bu karedeki leke indeksi (QC için)


@dataclass
class TrackMarker:
    id: int
    x: float
    y: float
    counted: bool


@dataclass
class _Track:
    id: int
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    hits: int = 1
    missed: int = 0
    started_before: bool = False
    counted_so_far: int = 0
    mult: list[int] = field(default_factory=list)
    areas: list[float] = field(default_factory=list)


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    c = len(s)
    return s[c // 2] if c % 2 else (s[c // 2 - 1] + s[c // 2]) / 2


class BlobTracker:
    def __init__(self) -> None:
        self.tracks: list[_Track] = []
        self.next_id = 1

    def reset(self) -> None:
        self.tracks.clear()

    @property
    def markers(self) -> list[TrackMarker]:
        return [TrackMarker(t.id, t.x, t.y, t.counted_so_far > 0) for t in self.tracks]

    def axis_speeds(self, vertical: bool) -> list[float]:
        return [abs(t.vy if vertical else t.vx) for t in self.tracks if t.counted_so_far > 0 and t.missed == 0]

    def update(self, blobs: list[Blob], vertical: bool, sign: float, line: float,
               max_distance: float, min_hits: int, max_missed: int = 6) -> list[CountEvent]:
        def axis(x: float, y: float) -> float:
            return y if vertical else x

        pairs: list[tuple[float, int, int]] = []
        for ti, t in enumerate(self.tracks):
            px, py = t.x + t.vx, t.y + t.vy
            for bi, b in enumerate(blobs):
                if sign * (axis(b.cx, b.cy) - axis(t.x, t.y)) < -0.03:
                    continue
                d = math.hypot(b.cx - px, b.cy - py)
                if d <= max_distance:
                    pairs.append((d, ti, bi))
        pairs.sort(key=lambda p: p[0])

        used_t: set[int] = set()
        used_b: set[int] = set()
        events: list[CountEvent] = []
        for _, ti, bi in pairs:
            if ti in used_t or bi in used_b:
                continue
            used_t.add(ti)
            used_b.add(bi)
            b, t = blobs[bi], self.tracks[ti]
            t.vx = 0.6 * t.vx + 0.4 * (b.cx - t.x)
            t.vy = 0.6 * t.vy + 0.4 * (b.cy - t.y)
            t.x, t.y = b.cx, b.cy
            t.hits += 1
            t.missed = 0
            t.mult = (t.mult + [b.multiplicity])[-5:]
            t.areas = (t.areas + [b.area])[-9:]
            if t.counted_so_far == 0:
                if t.started_before and t.hits >= min_hits and sign * (axis(t.x, t.y) - line) >= 0:
                    m = max(1, round(sum(t.mult) / len(t.mult)))
                    t.counted_so_far = m
                    events.append(CountEvent(t.id, m, True, median(t.areas), bi))
            else:
                recent = t.mult[-3:]
                if len(recent) == 3 and min(recent) > t.counted_so_far:
                    events.append(CountEvent(t.id, min(recent) - t.counted_so_far, False, 0.0, bi))
                    t.counted_so_far = min(recent)

        for i, t in enumerate(self.tracks):
            if i not in used_t:
                t.missed += 1
                t.x += t.vx
                t.y += t.vy
        self.tracks = [t for t in self.tracks
                       if t.missed <= max_missed and -0.1 <= t.x <= 1.1 and -0.1 <= t.y <= 1.1]

        for bi, b in enumerate(blobs):
            if bi in used_b:
                continue
            self.tracks.append(_Track(id=self.next_id, x=b.cx, y=b.cy,
                                      started_before=sign * (axis(b.cx, b.cy) - line) < 0,
                                      mult=[b.multiplicity], areas=[b.area]))
            self.next_id += 1
        return events
