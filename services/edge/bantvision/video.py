"""Video dosyasından sayım: kalibrasyon + işaretli çıktı videosu.

Kullanım:
    python -m bantvision.video bant.mp4                      # her şeyi otomatik bul
    python -m bantvision.video bant.mp4 --truth 57           # elle sayımla karşılaştır
    python -m bantvision.video bant.mp4 --direction right --roi 0.1,0.2,0.8,0.6 --line 0.5

İki geçiş yapar:
  1. Kalibrasyon: arka plan (örnek karelerin medyanı; videoda boş bant olmasa da çalışır), gürültüden eşik,
     optik akıştan akış yönü, çizgiyi geçen lekelerin medyanından tek ürün alanı.
  2. Sayım: çekirdek (`Pipeline`) aynen canlı kameradaki gibi çalışır; işaretli video, özet ve profil yazılır.

Klasik yöntem sabit kamera ister: kamera kayıyor, zoom yapıyor ya da sahne değişiyorsa sonuç güvenilmez.
"""
from __future__ import annotations

import argparse
import csv
import functools
import json
import math
import pathlib
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import cv2
import numpy as np

from .core import Pipeline, Profile
from .core.detector import CLASS_IDS, GROUPS
from .core.lineframe import nearest_direction
from .core.linescan import LineScanCounter, active_region, flow_profile, frame_moving, match_shift, motion_map
from .core.pipeline import FrameResult
from .core.profile import Roi
from .core.segmenter import downsample, roi_mask
from .core.tracker import median
from .overlay import draw_detect


@functools.lru_cache(maxsize=8)
def _mask(roi: tuple[float, float, float, float], polygon: tuple[tuple[float, float], ...] | None,
          w: int, h: int) -> np.ndarray:
    m = roi_mask(Roi(*roi), polygon, w, h)
    m.flags.writeable = False                    # önbellekteki dizi değiştirilmesin
    return m


def profile_mask(profile: Profile, w: int, h: int) -> np.ndarray:
    """§2.0 ROI maskesi (önbellekli; her karede yeniden hesaplanmaz)."""
    r = profile.roi
    poly = tuple(profile.roiPolygon) if profile.roiPolygon else None
    return _mask((r.x, r.y, r.width, r.height), poly, w, h)

PRESETS = {"generic": Profile, "egg": Profile.egg, "flour": Profile.flour_sack, "box": Profile.box,
           "people": Profile.people, "vehicle": Profile.vehicles, "animal": Profile.animals}
MODE_TR = {"blob": "leke (ayrık ürünler)", "linescan": "şerit tarama (tek sıra, bitişik hacimli ürünler)",
           "detect": "tanıma (kişi/araç/hayvan; iki yönlü giriş/çıkış)"}
DIRECTION_TR = {"down": "yukarıdan aşağı", "up": "aşağıdan yukarı", "right": "soldan sağa", "left": "sağdan sola"}

# BGR renkler (iOS bindirmesiyle aynı anlam: sarı ROI, turuncu çizgi, yeşil leke, camgöbeği sayılmış iz)
YELLOW, ORANGE, GREEN, CYAN, WHITE = (0, 220, 255), (0, 140, 255), (80, 220, 60), (230, 210, 40), (255, 255, 255)


# ---------------------------------------------------------------- video okuma

@dataclass
class VideoInfo:
    path: pathlib.Path
    fps: float
    frames: int
    width: int
    height: int

    @property
    def duration(self) -> float:
        return self.frames / self.fps if self.fps else 0.0


def probe(path: pathlib.Path) -> VideoInfo:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit(f"Video açılamadı: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    if not 1.0 <= fps <= 1000.0:  # bazı kapsayıcılar 0 ya da saçma değer döndürür
        fps = 30.0
    info = VideoInfo(path, fps, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
                     int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cap.release()
    return info


def read_frames(info: VideoInfo, start: float = 0.0, end: float | None = None,
                step: int = 1) -> Iterator[tuple[int, float, np.ndarray]]:
    """(kare no, zaman, BGR kare). Zaman, kare numarası / fps'tir (kapsayıcı zaman damgalarına güvenilmez)."""
    cap = cv2.VideoCapture(str(info.path))
    first = int(start * info.fps)
    if first:
        cap.set(cv2.CAP_PROP_POS_FRAMES, first)
    k = first
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                return
            t = k / info.fps
            if end is not None and t > end:
                return
            if (k - first) % step == 0:
                yield k, t, frame
            k += 1
    finally:
        cap.release()


def to_gray(frame: np.ndarray, rotation: int) -> np.ndarray:
    rot = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}
    if rotation in rot:
        frame = cv2.rotate(frame, rot[rotation])
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame


# ---------------------------------------------------------------- otomatik kalibrasyon

@dataclass
class Calibration:
    background: np.ndarray            # işleme çözünürlüğünde float32
    threshold: int
    direction: str | None             # None: hareket bulunamadı
    flow: tuple[float, float]          # medyan (dx, dy), işleme pikseli / kare
    expected_area: float = 0.0
    area_samples: int = 0
    background_from: str = "medyan"
    notes: list[str] = field(default_factory=list)


def _noise_threshold(p995: float) -> int:
    """Canlı kalibrasyonla (§5) aynı formül: gürültünün %99,5'i × 1,5 + 8, [12, 100]."""
    return int(min(100, max(12, int(p995 * 1.5) + 8)))


def temporal_noise_p995(info: VideoInfo, profile: Profile, window: float, pairs: int = 40) -> float:
    """Ardışık kare farklarından gürültü: ürünlerin nerede ne kadar beklediğinden bağımsızdır.

    İki ardışık karede piksellerin çoğu değişmez (yalnızca hareketli kenarlar değişir), bu yüzden
    |f(t) - f(t+1)| medyanı sensör/sıkıştırma gürültüsünü verir. Gauss gürültüde
    medyan = 0,6745·σ·√2 ve |N(0,σ)|'nın %99,5'i = 2,807·σ.
    """
    end = min(info.duration, window)
    step = max(1, int(end * info.fps) // pairs)
    meds: list[float] = []
    prev: np.ndarray | None = None
    for k, _, f in read_frames(info, 0.0, end):
        g = downsample(to_gray(f, profile.rotation), profile.processingWidth)[0].astype(np.float32)
        if prev is not None and k % step == 0:
            h, w = g.shape
            inside = profile_mask(profile, w, h)
            meds.append(float(np.median(np.abs(g - prev)[inside])))
        prev = g
    sigma = (float(np.median(meds)) if meds else 0.0) / (0.6745 * math.sqrt(2))
    return 2.807 * sigma


def estimate_background(info: VideoInfo, profile: Profile, window: float, samples: int = 60,
                        bg_range: tuple[float, float] | None = None, percentile: float = 50.0
                        ) -> tuple[np.ndarray, int, list[np.ndarray]]:
    """Arka plan = örnek karelerin piksel medyanı.

    `bg_range` verilirse (videoda boş bandın göründüğü aralık) yalnızca oradan öğrenilir ve eşik canlı
    kalibrasyondaki gibi |kare - arka plan| dağılımından hesaplanır. Verilmezse tüm pencereden öğrenilir:
    ürünler hareket ettiği için her pikselde çoğu örnek bant olur ve medyan ürünleri siler. Bu varsayım
    bant %50'den fazla dolu olduğunda bozulur (bkz. testler); eşik bu yüzden ardışık kare farkından alınır.

    `percentile` < 50: bant hiç boşalmıyor ama ürünler banttan parlaksa (koyu merdanede yumurta) her pikselin
    koyu hâlleri boş banttır; > 50: ürünler banttan koyuysa. Pikselin bu oranda boş görünmesi yeter.
    """
    start, end = bg_range if bg_range else (0.0, min(info.duration, window))
    n_avail = max(1, int((end - start) * info.fps))
    step = max(1, n_avail // samples)
    smalls = [downsample(to_gray(f, profile.rotation), profile.processingWidth)[0]
              for _, _, f in read_frames(info, start, end, step)]
    if len(smalls) < (3 if bg_range else 5):
        raise SystemExit("Kalibrasyon için yeterli kare okunamadı (video ya da --bg-range çok kısa).")
    stack = np.stack(smalls).astype(np.float32)
    bg = np.median(stack, axis=0) if percentile == 50 else np.percentile(stack, percentile, axis=0)
    if bg_range:
        h, w = bg.shape
        inside = profile_mask(profile, w, h)
        p995 = float(np.percentile(np.abs(stack - bg)[:, inside], 99.5))
    else:
        p995 = temporal_noise_p995(info, profile, window)
    return bg, _noise_threshold(p995), smalls


def estimate_direction(info: VideoInfo, profile: Profile, bg: np.ndarray,
                       threshold: int, window: float) -> tuple[str | None, tuple[float, float]]:
    """Ön plandaki piksellerin optik akış medyanı → baskın eksen ve işaret."""
    end = min(info.duration, window)
    pairs = max(2, min(40, int(end * info.fps) - 1))
    step = max(1, int(end * info.fps) // pairs)
    dxs: list[np.ndarray] = []
    dys: list[np.ndarray] = []
    prev = None
    h, w = bg.shape
    inside = profile_mask(profile, w, h)
    for k, _, f in read_frames(info, 0.0, end):
        g = downsample(to_gray(f, profile.rotation), profile.processingWidth)[0]
        if prev is not None and k % step == 0:
            flow = cv2.calcOpticalFlowFarneback(prev, g, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            fg = (np.abs(g.astype(np.float32) - bg) > threshold) & inside
            moving = fg & (np.hypot(flow[..., 0], flow[..., 1]) > 0.3)
            if moving.sum() > 20:
                dxs.append(flow[..., 0][moving])
                dys.append(flow[..., 1][moving])
        prev = g
    if not dxs:
        return None, (0.0, 0.0)
    dx, dy = float(np.median(np.concatenate(dxs))), float(np.median(np.concatenate(dys)))
    if max(abs(dx), abs(dy)) < 0.2:
        return None, (dx, dy)
    if abs(dy) >= abs(dx):
        return ("down" if dy > 0 else "up"), (dx, dy)
    return ("right" if dx > 0 else "left"), (dx, dy)


def unit_area(areas: list[float]) -> tuple[float, bool]:
    """Lekelerin alanlarından tek ürün alanı. (alan, karışık_mı) döner.

    Tek ürünler ile bitişik çiftler/üçlüler karışıksa medyan çifte kayar. Bu yüzden alt %20'lik dilimin
    1,4 katına kadar olan lekeler "tek" sayılır; bunlar örneklerin en az dörtte biriyse onların medyanı alınır.
    Hepsi çift olan bir videoda alan tek başına yeterli değildir (çift yumurta = büyük tek ürün):
    o durumda tek tek geçen ürünlerle ayrı kalibrasyon gerekir (`--profile`).
    """
    if len(areas) < 3:
        return 0.0, False
    s = sorted(areas)
    small = s[int(0.2 * (len(s) - 1))]
    singles = [a for a in s if a <= 1.4 * small]
    mixed = s[int(0.9 * (len(s) - 1))] > 1.6 * small
    if len(singles) >= max(3, len(s) // 4):
        return median(singles), mixed
    return median(s), mixed


def estimate_expected_area(info: VideoInfo, profile: Profile, bg: np.ndarray, window: float
                           ) -> tuple[float, int, bool]:
    """Çizgiyi geçen izlerin medyan alanlarından tek ürün alanı (bkz. `unit_area`)."""
    p = Profile.from_dict(profile.to_dict())
    p.expectedArea = 0.0
    p.splitTouching = False
    pipe = Pipeline(p)
    pipe.segmenter.bg = bg.copy()
    areas: list[float] = []
    for _, t, f in read_frames(info, 0.0, min(info.duration, window)):
        r = pipe.process(f, t)
        areas += [e.median_area for e in r.counts if e.is_first_crossing and e.median_area > 0]
    unit, mixed = unit_area(areas)
    return unit, len(areas), mixed


def estimate_direction_linescan(info: VideoInfo, profile: Profile, window: float, pairs: int = 40
                                ) -> tuple[str | None, tuple[float, float]]:
    """Şerit tarama (§4.9): önce hareketli bölge (§4.9.0, dikey ve yatay akış için ayrı), sonra dört yön için
    çizgi çevresindeki kayma; en büyük ortalama kayma akış yönüdür (yanlış yönde eşleşme belirsiz ya da ~0)."""
    end = min(info.duration, window)
    n_avail = max(2, int(end * info.fps))
    step = max(1, n_avail // pairs)
    smalls: list[np.ndarray] = []
    prev = None
    for k, _, f in read_frames(info, 0.0, end):
        g = downsample(to_gray(f, profile.rotation), profile.processingWidth)[0]
        if prev is not None and k % step == 0:
            smalls += [prev, g]
        prev = g
    if not smalls:
        return None, (0.0, 0.0)
    h, w = smalls[0].shape
    base = roi_mask(profile.roi, profile.roiPolygon, w, h)
    shifts: dict[str, list[float]] = {d: [] for d in ("down", "up", "right", "left")}
    # Eksen: hareketli bölgesindeki ortalama hareketi büyük olan (bant şeridi yoğun hareketlidir; ekran kaydındaki
    # ilerleme çubuğu gibi ince hareketler bölgeye seyreltilir)
    cands: list[tuple[float, tuple[str, str], Profile, np.ndarray, tuple[int, int, int, int]]] = []
    for dirs in (("down", "up"), ("right", "left")):
        q = Profile.from_dict(profile.to_dict())
        q.direction = dirs[0]
        maps = [motion_map(smalls[i + 1], smalls[i], base) for i in range(0, len(smalls), 2)]
        maps = [m for m in maps if frame_moving(m, q)]
        if len(maps) < 3:
            continue
        med_map = np.sort(np.stack(maps), axis=0)[(len(maps) - 1) // 2]
        region = active_region(med_map, q, base)
        if region is None:
            continue
        mask, bounds = region
        cands.append((float(med_map[mask].mean()) if mask.any() else 0.0, dirs, q, mask, bounds))
    if cands:
        _, dirs, q, mask, bounds = max(cands, key=lambda c: c[0])
        for d in dirs:
            q.direction = d
            for i in range(0, len(smalls), 2):
                fa, fb = flow_profile(smalls[i], q, mask, bounds), flow_profile(smalls[i + 1], q, mask, bounds)
                if fa is None or fb is None:
                    continue
                m = match_shift(fa[0][1], fb[0][1], fb[1])
                shifts[d].append(m[0] if m else 0.0)
    # Ortalama: ekran kayıtlarında tekrarlanan karelerin kayması 0'dır, medyanı sıfıra çeker
    med = {d: (float(np.mean(v)) if v else 0.0) for d, v in shifts.items()}
    best = max(med, key=lambda d: med[d])
    if med[best] < 0.2:
        return None, (0.0, 0.0)
    flow = {"down": (0.0, med[best]), "up": (0.0, -med[best]), "right": (med[best], 0.0), "left": (-med[best], 0.0)}
    return best, flow[best]


def learn_product_length(info: VideoInfo, profile: Profile, window: float) -> float:
    """Şerit tarama (§4.9.5) ön geçişi: ürün boyunu öğren ki sayım geçişinde sayılar video boyunca aksın
    (tek geçişte boy ancak ~3 alan boyu bant aktıktan sonra öğrenilir)."""
    q = Profile.from_dict(profile.to_dict())
    q.productLength = 0.0
    lc = LineScanCounter()
    for _, _, f in read_frames(info, 0.0, min(info.duration, window)):
        lc.process(downsample(to_gray(f, q.rotation), q.processingWidth)[0], q)
        if lc.product_length > 0:
            return lc.product_length
    lc.flush(q)
    return lc.product_length


def calibrate(info: VideoInfo, profile: Profile, window: float, fixed_direction: bool,
              fixed_area: bool, bg_range: tuple[float, float] | None = None,
              bg_percentile: float = 50.0, threshold: int | None = None) -> Calibration:
    if profile.countMode == "detect":
        # §4.10: arka plan, eşik, alan gerekmez. Sayım yönü = giriş yönü (hazır profil ya da --direction);
        # kişi iki yönde de geçtiğinden hareketten tahmin edilmez.
        cal = Calibration(np.zeros((2, 2), np.float32), profile.diffThreshold, profile.direction, (0.0, 0.0),
                          background_from="gerekmiyor")
        if not fixed_direction:
            cal.notes.append("Giriş yönü: " + DIRECTION_TR.get(profile.direction, profile.direction)
                             + " (hazır profil). Ters ise yönü değiştir.")
        return cal
    if profile.countMode == "linescan":
        # §4.9: arka plan ve leke alanı gerekmez; yalnızca yön (ürün boyu sayım sırasında öğrenilir)
        first = next((f for _, _, f in read_frames(info, 0.0, min(info.duration, 1.0))), None)
        if first is None:
            raise SystemExit("Videodan kare okunamadı.")
        bg = downsample(to_gray(first, profile.rotation), profile.processingWidth)[0].astype(np.float32)
        cal = Calibration(bg, profile.diffThreshold, profile.direction, (0.0, 0.0), background_from="gerekmiyor")
        if not fixed_direction:
            d, flow = estimate_direction_linescan(info, profile, window)
            cal.flow = flow
            if d is None:
                cal.notes.append("Akış yönü bulunamadı (hareket çok az); varsayılan kullanıldı: "
                                 + DIRECTION_TR.get(profile.direction, profile.direction) + ".")
            else:
                profile.direction = d
                cal.direction = d
        if profile.productLength <= 0:
            plen = learn_product_length(info, profile, window)
            if plen > 0:
                profile.productLength = plen
            else:
                cal.notes.append("Ürün boyu öğrenilemedi (bant hareketi ya da ürün aralıkları bulunamadı). "
                                 "Alanı ve çizgiyi bandın üstüne koyup tekrar dene.")
        return cal
    bg, th, _ = estimate_background(info, profile, window, bg_range=bg_range, percentile=bg_percentile)
    if threshold is not None:                    # elle: hareketli zemin (merdane) gürültüsü eşiği şişirdiğinde
        th = threshold
    cal = Calibration(bg, th, profile.direction, (0.0, 0.0))
    if bg_range:
        cal.background_from = f"aralık {bg_range[0]:.1f}-{bg_range[1]:.1f} sn"
    if bg_percentile != 50:
        cal.background_from += f", %{bg_percentile:g} yüzdelik"
    profile.diffThreshold = th
    if not fixed_direction:
        d, flow = estimate_direction(info, profile, bg, th, window)
        cal.flow = flow
        if d is None:
            cal.notes.append("Akış yönü bulunamadı (hareket çok az); varsayılan kullanıldı: "
                             + DIRECTION_TR.get(profile.direction, profile.direction) + ".")
        else:
            profile.direction = d
            cal.direction = d
    if not fixed_area:
        area, n, mixed = estimate_expected_area(info, profile, bg, window)
        cal.expected_area, cal.area_samples = area, n
        if mixed:
            # Not hem masaüstünde hem web panelinde gösterilir: komut satırına özgü ipucu burada yok
            cal.notes.append("Leke boyları çok değişken (bitişik ürünler ya da farklı boylar). Tek ürün alanı "
                             "alt kümeden alındı; sayım şüpheliyse ürünlerin tek tek geçtiği bir videoyla ayrıca "
                             "kalibre et.")
        if area > 0:
            profile.expectedArea = area
        else:
            cal.notes.append(f"Tek ürün alanı öğrenilemedi (çizgiyi geçen {n} leke); bitişik ürün ayırma kapalı.")
    return cal


# ---------------------------------------------------------------- çizim

def split_numbers(numbers: dict[int, list[int]], splits: list[tuple[int, int, int]]) -> None:
    """Yapışık lekeden ayrılan ürün kendi numarasını alır (ebeveynin son numaraları çocuğa geçer)."""
    for parent, child, counted in splits:
        ns = numbers.get(parent)
        if not ns or counted <= 0:
            continue
        k = min(counted, len(ns))
        numbers[child] = ns[-k:]
        rest = ns[:-k]
        if rest:
            numbers[parent] = rest
        else:
            numbers.pop(parent, None)


def number_label(ns: list[int]) -> str:
    """Ürün üstündeki yazı: tek ürün "34"; yapışık ürünler "34·35"; çok sayıda "34…40"."""
    if len(ns) <= 3:
        return "·".join(str(n) for n in ns)
    return f"{ns[0]}…{ns[-1]}"


def _hex_id(i: int) -> str:
    return f"{(i * 2654435761) & 0xFFFF:04X}"  # kısa, ardışık id'lerde bile ayırt edilebilir


def draw(frame: np.ndarray, profile: Profile, r: FrameResult, flash: float,
         labels: dict[int, str] | None = None) -> np.ndarray:
    h, w = frame.shape[:2]
    s = max(1.0, w / 960)                       # çizgi kalınlıkları çözünürlükle ölçeklensin
    th = max(1, round(2 * s))
    roi = profile.roi
    x0, y0 = int(roi.x * w), int(roi.y * h)
    x1, y1 = int((roi.x + roi.width) * w), int((roi.y + roi.height) * h)
    shade = frame.copy()
    shade[:] = (0, 0, 0)
    mask = ~profile_mask(profile, w, h)
    frame[mask] = cv2.addWeighted(frame, 0.65, shade, 0.35, 0)[mask]
    if profile.roiPolygon:
        pts = np.array([[int(x * w), int(y * h)] for x, y in profile.roiPolygon], np.int32)
        cv2.polylines(frame, [pts], True, YELLOW, th)
    else:
        cv2.rectangle(frame, (x0, y0), (x1, y1), YELLOW, th)
    if profile.countLine:                       # §4.8 açılı çizgi + akış oku (a→b'nin sağ eli)
        (ax, ay), (bx, by) = profile.countLine
        pa, pb = (int(ax * w), int(ay * h)), (int(bx * w), int(by * h))
        cv2.line(frame, pa, pb, ORANGE, th * 2, cv2.LINE_AA)
        dx, dy = pb[0] - pa[0], pb[1] - pa[1]
        ln = max(1.0, math.hypot(dx, dy))
        mid = ((pa[0] + pb[0]) // 2, (pa[1] + pb[1]) // 2)
        tip = (int(mid[0] - dy / ln * 40 * s), int(mid[1] + dx / ln * 40 * s))
        cv2.arrowedLine(frame, mid, tip, ORANGE, th * 2, cv2.LINE_AA, tipLength=0.35)
    elif profile.vertical:
        ly = int(profile.linePosition * h)
        cv2.line(frame, (x0, ly), (x1, ly), ORANGE, th * 2)
    else:
        lx = int(profile.linePosition * w)
        cv2.line(frame, (lx, y0), (lx, y1), ORANGE, th * 2)
    for b in r.blobs:
        bx, by, bw, bh = b.bbox
        p0, p1 = (int(bx * w), int(by * h)), (int((bx + bw) * w), int((by + bh) * h))
        cv2.rectangle(frame, p0, p1, GREEN, th)
        if b.multiplicity > 1:
            cv2.putText(frame, f"x{b.multiplicity}", (p0[0], max(12, p0[1] - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6 * s, GREEN, th, cv2.LINE_AA)
    for t in r.tracks:
        c = (int(t.x * w), int(t.y * h))
        label = (labels or {}).get(t.id)
        if label:                                # sayılan ürünün üstünde sayım sıra numarası (iPhone ile aynı)
            scale = 0.6 * s
            (tw, tht), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX, scale, max(1, th))
            rad = max(tht, tw // 2) // 2 + int(10 * s)
            cv2.circle(frame, c, rad, CYAN, -1, cv2.LINE_AA)
            cv2.putText(frame, label, (c[0] - tw // 2, c[1] + tht // 2), cv2.FONT_HERSHEY_DUPLEX, scale,
                        (20, 20, 20), max(1, th), cv2.LINE_AA)
        else:
            cv2.circle(frame, c, max(3, round(5 * s)), CYAN if t.counted else WHITE, -1, cv2.LINE_AA)
    # sayaç kutusu; yeni sayımda kısa süre yeşil yanar
    box = (0, 160, 0) if flash > 0 else (30, 30, 30)
    cv2.rectangle(frame, (0, 0), (int(330 * s), int(70 * s)), box, -1)
    cv2.putText(frame, f"{r.total}", (int(12 * s), int(54 * s)), cv2.FONT_HERSHEY_DUPLEX, 1.7 * s, WHITE,
                max(2, th), cv2.LINE_AA)
    cv2.putText(frame, f"adet  {profile.direction}  t={r.ts:5.1f}s", (int(140 * s), int(44 * s)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55 * s, WHITE, 1, cv2.LINE_AA)
    return frame


# ---------------------------------------------------------------- sayım geçişi

@dataclass
class RunResult:
    total: int
    per_minute: dict[int, int]
    events: list[tuple[float, int, int, int]]   # (zaman, iz, delta, toplam)
    frames: int
    seconds: float
    product_length: float = 0.0                  # şerit tarama: öğrenilen ürün boyu (ROI akış uzunluğuna oranla)
    total_out: int = 0                           # tanıma: çıkış sayısı (total = giriş)
    per_minute_out: dict[int, int] = field(default_factory=dict)
    crossings: list[tuple[float, int, str, int, int]] = field(default_factory=list)  # (zaman, iz, yön, giriş, çıkış)


def count(info: VideoInfo, profile: Profile, cal: Calibration, out_path: pathlib.Path | None,
          out_width: int, progress: bool | Callable[[float, int], None] = True,
          start: float = 0.0, end: float | None = None) -> RunResult:
    """`progress`: True → konsola yüzde; fonksiyon → (0–1 oran, anlık sayı) ile çağrılır (analiz sunucusu)."""
    if profile.countMode == "detect":
        return count_detect(info, profile, out_path, out_width, progress, start, end)
    pipe = Pipeline(profile)
    pipe.segmenter.bg = cal.background.copy()
    writer = None
    per_minute: dict[int, int] = {}
    events: list[tuple[float, int, int, int]] = []
    flash = 0.0
    t0 = time.perf_counter()
    n = 0
    numbers: dict[int, list[int]] = {}            # iz → bu izde sayılan ürünlerin sıra numaraları
    last_t = 0.0
    for k, t, frame in read_frames(info, start, end):
        last_t = t
        r = pipe.process(frame, t)
        split_numbers(numbers, pipe.tracker.last_splits)
        running = pipe.total - sum(e.delta for e in r.counts)
        for e in r.counts:
            numbers.setdefault(e.track_id, []).extend(range(running + 1, running + e.delta + 1))
            running += e.delta
        live = {m.id for m in r.tracks}
        numbers = {tid: ns for tid, ns in numbers.items() if tid in live}
        labels = {tid: number_label(ns) for tid, ns in numbers.items()}
        for e in r.counts:
            per_minute[int(t // 60)] = per_minute.get(int(t // 60), 0) + e.delta
            events.append((round(t, 3), e.track_id, e.delta, pipe.total))
            flash = 0.25
        if out_path is not None:
            img = frame
            if profile.rotation in (90, 180, 270):
                img = cv2.rotate(img, {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
                                       270: cv2.ROTATE_90_COUNTERCLOCKWISE}[profile.rotation])
            img = draw(img.copy(), profile, r, flash, labels)
            if img.shape[1] > out_width:
                img = cv2.resize(img, (out_width, round(img.shape[0] * out_width / img.shape[1])),
                                 interpolation=cv2.INTER_AREA)
            if writer is None:
                writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), info.fps,
                                         (img.shape[1], img.shape[0]))
            writer.write(img)
        flash = max(0.0, flash - 1 / info.fps)
        n += 1
        if progress and info.frames and k % max(1, info.frames // 20) == 0:
            if callable(progress):
                progress(min(1.0, k / info.frames), pipe.total)
            else:
                print(f"\r  işleniyor %{100 * k // max(1, info.frames):3d}  sayı={pipe.total}", end="", flush=True)
    if writer is not None:
        writer.release()
    for e in pipe.finish(last_t):               # §4.9: son karede çizgiye yarım binmiş ürünler
        per_minute[int(last_t // 60)] = per_minute.get(int(last_t // 60), 0) + e.delta
        events.append((round(last_t, 3), e.track_id, e.delta, pipe.total))
    if callable(progress):
        progress(1.0, pipe.total)
    elif progress:
        print(f"\r  işleniyor %100  sayı={pipe.total}          ")
    return RunResult(pipe.total, per_minute, events, n, time.perf_counter() - t0, pipe.linescan.product_length)


def _rotated(img: np.ndarray, rotation: int) -> np.ndarray:
    if rotation in (90, 180, 270):
        return cv2.rotate(img, {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
                                270: cv2.ROTATE_90_COUNTERCLOCKWISE}[rotation])
    return img


def count_detect(info: VideoInfo, profile: Profile, out_path: pathlib.Path | None, out_width: int,
                 progress: bool | Callable[[float, int], None] = True, start: float = 0.0,
                 end: float | None = None) -> RunResult:
    """§4.10 iki yönlü geçiş: `total` giriş, `total_out` çıkış. Sayılan kişinin kutusunda "G3"/"Ç2" yazar."""
    pipe = Pipeline(profile)
    writer = None
    per_min: dict[int, int] = {}
    per_min_out: dict[int, int] = {}
    crossings: list[tuple[float, int, str, int, int]] = []
    labels: dict[int, str] = {}
    flash, flash_in = 0.0, True
    t0 = time.perf_counter()
    n = 0
    span = ((min(end, info.duration) if end is not None else info.duration) - start) or 1.0
    for _, t, frame in read_frames(info, start, end):
        r = pipe.process(frame, t)
        n_in = pipe.total - len(r.counts)
        n_out = pipe.total_out - len(r.counts_out)
        for e in r.counts:
            n_in += 1
            labels[e.track_id] = f"G{n_in}"
            per_min[int(t // 60)] = per_min.get(int(t // 60), 0) + 1
            crossings.append((round(t, 3), e.track_id, "giris", n_in, n_out))
            flash, flash_in = 0.35, True
        for e in r.counts_out:
            n_out += 1
            labels[e.track_id] = f"Ç{n_out}"
            per_min_out[int(t // 60)] = per_min_out.get(int(t // 60), 0) + 1
            crossings.append((round(t, 3), e.track_id, "cikis", pipe.total, n_out))
            flash, flash_in = 0.35, False
        alive = {tr.id for tr in pipe.detect.tracker.tracks}
        labels = {i: lab for i, lab in labels.items() if i in alive}
        if out_path is not None:
            img = draw_detect(_rotated(frame, profile.rotation).copy(), profile, r.detect, pipe.total,
                              pipe.total_out, t, flash, flash_in, labels)
            if img.shape[1] > out_width:
                img = cv2.resize(img, (out_width, round(img.shape[0] * out_width / img.shape[1])),
                                 interpolation=cv2.INTER_AREA)
            if writer is None:
                writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), info.fps,
                                         (img.shape[1], img.shape[0]))
            writer.write(img)
        flash = max(0.0, flash - 1 / info.fps)
        n += 1
        if progress and n % max(1, int(info.fps * 2)) == 0:
            frac = min(1.0, (t - start) / span)
            if callable(progress):
                progress(frac, pipe.total)
            else:
                print(f"\r  işleniyor %{int(100 * frac):3d}  giriş={pipe.total}  çıkış={pipe.total_out}",
                      end="", flush=True)
    if writer is not None:
        writer.release()
    if callable(progress):
        progress(1.0, pipe.total)
    elif progress:
        print(f"\r  işleniyor %100  giriş={pipe.total}  çıkış={pipe.total_out}          ")
    return RunResult(pipe.total, per_min, [(c[0], c[1], 1, c[3]) for c in crossings if c[2] == "giris"], n,
                     time.perf_counter() - t0, total_out=pipe.total_out, per_minute_out=per_min_out,
                     crossings=crossings)


# ---------------------------------------------------------------- CLI

def build_profile(a: argparse.Namespace) -> Profile:
    if a.profile:
        p = Profile.from_dict(json.loads(pathlib.Path(a.profile).read_text(encoding="utf-8")))
    else:
        p = PRESETS[a.preset]()
        p.name = f"Video: {pathlib.Path(a.video).stem}"[:80]
    if a.roi:
        x, y, w, h = (float(v) for v in a.roi.split(","))
        p.roi = Roi(x, y, w, h)
    if a.count_line:
        vals = [float(v) for v in a.count_line.split(",")]
        if len(vals) != 4 or not all(0 <= v <= 1 for v in vals):
            raise SystemExit("--count-line biçimi: ax,ay,bx,by (0-1)")
        p.countLine = ((vals[0], vals[1]), (vals[2], vals[3]))
        # uyumluluk: direction akışa en yakın eksen (§4.8); yön tahmini atlanır
        p.direction = nearest_direction(p.countLine[0], p.countLine[1], 1.0)
    if a.roi_polygon:
        pts = [tuple(float(v) for v in pair.split(",")) for pair in a.roi_polygon.split(";") if pair.strip()]
        if any(len(pt) != 2 for pt in pts):
            raise SystemExit("--roi-polygon biçimi: x,y;x,y;x,y (0-1)")
        try:
            p.set_polygon([(pt[0], pt[1]) for pt in pts])
        except ValueError as e:
            raise SystemExit(f"--roi-polygon: {e}") from e
    if a.line is not None:
        p.linePosition = a.line
    if a.direction:
        p.direction = a.direction
    if a.rotation is not None:
        p.rotation = a.rotation
    if a.width:
        p.processingWidth = a.width
    if a.expected_area is not None:
        p.expectedArea = a.expected_area
    if a.mode:
        p.countMode = a.mode
    if a.product_length is not None:
        p.productLength = a.product_length
    if a.classes:
        names: list[str] = []
        for c in a.classes.split(","):
            names += GROUPS.get(c.strip(), [c.strip()])
        bad = [c for c in names if c not in CLASS_IDS]
        if bad:
            raise SystemExit(f"--classes: bilinmeyen sınıf {bad}; seçenekler: {sorted(GROUPS)} ya da {sorted(CLASS_IDS)}")
        p.detectClasses = names
    if a.anchor:
        p.countAnchor = a.anchor
    if a.conf is not None:
        p.detectConfidence = a.conf
    if p.countMode == "detect" and not p.detectClasses:
        raise SystemExit("Tanıma modu için sınıf gerekli: --classes people")
    if p.countMode == "linescan" and p.countLine is not None:
        raise SystemExit("Şerit tarama açılı çizgiyle çalışmaz; düz çizgi (--line, --direction) kullan.")
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bantvision.video", description=__doc__.split("\n\n")[0])
    ap.add_argument("video")
    ap.add_argument("--out", help="çıktı klasörü (varsayılan: <video>_analiz/)")
    ap.add_argument("--truth", type=int, help="elle sayılan doğru adet; hata yüzdesi raporlanır")
    ap.add_argument("--preset", choices=sorted(PRESETS), default="generic")
    ap.add_argument("--profile", help="başlangıç profili (contracts/product-profile.schema.json)")
    ap.add_argument("--direction", choices=["down", "up", "right", "left"], help="vermezsen otomatik bulunur")
    ap.add_argument("--roi", help="x,y,genişlik,yükseklik (0-1), ör. 0.1,0.2,0.8,0.6")
    ap.add_argument("--count-line", help="açılı sayım çizgisi ax,ay,bx,by (0-1); akış a→b'nin sağ eli")
    ap.add_argument("--roi-polygon", help="çokgen ROI köşeleri (0-1), ör. 0.3,0.05;0.8,0.05;0.65,0.95;0.1,0.95")
    ap.add_argument("--line", type=float, help="sayım çizgisi konumu (0-1, akış ekseninde)")
    ap.add_argument("--rotation", type=int, choices=[0, 90, 180, 270])
    ap.add_argument("--width", type=int, help="işleme genişliği (px), ör. 160/240/360")
    ap.add_argument("--expected-area", type=float, help="tek ürün alanı (vermezsen otomatik öğrenilir)")
    ap.add_argument("--mode", choices=["blob", "linescan", "detect"],
                    help="sayım yöntemi: blob = ayrık ürünler (arka plan farkı), linescan = şerit tarama (tek sıra "
                         "bitişik torba/koli; boş bant gerekmez), detect = nesne tanıma (kişi/araç/hayvan; iki yönlü "
                         "giriş/çıkış). Varsayılan: hazır profilden")
    ap.add_argument("--classes", help="tanıma: people | vehicle | animal ya da sınıf listesi (person,car,...)")
    ap.add_argument("--anchor", choices=["center", "bottom"],
                    help="tanıma: çizgiye göre konum noktası; tepeden kamera center, yatık kamera bottom (ayak)")
    ap.add_argument("--conf", type=float, help="tanıma: yeni iz başlatan en düşük güven (0-1)")
    ap.add_argument("--start", type=float, default=0.0, help="videonun bu saniyesinden başla")
    ap.add_argument("--end", type=float, help="videonun bu saniyesinde bitir")
    ap.add_argument("--truth-out", type=int, help="tanıma: elle sayılan doğru çıkış adedi")
    ap.add_argument("--product-length", type=float,
                    help="şerit tarama: tek ürün boyu, ROI'nin akış uzunluğuna oranla (vermezsen otomatik öğrenilir)")
    ap.add_argument("--bg-range", help="boş bandın göründüğü aralık (sn), ör. 0,1.5; bant çok doluysa gerekli")
    ap.add_argument("--bg-percentile", type=float, default=50.0,
                    help="bant hiç boşalmıyorsa arka plan yüzdeliği: ürün banttan parlak → 15, koyu → 85 (varsayılan 50)")
    ap.add_argument("--threshold", type=int,
                    help="arka plan fark eşiği (5-120); vermezsen gürültüden otomatik (hareketli zeminde yüksek çıkabilir)")
    ap.add_argument("--calib-seconds", type=float, default=30.0, help="kalibrasyonda kullanılacak ilk N saniye")
    ap.add_argument("--out-width", type=int, default=960, help="işaretli videonun genişliği")
    ap.add_argument("--no-video", action="store_true", help="işaretli video yazma (daha hızlı)")
    ap.add_argument("--progress-json", action="store_true",
                    help="makinece okunur ilerleme: stdout'a JSON satırları (stage/progress; analiz sunucusu)")
    a = ap.parse_args(argv)

    def emit(**kw: object) -> None:
        if a.progress_json:
            print(json.dumps(kw), flush=True)

    src = pathlib.Path(a.video)
    info = probe(src)
    out_dir = pathlib.Path(a.out) if a.out else src.with_name(src.stem + "_analiz")
    out_dir.mkdir(parents=True, exist_ok=True)
    profile = build_profile(a)

    print(f"Video: {src.name}  {info.width}x{info.height}  {info.fps:.1f} fps  {info.duration:.1f} sn")
    print("1/2 Kalibrasyon...")
    emit(stage="calibrating", seconds=round(info.duration, 2), fps=info.fps, width=info.width, height=info.height)
    bg_range = tuple(float(v) for v in a.bg_range.split(",")) if a.bg_range else None
    cal = calibrate(info, profile, a.calib_seconds, fixed_direction=bool(a.direction) or profile.countLine is not None,
                    fixed_area=a.expected_area is not None or profile.expectedArea > 0,
                    bg_range=bg_range, bg_percentile=a.bg_percentile, threshold=a.threshold)  # type: ignore[arg-type]
    detect = profile.countMode == "detect"
    if not detect:                               # tanımada görüntü saklanmaz (kişisel veri)
        cv2.imwrite(str(out_dir / "arka_plan.png"), cv2.resize(
            cal.background.astype(np.uint8), (cal.background.shape[1] * 3, cal.background.shape[0] * 3),
            interpolation=cv2.INTER_NEAREST))
    print(f"  yöntem: {MODE_TR.get(profile.countMode, profile.countMode)}")
    if detect:
        print(f"  sınıflar: {', '.join(profile.detectClasses)}  giriş yönü: "
              f"{DIRECTION_TR.get(profile.direction, profile.direction)}  konum noktası: {profile.countAnchor}")
    elif profile.countMode == "linescan":
        print(f"  yön={profile.direction} (akış {cal.flow[0]:+.2f}, {cal.flow[1]:+.2f} px/kare)"
              f"  ürün boyu={profile.productLength:.3f} (alanın akış boyuna oranı)")
    else:
        print(f"  arka plan: {cal.background_from} (bkz. arka_plan.png; boş bant görünmeli)")
        print(f"  eşik={cal.threshold}  yön={profile.direction} (akış dx={cal.flow[0]:+.2f} dy={cal.flow[1]:+.2f})"
              f"  tek ürün alanı={profile.expectedArea:.5f} ({cal.area_samples} örnek)")
    for note in cal.notes:
        print("  ! " + note)
    if any("Leke boyları" in n for n in cal.notes):
        print("    (ayrı kalibrasyon: --profile ile ürünlerin tek tek geçtiği videodan üretilmiş profil.json)")

    print("2/2 Sayım...")
    emit(stage="counting")
    report: bool | Callable[[float, int], None] = (
        (lambda f, n: emit(progress=round(f, 4), count=n)) if a.progress_json else True)
    res = count(info, profile, cal, None if a.no_video else out_dir / "isaretli.mp4", a.out_width, report,
                start=a.start, end=a.end)

    summary = {
        "video": src.name, "fps": info.fps, "seconds": round(info.duration, 2),
        "size": [info.width, info.height], "count": res.total, "truth": a.truth,
        "errorPct": (round(100 * (res.total - a.truth) / a.truth, 2) if a.truth else None),
        "calibration": {"countMode": profile.countMode, "productLength": round(profile.productLength, 4),
                        "threshold": cal.threshold, "direction": profile.direction,
                        "background": cal.background_from,
                        "flow": [round(cal.flow[0], 3), round(cal.flow[1], 3)],
                        "expectedArea": profile.expectedArea, "areaSamples": cal.area_samples,
                        "notes": cal.notes},
        "processingFps": round(res.frames / res.seconds, 1) if res.seconds else None,
    }
    if detect:
        summary.update({"countOut": res.total_out, "truthOut": a.truth_out, "classes": profile.detectClasses,
                        "range": [a.start, a.end]})
    (out_dir / "ozet.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "profil.json").write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    with (out_dir / "sayimlar.csv").open("w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh, delimiter=";")
        if detect:
            wr.writerow(["zaman_sn", "iz", "yon", "giris_toplam", "cikis_toplam"])
            wr.writerows(res.crossings)
        else:
            wr.writerow(["zaman_sn", "iz", "delta", "toplam"])
            wr.writerows(res.events)

    if detect:
        print(f"\nGİRİŞ: {res.total}   ÇIKIŞ: {res.total_out}")
        for name, got, truth in (("giriş", res.total, a.truth), ("çıkış", res.total_out, a.truth_out)):
            if truth:
                print(f"  {name}: doğru {truth}, fark {got - truth:+d}")
        print(f"Çıktılar: {out_dir}" + ("" if a.no_video else "  (isaretli.mp4, ozet.json, profil.json, sayimlar.csv)"))
        return 0

    print(f"\nSAYI: {res.total}", end="")
    if a.truth:
        diff = res.total - a.truth
        print(f"   doğru: {a.truth}   fark: {diff:+d} ({100 * diff / a.truth:+.1f}%)", end="")
    print(f"\nÇıktılar: {out_dir}" + ("" if a.no_video else "  (isaretli.mp4, arka_plan.png, ozet.json, profil.json, sayimlar.csv)"))
    if profile.countMode != "linescan" and (not math.isfinite(profile.expectedArea) or profile.expectedArea == 0):
        print("İpucu: ürünler birbirine değiyorsa --expected-area ile tek ürün alanını elle ver.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
