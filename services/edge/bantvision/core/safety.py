"""Poz güvenlik çözümleyicisi: kişi tanıma + izleyici (detect_count.DetectCounter) + poz (MoveNet) + kurallar.

Yalnızca onaylı ve bu karede tanımayla gözlenen izlerin pozuna bakılır. **Alan kısıtı yok** (kullanıcı kararı,
2026-10-07): kural karedeki her kişiye uygulanır; profilde çizili bir alan (ROI / çokgen) varsa yok sayılır, tanıma ve
izleme her zaman tam karede çalışır. Kurallar ve süreler pose_rules.py'de; tasarım
docs/superpowers/specs/2026-10-06-poz-guvenlik-design.md. Kopma toleransı kare hızına uyar: yavaş akışta (örn. 1 kare/sn)
sabit 0,5 sn tolerans bölümü sürekli koparırdı.

Üçüncü kural telefon kullanımı (phone_rules.py; tasarım docs/superpowers/specs/2026-11-16-telefon-alarmi-design.md):
kare kararı değil, kişi kırpıntısında telefon araması (iz başına en çok `PHONE_FPS`/sn, kare başına en çok
`PHONE_MAX_PER_FRAME` arama: sırası gelen izlerden en uzun süredir aranmamış olanlar, hiç aranmamış olan önce; eklemlerden
karar çıkamayacak izde arama yapılmaz) + dilimli kanıt penceresi; kendi bölüm izleyicisi (`PhoneEvidence`) aynı `fired` /
`ended` / `active` biçimini üretir. Kural kapalıyken (varsayılan) kırpıntı araması hiç yapılmaz, davranış ve model
çağrıları önceki gibidir.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from .detect_count import DetectCounter
from .people_track import MotTrack
from .phone_rules import PHONE_FPS, PHONE_MAX_PER_FRAME, PhoneEvidence, find_phones, phone_hit, phone_possible
from .pose_rules import GRACE_S, EpisodeTracker, hands_up, lying
from .profile import Profile, Roi

Box = tuple[float, float, float, float]


@dataclass
class SafetyAlarm:
    kind: str                                   # "hands_up" | "lying" | "phone"
    track_id: int
    box: Box                                    # normalize
    started: float                              # olayın başladığı zaman (bölüm başlangıcı)
    ts: float                                   # alarmın doğduğu zaman


@dataclass
class SafetyResult:
    tracks: list[MotTrack] = field(default_factory=list)                    # bu karede gözlenen onaylı izler
    poses: dict[int, np.ndarray] = field(default_factory=dict)              # iz → eklemler (17×3, piksel)
    active: list[tuple[int, str, float, bool]] = field(default_factory=list)    # (iz, tür, süre sn, alarm verdi mi)
    fired: list[SafetyAlarm] = field(default_factory=list)                  # bu karede doğan alarmlar
    ended: list[tuple[int, str, bool]] = field(default_factory=list)        # biten bölümler (iz, tür, alarm verdi mi)
    # biten bölümün son olumlu gözlemi (iz, tür) → zaman: pozda son True kare, telefonda son isabet. Bitiş bildirimi
    # toleranstan (FIRED_GRACE_S / PHONE_END_S) sonra gelir; canlı alarm kaydının endedAt'i bu ana geri alınır.
    ended_last: dict[tuple[int, str], float] = field(default_factory=dict)
    boxes: dict[int, Box] = field(default_factory=dict)                     # alarm vermiş etkin izlerin son bilinen kutusu


def grace_for(fps: float) -> float:
    """Kopma toleransı (sn): en az `GRACE_S`, ve en az ~2,5 kare aralığı (yavaş akışta tek kare kaçığı bölmesin)."""
    return max(GRACE_S, 2.5 / fps) if fps > 0 else GRACE_S


class SafetyAnalyzer:
    def __init__(self, detector: Any | None = None, pose: Any | None = None) -> None:
        self.dc = DetectCounter(detector=detector, motion=False)
        self._pose = pose
        self.episodes = EpisodeTracker()
        self.phone = PhoneEvidence()                                # telefon kuralı bölümleri (anahtar (iz, "phone"))
        self._phone_last: dict[int, float] = {}                     # iz → son telefon araması zamanı
        self._last_box: dict[int, Box] = {}                         # iz → son gözlenen kutu
        self._reset_ended: list[tuple[int, str, bool]] = []         # reset() ile kesilen alarmlı bölümler
        self._reset_last: dict[tuple[int, str], float] = {}         # ve son olumlu gözlemleri
        self.ended_last: dict[tuple[int, str], float] = {}          # son end_all()'ın bölümlerinin son olumlu gözlemi

    @property
    def pose(self) -> Any:
        if self._pose is None:
            from .pose import PoseEstimator

            self._pose = PoseEstimator()
        return self._pose

    def enable_gate(self) -> None:
        self.dc.enable_gate()

    def active(self) -> list[tuple[int, str, float, bool]]:
        """Süren bölümler (iz, tür, süre sn, alarm verdi mi): eller yukarı / yatma ve telefon birlikte. Dışarıdan (canlı
        durum) bölümler buradan okunur; `episodes` yalnız ilk iki kuralı taşır."""
        return self.episodes.active() + self.phone.active()

    def _close_fired(self) -> tuple[list[tuple[int, str, bool]], dict[tuple[int, str], float]]:
        """Tüm bölümleri kapatır; alarm vermişler (iz, tür, True) ve son olumlu gözlemleri."""
        ends: list[tuple[int, str, bool]] = []
        last: dict[tuple[int, str], float] = {}
        for tracker in (self.episodes, self.phone):
            for k, fired in tracker.close_all():
                if fired:
                    ends.append((k[0], k[1], fired))
                    last.setdefault(k, tracker.ended_last[k])
        return ends, last

    def reset(self) -> None:
        """İzleyici ve bölümler sıfırlanır; alarm vermiş bölümler bir SONRAKİ `process()` sonucunda `ended` olarak
        bildirilir (alarm günlüğü kapanabilsin)."""
        ends, last = self._close_fired()
        self._reset_ended += ends
        self._reset_last = {**last, **self._reset_last}             # önce kesilenin değeri kalır (ilk bildirim)
        self.dc.reset()
        self.episodes = EpisodeTracker()                            # telefon bölümlerini close_all zaten boşalttı
        self._phone_last.clear()
        self._last_box.clear()

    def end_all(self) -> list[tuple[int, str, bool]]:
        """Kapanış (oturum durdu): alarm vermiş her açık bölüm bitirilip döndürülür; `reset()` ile kesilip henüz
        bildirilmemiş olanlar ve ertelenmiş sonlar dahil. Sonrasında analizörün bölümü kalmaz. Son olumlu
        gözlemleri `ended_last`'ta (bir sonraki end_all'a dek)."""
        ends, last = self._close_fired()
        ends = self._reset_ended + ends
        self.ended_last = {**last, **self._reset_last}
        self._reset_ended, self._reset_last = [], {}
        self._phone_last.clear()
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
        rules = [(k, fn, rule) for k, fn, rule in (("hands_up", hands_up, sf.handsUp), ("lying", lying, sf.lying))
                 if rule.enabled]
        phone = sf.phone.enabled
        due: list[tuple[float, int, Box, tuple[float, float, float, float], np.ndarray]] = []   # aranmak isteyen izler
        for t in r.tracks if rules or phone else []:                # üç kural da kapalı: poz hiç çalışmaz
            x1, y1, x2, y2 = (float(v) for v in t.box)
            box = (x1, y1, x2, y2)
            box_px = (x1 * w, y1 * h, x2 * w, y2 * h)
            self._last_box[t.id] = box
            kp = self.pose.estimate(bgr, box_px)
            if kp is None:                                          # poz modeli hazır değil / yüklenemedi: karar yok
                continue
            res.poses[t.id] = kp
            for kind, fn, rule in rules:
                if self.episodes.update((t.id, kind), fn(kp), ts, rule.seconds, grace_s=grace):
                    # update bölümü az önce yeniledi: etkin listedeki süre = ts − başlangıç
                    dur = next(a[2] for a in self.episodes.active() if a[0] == t.id and a[1] == kind)
                    res.fired.append(SafetyAlarm(kind, t.id, box, ts - dur, ts))
            if phone:
                self.phone.observe(t.id, ts)
                last = self._phone_last.get(t.id)
                # Zaman geri gittiyse (video başa sardı) hemen aranır. Eklemlerden karar çıkamayacaksa (ölçek ya da
                # görünen bilek/baş yok) arama yapılmaz: ne bütçeden yer ne arama sayılır.
                if (last is None or ts < last or ts - last >= 1.0 / PHONE_FPS - 1e-9) and phone_possible(kp):
                    due.append((float("-inf") if last is None or ts < last else last, t.id, box, box_px, kp))
        # Kare başına en çok PHONE_MAX_PER_FRAME arama: en uzun süredir aranmamış izler (hiç aranmamış olan önce)
        for _last, tid, box, box_px, kp in sorted(due, key=lambda d: (d[0], d[1]))[:PHONE_MAX_PER_FRAME]:
            self._phone_last[tid] = ts
            hit = phone_hit(find_phones(self.dc.detector, bgr, box_px), kp)
            if self.phone.update(tid, ts, hit, sf.phone.seconds):
                started = self.phone.started(tid)               # bölüm başı; ateşleyen kare ıska olabilir
                res.fired.append(SafetyAlarm("phone", tid, box, ts if started is None else started, ts))
        alive = {t.id for t in self.dc.tracker.tracks}
        # sweep aynı anahtarı iki kez bildirebilir ya da etkin bölümü olan anahtarı bitmiş sayabilir (eski bölümün
        # ertelenmiş sonu): olduğu gibi aktarılır, tekilleştirilmez.
        res.ended = self._reset_ended + [(k[0], k[1], fired)
                                         for k, fired in self.episodes.sweep(ts, alive, grace_s=grace)
                                         + self.phone.sweep(ts, alive)]
        res.ended_last = {**self.episodes.ended_last, **self.phone.ended_last, **self._reset_last}
        self._reset_ended, self._reset_last = [], {}
        self._phone_last = {tid: v for tid, v in self._phone_last.items() if tid in alive}
        res.active = self.active()
        ids = {a[0] for a in res.active}
        self._last_box = {tid: b for tid, b in self._last_box.items() if tid in ids}
        # Alarmlı iz bu karede gözlenmese de (tanıma kaçırdı) kırmızı kutu son bilinen yerinde kalsın
        res.boxes = {a[0]: self._last_box[a[0]] for a in res.active if a[3] and a[0] in self._last_box}
        return res
