"""Nesne tanıma (kişi, araç, hayvan) — docs/03-algorithm.md §4.10.

Hazır YOLOX-S modeli (Megvii, Apache-2.0; COCO sınıfları), ONNX Runtime ile işlemcide ya da ekran kartında (core/devices.py) çalışır (PyTorch gerekmez).
Model depoda tutulmaz: ilk kullanımda resmi sürümden indirilir ve SHA-256 ile doğrulanır. Konum:
`BANTVISION_MODEL_DIR` (varsayılan: kullanıcı önbelleği).
"""
from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass
from typing import Any

import numpy as np

from . import devices, yolox
from .model_download import download_verified

MODEL_NAME = "yolox_s.onnx"
MODEL_URL = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx"
MODEL_SHA256 = "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063"
INPUT = yolox.INPUT

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
    """Modeli yoksa indirir (core/model_download.py: akış halinde, zaman aşımlı, SHA-256 doğrulamalı); herhangi bir
    hatada yarım dosya (.part) silinir ve hata fırlatılır."""
    return download_verified(MODEL_URL, model_path(), MODEL_SHA256, label="Kişi tanıma modeli")


class ObjectDetector:
    def __init__(self, path: pathlib.Path | None = None, device: str | None = None) -> None:
        """`device`: "auto" | "cpu" | kart kimliği; verilmezse süreç varsayılanı (`devices.default_choice()`)."""

        def configure(so: Any) -> None:
            so.intra_op_num_threads = max(1, min(6, (os.cpu_count() or 2) // 2))
            # Boşta dönerek bekleme kapalı: canlı sayımda okuyucu, sunucu ve başka oturumlarla işlemci paylaşılır
            so.add_session_config_entry("session.intra_op.allow_spinning", "0")

        choice = device if device is not None else devices.default_choice()
        self.session = devices.open_session(path or ensure_model(), configure, choice)

    @property
    def used(self) -> devices.Used:
        """Gerçekte çalışan cihaz (ekran kartı ya da işlemci + varsa düşüş notu)."""
        return self.session.used

    @property
    def broken(self) -> str | None:
        """Oturum kalıcı olarak kullanılamıyorsa Türkçe hata iletisi (bkz. `devices.GuardedSession.broken`), yoksa None."""
        return self.session.broken

    def detect(self, bgr: np.ndarray, classes: list[str], conf: float = 0.35, iou: float = 0.45) -> list[Detection]:
        """Görüntü koordinatında (piksel) kutular; yalnızca istenen sınıflar."""
        h, w = bgr.shape[:2]
        x, r = yolox.letterbox(bgr, INPUT)
        out = self.session.run(None, {self.session.get_inputs()[0].name: x})[0][0]
        names = [c for c in classes if c in CLASS_IDS]
        ids = [CLASS_IDS[c] for c in names]
        return [Detection(x1, y1, x2, y2, sc, names[c])
                for x1, y1, x2, y2, sc, c in yolox.decode(out, r, w, h, ids, conf, iou)]
