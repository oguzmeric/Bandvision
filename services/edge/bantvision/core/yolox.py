"""YOLOX ortak yardımcıları: letterbox + ham ızgara çıktısı çözme + sınıf başına NMS.

`ObjectDetector` (COCO) ve `FireDetector` (yangın/duman) aynı çıktı düzenini paylaşır: [N, 5 + sınıf] =
(cx, cy, w, h ham, nesnelik, sınıf puanları...), giriş 640×640.
"""
from __future__ import annotations

import functools

import cv2
import numpy as np

INPUT = 640


def letterbox(bgr: np.ndarray, size: int = INPUT) -> tuple[np.ndarray, float]:
    """YOLOX girişi: sağ/alt 114 gri dolgu, BGR, 0–255, [1,3,size,size] float32. Döner: (tensör, ölçek r)."""
    h, w = bgr.shape[:2]
    r = min(size / h, size / w)
    img = np.full((size, size, 3), 114, np.uint8)
    img[: round(h * r), : round(w * r)] = cv2.resize(bgr, (round(w * r), round(h * r)),
                                                      interpolation=cv2.INTER_LINEAR)
    return img.transpose(2, 0, 1)[None].astype(np.float32), r


@functools.lru_cache(maxsize=4)
def grids(size: int) -> tuple[np.ndarray, np.ndarray]:
    gs, strides = [], []
    for s in (8, 16, 32):
        n = size // s
        xv, yv = np.meshgrid(np.arange(n), np.arange(n))
        gs.append(np.stack((xv, yv), 2).reshape(-1, 2))
        strides.append(np.full((n * n, 1), s))
    return np.concatenate(gs).astype(np.float32), np.concatenate(strides).astype(np.float32)


def decode(out: np.ndarray, r: float, w: int, h: int, class_ids: list[int], conf: float,
           iou: float) -> list[tuple[float, float, float, float, float, int]]:
    """`out`: [N, 5+sınıf] ham çıktı. Yalnız `class_ids` sınıfları; sınıf başına NMS. Piksel koordinatı (orijinal
    görüntü, `r` ile geri ölçeklenmiş ve görüntüye kırpılmış). Döner: (x1, y1, x2, y2, skor, `class_ids` içindeki sıra)."""
    if not class_ids:
        return []
    grid, stride = grids(INPUT)
    xy = (out[:, :2] + grid) * stride
    wh = np.exp(out[:, 2:4]) * stride
    cls_scores = out[:, 5:][:, class_ids] * out[:, 4:5]
    best = cls_scores.argmax(1)
    score = cls_scores[np.arange(len(best)), best]
    keep = score >= conf
    if not keep.any():
        return []
    xy, wh, score, best = xy[keep], wh[keep], score[keep], best[keep]
    boxes = np.concatenate([xy - wh / 2, xy + wh / 2], 1) / r
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, w)
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, h)
    res: list[tuple[float, float, float, float, float, int]] = []
    for c in np.unique(best):
        m = best == c
        idx = cv2.dnn.NMSBoxes(
            [[float(b[0]), float(b[1]), float(b[2] - b[0]), float(b[3] - b[1])] for b in boxes[m]],
            [float(s) for s in score[m]], conf, iou)
        for i in np.array(idx).reshape(-1):
            b = boxes[m][int(i)]
            res.append((float(b[0]), float(b[1]), float(b[2]), float(b[3]), float(score[m][int(i)]), int(c)))
    return res
