"""Yangın/duman çözümleyicisi (countMode = "fire"): kare başına tanıma → karar katmanı → bölüm ve alarm.

Kurallar ve sabitler fire_rules.py'de; tasarım docs/superpowers/specs/2026-11-08-yangin-duman-design.md §3.3. Sınıf
başına (alev / duman) tek bölüm vardır; iz numarası sabittir (`TRACK_IDS`: alev 0, duman 1) ki alarm sink'in
`(oturum, iz, tür)` anahtarı safety'deki gibi çalışsın. Sözleşme `SafetyAnalyzer` ile aynıdır: `process`, `reset`
(alarm vermiş bölümler bir SONRAKİ `process` sonucunda `ended`), `end_all`. Analiz hızı sınırı (`MAX_FPS`) oturumda
uygulanır, burada değil. Dedektör hataları (ör. `FireModelMissing`) yutulmaz; model sağlığı oturumun işidir.

Kare akışı: hareket kıyas karesi (`MotionHistory`) yoksa (ilk kare) ya da kare geneli `GLOBAL_CHANGE_MAX`'tan fazla
değiştiyse kare **oy dışıdır**: pencereye girmez, bölümü başlatmaz/uzatmaz, alarm doğurmaz; bölüm sonu (`END_S`) yine de
son olumlu kareden duvar saatiyle sayılır. Oy veren karede geçerli (eşik, en küçük kutu, hariç bölge merkezi) ve kutu
içi değişimi `MOTION_MIN`'i aşan kutular olumludur.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from .fire_rules import (
    END_S,
    EPS,
    GLOBAL_CHANGE_MAX,
    KINDS,
    MOTION_MIN,
    TRACK_IDS,
    Box,
    CellVotes,
    MotionHistory,
    big_enough,
    changed_ratio,
    class_conf,
    in_ignore_zone,
    small_gray,
)
from .profile import FireConfig, Profile


@dataclass
class FireAlarm:
    kind: str                                   # "fire" | "smoke"
    track_id: int                               # 0 (fire) / 1 (smoke)
    box: Box                                    # normalize: tetikleyen hücreye değen son karedeki kutuların birleşimi
    started: float                              # bölümün ilk olumlu karesi
    ts: float                                   # alarmın doğduğu zaman


@dataclass
class FireResult:
    detections: list[tuple[str, Box, float, bool]] = field(default_factory=list)   # (tür, normalize kutu, skor, hareket)
    active: list[tuple[int, str, float, bool]] = field(default_factory=list)       # (iz, tür, süre sn, alarm verdi mi)
    fired: list[FireAlarm] = field(default_factory=list)                           # bu karede doğan alarmlar
    ended: list[tuple[int, str, bool]] = field(default_factory=list)               # biten bölümler (iz, tür, alarm)
    boxes: dict[int, Box] = field(default_factory=dict)                            # alarm vermiş açık bölümlerin kutusu


@dataclass
class _Episode:
    started: float
    last_pos: float
    fired: bool = False
    box: Box | None = None


def _union(boxes: list[Box]) -> Box:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


class FireAnalyzer:
    def __init__(self, detector: Any | None = None) -> None:
        self._detector = detector
        self.history = MotionHistory()
        self.votes: dict[str, CellVotes] = {k: CellVotes() for k in KINDS}
        self.episodes: dict[str, _Episode] = {}
        self._reset_ended: list[tuple[int, str, bool]] = []     # reset() ile kesilen alarmlı bölümler
        self._last_ts: float | None = None

    @property
    def detector(self) -> Any:
        if self._detector is None:
            from .fire_model import FireDetector

            self._detector = FireDetector()
        return self._detector

    def _clear(self) -> None:
        self.history.clear()
        for v in self.votes.values():
            v.clear()
        self.episodes = {}
        self._last_ts = None

    def _close(self, only_fired: bool) -> list[tuple[int, str, bool]]:
        return [(TRACK_IDS[k], k, ep.fired) for k, ep in self.episodes.items() if ep.fired or not only_fired]

    def reset(self) -> None:
        """Geçmiş, oylar ve bölümler sıfırlanır; alarm vermiş bölümler bir SONRAKİ `process()` sonucunda `ended` olarak
        bildirilir (alarm günlüğü kapanabilsin)."""
        self._reset_ended += self._close(only_fired=True)
        self._clear()

    def end_all(self) -> list[tuple[int, str, bool]]:
        """Kapanış (oturum durdu): alarm vermiş her açık bölüm ve `reset()` ile kesilip henüz bildirilmemiş olanlar.
        Sonrasında analizörün bölümü kalmaz."""
        ends = self._reset_ended + self._close(only_fired=True)
        self._reset_ended = []
        self.episodes = {}
        return ends

    def active(self) -> list[tuple[int, str, float, bool]]:
        """Açık bölümler: (iz, tür, süre sn, alarm verdi mi) — `FireResult.active` ve canlı durum bloğu."""
        return [(TRACK_IDS[k], k, self.episodes[k].last_pos - self.episodes[k].started, self.episodes[k].fired)
                for k in KINDS if k in self.episodes]

    def process(self, frame: np.ndarray, ts: float, profile: Profile) -> FireResult:
        cfg: FireConfig = getattr(profile, "fire", None) or FireConfig()
        bgr = frame if frame.ndim == 3 else cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        h, w = bgr.shape[:2]
        res = FireResult(ended=self._reset_ended)
        self._reset_ended = []
        if self._last_ts is not None and ts < self._last_ts:      # zaman geri gitti (video başa sardı): baştan
            res.ended += self._close(only_fired=False)
            self._clear()
        self._last_ts = ts

        small = small_gray(bgr)
        ref = self.history.push(ts, small)
        voting = ref is not None and changed_ratio(small, ref) <= GLOBAL_CHANGE_MAX
        conf = class_conf(cfg)
        pos: dict[str, list[Box]] = {k: [] for k in conf}
        for d in self.detector.detect(bgr, conf) if conf else []:   # iki kural kapalı: model hiç çalışmaz
            if d.cls not in conf or d.score < conf[d.cls]:
                continue
            px = (float(d.x1), float(d.y1), float(d.x2), float(d.y2))
            if not big_enough(px, h) or in_ignore_zone(px, cfg.ignoreZones, w, h):
                continue
            nb = (min(1.0, max(0.0, px[0] / w)), min(1.0, max(0.0, px[1] / h)),
                  min(1.0, max(0.0, px[2] / w)), min(1.0, max(0.0, px[3] / h)))
            moved = voting and ref is not None and changed_ratio(small, ref, nb) >= MOTION_MIN
            res.detections.append((d.cls, nb, float(d.score), moved))
            if moved:
                pos[d.cls].append(nb)

        for kind in KINDS:
            ep = self.episodes.get(kind)
            if ep is not None and ts - ep.last_pos >= END_S - EPS:  # oy dışı kareler ve kapalı kural dahil
                res.ended.append((TRACK_IDS[kind], kind, ep.fired))
                del self.episodes[kind]
                ep = None
            if kind not in conf or not voting:
                continue
            rule = getattr(cfg, kind)
            votes = self.votes[kind]
            votes.add(ts, pos[kind])
            votes.prune(ts, rule.seconds)
            if pos[kind]:
                if ep is None:
                    ep = self.episodes[kind] = _Episode(ts, ts)
                ep.last_pos = ts
                if ep.fired:
                    ep.box = _union(pos[kind])                       # alarmlı kutu alevi izler
            if ep is not None and not ep.fired and ts - ep.started >= rule.seconds - EPS:
                cell = votes.trigger(ts, rule.seconds)
                if cell is not None:
                    ep.fired = True
                    # trigger en az MIN_HITS değen kare buldu: box_at None olamaz (yedek yalnız tür için)
                    ep.box = votes.box_at(cell) or (0.0, 0.0, 1.0, 1.0)
                    res.fired.append(FireAlarm(kind, TRACK_IDS[kind], ep.box, ep.started, ts))

        res.active = self.active()
        res.boxes = {TRACK_IDS[k]: ep.box for k, ep in self.episodes.items() if ep.fired and ep.box is not None}
        return res
