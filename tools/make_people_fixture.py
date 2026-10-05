"""iOS ↔ Python eşdeğerliği: kişi izleyicisi (§4.10) için sabit senaryolar ve beklenen olaylar.

Kullanım: python tools/make_people_fixture.py            (services/edge kurulu olmalı)
          python tools/make_people_fixture.py --check    (yazmaz; dosya güncel değilse 1 ile çıkar)

Üretir: apps/ios/BantSayacTests/people_parity.json
  {"scenarios": [{"name", "anchor", "line", "frames": [{"d": [[x1,y1,x2,y2,güven], ...], "m": [[x1,y1,x2,y2], ...]}],
                  "events": [[kare, izKimliği, +1 giriş / −1 çıkış], ...]}]}
Girdiler 5 ondalığa yuvarlanır (JSON'dan iki dilde de aynı sayı okunur); beklenen olaylar Python izleyicisinin
yuvarlanmış girdilerle ürettikleridir. Swift testi (PeopleTrackerTests) aynı karede aynı iz kimliğiyle aynı olayları
bekler. İzleyici değişince bu araç yeniden çalıştırılır; services/edge/tests/test_people_fixture.py güncelliği denetler.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "apps" / "ios" / "BantSayacTests" / "people_parity.json"
sys.path.insert(0, str(ROOT / "services" / "edge"))

from bantvision.core.people_track import MotParams, MotTracker  # noqa: E402
from bantvision.core.sim_people import LINE, Faults, scenario, scenario_motion  # noqa: E402

# (ad, tohum, hareket var mı, konum noktası, kusurlar)
SCENARIOS = [
    ("grup-0", 0, False, "center", Faults()),
    ("grup-1", 1, False, "center", Faults()),
    ("grup-agir-2", 2, False, "center", Faults(miss=0.25, part=0.1, merge=0.1)),
    ("hareket-3", 3, True, "center", Faults()),
    ("hareket-4", 4, True, "center", Faults()),
    ("hareket-agir-5", 5, True, "center", Faults(miss=0.25, part=0.1, merge=0.1)),
    ("hareket-ayak-6", 6, True, "bottom", Faults()),
]


def r5(v: float) -> float:
    return round(float(v), 5)


def build() -> dict:
    out = []
    for name, seed, motion, anchor_mode, faults in SCENARIOS:
        if motion:
            dets, blobs, _, _ = scenario_motion(seed, faults)
        else:
            dets, _, _ = scenario(seed, faults)
            blobs = [[] for _ in dets]
        frames = [{"d": [[r5(b[0]), r5(b[1]), r5(b[2]), r5(b[3]), r5(s)] for b, s in fd],
                   "m": [[r5(b[0]), r5(b[1]), r5(b[2]), r5(b[3])] for b in fm]}
                  for fd, fm in zip(dets, blobs)]
        t = MotTracker(MotParams(max_age=25))
        events = []
        for k, fr in enumerate(frames):
            ins, outs = t.update([((d[0], d[1], d[2], d[3]), d[4]) for d in fr["d"]], lambda x, y: y - LINE,
                                 anchor_mode, [tuple(m) for m in fr["m"]] if motion else None)
            events += [[k, tr.id, 1] for tr in ins] + [[k, tr.id, -1] for tr in outs]
        out.append({"name": name, "anchor": anchor_mode, "line": LINE, "maxAge": 25, "motion": motion,
                    "frames": frames, "events": events})
    return {"scenarios": out}


def main() -> int:
    text = json.dumps(build(), separators=(",", ":")) + "\n"
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("people_parity.json güncel değil: python tools/make_people_fixture.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    data = json.loads(text)
    for s in data["scenarios"]:
        print(f"{s['name']}: {len(s['frames'])} kare, {len(s['events'])} olay")
    print(f"{OUT} ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
