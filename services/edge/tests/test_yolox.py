"""Ortak YOLOX çözme: ObjectDetector çıktısı eski (donmuş) çözümle aynı kalır (R3)."""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np
import pytest

from bantvision.core import yolox
from bantvision.core.detector import CLASS_IDS, ObjectDetector


def _old_grids(size: int) -> tuple[np.ndarray, np.ndarray]:
    grids, strides = [], []
    for s in (8, 16, 32):
        n = size // s
        xv, yv = np.meshgrid(np.arange(n), np.arange(n))
        grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
        strides.append(np.full((n * n, 1), s))
    return np.concatenate(grids).astype(np.float32), np.concatenate(strides).astype(np.float32)


def _reference_detect(out: np.ndarray, h: int, w: int, classes: list[str], conf: float,
                      iou: float) -> list[tuple[float, float, float, float, float, str]]:
    """`ObjectDetector.detect`in yolox.py'den önceki hâli (donmuş kopya)."""
    r = min(640 / h, 640 / w)
    grid, stride = _old_grids(640)
    xy = (out[:, :2] + grid) * stride
    wh = np.exp(out[:, 2:4]) * stride
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
    res = []
    for c in np.unique(best):
        m = best == c
        idx = cv2.dnn.NMSBoxes(
            [[float(b[0]), float(b[1]), float(b[2] - b[0]), float(b[3] - b[1])] for b in boxes[m]],
            [float(s) for s in score[m]], conf, iou)
        name = classes[[CLASS_IDS[k] for k in classes].index(ids[int(c)])]
        for i in np.array(idx).reshape(-1):
            b = boxes[m][int(i)]
            res.append((float(b[0]), float(b[1]), float(b[2]), float(b[3]), float(score[m][int(i)]), name))
    return res


def _raw(seed: int, n_cls: int = 80) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out = np.zeros((8400, 5 + n_cls), np.float32)
    out[:, :2] = rng.uniform(-1, 2, (8400, 2))
    out[:, 2:4] = rng.uniform(0.2, 3.2, (8400, 2))
    out[:, 4] = rng.uniform(0, 1, 8400) ** 4
    out[:, 5:] = rng.uniform(0, 1, (8400, n_cls)) ** 3
    return out


class _Session:
    def __init__(self, out: np.ndarray) -> None:
        self.out, self.used, self.broken = out, None, None

    def get_inputs(self) -> list[Any]:
        return [type("I", (), {"name": "images"})()]

    def run(self, names: Any, feeds: Any) -> list[np.ndarray]:
        return [self.out[None]]


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("shape", [(480, 640), (720, 1280), (1080, 1920), (640, 480), (333, 777)])
@pytest.mark.parametrize("classes", [["person"], ["person", "car", "dog"], ["cow", "sheep", "horse", "bus"]])
def test_object_detector_matches_frozen_reference(seed: int, shape: tuple[int, int], classes: list[str],
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    out = _raw(seed)
    h, w = shape
    det = ObjectDetector.__new__(ObjectDetector)
    det.session = _Session(out)                                     # type: ignore[assignment]
    got = det.detect(np.zeros((h, w, 3), np.uint8), classes, conf=0.3, iou=0.45)
    want = _reference_detect(out, h, w, classes, 0.3, 0.45)
    assert want, "tohum anlamlı sayıda aday üretmeli"
    assert [(d.x1, d.y1, d.x2, d.y2, d.score, d.cls) for d in got] == want


def test_object_detector_no_known_class_returns_empty() -> None:
    det = ObjectDetector.__new__(ObjectDetector)
    det.session = _Session(_raw(0))                                 # type: ignore[assignment]
    assert det.detect(np.zeros((480, 640, 3), np.uint8), ["unicorn"]) == []


def test_letterbox_pads_right_bottom_with_114_and_returns_scale() -> None:
    img = np.full((360, 720, 3), 7, np.uint8)
    x, r = yolox.letterbox(img, 640)
    assert x.shape == (1, 3, 640, 640) and x.dtype == np.float32
    assert r == pytest.approx(640 / 720)
    assert x[0, 0, 0, 0] == 7 and x[0, 0, 639, 639] == 114 and x[0, 2, 400, 10] == 114


def test_decode_rescales_to_original_pixels_and_clips() -> None:
    out = np.zeros((8400, 7), np.float32)
    out[:, 4] = 0.0
    out[0, :2] = (0, 0)                      # stride 8, hücre (0,0): merkez (0,0)
    out[0, 2:4] = np.log(40 / 8)             # 40×40 px kutu (girdi uzayı)
    out[0, 4], out[0, 6] = 0.9, 0.8
    res = yolox.decode(out, 0.5, 1280, 720, [0, 1], 0.5, 0.45)
    assert len(res) == 1
    x1, y1, x2, y2, sc, c = res[0]
    assert (x1, y1) == (0.0, 0.0) and x2 == pytest.approx(40.0) and y2 == pytest.approx(40.0)   # (±20)/0.5, sol/üst kırpık
    assert sc == pytest.approx(0.72) and c == 1
