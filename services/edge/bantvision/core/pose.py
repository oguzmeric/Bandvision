"""Poz tahmini: MoveNet SinglePose Thunder (Google, Apache-2.0), ONNX Runtime (CPU). Kişi kutusu başına çalışır.

Kutu 1,25× genişletilip kareye çevrilir (dışı siyah), 256×256 RGB int32 girdi; çıkış 17×(y, x, güven) normalize →
görüntü pikseline geri çevrilir. Model ilk kullanımda GitHub sürümünden indirilir, SHA-256 doğrulanır.
"""
from __future__ import annotations

import contextlib
import os
import pathlib
import time
import urllib.request

import cv2
import numpy as np

from .detector import _sha256
from .pose_model import INPUT_SIZE, MODEL_NAME, MODEL_SHA256, MODEL_URL

Crop = tuple[float, float, float]


def square_crop(box_px: tuple[float, float, float, float], pad: float = 1.25) -> Crop:
    x1, y1, x2, y2 = box_px
    side = max(x2 - x1, y2 - y1) * pad
    return (x1 + x2) / 2 - side / 2, (y1 + y2) / 2 - side / 2, side


def make_input(bgr: np.ndarray, crop: Crop) -> np.ndarray:
    x0, y0, side = crop
    s = max(1, round(side))
    canvas = np.zeros((s, s, 3), np.uint8)
    h, w = bgr.shape[:2]
    ix0, iy0 = round(x0), round(y0)
    sx0, sy0, sx1, sy1 = max(0, ix0), max(0, iy0), min(w, ix0 + s), min(h, iy0 + s)
    if sx1 > sx0 and sy1 > sy0:
        canvas[sy0 - iy0:sy1 - iy0, sx0 - ix0:sx1 - ix0] = bgr[sy0:sy1, sx0:sx1]
    img = cv2.resize(canvas, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_LINEAR)
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


DOWNLOAD_TIMEOUT_S = 30.0               # bağlanma ve her okuma için (takılan ağ sonsuza dek beklemez)
DOWNLOAD_DEADLINE_S = 300.0             # tüm indirme için üst sınır (yavaş damlayan bağlantı da biter)
_CHUNK = 1 << 16


def _download(url: str, dest: pathlib.Path, deadline_s: float) -> None:
    end = time.monotonic() + deadline_s
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_S) as resp, dest.open("wb") as fh:
        while chunk := resp.read(_CHUNK):
            if time.monotonic() > end:
                raise TimeoutError(f"Poz modeli {deadline_s:.0f} sn içinde indirilemedi.")
            fh.write(chunk)


def ensure_pose_model(deadline_s: float = DOWNLOAD_DEADLINE_S) -> pathlib.Path:
    """Poz modelini yoksa indirir (akış halinde, zaman aşımlı); parmak izi tutmazsa ya da herhangi bir hatada yarım
    dosyayı (.part) siler ve hata verir."""
    p = pose_model_path()
    if p.exists() and _sha256(p) == MODEL_SHA256:
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".part")
    try:
        _download(MODEL_URL, tmp, deadline_s)
        if _sha256(tmp) != MODEL_SHA256:
            raise RuntimeError("Poz modeli doğrulanamadı (SHA-256 tutmuyor).")
        tmp.replace(p)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise
    return p


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
