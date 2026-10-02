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
from collections.abc import Iterator
from dataclasses import dataclass, field

import cv2
import numpy as np

from .core import Pipeline, Profile
from .core.pipeline import FrameResult
from .core.profile import Roi
from .core.segmenter import downsample, roi_mask
from .core.tracker import median


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

PRESETS = {"generic": Profile, "egg": Profile.egg, "flour": Profile.flour_sack}

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
                        bg_range: tuple[float, float] | None = None) -> tuple[np.ndarray, int, list[np.ndarray]]:
    """Arka plan = örnek karelerin piksel medyanı.

    `bg_range` verilirse (videoda boş bandın göründüğü aralık) yalnızca oradan öğrenilir ve eşik canlı
    kalibrasyondaki gibi |kare - arka plan| dağılımından hesaplanır. Verilmezse tüm pencereden öğrenilir:
    ürünler hareket ettiği için her pikselde çoğu örnek bant olur ve medyan ürünleri siler. Bu varsayım
    bant %50'den fazla dolu olduğunda bozulur (bkz. testler); eşik bu yüzden ardışık kare farkından alınır.
    """
    start, end = bg_range if bg_range else (0.0, min(info.duration, window))
    n_avail = max(1, int((end - start) * info.fps))
    step = max(1, n_avail // samples)
    smalls = [downsample(to_gray(f, profile.rotation), profile.processingWidth)[0]
              for _, _, f in read_frames(info, start, end, step)]
    if len(smalls) < (3 if bg_range else 5):
        raise SystemExit("Kalibrasyon için yeterli kare okunamadı (video ya da --bg-range çok kısa).")
    stack = np.stack(smalls).astype(np.float32)
    bg = np.median(stack, axis=0)
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


def calibrate(info: VideoInfo, profile: Profile, window: float, fixed_direction: bool,
              fixed_area: bool, bg_range: tuple[float, float] | None = None) -> Calibration:
    bg, th, _ = estimate_background(info, profile, window, bg_range=bg_range)
    cal = Calibration(bg, th, profile.direction, (0.0, 0.0))
    if bg_range:
        cal.background_from = f"aralık {bg_range[0]:.1f}-{bg_range[1]:.1f} sn"
    profile.diffThreshold = th
    if not fixed_direction:
        d, flow = estimate_direction(info, profile, bg, th, window)
        cal.flow = flow
        if d is None:
            cal.notes.append("Akış yönü bulunamadı (hareket çok az); varsayılan kullanıldı: " + profile.direction)
        else:
            profile.direction = d
            cal.direction = d
    if not fixed_area:
        area, n, mixed = estimate_expected_area(info, profile, bg, window)
        cal.expected_area, cal.area_samples = area, n
        if mixed:
            cal.notes.append("Leke boyları çok değişken (bitişik ürünler ya da farklı boylar). Tek ürün alanı "
                             "alt kümeden alındı; şüphen varsa tek tek geçen ürünlerle ayrı kalibre et (--profile).")
        if area > 0:
            profile.expectedArea = area
        else:
            cal.notes.append(f"Tek ürün alanı öğrenilemedi (çizgiyi geçen {n} leke); bitişik ürün ayırma kapalı.")
    return cal


# ---------------------------------------------------------------- çizim

def _hex_id(i: int) -> str:
    return f"{(i * 2654435761) & 0xFFFF:04X}"  # kısa, ardışık id'lerde bile ayırt edilebilir


def draw(frame: np.ndarray, profile: Profile, r: FrameResult, flash: float) -> np.ndarray:
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
    if profile.vertical:
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
        col = CYAN if t.counted else WHITE
        cv2.circle(frame, c, max(3, round(5 * s)), col, -1, cv2.LINE_AA)
        cv2.putText(frame, _hex_id(t.id), (c[0] + 8, c[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45 * s, col,
                    max(1, th - 1), cv2.LINE_AA)
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


def count(info: VideoInfo, profile: Profile, cal: Calibration, out_path: pathlib.Path | None,
          out_width: int, progress: bool = True) -> RunResult:
    pipe = Pipeline(profile)
    pipe.segmenter.bg = cal.background.copy()
    writer = None
    per_minute: dict[int, int] = {}
    events: list[tuple[float, int, int, int]] = []
    flash = 0.0
    t0 = time.perf_counter()
    n = 0
    for k, t, frame in read_frames(info):
        r = pipe.process(frame, t)
        for e in r.counts:
            per_minute[int(t // 60)] = per_minute.get(int(t // 60), 0) + e.delta
            events.append((round(t, 3), e.track_id, e.delta, pipe.total))
            flash = 0.25
        if out_path is not None:
            img = frame
            if profile.rotation in (90, 180, 270):
                img = cv2.rotate(img, {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
                                       270: cv2.ROTATE_90_COUNTERCLOCKWISE}[profile.rotation])
            img = draw(img.copy(), profile, r, flash)
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
            print(f"\r  işleniyor %{100 * k // max(1, info.frames):3d}  sayı={pipe.total}", end="", flush=True)
    if writer is not None:
        writer.release()
    if progress:
        print(f"\r  işleniyor %100  sayı={pipe.total}          ")
    return RunResult(pipe.total, per_minute, events, n, time.perf_counter() - t0)


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
    ap.add_argument("--roi-polygon", help="çokgen ROI köşeleri (0-1), ör. 0.3,0.05;0.8,0.05;0.65,0.95;0.1,0.95")
    ap.add_argument("--line", type=float, help="sayım çizgisi konumu (0-1, akış ekseninde)")
    ap.add_argument("--rotation", type=int, choices=[0, 90, 180, 270])
    ap.add_argument("--width", type=int, help="işleme genişliği (px), ör. 160/240/360")
    ap.add_argument("--expected-area", type=float, help="tek ürün alanı (vermezsen otomatik öğrenilir)")
    ap.add_argument("--bg-range", help="boş bandın göründüğü aralık (sn), ör. 0,1.5; bant çok doluysa gerekli")
    ap.add_argument("--calib-seconds", type=float, default=30.0, help="kalibrasyonda kullanılacak ilk N saniye")
    ap.add_argument("--out-width", type=int, default=960, help="işaretli videonun genişliği")
    ap.add_argument("--no-video", action="store_true", help="işaretli video yazma (daha hızlı)")
    a = ap.parse_args(argv)

    src = pathlib.Path(a.video)
    info = probe(src)
    out_dir = pathlib.Path(a.out) if a.out else src.with_name(src.stem + "_analiz")
    out_dir.mkdir(parents=True, exist_ok=True)
    profile = build_profile(a)

    print(f"Video: {src.name}  {info.width}x{info.height}  {info.fps:.1f} fps  {info.duration:.1f} sn")
    print("1/2 Kalibrasyon...")
    bg_range = tuple(float(v) for v in a.bg_range.split(",")) if a.bg_range else None
    cal = calibrate(info, profile, a.calib_seconds, fixed_direction=bool(a.direction),
                    fixed_area=a.expected_area is not None or profile.expectedArea > 0,
                    bg_range=bg_range)  # type: ignore[arg-type]
    cv2.imwrite(str(out_dir / "arka_plan.png"), cv2.resize(
        cal.background.astype(np.uint8), (cal.background.shape[1] * 3, cal.background.shape[0] * 3),
        interpolation=cv2.INTER_NEAREST))
    print(f"  arka plan: {cal.background_from} (bkz. arka_plan.png; boş bant görünmeli)")
    print(f"  eşik={cal.threshold}  yön={profile.direction} (akış dx={cal.flow[0]:+.2f} dy={cal.flow[1]:+.2f})"
          f"  tek ürün alanı={profile.expectedArea:.5f} ({cal.area_samples} örnek)")
    for note in cal.notes:
        print("  ! " + note)

    print("2/2 Sayım...")
    res = count(info, profile, cal, None if a.no_video else out_dir / "isaretli.mp4", a.out_width)

    summary = {
        "video": src.name, "fps": info.fps, "seconds": round(info.duration, 2),
        "size": [info.width, info.height], "count": res.total, "truth": a.truth,
        "errorPct": (round(100 * (res.total - a.truth) / a.truth, 2) if a.truth else None),
        "calibration": {"threshold": cal.threshold, "direction": profile.direction,
                        "background": cal.background_from,
                        "flow": [round(cal.flow[0], 3), round(cal.flow[1], 3)],
                        "expectedArea": profile.expectedArea, "areaSamples": cal.area_samples,
                        "notes": cal.notes},
        "processingFps": round(res.frames / res.seconds, 1) if res.seconds else None,
    }
    (out_dir / "ozet.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "profil.json").write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    with (out_dir / "sayimlar.csv").open("w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh, delimiter=";")
        wr.writerow(["zaman_sn", "iz", "delta", "toplam"])
        wr.writerows(res.events)

    print(f"\nSAYI: {res.total}", end="")
    if a.truth:
        diff = res.total - a.truth
        print(f"   doğru: {a.truth}   fark: {diff:+d} ({100 * diff / a.truth:+.1f}%)", end="")
    print(f"\nÇıktılar: {out_dir}" + ("" if a.no_video else "  (isaretli.mp4, arka_plan.png, ozet.json, profil.json, sayimlar.csv)"))
    if not math.isfinite(profile.expectedArea) or profile.expectedArea == 0:
        print("İpucu: ürünler birbirine değiyorsa --expected-area ile tek ürün alanını elle ver.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
