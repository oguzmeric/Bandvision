"""Personel rengi doğruluğu (§4.10 eki, kabul ölçütü: her kamera açısında ≥ %95).

Kullanım: python tools/eval_staff.py VIDEO --profile PROFİL.json --labels VIDEO.staff.json --angle tepeden
Etiket: [{"t": saniye, "dir": "in"|"out", "staff": true|false}] — her gerçek geçiş elle etiketlenir.
Her etiket aynı yönde ±1,5 sn içindeki en yakın tahmine eşlenir. Sonuç:
- yakalama = personel etiketlerinden personel sayılan oranı;
- yanlış hariç tutma = müşteri etiketlerinden personel sayılan oranı.
Kayıtlar kullanıcınındır; public repoya konmaz.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "edge"))


def match(labels: list[dict], preds: list[tuple[float, str, bool]], tol: float = 1.5) -> dict[str, int]:
    used: set[int] = set()
    r = {"staff": 0, "staff_ok": 0, "customer": 0, "customer_excluded": 0, "missed": 0, "extra": 0}
    for lab in sorted(labels, key=lambda x: x["t"]):
        r["staff" if lab["staff"] else "customer"] += 1
        best = None
        for k, (t, d, _) in enumerate(preds):
            if k not in used and d == lab["dir"] and abs(t - lab["t"]) <= tol and (
                    best is None or abs(t - lab["t"]) < abs(preds[best][0] - lab["t"])):
                best = k
        if best is None:
            r["missed"] += 1
            continue
        used.add(best)
        if lab["staff"] and preds[best][2]:
            r["staff_ok"] += 1
        if not lab["staff"] and preds[best][2]:
            r["customer_excluded"] += 1
    r["extra"] = len(preds) - len(used)
    return r


def run(video: str, profile_path: str) -> list[tuple[float, str, bool]]:
    import cv2

    from bantvision.core import Pipeline, Profile

    p = Profile.from_dict(json.loads(pathlib.Path(profile_path).read_text(encoding="utf-8")))
    pipe = Pipeline(p)
    pipe.counting = True
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    preds: list[tuple[float, str, bool]] = []
    k = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        ts = k / fps
        r = pipe.process(frame, ts)
        preds += [(ts, "in", False)] * len(r.counts) + [(ts, "out", False)] * len(r.counts_out)
        preds += [(ts, "in" if d > 0 else "out", True) for _, d in r.staff_events]
        k += 1
    return preds


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--angle", required=True)
    a = ap.parse_args()
    labels = json.loads(pathlib.Path(a.labels).read_text(encoding="utf-8"))
    r = match(labels, run(a.video, a.profile))
    cap = r["staff_ok"] / r["staff"] if r["staff"] else 1.0
    fx = r["customer_excluded"] / r["customer"] if r["customer"] else 0.0
    ok = cap >= 0.95 and fx <= 0.05
    print(f"{a.angle}: personel yakalama %{100 * cap:.1f} ({r['staff_ok']}/{r['staff']}), "
          f"yanlış hariç tutma %{100 * fx:.1f} ({r['customer_excluded']}/{r['customer']}), "
          f"kaçan geçiş {r['missed']}, fazla {r['extra']} → {'GEÇTİ' if ok else 'KALDI'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
