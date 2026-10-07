"""Poz güvenlik çözümleyicisi: kişi tanıma + izleyici (detect_count.DetectCounter) + poz (MoveNet) + kurallar.

Yalnızca onaylı ve bu karede tanımayla gözlenen izlerin pozuna bakılır. **Alan kısıtı yok** (kullanıcı kararı,
2026-10-07): kural karedeki her kişiye uygulanır; profilde çizili bir alan (ROI / çokgen) varsa yok sayılır, tanıma ve
izleme her zaman tam karede çalışır. Kurallar ve süreler pose_rules.py'de; tasarım
docs/superpowers/specs/2026-10-06-poz-guvenlik-design.md. Kopma toleransı kare hızına uyar: yavaş akışta (örn. 1 kare/sn)
sabit 0,5 sn tolerans bölümü sürekli koparırdı.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from .detect_count import DetectCounter
from .people_track import MotTrack
from .pose_rules import GRACE_S, EpisodeTracker, hands_up, lying
from .profile import Profile, Roi

Box = tuple[float, float, float, float]


@dataclass
class SafetyAlarm:
    kind: str                                   # "hands_up" | "lying"
    track_id: int
    box: Box                                    # normalize
    started: float                              # olayın başladığı zaman (ts − süre)
    ts: float                                   # alarmın doğduğu zaman


@dataclass
class SafetyResult:
    tracks: list[MotTrack] = field(default_factory=list)                    # bu karede gözlenen onaylı izler
    poses: dict[int, np.ndarray] = field(default_factory=dict)              # iz → eklemler (17×3, piksel)
    active: list[tuple[int, str, float, bool]] = field(default_factory=list)    # (iz, tür, süre sn, alarm verdi mi)
    fired: list[SafetyAlarm] = field(default_factory=list)                  # bu karede doğan alarmlar
    ended: list[tuple[int, str, bool]] = field(default_factory=list)        # biten bölümler (iz, tür, alarm verdi mi)
    boxes: dict[int, Box] = field(default_factory=dict)                     # alarm vermiş etkin izlerin son bilinen kutusu


def grace_for(fps: float) -> float:
    """Kopma toleransı (sn): en az `GRACE_S`, ve en az ~2,5 kare aralığı (yavaş akışta tek kare kaçığı bölmesin)."""
    return max(GRACE_S, 2.5 / fps) if fps > 0 else GRACE_S


class SafetyAnalyzer:
    def __init__(self, detector: Any | None = None, pose: Any | None = None) -> None:
        self.dc = DetectCounter(detector=detector, motion=False)
        self._pose = pose
        self.episodes = EpisodeTracker()
        self._last_box: dict[int, Box] = {}                         # iz → son gözlenen kutu
        self._reset_ended: list[tuple[int, str, bool]] = []         # reset() ile kesilen alarmlı bölümler

    @property
    def pose(self) -> Any:
        if self._pose is None:
            from .pose import PoseEstimator

            self._pose = PoseEstimator()
        return self._pose

    def enable_gate(self) -> None:
        self.dc.enable_gate()

    def reset(self) -> None:
        """İzleyici ve bölümler sıfırlanır; alarm vermiş bölümler bir SONRAKİ `process()` sonucunda `ended` olarak
        bildirilir (alarm günlüğü kapanabilsin)."""
        # sweep(alive=∅) ertelenmiş sonları ve tüm etkin bölümleri verip temizler (EpisodeTracker'ın açık arayüzü)
        self._reset_ended += [(k[0], k[1], fired) for k, fired in self.episodes.sweep(0.0, set()) if fired]
        self.dc.reset()
        self.episodes = EpisodeTracker()
        self._last_box.clear()

    def end_all(self) -> list[tuple[int, str, bool]]:
        """Kapanış (oturum durdu): alarm vermiş her açık bölüm bitirilip döndürülür; `reset()` ile kesilip henüz
        bildirilmemiş olanlar ve ertelenmiş sonlar dahil. Sonrasında analizörün bölümü kalmaz."""
        ends = self._reset_ended + [(k[0], k[1], fired) for k, fired in self.episodes.sweep(0.0, set()) if fired]
        self._reset_ended = []
        self._last_box.clear()
        return ends

    def process(self, bgr: np.ndarray, profile: Profile, fps: float, ts: float) -> SafetyResult:
        h, w = bgr.shape[:2]
        # Tanıma ve izleyici tam karede (alan kısıtı yok, sayım çizgisi önemsiz); profildeki alan yok sayılır.
        full = replace(profile, roi=Roi(0.0, 0.0, 1.0, 1.0), roiPolygon=None, countLine=None)
        r = self.dc.process(bgr, full, fps)
        res = SafetyResult(tracks=r.tracks)
        grace = grace_for(fps)
        sf = profile.safety
        rules = [("hands_up", hands_up, sf.handsUp), ("lying", lying, sf.lying)]
        for t in r.tracks:
            x1, y1, x2, y2 = (float(v) for v in t.box)
            box = (x1, y1, x2, y2)
            self._last_box[t.id] = box
            kp = self.pose.estimate(bgr, (x1 * w, y1 * h, x2 * w, y2 * h))
            if kp is None:                                          # poz modeli hazır değil / yüklenemedi: karar yok
                continue
            res.poses[t.id] = kp
            for kind, fn, rule in rules:
                if not rule.enabled:
                    continue
                if self.episodes.update((t.id, kind), fn(kp), ts, rule.seconds, grace_s=grace):
                    # update bölümü az önce yeniledi: etkin listedeki süre = ts − başlangıç
                    dur = next(a[2] for a in self.episodes.active() if a[0] == t.id and a[1] == kind)
                    res.fired.append(SafetyAlarm(kind, t.id, box, ts - dur, ts))
        alive = {t.id for t in self.dc.tracker.tracks}
        # sweep aynı anahtarı iki kez bildirebilir ya da etkin bölümü olan anahtarı bitmiş sayabilir (eski bölümün
        # ertelenmiş sonu): olduğu gibi aktarılır, tekilleştirilmez.
        res.ended = self._reset_ended + [(k[0], k[1], fired)
                                         for k, fired in self.episodes.sweep(ts, alive, grace_s=grace)]
        self._reset_ended = []
        res.active = self.episodes.active()
        ids = {a[0] for a in res.active}
        self._last_box = {tid: b for tid, b in self._last_box.items() if tid in ids}
        # Alarmlı iz bu karede gözlenmese de (tanıma kaçırdı) kırmızı kutu son bilinen yerinde kalsın
        res.boxes = {a[0]: self._last_box[a[0]] for a in res.active if a[3] and a[0] in self._last_box}
        return res
