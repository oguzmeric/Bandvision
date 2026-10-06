"""iOS ↔ Python eşdeğerliği: personel rengi (§4.10 eki).

Kullanım: python tools/make_staff_fixture.py [--check]
Üretir: apps/ios/BantSayacTests/staff_parity.json — renk çevirisi, ızgara noktaları, kare oyu, öğretme (baskın renk),
izleyicide personel kararı ve küçük sentetik karelerde giriş noktaları: `voteFrames` (vote_bgr ↔ StaffColor.vote:
komşu kutu dışlama, küçük kutu) ve `teachFrames` (teach_bgr ↔ StaffColor.teach: iç içe kutular, kenarda kırpılan
kare, karanlık). Girdiler sabit tohumlu; Lab 6 ondalık (Swift testi 1e-4 toleransla karşılaştırır).
Eşiğe 1e-3'ten yakın oy durumları ve baskın renk kutucuk sınırına yakın öğretme durumları üretilmez (iki dilde son
basamak farkı kararı değiştirmesin).
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "apps" / "ios" / "BantSayacTests" / "staff_parity.json"
sys.path.insert(0, str(ROOT / "services" / "edge"))

from bantvision.core import staff_color as sc
from bantvision.core.people_track import MotParams, MotTracker
from bantvision.core.sim_people import LINE, Faults, scenario


def r6(v: float) -> float:
    return round(float(v), 6)


def build() -> dict:
    rng = np.random.default_rng(7)
    rgbs = [(0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255), (128, 128, 128), (10, 10, 10)]
    rgbs += [tuple(int(v) for v in rng.integers(0, 256, 3)) for _ in range(200)]
    lab = [[*c, *(r6(v) for v in sc.srgb_to_lab(*c))] for c in rgbs]

    points = []
    for w, h, box, anchor in [(640, 360, (0.2, 0.1, 0.4, 0.9), "bottom"), (352, 288, (0.0, 0.0, 1.0, 1.0), "center"),
                              (1920, 1080, (0.71, 0.33, 0.79, 0.97), "bottom")]:
        pts = [list(sc.to_pixel(x, y, w, h)) for x, y in sc.grid_points(sc.torso_region(box, anchor))]
        points.append({"w": w, "h": h, "box": list(box), "anchor": anchor, "pts": pts})

    votes = []
    while len(votes) < 60:
        base = rng.integers(0, 256, 3)
        n = int(rng.integers(30, 145))
        rgb = np.clip(base + rng.normal(0, 25, (n, 3)), 0, 255).astype(np.uint8)
        colors = [sc.srgb_to_lab(*(int(v) for v in rng.integers(0, 256, 3))) for _ in range(int(rng.integers(1, 4)))]
        if rng.random() < 0.5:
            colors[0] = sc.srgb_to_lab(*(int(v) for v in base))
        labs = sc.labs_from_rgb(rgb)
        c = np.asarray(colors)
        d = np.sqrt((0.5 * (labs[:, None, 0] - c[None, :, 0])) ** 2 + (labs[:, None, 1] - c[None, :, 1]) ** 2
                    + (labs[:, None, 2] - c[None, :, 2]) ** 2)
        if np.any(np.abs(d - sc.MATCH_DIST) < 1e-3) or np.any(np.abs(labs[:, 0] - sc.DARK_L) < 1e-3):
            continue
        hits = int(((d.min(axis=1) < sc.MATCH_DIST) & (labs[:, 0] >= sc.DARK_L)).sum())
        if n >= sc.MIN_POINTS and abs(hits - sc.MIN_FRACTION * n) < 1e-9:
            continue
        votes.append({"rgb": rgb.tolist(), "colors": [[r6(v) for v in col] for col in colors],
                      "vote": sc.vote_labs(sc.labs_from_rgb(rgb), [tuple(r6(v) for v in col) for col in colors])})

    dominant = []
    for _ in range(20):
        base = rng.integers(0, 256, 3)
        rgb = np.clip(base + rng.normal(0, 30, (144, 3)), 0, 255).astype(np.uint8)
        c = sc.dominant_color(sc.labs_from_rgb(rgb))
        dominant.append({"rgb": rgb.tolist(), "lab": None if c is None else [r6(v) for v in c]})

    tracker = []
    for seed in (0, 1, 2):
        dets, _, _ = scenario(seed, Faults(miss=0.15, part=0.1))
        frames, vote_of = [], {}
        for k, fd in enumerate(dets):
            d = [[round(float(v), 5) for v in (*b, s)] for b, s in fd]
            v = [int(rng.choice([1, 1, 1, 0, -1])) if b[0] < 0.5 else int(rng.choice([0, 0, 0, 1, -1]))
                 for b in d]                                            # soldakiler çoğunlukla personel
            frames.append({"d": d, "v": v})
            vote_of[k] = {tuple(b[:4]): (None if x < 0 else bool(x)) for b, x in zip(d, v)}
        t = MotTracker(MotParams(max_age=25))
        events = []
        for k, fr in enumerate(frames):
            ins, outs = t.update([((b[0], b[1], b[2], b[3]), b[4]) for b in fr["d"]], lambda _x, y: y - LINE,
                                 staff_vote=lambda box, _o, vo=vote_of[k]: vo.get(tuple(float(v) for v in box)))
            events += [[k, tr.id, 1, 0] for tr in ins] + [[k, tr.id, -1, 0] for tr in outs]
            events += [[k, tr.id, 1, 1] for tr in t.staff_entered] + [[k, tr.id, -1, 1] for tr in t.staff_exited]
        tracker.append({"name": f"personel-{seed}", "line": LINE, "maxAge": 25, "frames": frames, "events": events})
    images, vote_frames, teach_frames = frame_cases(rng)
    return {"lab": lab, "points": points, "votes": votes, "dominant": dominant, "tracker": tracker,
            "palette": [list(c) for c in PALETTE], "images": images, "voteFrames": vote_frames,
            "teachFrames": teach_frames}


# ---------------------------------------------------------------------- kare girişleri (vote_bgr / teach_bgr)
# Küçük sentetik RGB kareler: `palette` + satır sıralı indeks dizgisi (her piksel tek karakter, ALPHABET'te sırası).
# Swift testi StaffColor.vote / StaffColor.teach'i bu piksellerden okuyan `rgbAt` ile çağırır.

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
IMG_W, IMG_H = 64, 48
PALETTE = [(126, 128, 131), (118, 121, 119), (134, 131, 129),            # 0–2 gri zemin
           (236, 118, 24), (229, 126, 31), (243, 111, 18),                # 3–5 turuncu yelek
           (31, 62, 181), (24, 70, 172), (38, 55, 190),                   # 6–8 mavi
           (40, 150, 70), (52, 141, 63),                                  # 9–10 yeşil
           (9, 8, 10), (6, 7, 5),                                         # 11–12 çok koyu (L < 8)
           (205, 196, 188), (212, 203, 193)]                              # 13–14 açık gömlek
GRAY, ORANGE, BLUE, GREEN, DARK, SHIRT = [0, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10], [11, 12], [13, 14]


class Canvas:
    def __init__(self, rng: np.random.Generator, base: list[int]) -> None:
        self.rng = rng
        self.idx = rng.choice(base, size=(IMG_H, IMG_W))

    def paint(self, rect: tuple[float, float, float, float], shades: list[int]) -> Canvas:
        """Normalize dikdörtgeni (piksel sınırlarına yuvarlanır) gölge paletinden rastgele piksellerle boyar."""
        x0, y0 = int(np.floor(rect[0] * IMG_W)), int(np.floor(rect[1] * IMG_H))
        x1, y1 = int(np.ceil(rect[2] * IMG_W)), int(np.ceil(rect[3] * IMG_H))
        self.idx[y0:y1, x0:x1] = self.rng.choice(shades, size=(y1 - y0, x1 - x0))
        return self

    def bgr(self) -> np.ndarray:
        return np.asarray(PALETTE, np.uint8)[self.idx][:, :, ::-1].copy()

    def encode(self) -> dict:
        return {"w": IMG_W, "h": IMG_H, "px": "".join(ALPHABET[i] for i in self.idx.ravel())}


def _sample_labs(bgr: np.ndarray, pts: list[tuple[float, float]]) -> np.ndarray:
    h, w = bgr.shape[:2]
    px = [sc.to_pixel(x, y, w, h) for x, y in pts]
    return sc.labs_from_rgb(np.array([bgr[py, pxx, ::-1] for pxx, py in px]).reshape(-1, 3))


def _vote_points(bgr: np.ndarray, box: sc.Box, others: list[sc.Box], anchor: str) -> list[tuple[float, float]]:
    return [(x, y) for x, y in sc.grid_points(sc.torso_region(box, anchor))
            if not any(sc._inside(o, x, y) for o in others)]


def _vote_is_stable(bgr: np.ndarray, box: sc.Box, others: list[sc.Box], anchor: str,
                    colors: list[sc.LabColor]) -> bool:
    """Eşiğe çok yakın nokta yoksa (uzaklık ~20, L ~8) iki dilde son basamak farkı oyu değiştiremez."""
    pts = _vote_points(bgr, box, others, anchor)
    if not pts or not colors:
        return True
    labs = _sample_labs(bgr, pts)
    c = np.asarray(colors)
    d = np.sqrt((0.5 * (labs[:, None, 0] - c[None, :, 0])) ** 2 + (labs[:, None, 1] - c[None, :, 1]) ** 2
                + (labs[:, None, 2] - c[None, :, 2]) ** 2)
    return not (np.any(np.abs(d - sc.MATCH_DIST) < 1e-3) or np.any(np.abs(labs[:, 0] - sc.DARK_L) < 1e-3))


def _teach_region(boxes: list[sc.Box], point: tuple[float, float], anchor: str) -> sc.Box:
    inside = [b for b in boxes if sc._inside(b, *point)]
    if inside:
        return sc.torso_region(min(inside, key=lambda b: (b[2] - b[0]) * (b[3] - b[1])), anchor)
    hx, hy = sc.TEACH_PATCH / 2, sc.TEACH_PATCH / 2 * IMG_W / IMG_H
    x, y = point
    return (max(0.0, x - hx), max(0.0, y - hy), min(1.0, x + hx), min(1.0, y + hy))


def _teach_is_stable(bgr: np.ndarray, boxes: list[sc.Box], point: tuple[float, float], anchor: str) -> bool:
    """Kutucuk sınırına (a/8, b/8 tam sayıya) ya da karanlık eşiğine çok yakın örnek yoksa baskın renk kararlıdır."""
    labs = _sample_labs(bgr, sc.grid_points(_teach_region(boxes, point, anchor)))
    near_bin = np.abs(labs[:, 1:] / 8 - np.round(labs[:, 1:] / 8)) < 1e-7
    return not (np.any(near_bin) or np.any(np.abs(labs[:, 0] - sc.DARK_L) < 1e-3))


def frame_cases(rng: np.random.Generator) -> tuple[list[dict], list[dict], list[dict]]:
    orange = sc.srgb_to_lab(*PALETTE[4])
    blue = sc.srgb_to_lab(*PALETTE[7])
    green = sc.srgb_to_lab(*PALETTE[9])
    canvases: list[Canvas] = []
    votes: list[dict] = []
    teach: list[dict] = []

    def add(c: Canvas) -> int:
        canvases.append(c)
        return len(canvases) - 1

    def vote(name: str, img: int, box: sc.Box, others: list[sc.Box], anchor: str,
             colors: list[sc.LabColor]) -> bool | None:
        bgr = canvases[img].bgr()
        cols = [tuple(r6(v) for v in col) for col in colors]
        assert _vote_is_stable(bgr, box, others, anchor, cols), name
        v = sc.vote_bgr(bgr, box, others, anchor, cols)
        votes.append({"name": name, "image": img, "box": list(box), "others": [list(o) for o in others],
                      "anchor": anchor, "colors": [list(col) for col in cols], "vote": v})
        return v

    def teach_case(name: str, img: int, boxes: list[sc.Box], point: tuple[float, float],
                   anchor: str) -> sc.LabColor | None:
        bgr = canvases[img].bgr()
        assert _teach_is_stable(bgr, boxes, point, anchor), name
        c = sc.teach_bgr(bgr, boxes, point, anchor)
        teach.append({"name": name, "image": img, "boxes": [list(b) for b in boxes], "point": list(point),
                      "anchor": anchor, "lab": None if c is None else [r6(v) for v in c]})
        return c

    # Kişi: gövde (bottom: kutu yüksekliğinin %15–45'i) turuncu yelek, bacaklar mavi
    person = (0.30, 0.06, 0.62, 0.98)
    t = sc.torso_region(person, "bottom")
    img = add(Canvas(rng, GRAY).paint(person, SHIRT).paint((person[0], t[3], person[2], person[3]), BLUE)
              .paint(t, ORANGE))
    assert vote("yelek-eşleşir", img, person, [], "bottom", [orange]) is True
    assert vote("yelek-başka-renk", img, person, [], "bottom", [green, blue]) is False
    assert vote("renk-yok", img, person, [], "bottom", []) is None
    assert vote("küçük-kutu", img, (0.40, 0.30, 0.52, 0.80), [], "bottom", [orange]) is None   # 7,7 px < 8
    # Komşu kutu gövdenin üst 10 satırını örter: 24 nokta kalır (< 36) → oy yok
    rows = [t[1] + (j + 0.5) / sc.GRID * (t[3] - t[1]) for j in range(sc.GRID)]
    cover = (0.0, 0.0, 1.0, (rows[9] + rows[10]) / 2)
    assert len(_vote_points(canvases[img].bgr(), person, [cover], "bottom")) == 24
    assert vote("komşu-örter-az-nokta", img, person, [cover], "bottom", [orange]) is None
    assert vote("komşu-yok-aynı-kutu", img, person, [], "bottom", [orange]) is True

    # Gövdenin yalnızca sol 2/12'si turuncu (%17 < %25 → hayır); komşu sağ 8/12'yi örtünce kalan 48 noktanın
    # yarısı turuncu → evet: karar kalan noktalardan
    person2 = (0.20, 0.04, 0.70, 0.98)
    t2 = sc.torso_region(person2, "center")
    cols = [t2[0] + (i + 0.5) / sc.GRID * (t2[2] - t2[0]) for i in range(sc.GRID)]
    split = (cols[1] + cols[2]) / 2
    img2 = add(Canvas(rng, GRAY).paint(person2, SHIRT).paint(t2, BLUE).paint((t2[0], t2[1], split, t2[3]), ORANGE))
    neighbour = ((cols[3] + cols[4]) / 2, 0.0, 1.0, 1.0)
    assert len(_vote_points(canvases[img2].bgr(), person2, [neighbour], "center")) == 48
    assert vote("komşusuz-az-turuncu", img2, person2, [], "center", [orange]) is False
    assert vote("komşu-sonrası-kalan-noktalar", img2, person2, [neighbour], "center", [orange]) is True
    assert vote("iki-renk-biri-mavi", img2, person2, [], "center", [green, blue]) is True

    # Öğretme: iç içe iki kutu — tıklanan noktayı içeren en küçük kutunun gövdesi (dış: mavi, iç: turuncu)
    outer, inner = (0.05, 0.02, 0.95, 0.98), (0.40, 0.30, 0.62, 0.96)
    to, ti = sc.torso_region(outer, "center"), sc.torso_region(inner, "center")
    img3 = add(Canvas(rng, GRAY).paint(outer, SHIRT).paint(to, BLUE).paint(ti, ORANGE)
               .paint((0.0, 0.85, 0.12, 1.0), GREEN).paint((0.80, 0.0, 1.0, 0.25), DARK))
    click = (0.50, 0.90)                                    # iki kutunun da içinde, gövdelerin dışında
    c_in = teach_case("iç-içe-en-küçük-kutu", img3, [outer, inner], click, "center")
    c_out = teach_case("yalnız-dış-kutu", img3, [outer], click, "center")
    assert c_in is not None and c_out is not None and sc.color_distance(c_in, orange) < 15
    assert sc.color_distance(c_out, blue) < 15
    # Kutusuz: tıklanan yer çevresi; görüntü kenarında kare kırpılır (sol alt köşe yeşil)
    corner = (0.01, 0.98)
    assert corner[0] - sc.TEACH_PATCH / 2 < 0 and corner[1] + sc.TEACH_PATCH / 2 * IMG_W / IMG_H > 1
    c_edge = teach_case("kutusuz-kenarda-kırpılan-kare", img3, [], corner, "center")
    assert c_edge is not None and sc.color_distance(c_edge, green) < 15
    assert teach_case("kutu-dışına-tıklama", img3, [inner], (0.03, 0.95), "bottom") is not None
    assert teach_case("çok-karanlık", img3, [], (0.92, 0.10), "center") is None

    # Rastgele kareler: 1–3 kişi kutusu, bazen öğretilen renk gövdeyle aynı
    shades = [ORANGE, BLUE, GREEN, SHIRT, DARK]
    while len(canvases) < 12:
        c = Canvas(rng, GRAY)
        boxes: list[sc.Box] = []
        for _ in range(int(rng.integers(1, 4))):
            x0, y0 = float(rng.uniform(0.0, 0.6)), float(rng.uniform(0.0, 0.3))
            box = (round(x0, 4), round(y0, 4), round(x0 + float(rng.uniform(0.15, 0.4)), 4),
                   round(y0 + float(rng.uniform(0.4, 0.7)), 4))
            anchor_paint = "bottom" if rng.random() < 0.5 else "center"
            c.paint(box, shades[int(rng.integers(0, 4))]).paint(sc.torso_region(box, anchor_paint),
                                                                 shades[int(rng.integers(0, 5))])
            boxes.append(box)
        k = add(c)
        bgr = c.bgr()
        for bi, box in enumerate(boxes):
            anchor = "bottom" if rng.random() < 0.5 else "center"
            others = [o for oi, o in enumerate(boxes) if oi != bi]
            colors = [sc.srgb_to_lab(*PALETTE[int(rng.integers(3, 11))]) for _ in range(int(rng.integers(1, 4)))]
            if _vote_is_stable(bgr, box, others, anchor, [tuple(r6(v) for v in col) for col in colors]):
                vote(f"rastgele-{k}-{bi}", k, box, others, anchor, colors)
        for pi in range(3):                                 # çoğunlukla bir kutunun içine tıklanır
            bx = boxes[int(rng.integers(0, len(boxes)))] if pi < 2 else (0.0, 0.0, 1.0, 1.0)
            point = (round(float(rng.uniform(bx[0], bx[2])), 4), round(float(rng.uniform(bx[1], bx[3])), 4))
            anchor = "bottom" if rng.random() < 0.5 else "center"
            if _teach_is_stable(bgr, boxes, point, anchor):
                teach_case(f"rastgele-{k}-{pi}", k, boxes, point, anchor)
    return [c.encode() for c in canvases], votes, teach


def main() -> int:
    text = json.dumps(build(), separators=(",", ":")) + "\n"
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("staff_parity.json güncel değil: python tools/make_staff_fixture.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    data = json.loads(text)
    staff = sum(e[3] for s in data["tracker"] for e in s["events"])
    print(f"{OUT.name}: {len(data['lab'])} renk, {len(data['votes'])} oy, {staff} personel geçişi, "
          f"{len(data['images'])} kare, {len(data['voteFrames'])} kare oyu, {len(data['teachFrames'])} öğretme")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
