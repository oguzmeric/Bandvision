"""Ekranda oynatılıp telefonla çekilecek, sayısı bilinen test bandı videoları (masa başı doğruluk testi).

Kullanım: python tools/make_test_video.py [--out data/test_videos] [--count 100] [--seed 7]

Üretir:
  1_kalibrasyon.mp4      boş bant + tek tek geçen 8 yumurta (uygulamada Kalibre akışı için)
  2_test_<N>_yumurta.mp4  N yumurta: çoğu tek, bir kısmı arka arkaya ya da yan yana bitişik
  manifest.json           doğru sayılar, grup düzeni, her yumurtanın ekran ortasını geçtiği an

Bant ekranın ortasında dikeydir, yumurtalar yukarıdan aşağı akar: telefon dik tutulup ekrana doğrultulunca
uygulamada da "aşağı" akış olur. Talimatlar bant dışındaki yan panellerde yazar; ROI yalnızca bandı kapsamalı.
H.264 (yuv420p) yazılır: Windows, iPhone ve tarayıcılarda açılır. Gerekli: pip install imageio-ffmpeg pillow
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import random
import subprocess
from dataclasses import asdict, dataclass

import cv2
import numpy as np

W, H, FPS = 1920, 1080, 30
BELT_X0, BELT_X1 = 710, 1210               # bant sütunu (ROI ≈ x 0.37, genişlik 0.26)
SPEED = 420.0                               # px/sn
RX, RY = 52.0, 68.0                         # yumurta yarı eksenleri (px, ölçek 1)
BG_COLOR = (44, 40, 38)                     # bant dışı (BGR)
BELT_COLOR = 78
EGG_COLORS = [(214, 229, 240), (200, 220, 236), (150, 186, 226), (138, 172, 214)]  # krem/beyaz, açık kahve


@dataclass
class Egg:
    y0: float           # t=0 anında merkez y (negatif: ekran üstü)
    x: float
    scale: float
    angle: float
    color: tuple[int, int, int]
    group: int
    kind: str           # single | pair_vertical | pair_side

    def y(self, t: float) -> float:
        return self.y0 + SPEED * t


# ---------------------------------------------------------------- düzen

def layout(n_single: int, n_vpair: int, n_hpair: int, rng: random.Random, lead_px: float,
           gap_lengths: tuple[float, float]) -> list[Egg]:
    kinds = ["single"] * n_single + ["pair_vertical"] * n_vpair + ["pair_side"] * n_hpair
    rng.shuffle(kinds)
    eggs: list[Egg] = []
    cx = (BELT_X0 + BELT_X1) / 2
    head = -RY * 1.3 - lead_px               # bir sonraki grubun alt ucu (ekran koordinatı, t=0)

    def egg(y: float, x: float, g: int, kind: str) -> Egg:
        return Egg(y, x + rng.uniform(-12, 12), rng.uniform(0.92, 1.08), rng.uniform(-12, 12),
                   rng.choice(EGG_COLORS), g, kind)

    for g, kind in enumerate(kinds):
        if kind == "single":
            eggs.append(egg(head - RY, cx, g, kind))
            length = 2 * RY
        elif kind == "pair_vertical":            # arka arkaya, birbirine değiyor
            eggs.append(egg(head - RY, cx, g, kind))
            eggs.append(egg(head - 3 * RY + 4, cx, g, kind))
            length = 4 * RY - 4
        else:                                     # yan yana, birbirine değiyor
            eggs.append(egg(head - RY, cx - RX + 2, g, kind))
            eggs.append(egg(head - RY, cx + RX - 2, g, kind))
            length = 2 * RY
        head -= length * 1.1 + 2 * RY * rng.uniform(*gap_lengths)
    return eggs


# ---------------------------------------------------------------- çizim

def belt_base(rng: np.random.Generator) -> np.ndarray:
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = BG_COLOR
    belt = np.full((H, BELT_X1 - BELT_X0), float(BELT_COLOR), np.float32)
    belt += rng.normal(0, 2.0, belt.shape).astype(np.float32)          # sabit doku (bant hareket etmiyor gibi)
    img[:, BELT_X0:BELT_X1] = np.clip(belt, 0, 255).astype(np.uint8)[..., None]
    for x in (BELT_X0 - 14, BELT_X1):                                   # yan raylar
        img[:, x:x + 14] = (150, 150, 155)
    return img


def draw_egg(img: np.ndarray, e: Egg, y: float) -> None:
    c = (round(e.x), round(y))
    ax = (int(RX * e.scale), int(RY * e.scale))
    if c[1] + ax[1] * 1.3 < 0 or c[1] - ax[1] * 1.3 > H:
        return
    cv2.ellipse(img, (c[0] + 7, c[1] + 9), ax, e.angle, 0, 360, (30, 30, 32), -1, cv2.LINE_AA)   # gölge
    base = np.array(e.color, np.float32)
    for i in range(6):                                                     # basit gölgelendirme
        f = 1 - i / 6
        col = tuple(int(v) for v in np.clip(base * (0.80 + 0.20 * (1 - f)), 0, 255))
        cv2.ellipse(img, (c[0] - i, c[1] - i), (max(2, int(ax[0] * f)), max(2, int(ax[1] * f))), e.angle,
                    0, 360, col, -1, cv2.LINE_AA)
    hx, hy = int(c[0] - ax[0] * 0.35), int(c[1] - ax[1] * 0.45)           # parlama
    cv2.ellipse(img, (hx, hy), (int(ax[0] * 0.22), int(ax[1] * 0.14)), e.angle - 30, 0, 360,
                (250, 252, 255), -1, cv2.LINE_AA)


class Text:
    def __init__(self) -> None:
        from PIL import ImageFont
        fonts = pathlib.Path("C:/Windows/Fonts")
        try:
            self.big = ImageFont.truetype(str(fonts / "segoeuib.ttf"), 46)
            self.small = ImageFont.truetype(str(fonts / "segoeui.ttf"), 32)
        except OSError:
            self.big = self.small = ImageFont.load_default()

    def panel(self, img: np.ndarray, left: list[str], right: list[str]) -> np.ndarray:
        from PIL import Image, ImageDraw
        pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        d = ImageDraw.Draw(pil)
        for x, lines in ((40, left), (BELT_X1 + 50, right)):
            y = 80
            for i, line in enumerate(lines):
                d.text((x, y), line, font=self.big if i == 0 else self.small, fill=(255, 220, 120) if i == 0
                       else (230, 230, 230))
                y += 70 if i == 0 else 48
        return cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)


# ---------------------------------------------------------------- video

def render(path: pathlib.Path, eggs: list[Egg], seconds: float, captions, seed: int) -> None:
    import imageio_ffmpeg
    base = belt_base(np.random.default_rng(seed))
    text = Text()
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-crf", "18", "-preset", "medium", "-movflags", "+faststart", str(path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    cache: dict[tuple[tuple[str, ...], tuple[str, ...]], np.ndarray] = {}
    for k in range(int(seconds * FPS)):
        t = k / FPS
        left, right = captions(t)
        key = (tuple(left), tuple(right))
        if key not in cache:                      # yazı yalnızca değişince yeniden çizilir
            cache = {key: text.panel(base.copy(), left, right)}
        img = cache[key].copy()
        for e in eggs:
            draw_egg(img, e, e.y(t))
        img[:, :BELT_X0 - 14] = cache[key][:, :BELT_X0 - 14]          # paneller üstüne taşan gölgeyi temizle
        img[:, BELT_X1 + 14:] = cache[key][:, BELT_X1 + 14:]
        proc.stdin.write(img.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg başarısız")


def leave_time(eggs: list[Egg]) -> float:
    return max((H + RY * 1.3 - e.y0) / SPEED for e in eggs)


def crossing_times(eggs: list[Egg]) -> list[float]:
    return sorted(round((H / 2 - e.y0) / SPEED, 3) for e in eggs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/test_videos")
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(a.seed)

    # --- 1) kalibrasyon: 6 sn boş bant, 3 sn geri sayım, 8 tek yumurta (geniş aralıklı)
    empty, countdown = 6.0, 3.0
    calib = layout(8, 0, 0, rng, lead_px=SPEED * (empty + countdown), gap_lengths=(2.2, 2.8))
    calib_end = leave_time(calib) + 3.0

    def calib_captions(t: float) -> tuple[list[str], list[str]]:
        roi = ["Sarı alan (ROI):", "yalnızca gri bandı", "kapsasın, yazıları değil.", "Turuncu çizgi ortada."]
        if t < empty:
            return ["1. BOŞ BANDI ÖĞREN", "Kalibre → ROI'yi ayarla", "→ '1. Boş bandı öğren'", f"({empty - t:3.0f} sn)"], roi
        if t < empty + countdown:
            return ["2. ÖRNEK GEÇİR", "'2. Örnek geçir (8)'e bas", f"Yumurtalar {empty + countdown - t:.0f} sn sonra"], roi
        if t < calib_end - 3.0:
            return ["2. ÖRNEK GEÇİR", "8 yumurta tek tek geçiyor", "Telefonu oynatma"], roi
        return ["3. KAYDET", "Kalibrasyon bitti.", "'Kaydet'e bas, sonra", "2_test videosunu aç."], roi

    render(out / "1_kalibrasyon.mp4", calib, calib_end, calib_captions, a.seed)

    # --- 2) test: N yumurta; %70 tek, %20 arka arkaya çift, %10 yan yana çift
    n_v = round(a.count * 0.10)
    n_h = round(a.count * 0.05)
    n_s = a.count - 2 * (n_v + n_h)
    lead = 6.0
    test = layout(n_s, n_v, n_h, rng, lead_px=SPEED * lead, gap_lengths=(0.9, 1.6))
    assert len(test) == a.count
    run_end = leave_time(test)
    total = run_end + 3.0 + 6.0

    def test_captions(t: float) -> tuple[list[str], list[str]]:
        if t < lead:
            return ["HAZIRLIK", "Sıfırla → Başlat", f"Yumurtalar {lead - t:.0f} sn sonra"], \
                   ["Bu videoda", f"{a.count} yumurta var.", "Bir kısmı birbirine", "değerek geçer."]
        if t < run_end + 3.0:
            m, s = divmod(int(t - lead), 60)
            return ["SAYIM SÜRÜYOR", f"geçen süre {m}:{s:02d}"], ["Telefonu", "oynatma."]
        return ["BİTTİ", "Doğru sayı:", f"{a.count} yumurta"], ["Uygulamadaki", "sayıyı not et.",
                                                                  f"Doğruluk = sayı / {a.count}"]

    name = f"2_test_{a.count}_yumurta.mp4"
    render(out / name, test, total, test_captions, a.seed + 1)

    groups: dict[int, str] = {e.group: e.kind for e in test}
    manifest = {
        "seed": a.seed, "fps": FPS, "size": [W, H], "beltSpeedPxPerSec": SPEED,
        "roiHint": {"x": round((BELT_X0 - 10) / W, 3), "y": 0.05, "width": round((BELT_X1 - BELT_X0 + 20) / W, 3),
                    "height": 0.9},
        "videos": {
            "1_kalibrasyon.mp4": {"eggs": len(calib), "seconds": round(calib_end, 1),
                                  "emptyBeltSeconds": [0, empty]},
            name: {"eggs": len(test), "seconds": round(total, 1),
                   "groups": {k: sum(1 for v in groups.values() if v == k)
                              for k in ("single", "pair_vertical", "pair_side")},
                   "midlineCrossingsSec": crossing_times(test)},
        },
        "eggsDetail": [asdict(e) for e in test],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    for f in sorted(out.glob("*.mp4")):
        print(f"{f.name}: {f.stat().st_size / 1e6:.1f} MB")
    print(f"Test videosu: {a.count} yumurta, {math.ceil(total)} sn")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
