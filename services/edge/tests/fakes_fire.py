"""Yangın/duman testlerinin ortak sahteleri (model gerektirmez, ağ yok); `tests/` paket değil, pytest dizini yola ekler:
`from fakes_fire import FakeFireDetector, run`.

Sahte dedektör bir betikten (kare zamanı → kutu listesi) okur; `run` aynı betikle sentetik kareyi çizer: düz gri zemin,
"hareketli" kutunun içi her kare değişen gürültü, "durağan" kutunun içi sabit desen (alev resmi / kırmızı lamba).
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np

from bantvision.core.detector import Detection
from bantvision.core.fire import FireAnalyzer, FireResult
from bantvision.core.profile import Profile

W, H = 640, 480
BG = 110

PxBox = tuple[float, float, float, float]
Item = tuple[str, PxBox, float, bool]                  # (sınıf, piksel kutu, skor, hareketli mi)
Script = Callable[[float], list[Item]]


class FakeFireDetector:
    """`ts` (koşucu her kareden önce yazar) için betiğin kutularını döndürür; gerçek dedektör gibi `conf`'ta olmayan
    sınıfı ve eşik altı skoru atar. `calls`: her çağrının `conf` sözlüğü."""

    def __init__(self, script: Script) -> None:
        self.script = script
        self.ts = 0.0
        self.calls: list[dict[str, float]] = []

    def detect(self, _bgr: np.ndarray, conf: dict[str, float]) -> list[Detection]:
        self.calls.append(dict(conf))
        return [Detection(b[0], b[1], b[2], b[3], s, c) for c, b, s, _m in self.script(self.ts)
                if c in conf and s >= conf[c]]


def scene(items: list[Item], rng: np.random.Generator, flash: int = 0, grain: int = 0) -> np.ndarray:
    f = np.full((H, W, 3), BG, np.int16)
    if grain:                                          # sıkıştırma gürültüsü: 8×8 bloklar her kare ±grain oynar
        n = (rng.integers(0, 2, (H // 8, W // 8, 1)) * 2 - 1).astype(np.int16) * grain
        f += np.repeat(np.repeat(n, 8, 0), 8, 1)
    for _c, (x1, y1, x2, y2), _s, moving in items:
        xa, ya, xb, yb = int(x1), int(y1), int(x2), int(y2)
        if moving:
            f[ya:yb, xa:xb] = rng.integers(0, 256, (yb - ya, xb - xa, 3))
        else:                                          # mutlak koordinatta sabit dama deseni: her karede aynı
            yy, xx = np.mgrid[ya:yb, xa:xb]
            f[ya:yb, xa:xb] = ((((yy // 8) + (xx // 8)) % 2) * 160 + 40)[..., None]
    return np.clip(f + flash, 0, 255).astype(np.uint8)


def run(an: FireAnalyzer, det: FakeFireDetector, profile: Profile, fps: float, t0: float, t1: float,
        flash: Callable[[float], int] | None = None, seed: int = 0, grain: int = 0) -> list[tuple[float, FireResult]]:
    """[t0, t1) aralığında `fps` hızında kareler; her karede (ts, sonuç)."""
    rng = np.random.default_rng(seed)
    out: list[tuple[float, FireResult]] = []
    for k in range(round(t0 * fps), round(t1 * fps)):
        ts = k / fps
        det.ts = ts
        frame = scene(det.script(ts), rng, flash(ts) if flash else 0, grain)
        out.append((ts, an.process(frame, ts, profile)))
    return out


def make(script: Script, profile: Profile | None = None) -> tuple[FireAnalyzer, FakeFireDetector, Profile]:
    det = FakeFireDetector(script)
    return FireAnalyzer(detector=det), det, profile or Profile.fire_watch()


def fired(res: list[tuple[float, FireResult]]) -> list[tuple[float, object]]:
    return [(ts, a) for ts, r in res for a in r.fired]


def ended(res: list[tuple[float, FireResult]]) -> list[tuple[float, tuple[int, str, bool]]]:
    return [(ts, e) for ts, r in res for e in r.ended]
