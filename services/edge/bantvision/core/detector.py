"""Nesne tanıma (kişi, araç, hayvan) — docs/03-algorithm.md §4.10.

Hazır YOLOX-S modeli (Megvii, Apache-2.0; COCO sınıfları), ONNX Runtime ile işlemcide çalışır (PyTorch gerekmez).
Model depoda tutulmaz: ilk kullanımda resmi sürümden indirilir ve SHA-256 ile doğrulanır. Konum:
`BANTVISION_MODEL_DIR` (varsayılan: kullanıcı önbelleği).
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import urllib.request
from dataclasses import dataclass

import cv2
import numpy as np

MODEL_NAME = "yolox_s.onnx"
MODEL_URL = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx"
MODEL_SHA256 = "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063"
INPUT = 640

# COCO sınıf kimlikleri (YOLOX çıktısındaki sıra); yalnızca sayımda desteklenenler
CLASS_IDS = {
    "person": 0, "bicycle": 1, "car": 2, "motorcycle": 3, "bus": 5, "truck": 7,
    "bird": 14, "cat": 15, "dog": 16, "horse": 17, "sheep": 18, "cow": 19,
}
# Hazır gruplar (arayüz/analiz seçenekleri)
GROUPS = {
    "people": ["person"],
    "vehicle": ["car", "truck", "bus", "motorcycle", "bicycle"],
    "animal": ["cow", "sheep", "horse", "dog", "cat", "bird"],
}


@dataclass
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    cls: str


def model_path() -> pathlib.Path:
    base = os.environ.get("BANTVISION_MODEL_DIR") or str(pathlib.Path.home() / ".cache" / "bantvision")
    return pathlib.Path(base) / MODEL_NAME


def ensure_model() -> pathlib.Path:
    """Modeli yoksa indirir; parmak izi tutmazsa siler ve hata verir."""
    p = model_path()
    if p.exists() and _sha256(p) == MODEL_SHA256:
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".part")
    urllib.request.urlretrieve(MODEL_URL, tmp)
    if _sha256(tmp) != MODEL_SHA256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("Model dosyası doğrulanamadı (SHA-256 tutmuyor).")
    tmp.replace(p)
    return p


def _sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class ObjectDetector:
    def __init__(self, path: pathlib.Path | None = None) -> None:
        import onnxruntime as ort  # isteğe bağlı bağımlılık (analyzer/detect extra)

        so = ort.SessionOptions()
        so.intra_op_num_threads = max(1, min(6, (os.cpu_count() or 2) // 2))
        # Boşta dönerek bekleme kapalı: canlı sayımda okuyucu, sunucu ve başka oturumlarla işlemci paylaşılır
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.session = ort.InferenceSession(str(path or ensure_model()), so, providers=["CPUExecutionProvider"])
        self._grid, self._stride = _grids(INPUT)

    def detect(self, bgr: np.ndarray, classes: list[str], conf: float = 0.35, iou: float = 0.45) -> list[Detection]:
        """Görüntü koordinatında (piksel) kutular; yalnızca istenen sınıflar."""
        h, w = bgr.shape[:2]
        r = min(INPUT / h, INPUT / w)
        img = np.full((INPUT, INPUT, 3), 114, np.uint8)               # YOLOX: sağ/alt gri dolgu, BGR, 0–255
        img[: round(h * r), : round(w * r)] = cv2.resize(bgr, (round(w * r), round(h * r)),
                                                          interpolation=cv2.INTER_LINEAR)
        x = img.transpose(2, 0, 1)[None].astype(np.float32)
        out = self.session.run(None, {self.session.get_inputs()[0].name: x})[0][0]
        xy = (out[:, :2] + self._grid) * self._stride
        wh = np.exp(out[:, 2:4]) * self._stride
        ids = [CLASS_IDS[c] for c in classes if c in CLASS_IDS]
        if not ids:
            return []
        cls_scores = out[:, 5:][:, ids] * out[:, 4:5]
        best = cls_scores.argmax(1)
        score = cls_scores[np.arange(len(best)), best]
        keep = score >= conf
        if not keep.any():
            return []
        xy, wh, score, best = xy[keep], wh[keep], score[keep], best[keep]
        boxes = np.concatenate([xy - wh / 2, xy + wh / 2], 1) / r
        boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, w)
        boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, h)
        out_dets: list[Detection] = []
        for c in np.unique(best):
            m = best == c
            idx = cv2.dnn.NMSBoxes(
                [[float(b[0]), float(b[1]), float(b[2] - b[0]), float(b[3] - b[1])] for b in boxes[m]],
                [float(s) for s in score[m]], conf, iou)
            name = classes[[CLASS_IDS[k] for k in classes].index(ids[int(c)])]
            for i in np.array(idx).reshape(-1):
                b = boxes[m][int(i)]
                out_dets.append(Detection(float(b[0]), float(b[1]), float(b[2]), float(b[3]),
                                          float(score[m][int(i)]), name))
        return out_dets


def _grids(size: int) -> tuple[np.ndarray, np.ndarray]:
    grids, strides = [], []
    for s in (8, 16, 32):
        n = size // s
        xv, yv = np.meshgrid(np.arange(n), np.arange(n))
        grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
        strides.append(np.full((n * n, 1), s))
    return np.concatenate(grids).astype(np.float32), np.concatenate(strides).astype(np.float32)
