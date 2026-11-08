"""Yangın/duman modeli: YOLOX tabanlı, iki sınıf ("fire", "smoke"), ONNX Runtime (core/devices.py).

Model depoda tutulmaz; `FIRE_MODEL_URL` ayarlıysa ilk kullanımda indirilir ve SHA-256 ile doğrulanır, değilse dosyanın
`BANTVISION_MODEL_DIR` altında bulunması gerekir. Çıkış: ham YOLOX ızgarası [1, 8400, 7] = (cx, cy, w, h, nesnelik,
fire, smoke); çözme core/yolox.py'de ortaktır.
"""
from __future__ import annotations

import os
import pathlib
from typing import Any

import numpy as np

from . import devices, yolox
from .detector import Detection
from .model_download import download_verified

MODEL_NAME = "fire_smoke_v1.onnx"
FIRE_MODEL_URL: str | None = None
FIRE_MODEL_SHA256: str | None = None
CLASSES = ("fire", "smoke")
INPUT = yolox.INPUT
NMS_IOU = 0.45


class FireModelMissing(RuntimeError):
    """Yangın/duman model dosyası yok ve indirme adresi tanımlı değil."""


def fire_model_path() -> pathlib.Path:
    base = os.environ.get("BANTVISION_MODEL_DIR") or str(pathlib.Path.home() / ".cache" / "bantvision")
    return pathlib.Path(base) / MODEL_NAME


def ensure_fire_model() -> pathlib.Path:
    """Model dosyası varsa yolunu döndürür; yoksa URL tanımlıysa indirir; yoksa `FireModelMissing`."""
    path = fire_model_path()
    if FIRE_MODEL_URL is None or FIRE_MODEL_SHA256 is None:
        if path.exists():
            return path
        raise FireModelMissing("Yangın/duman modeli kurulu değil.")
    return download_verified(FIRE_MODEL_URL, path, FIRE_MODEL_SHA256, label="Yangın/duman modeli")


class FireDetector:
    def __init__(self, path: pathlib.Path | None = None, device: str | None = None) -> None:
        """`device`: "auto" | "cpu" | kart kimliği; verilmezse süreç varsayılanı (`devices.default_choice()`)."""

        def configure(so: Any) -> None:
            so.intra_op_num_threads = max(1, min(6, (os.cpu_count() or 2) // 2))
            so.add_session_config_entry("session.intra_op.allow_spinning", "0")

        choice = device if device is not None else devices.default_choice()
        self.session = devices.open_session(path or ensure_fire_model(), configure, choice)

    @property
    def used(self) -> devices.Used:
        return self.session.used

    @property
    def broken(self) -> str | None:
        return self.session.broken

    def detect(self, bgr: np.ndarray, conf: dict[str, float]) -> list[Detection]:
        """Piksel koordinatında kutular; `conf` sınıf başına eşik (eksik sınıf işlenmez), NMS sınıf başına."""
        h, w = bgr.shape[:2]
        x, r = yolox.letterbox(bgr, INPUT)
        out = self.session.run(None, {self.session.get_inputs()[0].name: x})[0][0]
        dets: list[Detection] = []
        for i, name in enumerate(CLASSES):
            if name not in conf:
                continue
            for x1, y1, x2, y2, sc, _ in yolox.decode(out, r, w, h, [i], conf[name], NMS_IOU):
                dets.append(Detection(x1, y1, x2, y2, sc, name))
        return dets
