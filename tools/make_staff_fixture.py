"""iOS ↔ Python eşdeğerliği: personel rengi (§4.10 eki).

Kullanım: python tools/make_staff_fixture.py [--check]
Üretir: apps/ios/BantSayacTests/staff_parity.json — renk çevirisi, ızgara noktaları, kare oyu, öğretme (baskın renk),
izleyicide personel kararı. Girdiler sabit tohumlu; Lab 6 ondalık (Swift testi 1e-4 toleransla karşılaştırır).
Eşiğe 1e-3'ten yakın oy durumları üretilmez (iki dilde son basamak farkı kararı değiştirmesin).
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
    return {"lab": lab, "points": points, "votes": votes, "dominant": dominant, "tracker": tracker}


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
    print(f"{OUT.name}: {len(data['lab'])} renk, {len(data['votes'])} oy, {staff} personel geçişi")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
