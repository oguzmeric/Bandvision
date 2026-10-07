"""Poz güvenlik testlerinin ortak sahteleri (model gerektirmez); `tests/` paket değil, pytest dizini yola ekler:
`from fakes_safety import FakeDetector, FakePose, hands_up_kp`. Şimdilik test_safety.py kullanır."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np


class FakeDetector:
    """Her karede verilen piksel kutularını kişi olarak döndürür."""

    def __init__(self, boxes: list[tuple[float, float, float, float]]) -> None:
        self.boxes = boxes

    def detect(self, crop: np.ndarray, _classes: object, conf: float = 0.15) -> list[object]:
        return [SimpleNamespace(x1=b[0], y1=b[1], x2=b[2], y2=b[3], score=0.9) for b in self.boxes]


class FakePose:
    """Kutudan bağımsız sabit eklemler (17×3 piksel); `kp` testte değiştirilir; `calls` çağrı sayısı."""

    def __init__(self, kp: np.ndarray) -> None:
        self.kp = kp
        self.calls = 0

    def estimate(self, _bgr: np.ndarray, _box: object) -> np.ndarray:
        self.calls += 1
        return self.kp


def hands_up_kp() -> np.ndarray:
    kp = np.zeros((17, 3))
    pts = {0: (320, 120), 5: (300, 170), 6: (340, 170), 7: (290, 160), 8: (350, 160), 9: (290, 100),
           10: (350, 100), 11: (305, 330), 12: (335, 330)}
    for i, (x, y) in pts.items():
        kp[i] = (x, y, 0.9)
    return kp
