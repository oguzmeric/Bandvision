"""Poz güvenlik kuralları: "eller yukarı" ve yerde yatan kişi (tasarım docs/superpowers/specs/2026-10-06-poz-guvenlik-design.md).

Eklemler COCO-17, piksel (x, y aşağı), güven. Kare kararları True / False / None (yetersiz eklem: karar yok).
`EpisodeTracker` iz ve tür başına bölüm tutar: True kareler sürdürür, `GRACE_S`'ten uzun kopma ya da iz kaybı bitirir,
süre eşiği aşılınca bölüm başına bir kez alarm. Alarm vermiş bölüm daha uzun (`FIRED_GRACE_S`) affedilir: tek olay
kısa bir kopmayla ikinci alarm kaydı üretmesin.

Eller yukarı eşikleri (`WRIST_UP`, `ELBOW_DOWN`) ofis NVR kamerasının gerçek kareleriyle ölçüldü (2026-10-07): yüksekten
eğik bakan kamerada teslim duruşunda bilek omzun ancak 0,19–0,37·s üstünde, dirsek omzun 0,14·s altına kadar görünüyor.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

KP_CONF = 0.3
GRACE_S = 0.5
FIRED_GRACE_S = 3.0                 # alarm vermiş bölümün kopma toleransı (iz kaybı dahil)
COOLDOWN_S = 60.0
WRIST_UP = 0.20                     # eller yukarı: bilek, aynı taraftaki omzun en az bu kadar (× s) üstünde
ELBOW_DOWN = 0.30                   # eller yukarı: dirsek görünürse omzun en çok bu kadar (× s) altında

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
    """Her iki tarafta: bilek.y ≤ omuz.y − WRIST_UP·s ve (dirsek görünürse) dirsek.y ≤ omuz.y + ELBOW_DOWN·s. İki omuz,
    iki bilek ve ölçek gerekli; yoksa None. Eller göğüs hizasında ya da aşağıda: False."""
    s = scale(kp)
    if s is None or not (_vis(kp, L_WR) and _vis(kp, R_WR)):
        return None
    for sh, el, wr in ((L_SH, L_EL, L_WR), (R_SH, R_EL, R_WR)):
        if not (kp[wr, 1] <= kp[sh, 1] - WRIST_UP * s):
            return False
        if _vis(kp, el) and not (kp[el, 1] <= kp[sh, 1] + ELBOW_DOWN * s):
            return False
    return True


def lying(kp: np.ndarray) -> bool | None:
    """Yerde yatan kişi (horizontal orientation or head at/below hips).
    θ is signed 0–180° (shoulders below hips in image = lying toward camera counts as lying).
    """
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


def _grace(ep: _Episode, grace_s: float) -> float:
    """Alarm vermiş bölüm en az FIRED_GRACE_S affedilir (uyarlanmış tolerans daha büyükse o)."""
    return max(grace_s, FIRED_GRACE_S) if ep.fired else grace_s


class EpisodeTracker:
    def __init__(self) -> None:
        self._eps: dict[tuple[int, str], _Episode] = {}
        self._pending_end: list[tuple[tuple[int, str], bool]] = []

    def update(
        self, key: tuple[int, str], verdict: bool | None, ts: float, threshold_s: float, grace_s: float = GRACE_S
    ) -> bool:
        """Bu karenin kararı; True dönerse bu karede alarm doğdu (bölüm başına bir kez).
        Stale episodes (non-monotonic ts, or gap > grace — FIRED_GRACE_S at least once fired) report end via
        _pending_end and restart. sweep() returns pending ends and removes ended episodes."""
        if verdict is not True:
            return False                                   # kopma: sweep toleransa göre bitirir
        ep = self._eps.get(key)
        gap = ts - ep.last_true if ep is not None else float('inf')
        # Stale episode (non-monotonic ts or gap > grace + epsilon): restart and report end
        if ep is not None and (ts < ep.last_true or gap > _grace(ep, grace_s) + 1e-9):
            self._pending_end.append((key, ep.fired))
            self._eps[key] = _Episode(ts, ts)
            return False
        if ep is None:
            self._eps[key] = _Episode(ts, ts)
            return False
        ep.last_true = ts
        if not ep.fired and ts - ep.start >= threshold_s:
            ep.fired = True
            return True
        return False

    def sweep(self, ts: float, alive: set[int], grace_s: float = GRACE_S) -> list[tuple[tuple[int, str], bool]]:
        """Biten bölümler: (anahtar, alarm vermiş mi). Son True'dan beri > tolerans (alarm vermişte en az FIRED_GRACE_S)
        ya da iz yok — iz kaybı alarmsız bölümü hemen, alarm vermiş bölümü tolerans dolunca bitirir.
        Returns pending ends (from update's stale restarts) plus newly dead episodes. Only deletes actually dead keys."""
        ended = self._pending_end.copy()
        self._pending_end.clear()
        dead = [
            (k, e.fired)
            for k, e in self._eps.items()
            if (k[0] not in alive and not e.fired) or ts - e.last_true > _grace(e, grace_s) + 1e-9 or ts < e.last_true
        ]
        ended.extend(dead)
        for k, _ in dead:
            self._eps.pop(k, None)
        return ended

    def close_all(self) -> list[tuple[tuple[int, str], bool]]:
        """Hepsini bitirir (sıfırlama/kapanış): ertelenmiş sonlar ve tüm bölümler (anahtar, alarm vermiş mi)."""
        ended = self._pending_end + [(k, e.fired) for k, e in self._eps.items()]
        self._pending_end, self._eps = [], {}
        return ended

    def active(self) -> list[tuple[int, str, float, bool]]:
        return [(k[0], k[1], e.last_true - e.start, e.fired) for k, e in self._eps.items()]
