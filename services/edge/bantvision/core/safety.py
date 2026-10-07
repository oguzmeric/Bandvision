"""Poz güvenlik çözümleyicisi: kişi tanıma + izleyici (detect_count.DetectCounter) + poz (MoveNet) + kurallar.

Yalnızca onaylı ve bu karede tanımayla gözlenen izlerin pozuna bakılır; alan (ROI) varsa konum noktası (alt orta)
alanda olmalı. Kurallar ve süreler pose_rules.py'de; tasarım docs/superpowers/specs/2026-10-06-poz-guvenlik-design.md.
Kopma toleransı kare hızına uyar: yavaş akışta (örn. 1 kare/sn) sabit 0,5 sn tolerans bölümü sürekli koparırdı.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .detect_count import DetectCounter, inside_roi
from .people_track import MotTrack
from .pose_rules import GRACE_S, EpisodeTracker, hands_up, lying
from .profile import Profile


@dataclass
class SafetyAlarm:
    kind: str                                   # "hands_up" | "lying"
    track_id: int
    box: tuple[float, float, float, float]      # normalize
    started: float                              # olayın başladığı zaman (ts − süre)
    ts: float                                   # alarmın doğduğu zaman


@dataclass
class SafetyResult:
    tracks: list[MotTrack] = field(default_factory=list)                    # bu karede gözlenen onaylı izler
    poses: dict[int, np.ndarray] = field(default_factory=dict)              # iz → eklemler (17×3, piksel)
    active: list[tuple[int, str, float, bool]] = field(default_factory=list)    # (iz, tür, süre sn, alarm verdi mi)
    fired: list[SafetyAlarm] = field(default_factory=list)                  # bu karede doğan alarmlar
    ended: list[tuple[int, str, bool]] = field(default_factory=list)        # biten bölümler (iz, tür, alarm verdi mi)


def grace_for(fps: float) -> float:
    """Kopma toleransı (sn): en az `GRACE_S`, ve en az ~2,5 kare aralığı (yavaş akışta tek kare kaçığı bölmesin)."""
    return max(GRACE_S, 2.5 / fps) if fps > 0 else GRACE_S


class SafetyAnalyzer:
    def __init__(self, detector: Any | None = None, pose: Any | None = None) -> None:
        self.dc = DetectCounter(detector=detector, motion=False)
        self._pose = pose
        self.episodes = EpisodeTracker()

    @property
    def pose(self) -> Any:
        if self._pose is None:
            from .pose import PoseEstimator

            self._pose = PoseEstimator()
        return self._pose

    def enable_gate(self) -> None:
        self.dc.enable_gate()

    def reset(self) -> None:
        self.dc.reset()
        self.episodes = EpisodeTracker()

    def process(self, bgr: np.ndarray, profile: Profile, fps: float, ts: float) -> SafetyResult:
        h, w = bgr.shape[:2]
        r = self.dc.process(bgr, profile, fps)                # sayım çizgisi önemsiz; geçişler kullanılmaz
        res = SafetyResult(tracks=r.tracks)
        grace = grace_for(fps)
        sf = profile.safety
        rules = [("hands_up", hands_up, sf.handsUp), ("lying", lying, sf.lying)]
        for t in r.tracks:
            x1, y1, x2, y2 = (float(v) for v in t.box)
            if not inside_roi(profile, (x1 + x2) / 2, y2):
                continue
            kp = self.pose.estimate(bgr, (x1 * w, y1 * h, x2 * w, y2 * h))
            res.poses[t.id] = kp
            for kind, fn, rule in rules:
                if not rule.enabled:
                    continue
                if self.episodes.update((t.id, kind), fn(kp), ts, rule.seconds, grace_s=grace):
                    # update bölümü az önce yeniledi: etkin listedeki süre = ts − başlangıç
                    dur = next(a[2] for a in self.episodes.active() if a[0] == t.id and a[1] == kind)
                    res.fired.append(SafetyAlarm(kind, t.id, (x1, y1, x2, y2), ts - dur, ts))
        alive = {t.id for t in self.dc.tracker.tracks}
        # sweep aynı anahtarı iki kez bildirebilir ya da etkin bölümü olan anahtarı bitmiş sayabilir (eski bölümün
        # ertelenmiş sonu): olduğu gibi aktarılır, tekilleştirilmez.
        res.ended = [(k[0], k[1], fired) for k, fired in self.episodes.sweep(ts, alive, grace_s=grace)]
        res.active = self.episodes.active()
        return res
