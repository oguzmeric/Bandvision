"""Yangın/duman modeli ölçümü (tasarım docs/superpowers/specs/2026-11-08-yangin-duman-design.md §4–§5).

    python tools/fire_train/eval_fire.py --model fire_smoke_v1.onnx [--coco instances_test.json]
                                         [--manifest videolar.json] [--device auto] [--out rapor.md] [--no-calibrate]

Ana uygulama ortamında (services/edge kurulu) çalışır; PyTorch/YOLOX gerekmez. Üç bölüm:

(a) **Görüntü düzeyi** (`--coco`, ör. prepare_data çıktısı `instances_test.json`): model her görüntüde uygulamadaki
    `FireDetector` ile (sınıf başına NMS 0,45, eşik `IMAGE_CONF`) çalışır; sınıf başına AP50 ve iki sınıfın ortalaması
    (mAP50). pycocotools kuruluysa COCOeval (101 nokta), değilse buradaki basit 11 nokta AP (`ap11`) kullanılır; rapor
    hangisinin kullanıldığını yazar.
(b) **Olay düzeyi** (`--manifest`): her video gerçek `FireAnalyzer` ile, canlıdaki gibi video zamanıyla ve en çok
    `MAX_FPS` (5) kare/sn oynatılır; varsayılan kurallar (alev 3 sn, duman 8 sn) ve her hassasiyet (Düşük / Normal /
    Yüksek) için: pozitif videolarda `ALARM_LIMIT_S` (15 sn) içinde alarm oranı, ilk alarm süresi, negatif videolarda
    yanlış alarm sayısı.
(c) **Eşik kalibrasyonu** (`--manifest`, `--no-calibrate` ile kapanır): sınıf başına `SWEEP` eşikleri tek tek denenir
    (yalnız o sınıfın kuralı açık); negatiflerde sıfır yanlış alarm veren en düşük eşik "Normal" önerisidir, "Düşük" ve
    "Yüksek" bugünkü aralıkla (+0,15 / −0,10) türetilir. Öneri `core/fire_rules.py` `THRESHOLDS`'a elle, ölçüm tablosuyla
    ayrı bir commit'te işlenir.

Model her video için yalnız bir kez çalışır: tespitler `CACHE_FLOOR` eşiğiyle saklanır, hassasiyet ve kalibrasyon
oynatmaları saklanan tespitleri süzer (sınıf başına açgözlü NMS'te yüksek eşikte kalan kutular alt eşikteki kümede de
aynen kalır; süzme, o eşikle yeniden çalıştırmayla aynı sonucu verir).

Manifest: `[{"video": "yol", "label": "fire"|"smoke"|"none", "start": sn (isteğe bağlı, varsayılan 0)}]`; yollar
manifest dosyasının klasörüne göredir. `label` videodaki olaydır (`none`: negatif video), `start` olayın görünmeye
başladığı an. Pozitif videoda olay türündeki ilk alarm `start ≤ t ≤ start + 15 sn` ise yakalanmıştır; diğer türdeki alarm
(alevli videoda duman) yanlış sayılmaz; `start`'tan önceki her alarm "olaydan önce" diye ayrıca sayılır. Negatif
videodaki her alarm yanlış alarmdır.

Kabul (v1): mAP50 (iki sınıf ortalaması) ≥ 0,60; Normal hassasiyette pozitif videoların ≥ %80'i 15 sn içinde alarm;
Normal hassasiyette negatif videolarda 0 yanlış alarm. Çıkış kodu: 0 geçti, 1 kaldı, 2 girdi hatası. Çıktı Türkçe
Markdown (ekrana ve `--out`). Veriler ve ölçüm dosyaları depoya konmaz.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import pathlib
import statistics
import sys
from collections.abc import Callable, Iterable, Iterator
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "edge"))

KINDS = ("fire", "smoke")                       # COCO kategori kimliği = sıra + 1 (prepare_data ile aynı)
NAMES = {"fire": "Yangın", "smoke": "Duman"}
LABELS = (*KINDS, "none")
SENSITIVITIES = ("low", "normal", "high")
SENS_NAMES = {"low": "Düşük", "normal": "Normal", "high": "Yüksek"}
MAP50_MIN = 0.60
POSITIVE_RATE_MIN = 0.80
ALARM_LIMIT_S = 15.0
MAX_FPS = 5.0                                   # core/fire_rules.py MAX_FPS ile aynı (testte denetlenir)
IOU_MATCH = 0.5
IMAGE_CONF = 0.01                               # görüntü düzeyi AP için düşük eşik (eğri tümüyle çıksın)
SWEEP = tuple(round(0.25 + 0.05 * i, 2) for i in range(12))      # 0,25 … 0,80
CACHE_FLOOR = SWEEP[0]                          # olay düzeyi tespit saklama eşiği (en düşük önayar eşiğinin altında)
LOW_STEP, HIGH_STEP = 0.15, 0.10                # bugünkü THRESHOLDS aralığı: düşük = normal + 0,15, yüksek = normal − 0,10
EPS = 1e-9
MANIFEST_FORMAT = '[{"video": "yol", "label": "fire"|"smoke"|"none", "start": saniye (isteğe bağlı)}]'


class InputError(Exception):
    """Ölçüme başlanamaz (manifest/COCO/model/video); ileti kullanıcıya gösterilir."""


# ---------------------------------------------------------------- (a) görüntü düzeyi

Box = tuple[float, float, float, float]          # COCO bbox: x, y, w, h


def iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def match(gts: dict[int, list[Box]], dets: list[tuple[int, float, Box]], thr: float = IOU_MATCH) -> list[bool]:
    """Tek sınıf: tespitler skora göre azalan sırayla aynı görüntüdeki eşleşmemiş en yüksek IoU'lu (≥ `thr`) kutuya
    eşlenir. Döner: sıralı tespitlerin doğru (True) / yanlış (False) bayrakları."""
    used: dict[int, set[int]] = {}
    flags: list[bool] = []
    for img, _score, box in sorted(dets, key=lambda d: -d[1]):
        best, best_iou = -1, thr - EPS
        for j, g in enumerate(gts.get(img, [])):
            if j in used.get(img, set()):
                continue
            v = iou(box, g)
            if v >= best_iou:
                best, best_iou = j, v
        if best >= 0:
            used.setdefault(img, set()).add(best)
        flags.append(best >= 0)
    return flags


def ap11(flags: list[bool], n_gt: int) -> float | None:
    """PASCAL VOC 11 nokta AP: r ∈ {0, 0,1, …, 1} için geri çağırma ≥ r olan noktalardaki en yüksek kesinliğin ortalaması.
    Gerçek kutu yoksa None."""
    if n_gt <= 0:
        return None
    tp = fp = 0
    points: list[tuple[float, float]] = []
    for f in flags:
        tp, fp = tp + f, fp + (not f)
        points.append((tp / n_gt, tp / (tp + fp)))
    total = 0.0
    for i in range(11):
        r = i / 10
        total += max((p for rec, p in points if rec >= r - EPS), default=0.0)
    return total / 11


def _box(b: list[float]) -> Box:
    return float(b[0]), float(b[1]), float(b[2]), float(b[3])


def simple_ap50(coco: dict[str, Any], dets: list[dict[str, Any]]) -> dict[str, float | None]:
    """Sınıf başına 11 nokta AP50 (`iscrowd` kutuları sayılmaz)."""
    out: dict[str, float | None] = {}
    for i, kind in enumerate(KINDS):
        cat = i + 1
        gts: dict[int, list[Box]] = {}
        for a in coco.get("annotations", []):
            if a["category_id"] == cat and not a.get("iscrowd"):
                gts.setdefault(a["image_id"], []).append(_box(a["bbox"]))
        cdets = [(d["image_id"], float(d["score"]), _box(d["bbox"])) for d in dets if d["category_id"] == cat]
        out[kind] = ap11(match(gts, cdets), sum(len(v) for v in gts.values()))
    return out


def coco_ap50(coco: dict[str, Any], dets: list[dict[str, Any]]) -> dict[str, float | None]:
    """pycocotools COCOeval ile sınıf başına AP50 (101 nokta). pycocotools yoksa ImportError."""
    import contextlib as _cl
    import io

    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval

    gt = COCO()
    gt.dataset = coco
    with _cl.redirect_stdout(io.StringIO()):
        gt.createIndex()
        dt = gt.loadRes(dets) if dets else None
    out: dict[str, float | None] = {}
    for i, kind in enumerate(KINDS):
        if dt is None:
            out[kind] = 0.0 if any(a["category_id"] == i + 1 for a in coco.get("annotations", [])) else None
            continue
        ev = COCOeval(gt, dt, "bbox")
        ev.params.catIds = [i + 1]
        with _cl.redirect_stdout(io.StringIO()):
            ev.evaluate()
            ev.accumulate()
            ev.summarize()
        out[kind] = None if ev.stats[1] < 0 else float(ev.stats[1])
    return out


def ap50(coco: dict[str, Any], dets: list[dict[str, Any]], use_pycocotools: bool = True) -> tuple[dict[str, Any], str]:
    """Sınıf başına AP50 + `mean` (yalnız gerçek kutusu olan sınıflar); ikinci değer yöntem adı."""
    res: dict[str, float | None] | None = None
    method = "11 nokta AP (pycocotools yok)"
    if use_pycocotools:
        try:
            res, method = coco_ap50(coco, dets), "pycocotools COCOeval (101 nokta)"
        except ImportError:
            res = None
    if res is None:
        res = simple_ap50(coco, dets)
    vals = [v for v in res.values() if v is not None]
    return {**res, "mean": sum(vals) / len(vals) if vals else None}, method


def read_coco(path: pathlib.Path) -> dict[str, Any]:
    try:
        coco = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise InputError(f"COCO dosyası okunamadı: {path.name} ({e})") from e
    if not isinstance(coco, dict) or not isinstance(coco.get("images"), list):
        raise InputError(f"COCO dosyası biçimsiz (images listesi yok): {path.name}")
    return coco


def predict_images(coco: dict[str, Any], base: pathlib.Path, detector: Any) -> list[dict[str, Any]]:
    """Her görüntüde model (`IMAGE_CONF` eşiğiyle) → COCO sonuç listesi. `file_name` göreliyse `base`'e göredir."""
    import cv2

    dets: list[dict[str, Any]] = []
    for im in coco["images"]:
        p = pathlib.Path(im["file_name"])
        bgr = cv2.imread(str(p if p.is_absolute() else base / p))
        if bgr is None:
            raise InputError(f"Görüntü açılamadı: {p.name}")
        for d in detector.detect(bgr, {k: IMAGE_CONF for k in KINDS}):
            dets.append({"image_id": im["id"], "category_id": KINDS.index(d.cls) + 1, "score": round(float(d.score), 5),
                         "bbox": [round(float(d.x1), 2), round(float(d.y1), 2), round(float(d.x2 - d.x1), 2),
                                  round(float(d.y2 - d.y1), 2)]})
    return dets


# ---------------------------------------------------------------- (b) olay düzeyi

def check_manifest(data: Any, base: pathlib.Path) -> list[dict[str, Any]]:
    if not isinstance(data, list) or not data:
        raise InputError(f"Manifest boş ya da liste değil; biçim: {MANIFEST_FORMAT}")
    out: list[dict[str, Any]] = []
    for i, e in enumerate(data, 1):
        if not isinstance(e, dict) or set(e) - {"video", "label", "start"} or "video" not in e or "label" not in e:
            raise InputError(f"Manifest kaydı {i} biçimsiz; biçim: {MANIFEST_FORMAT}")
        if e["label"] not in LABELS:
            raise InputError(f"Manifest kaydı {i}: bilinmeyen label {e['label']!r} (fire | smoke | none)")
        start = e.get("start", 0)
        if isinstance(start, bool) or not isinstance(start, (int, float)) or not math.isfinite(start) or start < 0:
            raise InputError(f"Manifest kaydı {i}: start sıfır ya da pozitif bir saniye olmalı")
        video = base / str(e["video"])
        if not video.is_file():
            raise InputError(f"Manifest kaydı {i}: video bulunamadı: {video.name}")
        out.append({"video": video, "label": e["label"], "start": float(start)})
    return out


def read_manifest(path: pathlib.Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise InputError(f"Manifest okunamadı: {path.name} ({e})") from e
    return check_manifest(data, path.parent)


def alarms_from_frames(frames: Iterable[tuple[float, Any]], analyzer: Any, profile: Any,
                       max_fps: float = MAX_FPS) -> list[tuple[float, str]]:
    """Kareleri (video zamanı, kare) canlı oturumdaki gibi en çok `max_fps` hızla analizöre verir: son analiz edilen
    kareden `1 / max_fps` sn dolmadan gelen kare atlanır (live/session.py `_fire_due`, video.py ile aynı kural). Döner:
    doğan alarmlar (zaman, tür)."""
    alarms: list[tuple[float, str]] = []
    last: float | None = None
    for t, frame in frames:
        if last is not None and last <= t < last + 1.0 / max_fps - 1e-6:
            continue
        last = t
        r = analyzer.process(frame, t, profile)
        alarms += [(float(a.ts), str(a.kind)) for a in r.fired]
    return alarms


def video_frames(path: pathlib.Path) -> Iterator[tuple[float, Any]]:
    """(kare no / fps, BGR kare); fps okunamazsa InputError."""
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise InputError(f"Video açılamadı: {path.name}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if not math.isfinite(fps) or fps <= 0 or fps > 240:
        cap.release()
        raise InputError(f"Videonun kare hızı okunamadı: {path.name}")
    try:
        n = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            yield n / fps, frame
            n += 1
    finally:
        cap.release()


def video_outcome(label: str, start: float, alarms: list[tuple[float, str]],
                  limit: float = ALARM_LIMIT_S) -> dict[str, Any]:
    """Tek videonun sonucu: `first` olay türündeki ilk alarmın `start`'tan gecikmesi (yoksa None), `caught` ≤ `limit`,
    `false` negatif videoda tüm alarmlar, `before` pozitif videoda `start`'tan önceki alarmlar."""
    if label == "none":
        return {"label": label, "first": None, "caught": False, "false": len(alarms), "before": 0}
    delays = sorted(t - start for t, k in alarms if k == label and t >= start - EPS)
    first = max(0.0, delays[0]) if delays else None
    return {"label": label, "first": first, "caught": first is not None and first <= limit + EPS, "false": 0,
            "before": sum(1 for t, _k in alarms if t < start - EPS)}


def aggregate(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    """Videoların sonuçlarını toplar: pozitif sayısı, yakalanan, oran, ilk alarm ortanca/en geç (yakalananlarda), tür
    başına (pozitif, yakalanan), negatif sayısı, negatiflerdeki yanlış alarm, pozitiflerde olaydan önceki alarm."""
    pos = [o for o in outcomes if o["label"] != "none"]
    neg = [o for o in outcomes if o["label"] == "none"]
    firsts = [o["first"] for o in pos if o["caught"]]
    return {
        "positives": len(pos), "caught": sum(o["caught"] for o in pos),
        "rate": sum(o["caught"] for o in pos) / len(pos) if pos else None,
        "medianFirst": statistics.median(firsts) if firsts else None, "maxFirst": max(firsts) if firsts else None,
        "byLabel": {k: (sum(1 for o in pos if o["label"] == k), sum(o["caught"] for o in pos if o["label"] == k))
                    for k in KINDS},
        "negatives": len(neg), "false": sum(o["false"] for o in neg), "before": sum(o["before"] for o in pos),
    }


# ---------------------------------------------------------------- (c) eşik kalibrasyonu

def suggest(sweep: dict[float, dict[str, Any]]) -> dict[str, float] | None:
    """Tek sınıfın eşik taraması (`eşik → aggregate`): negatiflerde sıfır yanlış alarm veren en düşük eşik Normal,
    Düşük = Normal + 0,15 (en çok 0,95), Yüksek = Normal − 0,10 (en az `CACHE_FLOOR`). Hiçbiri sıfır değilse None."""
    ok = sorted(t for t, agg in sweep.items() if agg["false"] == 0)
    if not ok:
        return None
    n = ok[0]
    return {"low": round(min(0.95, n + LOW_STEP), 2), "normal": n, "high": round(max(CACHE_FLOOR, n - HIGH_STEP), 2)}


# ---------------------------------------------------------------- oynatma (gerçek analizör)

class DetectionCache:
    """Video başına analiz edilen karelerin tespitleri (`CACHE_FLOOR` eşiğiyle). `detector(key)` bir oynatma için
    dedektör verir: o videonun i. çağrısı saklanan i. sonucu süzer, yoksa modeli çalıştırıp saklar. Aynı video aynı
    hızla oynatıldığından çağrı sırası karelerle birebirdir."""

    def __init__(self, model: Any, floor: float = CACHE_FLOOR) -> None:
        self.model = model
        self.floor = floor
        self.store: dict[str, list[list[Any]]] = {}

    def detector(self, key: str) -> Any:
        frames = self.store.setdefault(key, [])
        model, floor = self.model, self.floor

        class _Replay:
            i = 0

            def detect(self, bgr: Any, conf: dict[str, float]) -> list[Any]:
                if self.i < len(frames):
                    dets = frames[self.i]
                else:
                    dets = model.detect(bgr, {k: floor for k in KINDS})
                    frames.append(dets)
                self.i += 1
                return [d for d in dets if d.cls in conf and d.score >= conf[d.cls]]

        return _Replay()


@contextlib.contextmanager
def thresholds(values: dict[str, float]) -> Iterator[str]:
    """Geçici hassasiyet anahtarı: `core/fire_rules.py` `THRESHOLDS`'a "eval" eklenir (verilmeyen sınıf 1,0), çıkışta
    silinir. Döner: profilde kullanılacak hassasiyet adı."""
    from bantvision.core import fire_rules

    fire_rules.THRESHOLDS["eval"] = {k: values.get(k, 1.0) for k in KINDS}
    try:
        yield "eval"
    finally:
        fire_rules.THRESHOLDS.pop("eval", None)


def fire_profile(sensitivity: str, only: str | None = None) -> Any:
    """Varsayılan yangın profili (alev 3 sn, duman 8 sn); `only` verilirse yalnız o sınıfın kuralı açık."""
    from bantvision.core import Profile

    p = Profile.fire_watch()
    p.fire.sensitivity = sensitivity
    if only is not None:
        for k in KINDS:
            getattr(p.fire, k).enabled = k == only
    return p


def play(entries: list[dict[str, Any]], cache: DetectionCache, profile: Any,
         frames: Callable[[pathlib.Path], Iterable[tuple[float, Any]]] = video_frames) -> list[dict[str, Any]]:
    """Her videoyu gerçek `FireAnalyzer` ile oynatır; video başına sonuç (`video_outcome`)."""
    from bantvision.core.fire import FireAnalyzer

    out = []
    for e in entries:
        an = FireAnalyzer(detector=cache.detector(str(e["video"])))
        alarms = alarms_from_frames(frames(e["video"]), an, profile)
        out.append(video_outcome(e["label"], e["start"], alarms))
    return out


# ---------------------------------------------------------------- rapor

def num(x: float | None, d: int = 3) -> str:
    return "—" if x is None else f"{x:.{d}f}".replace(".", ",")


def pct(x: float | None) -> str:
    return "—" if x is None else "%" + f"{100 * x:.1f}".replace(".", ",")


def gates(image: dict[str, Any] | None, normal: dict[str, Any] | None) -> list[tuple[str, bool]]:
    """Kabul satırları (metin, geçti mi). Ölçülmeyen bölümün kapısı yazılmaz."""
    g: list[tuple[str, bool]] = []
    if image is not None:
        m = image["mean"]
        g.append((f"mAP50 (iki sınıf ortalaması) ≥ {num(MAP50_MIN, 2)}: {num(m)}", m is not None and m >= MAP50_MIN))
    if normal is not None:
        r = normal["rate"]
        pos_text = (f"Normal hassasiyette pozitif videoların ≥ {pct(POSITIVE_RATE_MIN)}'i {ALARM_LIMIT_S:g} sn içinde "
                    f"alarm: {pct(r)} ({normal['caught']}/{normal['positives']})")
        g.append((pos_text, r is not None and r >= POSITIVE_RATE_MIN - EPS))
        neg_text = (f"Normal hassasiyette negatif videolarda 0 yanlış alarm: {normal['false']} "
                    f"({normal['negatives']} video)")
        g.append((neg_text, normal["negatives"] > 0 and normal["false"] == 0))
    return g


def markdown(model: str, sha: str, image: tuple[dict[str, Any], str, dict[str, int]] | None,
             events: dict[str, dict[str, Any]] | None, sweeps: dict[str, dict[float, dict[str, Any]]] | None) -> str:
    lines = ["# Yangın/duman modeli ölçümü", "", f"Model: `{model}` — SHA-256 `{sha}`", ""]
    if image is not None:
        res, method, n_gt = image
        lines += ["## Görüntü düzeyi (mAP50)", "", f"Yöntem: {method}; IoU ≥ {num(IOU_MATCH, 2)}.", "",
                  "| Sınıf | AP50 | Gerçek kutu |", "|---|---|---|"]
        lines += [f"| {NAMES[k]} | {num(res[k])} | {n_gt[k]} |" for k in KINDS]
        lines += [f"| **Ortalama (mAP50)** | **{num(res['mean'])}** | |", ""]
    if events is not None:
        lines += ["## Olay düzeyi (videolar, varsayılan kurallar: alev 3 sn, duman 8 sn)", "",
                  (f"| Hassasiyet | Pozitif video | {ALARM_LIMIT_S:g} sn içinde alarm | Yangın | Duman | İlk alarm "
                   "(ortanca / en geç, sn) | Negatif video | Yanlış alarm | Olaydan önce alarm |"),
                  "|---|---|---|---|---|---|---|---|---|"]
        for s in SENSITIVITIES:
            a = events[s]
            by = {k: f"{a['byLabel'][k][1]}/{a['byLabel'][k][0]}" for k in KINDS}
            lines.append(f"| {SENS_NAMES[s]} | {a['positives']} | {pct(a['rate'])} ({a['caught']}) | {by['fire']} | "
                         f"{by['smoke']} | {num(a['medianFirst'], 1)} / {num(a['maxFirst'], 1)} | {a['negatives']} | "
                         f"{a['false']} | {a['before']} |")
        lines.append("")
    if sweeps is not None:
        lines += ["## Eşik kalibrasyonu (öneri)", "",
                  ("Sınıf başına tek kural açıkken eşik taraması. Normal önerisi: negatif videolarda sıfır yanlış "
                   "alarm veren en düşük eşik; Düşük/Yüksek bugünkü aralıkla (+0,15 / −0,10)."), "",
                  "| Sınıf | Eşik | Pozitif oran | Yanlış alarm |", "|---|---|---|---|"]
        for k in KINDS:
            for t, a in sorted(sweeps[k].items()):
                lines.append(f"| {NAMES[k]} | {num(t, 2)} | {pct(a['rate'])} | {a['false']} |")
        lines.append("")
        for k in KINDS:
            sg = suggest(sweeps[k])
            lines.append(f"- {NAMES[k]}: " + ("hiçbir eşikte sıfır yanlış alarm yok; eşik önerilmez" if sg is None else
                                              f"Düşük {num(sg['low'], 2)}, Normal {num(sg['normal'], 2)}, "
                                              f"Yüksek {num(sg['high'], 2)}"))
        lines.append("")
    g = gates(image[0] if image is not None else None, events["normal"] if events is not None else None)
    lines += ["## Kabul (v1)", ""] + [f"- {'GEÇTİ' if ok else 'KALDI'} — {text}" for text, ok in g]
    lines += ["", "Sonuç: " + ("GEÇTİ" if g and all(ok for _t, ok in g) else "KALDI")]
    return "\n".join(lines) + "\n"


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Yangın/duman modeli ölçümü (görüntü ve olay düzeyi)")
    ap.add_argument("--model", required=True, help="ONNX model dosyası")
    ap.add_argument("--coco", help="COCO gerçek kutular (ör. instances_test.json)")
    ap.add_argument("--manifest", help=f"video listesi: {MANIFEST_FORMAT}")
    ap.add_argument("--device", default="auto", help="auto | cpu | kart kimliği (Cihaz ayarları)")
    ap.add_argument("--out", help="Markdown raporunun yazılacağı dosya")
    ap.add_argument("--no-calibrate", action="store_true", help="eşik taramasını atla")
    a = ap.parse_args(argv)
    model_path = pathlib.Path(a.model)
    try:
        if not a.coco and not a.manifest:
            raise InputError("--coco ya da --manifest (ya da ikisi) gerekli")
        if not model_path.is_file():
            raise InputError(f"Model dosyası bulunamadı: {model_path.name}")
        coco = read_coco(pathlib.Path(a.coco)) if a.coco else None
        entries = read_manifest(pathlib.Path(a.manifest)) if a.manifest else None

        from bantvision.core.fire_model import FireDetector

        detector = FireDetector(path=model_path, device=a.device)
        image = None
        if coco is not None:
            dets = predict_images(coco, pathlib.Path(a.coco).parent, detector)
            res, method = ap50(coco, dets)
            n_gt = {k: sum(1 for x in coco.get("annotations", []) if x["category_id"] == i + 1)
                    for i, k in enumerate(KINDS)}
            image = (res, method, n_gt)
        events = sweeps = None
        if entries is not None:
            cache = DetectionCache(detector)
            events = {s: aggregate(play(entries, cache, fire_profile(s))) for s in SENSITIVITIES}
            if not a.no_calibrate:
                sweeps = {}
                for k in KINDS:                       # yalnız bu türün pozitifleri ve negatifler
                    sub = [e for e in entries if e["label"] in (k, "none")]
                    sweeps[k] = {}
                    for t in SWEEP:
                        with thresholds({k: t}) as sens:
                            sweeps[k][t] = aggregate(play(sub, cache, fire_profile(sens, only=k)))
    except InputError as e:
        print(f"Hata: {e}", file=sys.stderr)
        return 2
    text = markdown(model_path.name, sha256_file(model_path), image, events, sweeps)
    print(text)
    if a.out:
        pathlib.Path(a.out).write_text(text, encoding="utf-8")
    g = gates(image[0] if image else None, events["normal"] if events else None)
    return 0 if g and all(ok for _t, ok in g) else 1


if __name__ == "__main__":
    sys.exit(main())
