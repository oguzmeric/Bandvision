"""Poz güvenlik kuralları: "eller yukarı" ve yerde yatan kişi (tasarım docs/superpowers/specs/2026-10-06-poz-guvenlik-design.md).

Eklemler COCO-17, piksel (x, y aşağı), güven. Kare kararları True / False / None (yetersiz eklem: karar yok).
`EpisodeTracker` iz ve tür başına bölüm tutar: True kareler sürdürür, `GRACE_S`'ten uzun kopma ya da iz kaybı bitirir,
süre eşiği aşılınca bölüm başına bir kez alarm.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

KP_CONF = 0.3
GRACE_S = 0.5
COOLDOWN_S = 60.0

NOSE, L_SH, R_SH, L_EL, R_EL, L_WR, R_WR, L_HIP, R_HIP = 0, 5, 6, 7, 8, 9, 10, 11, 12
HEAD_ALT = (1, 2, 3, 4)


def _vis(kp: np.ndarray, i: int) -> bool:
    return bool(kp[i, 2] >= KP_CONF)


def head(kp: np.ndarray) -> np.ndarray | None:
    if _vis(kp, NOSE):
        return kp[NOSE, :2]
    pts = [kp[i, :2] for i in HEAD_ALT if _vis(kp, i)]
    return np.mean(pts, axis=0) if pts else None


def _mid(kp: np.ndarray, a: int, b: int) -> np.ndarray:
    return (kp[a, :2] + kp[b, :2]) / 2


def scale(kp: np.ndarray) -> float | None:
    """Gövde boyu (iki kalça görünürse) ya da 2,5 × baş–omuz ortası uzaklığı; omuzlar görünmezse None."""
    if not (_vis(kp, L_SH) and _vis(kp, R_SH)):
        return None
    sh = _mid(kp, L_SH, R_SH)
    if _vis(kp, L_HIP) and _vis(kp, R_HIP):
        s = float(np.linalg.norm(sh - _mid(kp, L_HIP, R_HIP)))
        return s if s > 0 else None
    h = head(kp)
    if h is None:
        return None
    d = float(np.linalg.norm(h - sh))
    return 2.5 * d if d > 0 else None


def hands_up(kp: np.ndarray) -> bool | None:
    s = scale(kp)
    if s is None or not (_vis(kp, L_WR) and _vis(kp, R_WR)):
        return None
    for sh, el, wr in ((L_SH, L_EL, L_WR), (R_SH, R_EL, R_WR)):
        if kp[wr, 1] > kp[sh, 1] - 0.35 * s:
            return False
        if _vis(kp, el) and kp[el, 1] > kp[sh, 1] + 0.15 * s:
            return False
    return True


def lying(kp: np.ndarray) -> bool | None:
    if not all(_vis(kp, i) for i in (L_SH, R_SH, L_HIP, R_HIP)):
        return None
    sh, hp = _mid(kp, L_SH, R_SH), _mid(kp, L_HIP, R_HIP)
    v = sh - hp
    s = float(np.linalg.norm(v))
    if s == 0:
        return None
    theta = math.degrees(math.atan2(abs(float(v[0])), -float(v[1])))   # 0° dik (omuz kalçanın üstünde), 90° yatay
    if theta >= 60.0:
        return True
    h = head(kp)
    return bool(h is not None and h[1] >= hp[1] - 0.1 * s)


@dataclass
class _Episode:
    start: float
    last_true: float
    fired: bool = False


class EpisodeTracker:
    def __init__(self) -> None:
        self._eps: dict[tuple[int, str], _Episode] = {}

    def update(self, key: tuple[int, str], verdict: bool | None, ts: float, threshold_s: float) -> bool:
        """Bu karenin kararı; True dönerse bu karede alarm doğdu (bölüm başına bir kez)."""
        if verdict is not True:
            return False                                   # kopma: sweep GRACE_S'e göre bitirir
        ep = self._eps.get(key)
        if ep is None or ts - ep.last_true > GRACE_S:
            ep = self._eps[key] = _Episode(ts, ts)
        ep.last_true = ts
        if not ep.fired and ts - ep.start >= threshold_s:
            ep.fired = True
            return True
        return False

    def sweep(self, ts: float, alive: set[int]) -> list[tuple[tuple[int, str], bool]]:
        """Biten bölümler (iz yok ya da son True'dan beri > GRACE_S): (anahtar, alarm vermiş mi)."""
        ended = [(k, e.fired) for k, e in self._eps.items() if k[0] not in alive or ts - e.last_true > GRACE_S]
        for k, _ in ended:
            del self._eps[k]
        return ended

    def active(self) -> list[tuple[int, str, float, bool]]:
        return [(k[0], k[1], e.last_true - e.start, e.fired) for k, e in self._eps.items()]
