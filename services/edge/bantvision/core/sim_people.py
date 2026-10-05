"""Kişi geçişi sentetik senaryoları (§4.10 testleri): yan yana gruplar + gerçekçi tanıma kusurları.

Mağazada en sık hata kaynağı yan yana geçen 2–3 kişidir. Üretilen her kare, tanıyıcının vereceği gibi
(normalize kutu, güven) listesidir; doğru giriş/çıkış sayısı bilinir. Kusurlar (hepsi tohumla belirlenir):

- kaçırma: kişi o karede bulunamaz;
- örtüşme: öndeki kişiyle büyük ölçüde üst üste binen arkadaki kişi çoğunlukla görünmez;
- titreme ve düşük güven (eşik altı tespit yalnızca mevcut izi sürdürebilir);
- yarım kutu: aynı kişiye ikinci, küçük (üst gövde) kutu;
- birleşme: bitişik iki kişi tek kutu olarak gelir.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

Box = tuple[float, float, float, float]
Frame = list[tuple[Box, float]]

LINE = 0.55        # yatay sayım çizgisi (y); aşağı yürüyen = giriş


@dataclass
class Faults:
    miss: float = 0.15
    occlusion: float = 0.7
    part: float = 0.06
    merge: float = 0.05
    jitter: float = 0.004


def side(x: float, y: float) -> float:
    return y - LINE


def scenario(seed: int, faults: Faults | None = None) -> tuple[list[Frame], int, int]:
    """(kareler, doğru giriş, doğru çıkış). 3–6 grup; grup 1–3 kişi, yan yana (kutular bitişik ya da üst üste)."""
    frames, _, down, up = scenario_motion(seed, faults, blind=0.0)
    return frames, down, up


def scenario_motion(seed: int, faults: Faults | None = None, blind: float = 0.12, noise: float = 0.02
                    ) -> tuple[list[Frame], list[list[Box]], int, int]:
    """Tepeden kamera: çizginin ±`blind` çevresinde tanıyıcı kişiyi bulamaz (kameranın tam altı); hareket lekeleri
    gerçek kişi kutularıdır, üst üste binenler tek lekede birleşir; `noise` olasılıkla rastgele sahte leke (gölge).
    (kareler, lekeler, doğru giriş, doğru çıkış)."""
    f = faults or Faults()
    rnd = random.Random(seed)
    people: list[tuple[int, float, float, float, float, float, float]] = []
    t0 = down = up = 0
    for _ in range(rnd.randint(3, 6)):
        k = rnd.choice([1, 2, 2, 3, 3])
        d = rnd.choice([1, 1, -1])
        vy = d * rnd.uniform(0.010, 0.022)
        w = rnd.uniform(0.07, 0.10)
        h = w * rnd.uniform(1.6, 2.2)
        gap = rnd.uniform(-0.01, 0.015)                     # negatif: kutular üst üste biner
        x0 = rnd.uniform(0.15, 0.85 - k * (w + gap))
        for i in range(k):
            people.append((t0 + rnd.randint(0, 3), x0 + i * (w + gap) + w / 2,
                           (0.1 if d > 0 else 1.0) + rnd.uniform(-0.03, 0.03), vy, w, h,
                           rnd.uniform(-0.002, 0.002)))
        if d > 0:
            down += k
        else:
            up += k
        t0 += rnd.randint(25, 70)

    frames: list[Frame] = []
    blobs: list[list[Box]] = []
    mrnd = random.Random(seed * 7919 + 1)          # hareket gürültüsü ayrı üreteçten: tanıma kareleri değişmesin
    for fi in range(t0 + 120):
        vis = []
        for s, x, y0, vy, w, h, vx in people:
            if fi < s:
                continue
            y = y0 + vy * (fi - s)
            if -0.05 < y < 1.1:
                vis.append((x + vx * (fi - s), y, w, h))
        vis.sort()
        dets: Frame = []
        merged: set[int] = set()
        for i, (x, y, w, h) in enumerate(vis):
            if i in merged:
                continue
            if (i + 1 < len(vis) and rnd.random() < f.merge and abs(vis[i + 1][1] - y) < 0.06
                    and vis[i + 1][0] - x < w * 1.2):
                x2, y2, w2, h2 = vis[i + 1]
                merged.add(i + 1)
                dets.append(((min(x - w / 2, x2 - w2 / 2), min(y - h / 2, y2 - h2 / 2),
                              max(x + w / 2, x2 + w2 / 2), max(y + h / 2, y2 + h2 / 2)), rnd.uniform(0.4, 0.7)))
                continue
            if rnd.random() < f.miss:
                continue
            behind = any(k != i and vis[k][1] > y and abs(vis[k][0] - x) < 0.5 * w and abs(vis[k][1] - y) < 0.5 * h
                         for k in range(len(vis)))
            if behind and rnd.random() < f.occlusion:
                continue
            j = [rnd.gauss(0, f.jitter) for _ in range(4)]
            b = (x - w / 2 + j[0], y - h / 2 + j[1], x + w / 2 + j[2], y + h / 2 + j[3])
            dets.append((b, rnd.uniform(0.25, 0.95)))
            if rnd.random() < f.part:
                dets.append(((b[0] + 0.1 * w, b[1], b[2] - 0.1 * w, b[1] + 0.55 * h), rnd.uniform(0.3, 0.7)))
        rnd.shuffle(dets)
        if blind > 0:
            dets = [(b, sc) for b, sc in dets if abs((b[1] + b[3]) / 2 - LINE) >= blind]
        frames.append(dets)
        blobs.append(_motion_blobs([(x - w / 2, y - h / 2, x + w / 2, y + h / 2) for x, y, w, h in vis], mrnd, noise))
    return frames, blobs, down, up


def _motion_blobs(boxes: list[Box], rnd: random.Random, noise: float) -> list[Box]:
    """Kesişen kişi kutuları tek leke (birleşik grup); kare dışına taşan kırpılır."""
    groups: list[list[float]] = []
    for b in boxes:
        cur = [max(0.0, b[0]), max(0.0, b[1]), min(1.0, b[2]), min(1.0, b[3])]
        if cur[2] <= cur[0] or cur[3] <= cur[1]:
            continue
        merged = True
        while merged:
            merged = False
            for g in groups:
                if g[0] < cur[2] and cur[0] < g[2] and g[1] < cur[3] and cur[1] < g[3]:
                    cur = [min(g[0], cur[0]), min(g[1], cur[1]), max(g[2], cur[2]), max(g[3], cur[3])]
                    groups.remove(g)
                    merged = True
                    break
        groups.append(cur)
    out = [(g[0], g[1], g[2], g[3]) for g in groups]
    if rnd.random() < noise:
        x, y = rnd.uniform(0.1, 0.9), rnd.uniform(0.1, 0.9)
        out.append((x - 0.03, y - 0.03, x + 0.03, y + 0.03))
    return out
