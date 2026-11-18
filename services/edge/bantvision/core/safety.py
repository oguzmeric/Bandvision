"""Poz güvenlik çözümleyicisi: kişi tanıma + izleyici (detect_count.DetectCounter) + poz (MoveNet) + kurallar.

Yalnızca onaylı ve bu karede tanımayla gözlenen izlerin pozuna bakılır. Tanıma ve izleme her zaman tam karede çalışır;
profildeki sayım alanı (ROI / çokgen) ve sayım çizgisi yok sayılır. **Analiz alanları** (`safety.areas`, tasarım
docs/superpowers/specs/2026-11-17-alarm-penceresi-design.md §11): alan yoksa kural karedeki herkese uygulanır; varsa
kutu merkezi hiçbir alanda olmayan iz izlemeden sonra süzülür (sonuçta yok: iz, poz, bölüm, alarm), alandaki ize
yalnız alanlarının izin verdiği kurallar işletilir (`area_rules`); izni kalkan kuralın bölümü görünmeyen kişininki gibi
toleransla biter. Kurallar ve süreler pose_rules.py'de; tasarım docs/superpowers/specs/2026-10-06-poz-guvenlik-design.md. Kopma toleransı kare hızına uyar: yavaş akışta (örn. 1 kare/sn)
sabit 0,5 sn tolerans bölümü sürekli koparırdı.

Üçüncü kural telefon kullanımı (phone_rules.py; tasarım docs/superpowers/specs/2026-11-16-telefon-alarmi-design.md):
kare kararı değil, kişi kırpıntısında telefon araması (iz başına en çok `PHONE_FPS`/sn, kare başına en çok
`PHONE_MAX_PER_FRAME` arama: sırası gelen izlerden en uzun süredir aranmamış olanlar, hiç aranmamış olan önce; eklemlerden
karar çıkamayacak izde arama yapılmaz) + dilimli kanıt penceresi; kendi bölüm izleyicisi (`PhoneEvidence`) aynı `fired` /
`ended` / `active` biçimini üretir. Kural kapalıyken (varsayılan) kırpıntı araması hiç yapılmaz, davranış ve model
çağrıları önceki gibidir.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import cv2
import numpy as np

from .detect_count import DetectCounter
from .people_track import MotTrack
from .phone_rules import PHONE_FPS, PHONE_MAX_PER_FRAME, PhoneEvidence, find_phones, phone_hit, phone_possible
from .pose_rules import GRACE_S, EpisodeTracker, hands_up, lying
from .profile import Profile, Roi, SafetyArea

Box = tuple[float, float, float, float]

# Çekirdek alarm türü → sözleşmedeki kural adı (profil `safety.<ad>`, alan `rules`, video işi `alarms[].kind`).
# Eşlemenin tek yeri: bindirme ve video işi buradan okur.
RULE_OF_KIND: dict[str, str] = {"hands_up": "handsUp", "lying": "lying", "phone": "phone"}


def in_area(box: Sequence[float], area: SafetyArea) -> bool:
    """Normalize kutunun (x1, y1, x2, y2) merkezi alan çokgeninin içinde mi (kenar dahil)."""
    poly = np.array(area.points, np.float32).reshape(-1, 1, 2)
    centre = ((float(box[0]) + float(box[2])) / 2, (float(box[1]) + float(box[3])) / 2)
    return bool(cv2.pointPolygonTest(poly, centre, False) >= 0)


def area_rules(box: Sequence[float], areas: list[SafetyArea]) -> tuple[set[str], dict[str, str]] | None:
    """Alan yoksa None (bütün kare, bütün kurallar serbest). Varsa: kutu merkezinin içinde olduğu alanların kural
    birleşimi (sözleşme adları) ve kural → listede ilk gelen ve o kuralı içeren alanın adı. Hiçbir alanda değilse
    `(set(), {})`."""
    if not areas:
        return None
    rules: set[str] = set()
    first: dict[str, str] = {}
    for a in areas:
        if in_area(box, a):
            for r in a.rules:
                rules.add(r)
                first.setdefault(r, a.name)
    return rules, first


@dataclass
class SafetyAlarm:
    kind: str                                   # "hands_up" | "lying" | "phone"
    track_id: int
    box: Box                                    # normalize
    started: float                              # olayın başladığı zaman (bölüm başlangıcı)
    ts: float                                   # alarmın doğduğu zaman
    area: str | None = None                     # alarmın analiz alanı (kuralı içeren ilk alan); alan yoksa None


@dataclass
class SafetyResult:
    tracks: list[MotTrack] = field(default_factory=list)                    # gözlenen onaylı izler (alan içinde)
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
        # Tanıma ve izleyici tam karede (sayım çizgisi önemsiz); profildeki sayım alanı yok sayılır.
        full = replace(profile, roi=Roi(0.0, 0.0, 1.0, 1.0), roiPolygon=None, countLine=None)
        r = self.dc.process(bgr, full, fps)
        sf = profile.safety
        # Analiz alanı süzgeci (izlemeden sonra, kurallardan önce): hiçbir alanda olmayan iz sonuca girmez; alandaki iz
        # için izinli kurallar ve kural → alan adı. Alan yoksa `allowed` None (her şey serbest).
        seen: list[tuple[MotTrack, tuple[set[str], dict[str, str]] | None]] = []
        for t in r.tracks:
            allowed = area_rules(t.box, sf.areas)
            if allowed is None or allowed[0]:
                seen.append((t, allowed))
        res = SafetyResult(tracks=[t for t, _ in seen])
        grace = grace_for(fps)
        rules = [(k, fn, rule) for k, fn, rule in (("hands_up", hands_up, sf.handsUp), ("lying", lying, sf.lying))
                 if rule.enabled]
        phone = sf.phone.enabled
        # aranmak isteyen izler: (son arama, iz, kutu, piksel kutu, eklemler, telefon kuralının alanı)
        due: list[tuple[float, int, Box, tuple[float, float, float, float], np.ndarray, str | None]] = []
        for t, allowed in seen if rules or phone else []:          # üç kural da kapalı: poz hiç çalışmaz
            mine = [x for x in rules if allowed is None or RULE_OF_KIND[x[0]] in allowed[0]]
            my_phone = phone and (allowed is None or "phone" in allowed[0])
            if not mine and not my_phone:                           # alanında kamerada açık kural yok: poz yok
                continue
            x1, y1, x2, y2 = (float(v) for v in t.box)
            box = (x1, y1, x2, y2)
            box_px = (x1 * w, y1 * h, x2 * w, y2 * h)
            self._last_box[t.id] = box
            kp = self.pose.estimate(bgr, box_px)
            if kp is None:                                          # poz modeli hazır değil / yüklenemedi: karar yok
                continue
            res.poses[t.id] = kp
            for kind, fn, rule in mine:
                if self.episodes.update((t.id, kind), fn(kp), ts, rule.seconds, grace_s=grace):
                    # update bölümü az önce yeniledi: etkin listedeki süre = ts − başlangıç
                    dur = next(a[2] for a in self.episodes.active() if a[0] == t.id and a[1] == kind)
                    area = None if allowed is None else allowed[1][RULE_OF_KIND[kind]]
                    res.fired.append(SafetyAlarm(kind, t.id, box, ts - dur, ts, area))
            if my_phone:
                self.phone.observe(t.id, ts)
                last = self._phone_last.get(t.id)
                # Zaman geri gittiyse (video başa sardı) hemen aranır. Eklemlerden karar çıkamayacaksa (ölçek ya da
                # görünen bilek/baş yok) arama yapılmaz: ne bütçeden yer ne arama sayılır.
                if (last is None or ts < last or ts - last >= 1.0 / PHONE_FPS - 1e-9) and phone_possible(kp):
                    area = None if allowed is None else allowed[1]["phone"]
                    due.append((float("-inf") if last is None or ts < last else last, t.id, box, box_px, kp, area))
        # Kare başına en çok PHONE_MAX_PER_FRAME arama: en uzun süredir aranmamış izler (hiç aranmamış olan önce)
        for _last, tid, box, box_px, kp, area in sorted(due, key=lambda d: (d[0], d[1]))[:PHONE_MAX_PER_FRAME]:
            self._phone_last[tid] = ts
            hit = phone_hit(find_phones(self.dc.detector, bgr, box_px), kp)
            if self.phone.update(tid, ts, hit, sf.phone.seconds):
                started = self.phone.started(tid)               # bölüm başı; ateşleyen kare ıska olabilir
                res.fired.append(SafetyAlarm("phone", tid, box, ts if started is None else started, ts, area))
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
