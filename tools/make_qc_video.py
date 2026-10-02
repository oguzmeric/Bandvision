"""Kalite kontrol test videosu: kusurları bilinen yumurtalar, dik kadraj, cevap anahtarıyla.

Kullanım: python tools/make_qc_video.py [--out data/test_videos] [--seed 3]
Gerekli: pip install imageio-ffmpeg pillow

Üretir:
  3_kalite_kontrol.mp4           720×1280, ~49 sn; uygulamanın video moduna doğrudan yüklenir
  3_kalite_kontrol_cevap.md      hangi yumurta ne (sıra, videodaki geçiş anı, durum)
  3_kalite_kontrol_cevap.json

Akış: 3 sn boş bant → 1. bölüm yalnızca iyi yumurtalar (Öğret'te ✓) → 2. bölüm karışık (~%30 kusurlu:
Kırık, Kirli, Kan lekesi, Deforme). Üst ve alt şeritte (yumurta profilinin ROI'si dışında: y < 0,1 ve y > 0,9)
bölüm bilgisi ve "son geçen yumurtanın gerçek durumu" yazar; ROI dışında olduğu için sayımı ve kırpıntıyı
etkilemez. Kalibrasyon gerekmez: yumurtalar tek sıra ve aralıklı.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import subprocess
from dataclasses import dataclass

import cv2
import numpy as np

W, H, FPS = 720, 1280, 30
SPEED = 360.0                      # px/sn
RX, RY = 52.0, 68.0
BELT = 78
TOP_BAND, BOTTOM_BAND = int(0.085 * H), int(0.915 * H)    # ROI (0.1–0.9) dışı
LINE_Y = H / 2                                             # uygulamadaki sayım çizgisi (linePosition 0,5)
EGG_COLORS = [(214, 229, 240), (200, 220, 236), (150, 186, 226), (138, 172, 214)]
DEFECTS = ["Kırık", "Kirli", "Kan lekesi", "Deforme"]
GOOD = "İyi"


@dataclass
class QCEgg:
    no: int
    y0: float
    x: float
    scale_x: float
    scale_y: float
    angle: float
    color: tuple[int, int, int]
    status: str
    seed: int

    def y(self, t: float) -> float:
        return self.y0 + SPEED * t

    @property
    def axes(self) -> tuple[int, int]:
        return int(RX * self.scale_x), int(RY * self.scale_y)

    def crossing_time(self) -> float:
        return (LINE_Y - self.y0) / SPEED


def plan(seed: int, n_good_first: int, n_mixed: int, lead_s: float) -> list[QCEgg]:
    rng = random.Random(seed)
    # 2. bölüm: kusurlar eşit dağılımlı, yerleri rastgele
    n_def = round(n_mixed * 0.3)
    mixed = [DEFECTS[i % len(DEFECTS)] for i in range(n_def)] + [GOOD] * (n_mixed - n_def)
    rng.shuffle(mixed)
    statuses = [GOOD] * n_good_first + mixed
    eggs: list[QCEgg] = []
    head = -RY * 1.3 - SPEED * lead_s
    for i, st in enumerate(statuses):
        s = rng.uniform(0.94, 1.06)
        sx, sy = s, s
        if st == "Deforme":                      # küçük ve uzamış
            sx, sy = s * 0.72, s * 0.95
        eggs.append(QCEgg(no=i + 1, y0=head - RY * sy, x=W / 2 + rng.uniform(-40, 40), scale_x=sx, scale_y=sy,
                          angle=rng.uniform(-12, 12), color=rng.choice(EGG_COLORS), status=st,
                          seed=rng.randrange(1 << 30)))
        head -= 2 * RY * sy + 2 * RY * rng.uniform(1.25, 1.8)
    return eggs


# ---------------------------------------------------------------- çizim

def belt_base(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    belt = np.full((H, W), float(BELT), np.float32) + rng.normal(0, 2.0, (H, W)).astype(np.float32)
    img = np.repeat(np.clip(belt, 0, 255).astype(np.uint8)[..., None], 3, axis=2)
    img[:, :14] = (150, 150, 155)
    img[:, W - 14:] = (150, 150, 155)
    return img


def draw_egg(img: np.ndarray, e: QCEgg, yc: float) -> None:
    ax = e.axes
    c = (round(e.x), round(yc))
    if c[1] + ax[1] * 1.3 < 0 or c[1] - ax[1] * 1.3 > H:
        return
    cv2.ellipse(img, (c[0] + 7, c[1] + 9), ax, e.angle, 0, 360, (30, 30, 32), -1, cv2.LINE_AA)
    base = np.array(e.color, np.float32)
    for i in range(6):
        f = 1 - i / 6
        col = tuple(int(v) for v in np.clip(base * (0.80 + 0.20 * (1 - f)), 0, 255))
        cv2.ellipse(img, (c[0] - i, c[1] - i), (max(2, int(ax[0] * f)), max(2, int(ax[1] * f))), e.angle,
                    0, 360, col, -1, cv2.LINE_AA)
    cv2.ellipse(img, (int(c[0] - ax[0] * 0.35), int(c[1] - ax[1] * 0.45)),
                (int(ax[0] * 0.22), int(ax[1] * 0.14)), e.angle - 30, 0, 360, (250, 252, 255), -1, cv2.LINE_AA)
    if e.status in (GOOD, "Deforme"):
        return
    # Kusuru yalnızca yumurtanın içine çiz: yerel katman + elips maskesi
    pad = 4
    x0, y0 = max(0, c[0] - ax[0] - pad), max(0, c[1] - ax[1] - pad)
    x1, y1 = min(W, c[0] + ax[0] + pad), min(H, c[1] + ax[1] + pad)
    if x1 <= x0 or y1 <= y0:
        return
    roi = img[y0:y1, x0:x1]
    layer = roi.copy()
    mask = np.zeros(roi.shape[:2], np.uint8)
    lc = (c[0] - x0, c[1] - y0)
    cv2.ellipse(mask, lc, (ax[0] - 3, ax[1] - 3), e.angle, 0, 360, 255, -1, cv2.LINE_AA)
    rng = random.Random(e.seed)
    if e.status == "Kırık":
        for _ in range(2):                                   # dallanan çatlak
            px, py = lc[0] + rng.uniform(-ax[0] * 0.5, ax[0] * 0.5), lc[1] - ax[1] * rng.uniform(0.5, 0.8)
            pts = [(px, py)]
            for _ in range(7):
                px += rng.uniform(-14, 14)
                py += rng.uniform(10, 22)
                pts.append((px, py))
            cv2.polylines(layer, [np.array(pts, np.int32)], False, (55, 60, 70), 3, cv2.LINE_AA)
        cv2.ellipse(layer, (int(lc[0] + ax[0] * 0.3), int(lc[1] + ax[1] * 0.2)), (9, 6), 30, 0, 360,
                    (95, 105, 120), -1, cv2.LINE_AA)        # küçük ezik
    elif e.status == "Kirli":
        for _ in range(rng.randint(4, 6)):
            cx = lc[0] + rng.uniform(-ax[0] * 0.6, ax[0] * 0.6)
            cy = lc[1] + rng.uniform(-ax[1] * 0.6, ax[1] * 0.6)
            cv2.ellipse(layer, (int(cx), int(cy)), (rng.randint(6, 14), rng.randint(4, 10)), rng.uniform(0, 180),
                        0, 360, (45, 75, 110), -1, cv2.LINE_AA)
    elif e.status == "Kan lekesi":
        cx = lc[0] + rng.uniform(-ax[0] * 0.3, ax[0] * 0.3)
        cy = lc[1] + rng.uniform(-ax[1] * 0.3, ax[1] * 0.3)
        cv2.circle(layer, (int(cx), int(cy)), int(ax[0] * 0.24), (35, 30, 120), -1, cv2.LINE_AA)
        cv2.circle(layer, (int(cx + 4), int(cy - 3)), int(ax[0] * 0.12), (25, 20, 90), -1, cv2.LINE_AA)
    roi[mask > 0] = layer[mask > 0]


class Banners:
    def __init__(self) -> None:
        from PIL import ImageFont
        fonts = pathlib.Path("C:/Windows/Fonts")
        try:
            self.font = ImageFont.truetype(str(fonts / "segoeuib.ttf"), 34)
            self.small = ImageFont.truetype(str(fonts / "segoeui.ttf"), 26)
        except OSError:
            self.font = self.small = ImageFont.load_default()

    def draw(self, img: np.ndarray, top: str, top2: str, bottom: str, bottom_color: tuple[int, int, int]) -> None:
        from PIL import Image, ImageDraw
        img[:TOP_BAND] = (32, 30, 28)
        img[BOTTOM_BAND:] = (32, 30, 28)
        pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        d = ImageDraw.Draw(pil)
        d.text((24, 12), top, font=self.font, fill=(255, 220, 120))
        d.text((24, 58), top2, font=self.small, fill=(220, 220, 220))
        d.text((24, BOTTOM_BAND + 30), bottom, font=self.font, fill=bottom_color)
        img[:] = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/test_videos")
    ap.add_argument("--seed", type=int, default=3)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    lead = 3.0
    eggs = plan(a.seed, n_good_first=10, n_mixed=34, lead_s=lead)
    first_mixed = eggs[10].crossing_time() - 1.5
    seconds = max((H + RY * 1.3 - e.y0) / SPEED for e in eggs) + 1.0
    crossings = sorted((e.crossing_time(), e) for e in eggs)

    import imageio_ffmpeg
    path = out / "3_kalite_kontrol.mp4"
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-crf", "18", "-preset", "medium", "-movflags", "+faststart", str(path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    base = belt_base(a.seed)
    banners = Banners()
    colors = {GOOD: (120, 220, 120), "Kırık": (255, 110, 110), "Kirli": (255, 170, 90),
              "Kan lekesi": (255, 90, 120), "Deforme": (200, 150, 255)}
    for k in range(int(seconds * FPS)):
        t = k / FPS
        img = base.copy()
        for e in eggs:
            draw_egg(img, e, e.y(t))
        if t < lead:
            top, top2 = "Kalite kontrol testi", f"Bant boş · yumurtalar {lead - t:.0f} sn sonra"
        elif t < first_mixed:
            top, top2 = "1. bölüm: yalnızca İYİ yumurtalar", "Öğret sekmesinde bunları İyi olarak işaretle"
        else:
            top, top2 = "2. bölüm: karışık", "Kusurlular: Kırık · Kirli · Kan lekesi · Deforme"
        passed = [e for ct, e in crossings if ct <= t]
        if passed:
            last = passed[-1]
            bottom, bcol = f"Son geçen: #{last.no}  {last.status}", colors[last.status]
        else:
            bottom, bcol = "Son geçen: —", (200, 200, 200)
        banners.draw(img, top, top2, bottom, bcol)
        proc.stdin.write(img.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg başarısız")

    rows = [{"no": e.no, "crossingSec": round(e.crossing_time(), 2), "status": e.status} for e in eggs]
    summary = {s: sum(1 for e in eggs if e.status == s) for s in [GOOD, *DEFECTS]}
    (out / "3_kalite_kontrol_cevap.json").write_text(json.dumps(
        {"seed": a.seed, "seconds": round(seconds, 1), "total": len(eggs), "summary": summary,
         "firstMixedSec": round(first_mixed, 1), "eggs": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# Kalite kontrol test videosu — cevap anahtarı", "",
             f"Toplam **{len(eggs)}** yumurta, {seconds:.0f} sn. "
             + " · ".join(f"{k}: {v}" for k, v in summary.items()), "",
             f"1. bölüm (yalnızca iyi): #1–#10. 2. bölüm (karışık): #11–#{len(eggs)}, ~{first_mixed:.0f}. sn'den itibaren.", "",
             "| # | Çizgiyi geçiş (sn) | Durum |", "|---|---|---|"]
    lines += [f"| {r['no']} | {r['crossingSec']:.1f} | {r['status']} |" for r in rows]
    (out / "3_kalite_kontrol_cevap.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{path.name}: {path.stat().st_size / 1e6:.1f} MB, {seconds:.1f} sn, {len(eggs)} yumurta, {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
