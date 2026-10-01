"""Swift eşdeğerlik testi için sentetik kare dizileri üretir (F0.2).

Kullanım:  python tools/gen_vectors.py out/vectors
Çıktı:     out/vectors/<senaryo>/frame_00000.png ... + expected.json
Swift testi: aynı profille (expected.json içindeki) kareleri sırayla işleyip toplamı karşılaştırır.
Not: Swift, Y düzlemi yerine PNG gri değerlerini kullanır; dönüş (rotation) 0'dır.
"""
from __future__ import annotations

import json
import pathlib
import sys

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "services" / "edge"))
from bantvision import sim
from bantvision.core import Pipeline, Profile


def calibrate() -> Profile:
    p = Profile.egg()
    pipe = Pipeline(p)
    sc = sim.single_file(n=8)
    pipe.start_background_learning()
    for img, ts in sc.empty_frames():
        pipe.process(img, ts)
    pipe.start_sample_learning(8)
    for img, ts in sc.frames():
        pipe.process(img, ts)
    return p


def main(out: str) -> None:
    root = pathlib.Path(out)
    profile = calibrate()
    for make in sim.ALL:
        sc = make()
        d = root / sc.name
        d.mkdir(parents=True, exist_ok=True)
        frames = list(sc.empty_frames(0.5)) + list(sc.frames())
        pipe = Pipeline(Profile.from_dict(profile.to_dict()))
        warmup = int(0.5 * sc.fps)
        for i, (img, ts) in enumerate(frames):
            cv2.imwrite(str(d / f"frame_{i:05d}.png"), img)
            if i == warmup:
                pipe.reset_count()
            pipe.process(img, ts)
        (d / "expected.json").write_text(json.dumps({
            "scenario": sc.name, "fps": sc.fps, "warmupFrames": warmup,
            "expectedCount": sc.expected_count, "pythonCount": pipe.total,
            "profile": profile.to_dict(),
        }, indent=2, ensure_ascii=False))
        print(f"{sc.name}: {len(frames)} kare, beklenen {sc.expected_count}, python {pipe.total}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out/vectors")
