"""Veri toplama modundan gelen YOLO veri setini kontrol eder (F1.3).

Kullanım: python tools/check_dataset.py dataset_dir [--draw out_dir]
Kontroller: her görüntünün etiketi var mı, etiket satırları geçerli mi (sınıf cx cy w h, 0-1 aralığı),
boş etiket oranı, kutu boyutu dağılımı. --draw ile kutular çizilmiş örnekler üretir.
"""
from __future__ import annotations

import argparse
import pathlib

import cv2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--draw")
    a = ap.parse_args()
    root = pathlib.Path(a.root)
    images = sorted((root / "images").glob("*.jpg"))
    problems, empty, boxes = 0, 0, []
    for img_path in images:
        lab = root / "labels" / (img_path.stem + ".txt")
        if not lab.exists():
            print("etiket yok:", img_path.name)
            problems += 1
            continue
        lines = [ln.split() for ln in lab.read_text().splitlines() if ln.strip()]
        if not lines:
            empty += 1
        for parts in lines:
            ok = len(parts) == 5 and all(0 <= float(v) <= 1 for v in parts[1:])
            if not ok:
                print("hatalı satır:", lab.name, parts)
                problems += 1
            else:
                boxes.append((float(parts[3]), float(parts[4])))
        if a.draw and lines:
            im = cv2.imread(str(img_path))
            h, w = im.shape[:2]
            for parts in lines:
                cx, cy, bw, bh = (float(v) for v in parts[1:])
                cv2.rectangle(im, (int((cx - bw / 2) * w), int((cy - bh / 2) * h)),
                              (int((cx + bw / 2) * w), int((cy + bh / 2) * h)), (0, 255, 0), 2)
            out = pathlib.Path(a.draw)
            out.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(out / img_path.name), im)
    print(f"{len(images)} görüntü, {len(boxes)} kutu, {empty} boş, {problems} sorun")
    raise SystemExit(1 if problems else 0)


if __name__ == "__main__":
    main()
