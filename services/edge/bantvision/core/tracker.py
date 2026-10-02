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
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)   # son eşleşen lekenin kutusu
    last_mult: int = 1                                               # o lekenin bu ize düşen çarpanı


# §4.0: izin tahmini konumu lekenin kutusunun bu oranı kadar dışına taşsa da "içinde" sayılır
MERGE_MARGIN = 0.05


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
               max_distance: float, min_hits: int, max_missed: int = 6,
               bounds: tuple[float, float, float, float] = (-0.1, 1.1, -0.1, 1.1)) -> list[CountEvent]:
        """`bounds`: silme sınırı (x0, x1, y0, y1); açılı çizgide çizgi çerçevesinin sınırları (§4.8)."""
        def axis(x: float, y: float) -> float:
            return y if vertical else x

        events: list[CountEvent] = []

        def observe(t: _Track, mult: int, area: float, bi: int) -> None:
            t.bbox, t.last_mult = blobs[bi].bbox, mult
            t.hits += 1
            t.missed = 0
            t.mult = (t.mult + [mult])[-5:]
            t.areas = (t.areas + [area])[-9:]
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

        used_t: set[int] = set()
        used_b: set[int] = set()

        # §4.0 Birleşik gruplar: tahmini konumu aynı lekenin kutusuna düşen ≥2 iz, birbirine değen ayrı
        # ürünlerdir. Lekenin ortasına zıplamazlar (yoksa ayrıldıklarında "geri gitme" kuralı yüzünden
        # kendi ürünlerini bulamaz, yeni iz doğar ve çift sayılır); kendi hızlarıyla ilerler, çarpanı paylaşırlar.
        preds = [(t.x + t.vx, t.y + t.vy) for t in self.tracks]
        owner: dict[int, tuple[float, int]] = {}
        for bi, b in enumerate(blobs):
            bx, by, bw, bh = b.bbox
            mx, my = MERGE_MARGIN * bw, MERGE_MARGIN * bh
            inside = [ti for ti, (px, py) in enumerate(preds)
                      if bx - mx <= px <= bx + bw + mx and by - my <= py <= by + bh + my]
            if len(inside) < 2:
                continue
            for ti in inside:   # iki lekenin kutusuna birden düşen iz, merkezi en yakın olana
                d = math.hypot(b.cx - preds[ti][0], b.cy - preds[ti][1])
                if ti not in owner or d < owner[ti][0]:
                    owner[ti] = (d, bi)
        groups: dict[int, list[int]] = {}
        for ti, (_, bi) in owner.items():
            groups.setdefault(bi, []).append(ti)
        for bi, members in groups.items():
            if len(members) < 2:
                continue
            b = blobs[bi]
            members.sort(key=lambda ti: -sign * axis(*preds[ti]))     # akışta öndeki önce
            n = len(members)
            total = max(b.multiplicity, n)
            # Grubu lekeye demirle: üyelerin ortalaması leke merkezine kaydırılır, kayma hıza da yansır.
            # Demirlenmeyen üyeler şişmiş hızla lekeden kopup öne kaçar, arkada sahipsiz leke yeni iz doğurur.
            dx = b.cx - sum(preds[ti][0] for ti in members) / n
            dy = b.cy - sum(preds[ti][1] for ti in members) / n
            for k, ti in enumerate(members):
                t = self.tracks[ti]
                nx, ny = preds[ti][0] + dx, preds[ti][1] + dy
                t.vx = 0.6 * t.vx + 0.4 * (nx - t.x)
                t.vy = 0.6 * t.vy + 0.4 * (ny - t.y)
                t.x, t.y = nx, ny
                observe(t, total // n + (1 if k < total % n else 0), b.area / n, bi)
                used_t.add(ti)
            used_b.add(bi)

        prev = {ti: (t.bbox, t.last_mult) for ti, t in enumerate(self.tracks)}
        greedy: set[int] = set()
        pairs: list[tuple[float, int, int]] = []
        for ti, t in enumerate(self.tracks):
            if ti in used_t:
                continue
            px, py = preds[ti]
            for bi, b in enumerate(blobs):
                if bi in used_b or sign * (axis(b.cx, b.cy) - axis(t.x, t.y)) < -0.03:
                    continue
                d = math.hypot(b.cx - px, b.cy - py)
                if d <= max_distance:
                    pairs.append((d, ti, bi))
        pairs.sort(key=lambda p: p[0])

        for _, ti, bi in pairs:
            if ti in used_t or bi in used_b:
                continue
            used_t.add(ti)
            used_b.add(bi)
            greedy.add(ti)
            b, t = blobs[bi], self.tracks[ti]
            t.vx = 0.6 * t.vx + 0.4 * (b.cx - t.x)
            t.vy = 0.6 * t.vy + 0.4 * (b.cy - t.y)
            t.x, t.y = b.cx, b.cy
            observe(t, b.multiplicity, b.area, bi)

        # §4.5b Bölünme: ×2 (ya da fazlası) lekeyi tek başına izleyen iz bu karede bölündüyse, artakalan parça
        # yeni ürün değil o izin çocuğudur. Çocuk çizgiye göre doğum tarafını ve sayılmışlığı ebeveynden devralır;
        # ebeveyn önceden 2 saydıysa çocuk 1'ini üstlenir (yeni olay yok). Aksi halde çizgiden sonra bölünen
        # çiftin ikinci ürünü "çizgiden sonra doğdu" diye hiç sayılmaz, ebeveyn de ortalama çarpanla 1 sayar.
        children: list[_Track] = []
        for bi, b in enumerate(blobs):
            if bi in used_b:
                continue
            best: tuple[float, int] | None = None
            for ti in greedy:
                (px, py, pw, ph), pm = prev[ti]
                t = self.tracks[ti]
                if pm < 2 or pw <= 0:
                    continue
                ox, oy = px + t.vx - MERGE_MARGIN * pw, py + t.vy - MERGE_MARGIN * ph
                if ox <= b.cx <= ox + pw * (1 + 2 * MERGE_MARGIN) and oy <= b.cy <= oy + ph * (1 + 2 * MERGE_MARGIN):
                    d = math.hypot(b.cx - t.x, b.cy - t.y)
                    if best is None or d < best[0]:
                        best = (d, ti)
            if best is None:
                continue
            parent = self.tracks[best[1]]
            keep = min(parent.counted_so_far, parent.last_mult)
            child = _Track(id=self.next_id, x=b.cx, y=b.cy, vx=parent.vx, vy=parent.vy, hits=parent.hits,
                           started_before=parent.started_before,
                           counted_so_far=min(parent.counted_so_far - keep, b.multiplicity),
                           mult=[b.multiplicity], areas=[b.area], bbox=b.bbox, last_mult=b.multiplicity)
            self.next_id += 1
            parent.counted_so_far = keep
            parent.mult = [parent.last_mult]
            prev[best[1]] = (parent.bbox, parent.last_mult)   # aynı ebeveyn ikinci kez bölünemez
            children.append(child)
            used_b.add(bi)

        for i, t in enumerate(self.tracks):
            if i not in used_t:
                t.missed += 1
                t.x += t.vx
                t.y += t.vy
        self.tracks = [t for t in self.tracks
                       if t.missed <= max_missed and bounds[0] <= t.x <= bounds[1] and bounds[2] <= t.y <= bounds[3]]

        # §4.6 Yeni iz hızı: banttaki her ürün aynı hızla gider; oturmuş izlerin (hits ≥ 3) medyan hızıyla başla.
        # Sıfır hızla doğan iz bir sonraki karede geride tahmin edilir, birleşik gruba giremez ve çift sayıma yol açar.
        settled = [t for t in self.tracks if t.hits >= 3 and t.missed == 0]
        vx0 = median([t.vx for t in settled]) if settled else 0.0
        vy0 = median([t.vy for t in settled]) if settled else 0.0
        for bi, b in enumerate(blobs):
            if bi in used_b:
                continue
            self.tracks.append(_Track(id=self.next_id, x=b.cx, y=b.cy, vx=vx0, vy=vy0,
                                      started_before=sign * (axis(b.cx, b.cy) - line) < 0,
                                      mult=[b.multiplicity], areas=[b.area],
                                      bbox=b.bbox, last_mult=b.multiplicity))
            self.next_id += 1
        self.tracks.extend(children)
        return events
