"""Yangın/duman karar sabitleri ve saf yardımcılar (tasarım docs/superpowers/specs/2026-11-08-yangin-duman-design.md §3.3).

Değerler başlangıç değerleridir; model eğitimi sonrası ölçümle kalibre edilir (§5). Kare başına akış (core/fire.py):
eşik (dedektörde) → en küçük kutu → hariç bölge (kutu merkezi) → hareket denetimi (`MotionHistory`, `changed_ratio`)
→ 8×6 hücre oyu (`CellVotes`). Kare geneli `GLOBAL_CHANGE_MAX`'tan fazla değiştiyse (ışık patlaması, IR geçişi) kare
oy dışıdır: pencerede ne olumlu ne olumsuz sayılır.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any

import cv2
import numpy as np

Box = tuple[float, float, float, float]

THRESHOLDS: dict[str, dict[str, float]] = {"low": {"fire": .60, "smoke": .65}, "normal": {"fire": .45, "smoke": .50},
                                           "high": {"fire": .35, "smoke": .40}}
MIN_SIDE = 0.015            # kutunun kısa kenarı / kare yüksekliği
MOTION_W = 160              # hareket geçmişindeki gri karenin genişliği (px)
MOTION_LAG_S = 1.0          # hareket kıyası bu kadar önceki (ya da daha eski en yakın) kareyle
MOTION_PIX = 8              # gri fark eşiği (bundan büyük fark "değişti")
MOTION_MIN = 0.02           # kutu içinde değişen piksel oranı bundan küçükse kutu durağandır, oy vermez
GLOBAL_CHANGE_MAX = 0.40    # kare genelinde değişen oran bundan büyükse kare oy dışı
GRID = (8, 6)               # (sütun, satır)
RATIO = 0.6                 # hücre: penceredeki oy veren karelerin en az bu oranında olumlu
MIN_HITS = 3                # ... ve en az bu kadar olumlu kare
END_S = 10.0                # son olumlu kareden bu kadar sonra bölüm biter
MAX_FPS = 5.0               # canlı oturumda en çok bu hızda analiz (oturum uygular, analizör değil)

KINDS = ("fire", "smoke")
TRACK_IDS = {"fire": 0, "smoke": 1}     # alarm sink'in (oturum, iz, tür) anahtarı için sabit iz
EPS = 1e-9


def class_conf(cfg: Any) -> dict[str, float]:
    """Açık kuralların sınıf eşikleri (`cfg`: FireConfig); bozuk hassasiyet "normal" sayılır."""
    th = THRESHOLDS.get(cfg.sensitivity, THRESHOLDS["normal"])
    return {k: th[k] for k in KINDS if getattr(cfg, k).enabled}


def big_enough(box: Box, frame_h: int) -> bool:
    """Piksel kutunun kısa kenarı kare yüksekliğinin `MIN_SIDE` katından küçük değil."""
    return min(box[2] - box[0], box[3] - box[1]) >= MIN_SIDE * frame_h


def in_ignore_zone(box: Box, zones: list[list[tuple[float, float]]], w: int, h: int) -> bool:
    """Piksel kutunun merkezi normalize hariç çokgenlerden birinin içinde (kenar dahil)."""
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    for z in zones:
        poly = np.array([(x * w, y * h) for x, y in z], np.float32).reshape(-1, 1, 2)
        if cv2.pointPolygonTest(poly, (float(cx), float(cy)), False) >= 0:
            return True
    return False


def small_gray(bgr: np.ndarray) -> np.ndarray:
    """Hareket geçmişi için `MOTION_W` genişliğe küçültülmüş gri kare."""
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    h, w = g.shape[:2]
    sh = max(1, round(h * MOTION_W / w))
    return cv2.resize(g, (MOTION_W, sh), interpolation=cv2.INTER_AREA)


def changed_ratio(cur: np.ndarray, ref: np.ndarray, box: Box | None = None) -> float:
    """`MOTION_PIX`'ten fazla değişen piksel oranı; `box` (normalize) verilirse yalnız kutu içinde (en az 1 px)."""
    if box is not None:
        h, w = cur.shape[:2]
        x1 = min(w - 1, max(0, math.floor(box[0] * w)))
        y1 = min(h - 1, max(0, math.floor(box[1] * h)))
        x2 = max(x1 + 1, min(w, math.ceil(box[2] * w)))
        y2 = max(y1 + 1, min(h, math.ceil(box[3] * h)))
        cur, ref = cur[y1:y2, x1:x2], ref[y1:y2, x1:x2]
    return float(np.count_nonzero(cv2.absdiff(cur, ref) > MOTION_PIX)) / max(1, cur.size)


class MotionHistory:
    """Küçük gri karelerin geçmişi. `push` kıyas karesini döndürür: `MOTION_LAG_S` önceki ya da ondan eski en yakın
    kare; geçmişte o kadar eski kare yoksa en eski kare; geçmiş boşsa (ilk kare) None. Zaman geri giderse ya da kare
    boyutu değişirse geçmiş atılır (None)."""

    def __init__(self) -> None:
        self._h: deque[tuple[float, np.ndarray]] = deque()

    def clear(self) -> None:
        self._h.clear()

    def push(self, ts: float, small: np.ndarray) -> np.ndarray | None:
        if self._h and (ts < self._h[-1][0] or self._h[-1][1].shape != small.shape):
            self._h.clear()
        cut = ts - MOTION_LAG_S + EPS
        while len(self._h) >= 2 and self._h[1][0] <= cut:     # baştaki: cut'tan eski en yakın kare kalır
            self._h.popleft()
        ref = self._h[0][1] if self._h else None
        self._h.append((ts, small))
        return ref


def box_cells(box: Box) -> np.ndarray:
    """Normalize kutunun kapladığı hücreler: (satır, sütun) bool ızgara; sıfır alanlı kutu da bir hücre işaretler."""
    cols, rows = GRID
    g = np.zeros((rows, cols), bool)
    c1 = min(cols - 1, max(0, math.floor(box[0] * cols)))
    r1 = min(rows - 1, max(0, math.floor(box[1] * rows)))
    c2 = min(cols - 1, max(c1, math.ceil(box[2] * cols - EPS) - 1))
    r2 = min(rows - 1, max(r1, math.ceil(box[3] * rows - EPS) - 1))
    g[r1:r2 + 1, c1:c2 + 1] = True
    return g


_K3 = np.ones((3, 3), np.uint8)


def neighbourhood(cells: np.ndarray) -> np.ndarray:
    """Hücre ya da 8-komşusu işaretli olan hücreler."""
    return cv2.dilate(cells.astype(np.uint8), _K3).astype(bool)


class CellVotes:
    """Bir sınıfın oy veren kareleri (oy dışı kareler hiç eklenmez). Her kare: zaman, komşulukla genişletilmiş ızgara,
    yalın (kutuların kendi kapladığı) ızgara ve geçerli kutular (her biri kendi komşuluk ızgarasıyla). Pencere
    `[now − seconds, now]` (kapalı: 1 kare/sn akışta 2 sn kural 3 kare görür)."""

    def __init__(self) -> None:
        self._v: deque[tuple[float, np.ndarray, np.ndarray, list[tuple[Box, np.ndarray]]]] = deque()

    def clear(self) -> None:
        self._v.clear()

    def add(self, ts: float, boxes: list[Box]) -> None:
        cols, rows = GRID
        raw = np.zeros((rows, cols), bool)
        grid = np.zeros((rows, cols), bool)
        marks: list[tuple[Box, np.ndarray]] = []
        for b in boxes:
            cells = box_cells(b)
            n = neighbourhood(cells)
            raw |= cells
            grid |= n
            marks.append((b, n))
        self._v.append((ts, grid, raw, marks))

    def prune(self, now: float, seconds: float) -> None:
        """Pencere dışı (`now − seconds`'tan eski) kareleri atar."""
        cut = now - seconds - EPS
        while self._v and self._v[0][0] < cut:
            self._v.popleft()

    def trigger(self, now: float, seconds: float) -> tuple[int, int] | None:
        """Penceredeki karelerin en az `RATIO` oranında ve en az `MIN_HITS` karede olumlu hücre (satır, sütun); birden
        çoksa en çok olumlu olan, eşitlikte kutuların kendisinin en çok kapladığı (alevin üstündeki hücre, komşu kenar
        hücresi değil). Pencere dışı eski kareler atılır."""
        self.prune(now, seconds)
        if not self._v:
            return None
        count = np.sum([g for _t, g, _r, _m in self._v], axis=0)
        ok = (count >= MIN_HITS) & (count >= RATIO * len(self._v) - EPS)
        if not ok.any():
            return None
        raw = np.sum([r for _t, _g, r, _m in self._v], axis=0)
        score = np.where(ok, count * (len(self._v) + 1) + raw, -1)
        r, c = np.unravel_index(int(np.argmax(score)), count.shape)
        return int(r), int(c)

    def box_at(self, cell: tuple[int, int]) -> Box | None:
        """Hücreye (komşuluk dahil) değen en son karedeki kutuların birleşimi."""
        for _t, _g, _r, marks in reversed(self._v):
            hit = [b for b, n in marks if n[cell]]
            if hit:
                return (min(b[0] for b in hit), min(b[1] for b in hit), max(b[2] for b in hit), max(b[3] for b in hit))
        return None
