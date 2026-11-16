"""Telefon kullanımı kuralı (güvenlik modunun üçüncü kuralı; tasarım docs/superpowers/specs/2026-11-16-telefon-alarmi-design.md).

Tam karede telefon çok küçük kalır (ofis kamerasında ~20 px, ölçüm 2026-11-16): telefon kişi kutusunun %20 paylı
kırpıntısında, kişi tanımadaki aynı COCO modeliyle yalnız "cell phone" sınıfı aranır (`find_phones`). İsabet: telefon
merkezi görünen bir bileğe ya da başa `PHONE_NEAR · ölçek` uzaklıktan yakın (`phone_hit`). Kırpıntıdaki bulgu kesintili
olduğundan (elinde telefon tutan kişide karelerin ~%25'i) eller yukarı gibi "sürekli doğru + kısa tolerans" yerine
dilimli kanıt penceresi kullanılır (`PhoneEvidence`): kural süresi S, `PHONE_SLOT_S`'lik dilimlere bölünür; iz son S
saniye boyunca gözlenmişse ve dilimlerin en az `PHONE_SLOT_RATIO` kadarında isabet varsa bölüm başına bir alarm.
Sabitler başlangıç değerleridir; tools/eval_pose.py ile kullanıcı kayıtlarında kalibre edilir.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .pose_rules import KP_CONF, L_WR, R_WR, head, scale

PHONE_CONF = 0.25                   # kırpıntıda telefon skoru eşiği
PHONE_NEAR = 0.6                    # telefon merkezi bilek/başa en çok bu kadar (× ölçek) uzak
PHONE_PAD = 0.2                     # kişi kutusu payı (her yönde, kutu boyunun oranı)
PHONE_FPS = 2.0                     # iz başına en çok saniyede bu kadar arama
PHONE_SLOT_S = 5.0                  # kanıt penceresi dilim boyu (sn)
PHONE_SLOT_RATIO = 0.6              # alarm için isabetli dilim oranı
PHONE_END_S = 15.0                  # isabetsiz bu kadar sn (ya da iz kaybı) bölümü bitirir

PHONE_CLASS = "cell phone"
KIND = "phone"

Phone = tuple[float, float, float, float, float]          # (x1, y1, x2, y2, skor), tam kare piksel


def find_phones(detector: Any, bgr: np.ndarray, box_px: tuple[float, float, float, float]) -> list[Phone]:
    """Kişi kutusu `PHONE_PAD` payla genişletilip kareye sınırlanarak kırpılır; kırpıntıda yalnız telefon aranır.
    Sonuç tam kare piksel. Kırpıntı boşsa (kutu kare dışında) dedektör çağrılmaz, `[]`."""
    h, w = bgr.shape[:2]
    bx1, by1, bx2, by2 = box_px
    px, py = PHONE_PAD * (bx2 - bx1), PHONE_PAD * (by2 - by1)
    # 1e-6: kayan nokta gürültüsü (örn. 100 − 20,000000000000004) tam sayı sınırını bir piksel kaydırmasın
    x0 = min(w, max(0, math.floor(bx1 - px + 1e-6)))
    y0 = min(h, max(0, math.floor(by1 - py + 1e-6)))
    x1 = min(w, max(0, math.ceil(bx2 + px - 1e-6)))
    y1 = min(h, max(0, math.ceil(by2 + py - 1e-6)))
    if x1 <= x0 or y1 <= y0:
        return []
    out: list[Phone] = []
    for d in detector.detect(bgr[y0:y1, x0:x1], [PHONE_CLASS], conf=PHONE_CONF):
        if d.cls == PHONE_CLASS:
            out.append((float(d.x1) + x0, float(d.y1) + y0, float(d.x2) + x0, float(d.y2) + y0, float(d.score)))
    return out


def phone_hit(phones: list[Phone], kp: np.ndarray) -> bool | None:
    """Telefon merkezi görünen bir bileğe ya da başa `PHONE_NEAR · ölçek` uzaklık içinde mi. Ölçek yoksa ya da hiçbir
    bilek/baş görünmüyorsa None (bu arama sayılmaz); telefon yoksa ya da hepsi uzaksa False."""
    s = scale(kp)
    if s is None:
        return None
    anchors = [kp[i, :2] for i in (L_WR, R_WR) if kp[i, 2] >= KP_CONF]
    hd = head(kp)
    if hd is not None:
        anchors.append(hd)
    if not anchors:
        return None
    limit = PHONE_NEAR * s
    for x1, y1, x2, y2, _score in phones:
        c = np.array(((x1 + x2) / 2, (y1 + y2) / 2))
        if any(float(np.linalg.norm(c - a)) <= limit for a in anchors):
            return True
    return False


@dataclass
class _PhoneEpisode:
    start: float                                    # ilk isabet
    last_hit: float
    last_seen: float                                # son karar (her update); süre = last_seen − start
    hits: list[float] = field(default_factory=list)  # son `seconds` içindeki isabet zamanları
    fired: bool = False


def _slot_ratio(hits: list[float], ts: float, seconds: float) -> float:
    """[ts − seconds, ts] penceresi n = ⌈seconds / PHONE_SLOT_S⌉ dilime bölünür (dilim i = [ts − seconds + i·SLOT, …),
    pencerenin sonundaki isabet son dilime); en az bir isabeti olan dilim oranı."""
    n = max(1, math.ceil(seconds / PHONE_SLOT_S - 1e-9))
    lo = ts - seconds
    slots = {min(n - 1, max(0, int((h - lo) // PHONE_SLOT_S))) for h in hits if lo - 1e-9 <= h <= ts + 1e-9}
    return len(slots) / n


class PhoneEvidence:
    """İz başına telefon bölümü (anahtar `(iz, "phone")`); çıktılar `pose_rules.EpisodeTracker` biçiminde.

    - `observe`: iz gözlem sürekliliği; son gözlemden `PHONE_END_S`'ten uzun süre geçtiyse (ya da zaman geri gittiyse:
      video başa sardı) gözlem yeniden başlar.
    - `update(hit=True)`: bölüm yoksa başlar. Her update'te (bölüm varsa, alarm verilmemişse) iz en az `seconds` gözlenmiş
      ve isabetli dilim oranı ≥ `PHONE_SLOT_RATIO` ise alarm (bölüm başına bir kez, True döner). `hit=None` (karar yok)
      bölümü ne uzatır ne bitirir; False ıska sayılır ama tek başına bitirmez (yalnız süre bitirir).
    - Bayat bölüm (zaman geri gitti ya da son isabetten > `PHONE_END_S`) update'te bitirilip bir sonraki `sweep`'te
      bildirilir; eski isabetlerle geç alarm doğmaz.
    - `sweep`: (iz yaşamıyor ve alarm vermemiş) ya da son isabetten > `PHONE_END_S` ya da zaman son isabetten geride
      → bitti. Alarm vermiş bölüm iz kaybında `PHONE_END_S` dolunca biter (≥ `pose_rules.FIRED_GRACE_S`).
    """

    def __init__(self) -> None:
        self._eps: dict[int, _PhoneEpisode] = {}
        self._obs: dict[int, tuple[float, float]] = {}            # iz → (gözlem başlangıcı, son gözlem)
        self._pending_end: list[tuple[tuple[int, str], bool]] = []

    def observe(self, track_id: int, ts: float) -> None:
        o = self._obs.get(track_id)
        start = ts if o is None or ts - o[1] > PHONE_END_S or ts < o[1] else o[0]
        self._obs[track_id] = (start, ts)

    def update(self, track_id: int, ts: float, hit: bool | None, seconds: float) -> bool:
        ep = self._eps.get(track_id)
        if ep is not None and (ts < ep.last_seen or ts - ep.last_hit > PHONE_END_S + 1e-9):
            self._pending_end.append(((track_id, KIND), ep.fired))
            del self._eps[track_id]
            ep = None
        if hit is True:
            if ep is None:
                ep = self._eps[track_id] = _PhoneEpisode(ts, ts, ts)
            ep.hits.append(ts)
            ep.last_hit = ts
        if ep is None:
            return False
        ep.last_seen = ts
        ep.hits = [h for h in ep.hits if h >= ts - seconds - 1e-9]
        if ep.fired:
            return False
        o = self._obs.get(track_id)
        if o is None or ts - o[0] < seconds - 1e-9:
            return False
        if _slot_ratio(ep.hits, ts, seconds) >= PHONE_SLOT_RATIO - 1e-9:
            ep.fired = True
            return True
        return False

    def sweep(self, ts: float, alive: set[int]) -> list[tuple[tuple[int, str], bool]]:
        ended = self._pending_end
        self._pending_end = []
        dead = [tid for tid, e in self._eps.items()
                if (tid not in alive and not e.fired) or ts - e.last_hit > PHONE_END_S + 1e-9 or ts < e.last_hit]
        for tid in dead:
            ended.append(((tid, KIND), self._eps.pop(tid).fired))
        self._obs = {tid: o for tid, o in self._obs.items() if tid in alive}
        return ended

    def close_all(self) -> list[tuple[tuple[int, str], bool]]:
        ended = self._pending_end + [((tid, KIND), e.fired) for tid, e in self._eps.items()]
        self._pending_end, self._eps, self._obs = [], {}, {}
        return ended

    def active(self) -> list[tuple[int, str, float, bool]]:
        return [(tid, KIND, e.last_seen - e.start, e.fired) for tid, e in self._eps.items()]
