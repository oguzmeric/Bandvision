"""Yangın/duman eğitim verisini hazırlar: D-Fire (YOLO txt) ve FireNet (Pascal VOC xml) → COCO json + `sources.csv`.

    python tools/fire_train/prepare_data.py --dfire D-FIRE-KÖKÜ [--firenet FIRENET-KÖKÜ] [--negatives KLASÖR]
                                            --out ÇIKIŞ [--seed 0] [--val 0.1] [--include-public]

Yalnız standart kitaplık kullanır (eğitim ortamında da ana ortamda da çalışır); görüntüler kopyalanmaz: COCO
`file_name` görüntünün mutlak yoludur (YOLOX `COCODataset` görüntüyü `os.path.join(data_dir, name, file_name)` ile açar;
mutlak yol olduğu gibi kalır).

Girdi düzeni:
- D-Fire: `train/images`, `train/labels`, `test/images`, `test/labels`; etiket YOLO txt (`sınıf cx cy w h`, normalize),
  boş dosya = "hiçbiri" (negatif, kutusuz görüntü olarak kalır). D-Fire'ın sınıf düzeni `DFIRE_CLASSES`'tadır ve bizim
  düzene (0 fire, 1 smoke; uygulamadaki `core/fire_model.py` `CLASSES`) çevrilir.
- `PublicDataset` ön ekli D-Fire dosyaları üçüncü taraf kamu setlerinden gelir ve özgün sağlayıcılarının koşullarına
  tabidir: `--include-public` verilmezse atılır, sayısı raporlanır.
- FireNet: altındaki her `*.xml` (VOC; `size/width`, `size/height`, `object/name` = "fire", `bndbox`); görüntü xml'deki
  `filename` adıyla xml'in klasöründe ya da kardeş `images` klasöründe, yoksa xml ile aynı adla aranır.
- `--negatives`: kutusuz (negatif) eğitim görüntüleri, ör. yanlış alarmlardan elde edilen ham kareler (zor örnek; bkz.
  docs/14-yangin-duman.md). Klasör altındaki her JPEG/PNG kutusuz görüntü olur. Uygulamanın zor örnek klasöründeki
  `image.jpg` (yanında `meta.json`) alarm resmidir ve üstünde kutular çizilidir: eğitimi bozacağı için atlanır, sayılır.

Bölümleme: D-Fire `test` → `test`; D-Fire `train`, FireNet'in ve `--negatives`'in tamamı eğitim havuzudur, havuzdan tohumlu `--val` oranı
(varsayılan %10) → `val`, kalanı `train`. Çıktı: `ÇIKIŞ/annotations/instances_{train,val,test}.json`, `ÇIKIŞ/sources.csv`
(`dosya;kaynak;lisans;bolum`) ve ekrana özet (bölüm başına görüntü/kutu, atılanlar). Çıkış kodu: 0 tamam, 2 girdi hatası.
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import random
import struct
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

CLASSES = ("fire", "smoke")                       # bizim düzen: core/fire_model.py `CLASSES` ile aynı (0 fire, 1 smoke)
CATEGORIES = [{"id": i + 1, "name": n, "supercategory": "event"} for i, n in enumerate(CLASSES)]   # COCO kimliği 1'den
# D-Fire'ın YOLO sınıf düzeni (D-Fire README'sine göre 0 = smoke, 1 = fire). Tek yerde tutulur; ilk gerçek hazırlıkta
# `--include-public` ile çıkan toplam kutu sayıları README'dekilerle (fire 14.692, smoke 11.865) karşılaştırılarak
# doğrulanır: sayılar yer değiştirmişse düzen ters demektir.
DFIRE_CLASSES = ("smoke", "fire")
PUBLIC_PREFIX = "PublicDataset"
IMAGE_EXTS = (".jpg", ".jpeg", ".png")
SPLITS = ("train", "val", "test")
SOURCES = {
    "dfire": ("D-Fire", "CC0-1.0"),
    "dfire-public": ("D-Fire PublicDataset (üçüncü taraf)", "Özgün sağlayıcının koşulları"),
    "firenet": ("FireNet", "MIT"),
    "negatives": ("Zor örnek (kendi kaydımız, ham kare)", "Kullanıcı izniyle; dağıtılmaz"),
}


class InputError(Exception):
    """Hazırlığa başlanamaz (eksik klasör, okunamayan görüntü boyu); ileti kullanıcıya gösterilir."""


@dataclass
class Item:
    path: pathlib.Path
    width: int
    height: int
    boxes: list[tuple[int, list[float]]]          # (bizim sınıf sırası, COCO bbox [x, y, w, h] piksel)
    source: str                                   # SOURCES anahtarı


@dataclass
class Stats:
    public_skipped: int = 0
    missing: int = 0                              # etiketi (D-Fire) ya da görüntüsü (FireNet) olmayan
    bad_lines: int = 0
    bad_boxes: int = 0
    drawn_skipped: int = 0                        # zor örnek klasöründeki kutusu çizili alarm resimleri
    unknown_names: dict[str, int] = field(default_factory=dict)


def image_size(path: pathlib.Path) -> tuple[int, int]:
    """(genişlik, yükseklik) — PNG IHDR ya da JPEG SOF başlığından (görüntü çözülmez, bağımlılık yok)."""
    with path.open("rb") as f:
        head = f.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
            w, h = struct.unpack(">II", head[16:24])
            return int(w), int(h)
        if head[:2] != b"\xff\xd8":
            raise InputError(f"Görüntü biçimi tanınmadı (yalnız JPEG/PNG): {path.name}")
        f.seek(2)
        while True:
            b = f.read(1)
            while b and b != b"\xff":
                b = f.read(1)
            while b == b"\xff":
                b = f.read(1)
            if not b:
                break
            marker = b[0]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:      # uzunluksuz işaretler
                continue
            seg = f.read(2)
            if len(seg) < 2:
                break
            length = struct.unpack(">H", seg)[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):   # SOFn: kesinlik, yükseklik, genişlik
                data = f.read(5)
                if len(data) < 5:
                    break
                h, w = struct.unpack(">HH", data[1:5])
                return int(w), int(h)
            f.seek(length - 2, 1)
    raise InputError(f"Görüntü boyu okunamadı: {path.name}")


def clip_box(x1: float, y1: float, x2: float, y2: float, w: int, h: int) -> list[float] | None:
    """Piksel köşeleri görüntüye kırpılmış COCO bbox'a çevirir; alanı sıfır olan kutu None."""
    x1, x2 = max(0.0, min(float(w), x1)), max(0.0, min(float(w), x2))
    y1, y2 = max(0.0, min(float(h), y1)), max(0.0, min(float(h), y2))
    if x2 - x1 <= 0 or y2 - y1 <= 0:
        return None
    return [round(x1, 2), round(y1, 2), round(x2 - x1, 2), round(y2 - y1, 2)]


def yolo_boxes(text: str, w: int, h: int, stats: Stats) -> list[tuple[int, list[float]]]:
    """D-Fire YOLO satırları → (bizim sınıf sırası, COCO bbox). Bozuk satır ve bilinmeyen sınıf atlanır, sayılır."""
    out: list[tuple[int, list[float]]] = []
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        try:
            if len(parts) != 5:
                raise ValueError(line)
            cls = int(parts[0])
            cx, cy, bw, bh = (float(p) for p in parts[1:5])
            if not 0 <= cls < len(DFIRE_CLASSES):
                raise ValueError(line)
        except ValueError:
            stats.bad_lines += 1
            continue
        box = clip_box((cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h, w, h)
        if box is None:
            stats.bad_boxes += 1
            continue
        out.append((CLASSES.index(DFIRE_CLASSES[cls]), box))
    return out


def images_in(folder: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS) if folder.is_dir() else []


def read_dfire(root: pathlib.Path, part: str, include_public: bool, stats: Stats) -> list[Item]:
    """D-Fire'ın `part` ("train" | "test") bölümü. Etiket dosyası olmayan görüntü atlanır ve sayılır."""
    img_dir, lab_dir = root / part / "images", root / part / "labels"
    if not img_dir.is_dir() or not lab_dir.is_dir():
        raise InputError(f"D-Fire klasörü eksik: {part}/images ve {part}/labels bekleniyor")
    items: list[Item] = []
    for img in images_in(img_dir):
        public = img.name.startswith(PUBLIC_PREFIX)
        if public and not include_public:
            stats.public_skipped += 1
            continue
        lab = lab_dir / (img.stem + ".txt")
        if not lab.is_file():
            stats.missing += 1
            continue
        w, h = image_size(img)
        boxes = yolo_boxes(lab.read_text(encoding="utf-8", errors="replace"), w, h, stats)
        items.append(Item(img.resolve(), w, h, boxes, "dfire-public" if public else "dfire"))
    return items


def voc_image(xml_path: pathlib.Path, filename: str) -> pathlib.Path | None:
    """VOC xml'inin görüntüsü: `filename` xml'in klasöründe ya da kardeş `images` klasöründe; yoksa xml ile aynı ad."""
    cands: list[pathlib.Path] = []
    if filename:
        cands += [xml_path.parent / filename, xml_path.parent.parent / "images" / filename]
    for e in IMAGE_EXTS:
        cands += [xml_path.with_suffix(e), xml_path.parent.parent / "images" / (xml_path.stem + e)]
    return next((c for c in cands if c.is_file()), None)


def read_firenet(root: pathlib.Path, stats: Stats) -> list[Item]:
    """FireNet VOC xml'leri (yalnız "fire" sınıfı). Görüntüsü bulunamayan xml atlanır ve sayılır."""
    if not root.is_dir():
        raise InputError("FireNet klasörü bulunamadı")
    items: list[Item] = []
    for xml_path in sorted(root.rglob("*.xml")):
        try:
            tree = ET.parse(xml_path).getroot()
        except ET.ParseError:
            stats.bad_lines += 1
            continue
        img = voc_image(xml_path, (tree.findtext("filename") or "").strip())
        if img is None:
            stats.missing += 1
            continue
        try:
            w = int(float(tree.findtext("size/width") or 0))
            h = int(float(tree.findtext("size/height") or 0))
        except ValueError:
            w = h = 0
        if w <= 0 or h <= 0:
            w, h = image_size(img)
        boxes: list[tuple[int, list[float]]] = []
        for obj in tree.iter("object"):
            name = (obj.findtext("name") or "").strip().lower()
            if name not in CLASSES:
                stats.unknown_names[name] = stats.unknown_names.get(name, 0) + 1
                continue
            try:
                x1, y1, x2, y2 = (float(obj.findtext(f"bndbox/{k}") or "") for k in ("xmin", "ymin", "xmax", "ymax"))
            except ValueError:
                stats.bad_lines += 1
                continue
            box = clip_box(x1, y1, x2, y2, w, h)
            if box is None:
                stats.bad_boxes += 1
                continue
            boxes.append((CLASSES.index(name), box))
        items.append(Item(img.resolve(), w, h, boxes, "firenet"))
    return items


def read_negatives(root: pathlib.Path, stats: Stats) -> list[Item]:
    """Klasör altındaki her JPEG/PNG kutusuz görüntü. Uygulamanın zor örnek klasöründeki alarm resmi (`image.jpg`,
    yanında `meta.json`) kutuları çizili olduğundan atlanır ve sayılır."""
    if not root.is_dir():
        raise InputError("Negatif görüntü klasörü bulunamadı")
    items: list[Item] = []
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() not in IMAGE_EXTS or not p.is_file():
            continue
        if p.name == "image.jpg" and (p.parent / "meta.json").is_file():
            stats.drawn_skipped += 1
            continue
        w, h = image_size(p)
        items.append(Item(p.resolve(), w, h, [], "negatives"))
    return items


def split(dfire_train: list[Item], dfire_test: list[Item], extra: list[Item], val: float,
          seed: int) -> dict[str, list[Item]]:
    """D-Fire test → test; D-Fire train + `extra` havuzundan tohumlu `val` oranı → val, kalanı train (sıra korunur)."""
    pool = dfire_train + extra
    n_val = round(len(pool) * val)
    val_idx = set(random.Random(seed).sample(range(len(pool)), n_val)) if n_val else set()
    return {"train": [it for i, it in enumerate(pool) if i not in val_idx],
            "val": [it for i, it in enumerate(pool) if i in val_idx], "test": list(dfire_test)}


def to_coco(items: list[Item], first_image_id: int = 1, first_ann_id: int = 1) -> dict[str, Any]:
    images, anns = [], []
    ann_id = first_ann_id
    for k, it in enumerate(items):
        img_id = first_image_id + k
        images.append({"id": img_id, "file_name": str(it.path), "width": it.width, "height": it.height})
        for cls, (x, y, w, h) in it.boxes:
            anns.append({"id": ann_id, "image_id": img_id, "category_id": cls + 1, "bbox": [x, y, w, h],
                         "area": round(w * h, 2), "iscrowd": 0})
            ann_id += 1
    return {"images": images, "annotations": anns, "categories": CATEGORIES}


def write_outputs(parts: dict[str, list[Item]], out: pathlib.Path) -> dict[str, dict[str, Any]]:
    """COCO json'ları ve `sources.csv`'yi yazar; bölüm başına özet döndürür. Görüntü ve kutu kimlikleri bölümler
    arasında da benzersizdir."""
    (out / "annotations").mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict[str, Any]] = {}
    next_img, next_ann = 1, 1
    for name in SPLITS:
        coco = to_coco(parts[name], next_img, next_ann)
        next_img += len(coco["images"])
        next_ann += len(coco["annotations"])
        (out / "annotations" / f"instances_{name}.json").write_text(json.dumps(coco, ensure_ascii=False),
                                                                      encoding="utf-8")
        boxes = {c: sum(1 for a in coco["annotations"] if a["category_id"] == i + 1) for i, c in enumerate(CLASSES)}
        summary[name] = {"images": len(coco["images"]), "negatives": sum(1 for it in parts[name] if not it.boxes),
                         "boxes": boxes}
    with (out / "sources.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["dosya", "kaynak", "lisans", "bolum"])
        for name in SPLITS:
            for it in parts[name]:
                src, lic = SOURCES[it.source]
                w.writerow([it.path.name, src, lic, name])
    return summary


def report(summary: dict[str, dict[str, Any]], stats: Stats, include_public: bool) -> None:
    print("Bölüm   görüntü  negatif  fire kutusu  smoke kutusu")
    for name in SPLITS:
        s = summary[name]
        print(f"{name:<7} {s['images']:>7}  {s['negatives']:>7}  {s['boxes']['fire']:>11}  {s['boxes']['smoke']:>12}")
    if include_public:
        print("PublicDataset görüntüleri DAHİL (özgün sağlayıcılarının koşullarına tabi; ürün modeli için kullanmayın).")
    else:
        print(f"PublicDataset ön ekli atılan görüntü: {stats.public_skipped} (dahil etmek için --include-public)")
    if stats.missing:
        print(f"Etiketi ya da görüntüsü bulunamadığı için atlanan: {stats.missing}")
    if stats.bad_lines or stats.bad_boxes:
        print(f"Bozuk etiket satırı/dosyası: {stats.bad_lines}, alanı sıfır kutu: {stats.bad_boxes}")
    if stats.drawn_skipped:
        print(f"Kutuları çizili alarm resmi atlandı (zor örnek; ham kare kullanın): {stats.drawn_skipped}")
    for name, n in sorted(stats.unknown_names.items()):
        print(f"Bilinmeyen VOC sınıfı atlandı: {name!r} × {n}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="D-Fire / FireNet → COCO (yangın/duman eğitimi)")
    ap.add_argument("--dfire", required=True, help="D-Fire kökü (train/, test/)")
    ap.add_argument("--firenet", help="FireNet kökü (VOC xml), isteğe bağlı")
    ap.add_argument("--negatives", help="kutusuz (negatif) görüntü klasörü, isteğe bağlı (zor örneklerin ham kareleri)")
    ap.add_argument("--out", required=True, help="çıkış klasörü (annotations/, sources.csv)")
    ap.add_argument("--val", type=float, default=0.1, help="eğitim havuzundan doğrulama oranı (0–0,5)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--include-public", action="store_true",
                    help="PublicDataset ön ekli D-Fire görüntülerini de al (üçüncü taraf koşulları)")
    a = ap.parse_args(argv)
    if not 0 <= a.val <= 0.5:
        print("Hata: --val 0 ile 0,5 arasında olmalı", file=sys.stderr)
        return 2
    stats = Stats()
    try:
        root = pathlib.Path(a.dfire)
        train = read_dfire(root, "train", a.include_public, stats)
        test = read_dfire(root, "test", a.include_public, stats)
        extra = read_firenet(pathlib.Path(a.firenet), stats) if a.firenet else []
        extra += read_negatives(pathlib.Path(a.negatives), stats) if a.negatives else []
    except (InputError, OSError) as e:
        print(f"Hata: {e}", file=sys.stderr)
        return 2
    parts = split(train, test, extra, a.val, a.seed)
    report(write_outputs(parts, pathlib.Path(a.out)), stats, a.include_public)
    return 0


if __name__ == "__main__":
    sys.exit(main())
