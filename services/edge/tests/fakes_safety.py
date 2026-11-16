"""Poz güvenlik testlerinin ortak sahteleri (model gerektirmez, ağ yok); `tests/` paket değil, pytest dizini yola ekler:
`from fakes_safety import FakeDetector, FakePose, hands_up_kp` (telefon: `FakePhoneDetector`, `phone_kp`). test_safety.py ve test_live.py kullanır (canlı oturumda
sahteler oturum açılmadan önce `manager.detector` / `manager.pose`'a konur)."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np


class FakeDetector:
    """Her karede verilen piksel kutularını kişi olarak döndürür."""

    def __init__(self, boxes: list[tuple[float, float, float, float]]) -> None:
        self.boxes = boxes

    def detect(self, crop: np.ndarray, _classes: object, conf: float = 0.15) -> list[object]:
        return [SimpleNamespace(x1=b[0], y1=b[1], x2=b[2], y2=b[3], score=0.9, cls="person") for b in self.boxes]


class FakePose:
    """Kutudan bağımsız sabit eklemler (17×3 piksel); `kp` testte değiştirilir (None: model hazır değil);
    `calls` çağrı sayısı."""

    def __init__(self, kp: np.ndarray | None) -> None:
        self.kp = kp
        self.calls = 0

    def estimate(self, _bgr: np.ndarray, _box: object) -> np.ndarray | None:
        self.calls += 1
        return self.kp


def hands_up_kp() -> np.ndarray:
    kp = np.zeros((17, 3))
    pts = {0: (320, 120), 5: (300, 170), 6: (340, 170), 7: (290, 160), 8: (350, 160), 9: (290, 100),
           10: (350, 100), 11: (305, 330), 12: (335, 330)}
    for i, (x, y) in pts.items():
        kp[i] = (x, y, 0.9)
    return kp


class FakePhoneDetector:
    """Sınıfa duyarlı sahte: "person" isteyen çağrıya verilen piksel kutularını kişi, "cell phone" isteyen çağrıya
    `phones` kutularını telefon olarak döndürür. Telefon kutuları **kırpıntıya göre** piksel (x1, y1, x2, y2, skor):
    `find_phones` kırpıntıyı tam kareye kendisi taşır. `calls` her çağrının sınıf listesi, `shapes` gelen görüntü
    şekli, `confs` güven eşiği."""

    def __init__(self, boxes: list[tuple[float, float, float, float]],
                 phones: list[tuple[float, float, float, float, float]] | None = None) -> None:
        self.boxes = boxes
        self.phones = phones or []
        self.calls: list[list[str]] = []
        self.shapes: list[tuple[int, ...]] = []
        self.confs: list[float] = []

    def detect(self, crop: np.ndarray, classes: list[str], conf: float = 0.15) -> list[object]:
        self.calls.append(list(classes))
        self.shapes.append(tuple(crop.shape))
        self.confs.append(conf)
        out: list[object] = []
        if "person" in classes:
            out += [SimpleNamespace(x1=b[0], y1=b[1], x2=b[2], y2=b[3], score=0.9, cls="person") for b in self.boxes]
        if "cell phone" in classes:
            out += [SimpleNamespace(x1=p[0], y1=p[1], x2=p[2], y2=p[3], score=p[4], cls="cell phone")
                    for p in self.phones]
        return out

    @property
    def phone_calls(self) -> int:
        return sum("cell phone" in c for c in self.calls)


def phone_kp() -> np.ndarray:
    """Ayakta, eller göğüs hizasında (eller yukarı / yatma değil). Ölçek omuz ortası–kalça ortası = 160 px;
    sol bilek (290, 260), sağ bilek (350, 260), burun (320, 120)."""
    kp = np.zeros((17, 3))
    pts = {0: (320, 120), 5: (300, 170), 6: (340, 170), 7: (285, 240), 8: (355, 240), 9: (290, 260),
           10: (350, 260), 11: (305, 330), 12: (335, 330)}
    for i, (x, y) in pts.items():
        kp[i] = (x, y, 0.9)
    return kp
