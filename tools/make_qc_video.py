"""Kalite kontrol test videosu: kusurları bilinen ürünler, dik kadraj, cevap anahtarıyla.

Kullanım: python tools/make_qc_video.py [--product egg|box] [--out data/test_videos] [--seed 3]
Gerekli: pip install imageio-ffmpeg pillow

Üretir (yumurta / koli):
  3_kalite_kontrol.mp4        / 4_kalite_kontrol_koli.mp4       720×1280, ~50 sn; video moduna doğrudan yüklenir
  3_kalite_kontrol_cevap.md   / 4_kalite_kontrol_koli_cevap.md  hangi ürün ne (sıra, geçiş anı, durum)
  3_kalite_kontrol_cevap.json / 4_kalite_kontrol_koli_cevap.json

Akış: 3 sn boş bant → 1. bölüm yalnızca iyi ürünler (Öğret'te İyi işaretle) → 2. bölüm karışık (~%30 kusurlu).
Yumurta kusurları: Kırık, Kirli, Kan lekesi, Deforme. Koli kusurları: Etiket yok, Ezik, Yırtık bant, Leke.
Üst ve alt şeritte (yumurta profilinin ROI'si dışında: y < 0,1 ve y > 0,9) bölüm bilgisi ve "son geçen ürünün
gerçek durumu" yazar; ROI dışında olduğu için sayımı ve kırpıntıyı etkilemez. Kalibrasyon gerekmez: ürünler
tek sıra ve aralıklı.
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
RX, RY = 52.0, 68.0                # yumurta yarı eksenleri
BW, BH = 190, 140                  # koli boyutu (px, ölçek 1)
BELT = 78
TOP_BAND, BOTTOM_BAND = int(0.085 * H), int(0.915 * H)    # ROI (0.1–0.9) dışı
LINE_Y = H / 2                                             # uygulamadaki sayım çizgisi (linePosition 0,5)
EGG_COLORS = [(214, 229, 240), (200, 220, 236), (150, 186, 226), (138, 172, 214)]
BOX_COLORS = [(95, 140, 185), (88, 132, 176), (104, 150, 194)]   # karton tonları (BGR)
GOOD = "İyi"
PRODUCTS = {
    "egg": {"noun": "yumurta", "stem": "3_kalite_kontrol",
            "defects": ["Kırık", "Kirli", "Kan lekesi", "Deforme"]},
    "box": {"noun": "koli", "stem": "4_kalite_kontrol_koli",
            "defects": ["Etiket yok", "Ezik", "Yırtık bant", "Leke"]},
}
STATUS_COLORS = {GOOD: (120, 220, 120), "Kırık": (255, 110, 110), "Kirli": (255, 170, 90),
                 "Kan lekesi": (255, 90, 120), "Deforme": (200, 150, 255), "Etiket yok": (255, 110, 110),
                 "Ezik": (255, 170, 90), "Yırtık bant": (255, 90, 120), "Leke": (200, 150, 255)}


@dataclass
class QCItem:
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


def mixed_statuses(rng: random.Random, defects: list[str], n_good_first: int, n_mixed: int) -> list[str]:
    # 2. bölüm: kusurlar eşit dağılımlı, yerleri rastgele
    n_def = round(n_mixed * 0.3)
    mixed = [defects[i % len(defects)] for i in range(n_def)] + [GOOD] * (n_mixed - n_def)
    rng.shuffle(mixed)
    return [GOOD] * n_good_first + mixed


def plan_eggs(seed: int, n_good_first: int, n_mixed: int, lead_s: float) -> list[QCItem]:
    rng = random.Random(seed)
    statuses = mixed_statuses(rng, PRODUCTS["egg"]["defects"], n_good_first, n_mixed)
    items: list[QCItem] = []
    head = -RY * 1.3 - SPEED * lead_s
    for i, st in enumerate(statuses):
        s = rng.uniform(0.94, 1.06)
        sx, sy = s, s
        if st == "Deforme":                      # küçük ve uzamış
            sx, sy = s * 0.72, s * 0.95
        items.append(QCItem(no=i + 1, y0=head - RY * sy, x=W / 2 + rng.uniform(-40, 40), scale_x=sx, scale_y=sy,
                            angle=rng.uniform(-12, 12), color=rng.choice(EGG_COLORS), status=st,
                            seed=rng.randrange(1 << 30)))
        head -= 2 * RY * sy + 2 * RY * rng.uniform(1.25, 1.8)
    return items


def plan_boxes(seed: int, n_good_first: int, n_mixed: int, lead_s: float) -> list[QCItem]:
    rng = random.Random(seed)
    statuses = mixed_statuses(rng, PRODUCTS["box"]["defects"], n_good_first, n_mixed)
    items: list[QCItem] = []
    head = -BH * 0.8 - SPEED * lead_s
    for i, st in enumerate(statuses):
        s = rng.uniform(0.95, 1.05)
        items.append(QCItem(no=i + 1, y0=head - BH * s / 2, x=W / 2 + rng.uniform(-50, 50), scale_x=s, scale_y=s,
                            angle=rng.uniform(-8, 8), color=rng.choice(BOX_COLORS), status=st,
                            seed=rng.randrange(1 << 30)))
        head -= BH * s + BH * rng.uniform(0.9, 1.4)
    return items


# ---------------------------------------------------------------- çizim

def belt_base(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    belt = np.full((H, W), float(BELT), np.float32) + rng.normal(0, 2.0, (H, W)).astype(np.float32)
    img = np.repeat(np.clip(belt, 0, 255).astype(np.uint8)[..., None], 3, axis=2)
    img[:, :14] = (150, 150, 155)
    img[:, W - 14:] = (150, 150, 155)
    return img


def draw_egg(img: np.ndarray, e: QCItem, yc: float) -> None:
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


def box_patch(b: QCItem) -> np.ndarray:
    """Kolinin üstten görünüşü (döndürülmemiş): karton, ortada koli bandı, sol üstte barkodlu etiket."""
    bw, bh = int(BW * b.scale_x), int(BH * b.scale_y)
    rng = random.Random(b.seed)
    base = np.array(b.color, np.float32)
    shade = (0.90 + 0.10 * np.linspace(0, 1, bh))[:, None, None]
    p = np.clip(base[None, None, :] * shade * np.ones((bh, bw, 1), np.float32), 0, 255).astype(np.uint8)
    for _ in range(25):                                    # karton dokusu
        y = rng.randrange(bh)
        cv2.line(p, (0, y), (bw, y), tuple(int(v * 0.96) for v in b.color), 1)
    tx0, tx1 = bw // 2 - 15, bw // 2 + 15                  # koli bandı
    tape = (150, 185, 220)
    if b.status == "Yırtık bant":
        g0, g1 = int(bh * rng.uniform(0.3, 0.4)), int(bh * rng.uniform(0.58, 0.7))
        cv2.rectangle(p, (tx0, 0), (tx1, g0), tape, -1)
        cv2.rectangle(p, (tx0, g1), (tx1, bh), tape, -1)
        for y_edge in (g0, g1):                            # yırtık kenarlar
            pts = [(tx0 + i * 5, y_edge + rng.randint(-6, 6)) for i in range(7)]
            cv2.polylines(p, [np.array(pts, np.int32)], False, (205, 225, 240), 2, cv2.LINE_AA)
        flap = np.array([(tx1, g0), (tx1 + 26, g0 + 12), (tx1 + 6, g0 + 30)], np.int32)   # kalkmış parça
        cv2.fillConvexPoly(p, flap, (195, 215, 235), cv2.LINE_AA)
        cv2.line(p, (tx0 + 4, g0 + 6), (tx1 - 4, g1 - 6), tuple(int(v * 0.7) for v in b.color), 2, cv2.LINE_AA)
    else:
        cv2.rectangle(p, (tx0, 0), (tx1, bh), tape, -1)
    cv2.line(p, (tx0 + 4, 0), (tx0 + 4, bh), (190, 215, 235), 1)       # bant parlaması
    if b.status != "Etiket yok":
        lx0, ly0, lw, lh = 10, 12, int(bw * 0.36), int(bh * 0.38)
        cv2.rectangle(p, (lx0, ly0), (lx0 + lw, ly0 + lh), (245, 245, 245), -1)
        for i in range(3):
            cv2.line(p, (lx0 + 6, ly0 + 8 + i * 7), (lx0 + lw - 10 - i * 8, ly0 + 8 + i * 7), (120, 120, 120), 2)
        x = lx0 + 6
        while x < lx0 + lw - 6:                            # barkod
            wbar = rng.choice((1, 1, 2, 3))
            cv2.rectangle(p, (x, ly0 + lh - 18), (x + wbar - 1, ly0 + lh - 5), (20, 20, 20), -1)
            x += wbar + rng.choice((1, 2))
    if b.status == "Ezik":                                  # bir köşe içe çökmüş
        corner = rng.choice([(bw - 1, bh - 1, -1, -1), (bw - 1, 0, -1, 1), (0, bh - 1, 1, -1)])
        cx, cy, sx, sy = corner
        tri = np.array([(cx, cy), (cx + sx * 60, cy), (cx, cy + sy * 48)], np.int32)
        cv2.fillConvexPoly(p, tri, tuple(int(v * 0.55) for v in b.color), cv2.LINE_AA)
        cv2.line(p, (cx + sx * 60, cy), (cx, cy + sy * 48), tuple(int(v * 0.35) for v in b.color), 3, cv2.LINE_AA)
        cv2.line(p, (cx + sx * 40, cy + sy * 6), (cx + sx * 8, cy + sy * 34), (60, 80, 100), 1, cv2.LINE_AA)
    if b.status == "Leke":                                  # ıslaklık/yağ lekesi
        stain = p.copy()
        cx, cy = int(bw * rng.uniform(0.55, 0.8)), int(bh * rng.uniform(0.45, 0.75))
        for _ in range(5):
            cv2.ellipse(stain, (cx + rng.randint(-14, 14), cy + rng.randint(-10, 10)),
                        (rng.randint(14, 26), rng.randint(10, 20)), rng.uniform(0, 180), 0, 360,
                        tuple(int(v * 0.5) for v in b.color), -1, cv2.LINE_AA)
        p = cv2.addWeighted(stain, 0.75, p, 0.25, 0)
    cv2.rectangle(p, (0, 0), (bw - 1, bh - 1), tuple(int(v * 0.6) for v in b.color), 2)
    return p


_box_cache: dict[int, tuple[np.ndarray, np.ndarray]] = {}


def draw_box(img: np.ndarray, b: QCItem, yc: float) -> None:
    if b.no not in _box_cache:                              # döndürülmüş görüntü + maske bir kez hazırlanır
        p = box_patch(b)
        h, w = p.shape[:2]
        d = int(np.hypot(w, h)) + 4
        canvas = np.zeros((d, d, 3), np.uint8)
        mask = np.zeros((d, d), np.uint8)
        ox, oy = (d - w) // 2, (d - h) // 2
        canvas[oy:oy + h, ox:ox + w] = p
        mask[oy:oy + h, ox:ox + w] = 255
        m = cv2.getRotationMatrix2D((d / 2, d / 2), b.angle, 1.0)
        _box_cache[b.no] = (cv2.warpAffine(canvas, m, (d, d), flags=cv2.INTER_LINEAR),
                            cv2.warpAffine(mask, m, (d, d), flags=cv2.INTER_LINEAR))
    rot, mask = _box_cache[b.no]
    d = rot.shape[0]
    for (dx, dy, layer) in ((8, 10, None), (0, 0, rot)):     # önce gölge, sonra kutu
        x0, y0 = round(b.x - d / 2) + dx, round(yc - d / 2) + dy
        ix0, iy0, ix1, iy1 = max(0, x0), max(0, y0), min(W, x0 + d), min(H, y0 + d)
        if ix1 <= ix0 or iy1 <= iy0:
            return
        a = (mask[iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0].astype(np.float32) / 255)[..., None]
        region = img[iy0:iy1, ix0:ix1].astype(np.float32)
        src = (np.full_like(region, (30, 30, 32)) if layer is None
               else layer[iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0].astype(np.float32))
        img[iy0:iy1, ix0:ix1] = (region * (1 - a) + src * a).astype(np.uint8)


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
    ap.add_argument("--product", choices=sorted(PRODUCTS), default="egg")
    ap.add_argument("--out", default="data/test_videos")
    ap.add_argument("--seed", type=int, default=3)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    spec = PRODUCTS[a.product]
    noun = spec["noun"]

    lead = 3.0
    if a.product == "egg":
        items, draw, half = plan_eggs(a.seed, 10, 34, lead), draw_egg, RY * 1.3
    else:
        items, draw, half = plan_boxes(a.seed, 10, 30, lead), draw_box, BH * 0.8
    first_mixed = items[10].crossing_time() - 1.5
    seconds = max((H + half - it.y0) / SPEED for it in items) + 1.0
    crossings = sorted((it.crossing_time(), it.no, it) for it in items)

    import imageio_ffmpeg
    path = out / f"{spec['stem']}.mp4"
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-crf", "18", "-preset", "medium", "-movflags", "+faststart", str(path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    base = belt_base(a.seed)
    banners = Banners()
    for k in range(int(seconds * FPS)):
        t = k / FPS
        img = base.copy()
        for it in items:
            draw(img, it, it.y(t))
        if t < lead:
            top, top2 = "Kalite kontrol testi", f"Bant boş · {noun}lar {lead - t:.0f} sn sonra"
        elif t < first_mixed:
            top, top2 = f"1. bölüm: yalnızca İYİ {noun}lar", "Öğret sekmesinde bunları İyi olarak işaretle"
        else:
            top, top2 = "2. bölüm: karışık", "Kusurlular: " + " · ".join(spec["defects"])
        passed = [it for ct, _, it in crossings if ct <= t]
        if passed:
            last = passed[-1]
            bottom, bcol = f"Son geçen: #{last.no}  {last.status}", STATUS_COLORS[last.status]
        else:
            bottom, bcol = "Son geçen: —", (200, 200, 200)
        banners.draw(img, top, top2, bottom, bcol)
        proc.stdin.write(img.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg başarısız")

    rows = [{"no": it.no, "crossingSec": round(it.crossing_time(), 2), "status": it.status} for it in items]
    summary = {s: sum(1 for it in items if it.status == s) for s in [GOOD, *spec["defects"]]}
    (out / f"{spec['stem']}_cevap.json").write_text(json.dumps(
        {"product": a.product, "seed": a.seed, "seconds": round(seconds, 1), "total": len(items),
         "summary": summary, "firstMixedSec": round(first_mixed, 1), "items": rows},
        ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# Kalite kontrol test videosu ({noun}) — cevap anahtarı", "",
             f"Toplam **{len(items)}** {noun}, {seconds:.0f} sn. "
             + " · ".join(f"{k}: {v}" for k, v in summary.items()), "",
             (f"1. bölüm (yalnızca iyi): #1–#10. 2. bölüm (karışık): #11–#{len(items)}, "
              f"~{first_mixed:.0f}. sn'den itibaren."), "",
             "| # | Çizgiyi geçiş (sn) | Durum |", "|---|---|---|"]
    lines += [f"| {r['no']} | {r['crossingSec']:.1f} | {r['status']} |" for r in rows]
    (out / f"{spec['stem']}_cevap.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{path.name}: {path.stat().st_size / 1e6:.1f} MB, {seconds:.1f} sn, {len(items)} {noun}, {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
