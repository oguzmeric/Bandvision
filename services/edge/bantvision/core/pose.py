"""Poz tahmini: MoveNet SinglePose Thunder (Google, Apache-2.0), ONNX Runtime (CPU). Kişi kutusu başına çalışır.

Kutu 1,25× genişletilip kareye çevrilir (dışı siyah), 256×256 RGB int32 girdi; çıkış 17×(y, x, güven) normalize →
görüntü pikseline geri çevrilir. Model ilk kullanımda GitHub sürümünden indirilir, SHA-256 doğrulanır.
"""
from __future__ import annotations

import os
import pathlib

import cv2
import numpy as np

from .model_download import DOWNLOAD_DEADLINE_S, DOWNLOAD_TIMEOUT_S, download_verified
from .pose_model import INPUT_SIZE, MODEL_NAME, MODEL_SHA256, MODEL_URL

Crop = tuple[float, float, float]


def square_crop(box_px: tuple[float, float, float, float], pad: float = 1.25) -> Crop:
    x1, y1, x2, y2 = box_px
    side = max(x2 - x1, y2 - y1) * pad
    return (x1 + x2) / 2 - side / 2, (y1 + y2) / 2 - side / 2, side


def make_input(bgr: np.ndarray, crop: Crop) -> np.ndarray:
    """Kare kırpma → 256×256 RGB int32. Görüntü içindeki kısım dilimlenir, yalnızca dışarı taşan kenarlar siyahla
    doldurulur (ayrı siyah tuval ayırıp kopyalamak yok); sonuç tam tuvalli eski yöntemle bire bir aynı."""
    x0, y0, side = crop
    s = max(1, round(side))
    h, w = bgr.shape[:2]
    ix0, iy0 = round(x0), round(y0)
    sx0, sy0, sx1, sy1 = max(0, ix0), max(0, iy0), min(w, ix0 + s), min(h, iy0 + s)
    if sx1 <= sx0 or sy1 <= sy0:                                  # kırpma tamamen görüntü dışında: siyah
        return np.zeros((1, INPUT_SIZE, INPUT_SIZE, 3), np.int32)
    sq = cv2.copyMakeBorder(bgr[sy0:sy1, sx0:sx1], sy0 - iy0, iy0 + s - sy1, sx0 - ix0, ix0 + s - sx1,
                            cv2.BORDER_CONSTANT, value=(0, 0, 0))
    img = cv2.resize(sq, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_LINEAR)
    return img[:, :, ::-1].astype(np.int32)[None]


def to_image(out: np.ndarray, crop: Crop) -> np.ndarray:
    x0, y0, side = crop
    kp = np.empty((17, 3))
    kp[:, 0] = x0 + out[:, 1] * side
    kp[:, 1] = y0 + out[:, 0] * side
    kp[:, 2] = out[:, 2]
    return kp


def pose_model_path() -> pathlib.Path:
    base = os.environ.get("BANTVISION_MODEL_DIR") or str(pathlib.Path.home() / ".cache" / "bantvision")
    return pathlib.Path(base) / MODEL_NAME


def ensure_pose_model(deadline_s: float = DOWNLOAD_DEADLINE_S) -> pathlib.Path:
    """Poz modelini yoksa indirir (core/model_download.py: akış halinde, zaman aşımlı, SHA-256 doğrulamalı); herhangi
    bir hatada yarım dosya (.part) silinir ve hata fırlatılır."""
    return download_verified(MODEL_URL, pose_model_path(), MODEL_SHA256, timeout=DOWNLOAD_TIMEOUT_S,
                             deadline=deadline_s, label="Poz modeli")


class PoseEstimator:
    def __init__(self, path: pathlib.Path | None = None) -> None:
        import onnxruntime as ort

        so = ort.SessionOptions()
        so.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 2) // 2))
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self._session = ort.InferenceSession(str(path or ensure_pose_model()), so, providers=["CPUExecutionProvider"])
        self._input = self._session.get_inputs()[0].name

    def estimate(self, bgr: np.ndarray, box_px: tuple[float, float, float, float]) -> np.ndarray:
        crop = square_crop(box_px)
        out = self._session.run(None, {self._input: make_input(bgr, crop)})[0]
        return to_image(np.asarray(out, np.float64).reshape(17, 3), crop)
