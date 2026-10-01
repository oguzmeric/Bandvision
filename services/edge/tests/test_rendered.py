"""Gerçeğe yakın render (tools/make_test_video.py): boy/açı/gölge değişkenliği olan yumurtalar, bitişik çiftler.

Sentetik düz elipslerin göstermediği bir kusuru yakaladı: uzun süre birleşik kalan çiftlerde izler şişmiş
hızla lekeden kopup öne kaçıyor, arkada her karede yeni iz doğuyordu (100 yumurtada 110 sayım). §4.0 demirleme,
§4.5b bölünme, §4.6 yeni iz hızı bunu düzeltir. ffmpeg gerekmez: kareler bellekte çizilir.
"""
from __future__ import annotations

import importlib.util
import pathlib
import random
import sys

import numpy as np
import pytest

from bantvision.core import Pipeline, Profile
from bantvision.core.profile import Roi

_TOOL = pathlib.Path(__file__).resolve().parents[3] / "tools" / "make_test_video.py"
_spec = importlib.util.spec_from_file_location("make_test_video", _TOOL)
assert _spec and _spec.loader
mtv = importlib.util.module_from_spec(_spec)
sys.modules["make_test_video"] = mtv   # dataclass, modülü sys.modules'ta arar
_spec.loader.exec_module(mtv)

ROI = Roi((mtv.BELT_X0 - 10) / mtv.W, 0.05, (mtv.BELT_X1 - mtv.BELT_X0 + 20) / mtv.W, 0.9)


def frames(eggs, seconds: float, seed: int):
    base = mtv.belt_base(np.random.default_rng(seed))
    for k in range(int(seconds * mtv.FPS)):
        t = k / mtv.FPS
        img = base.copy()
        for e in eggs:
            mtv.draw_egg(img, e, e.y(t))
        yield img, t


def calibrated_profile(seed: int) -> Profile:
    rng = random.Random(seed)
    calib = mtv.layout(8, 0, 0, rng, lead_px=mtv.SPEED * 1.5, gap_lengths=(2.2, 2.8))
    p = Profile.egg()
    p.roi = ROI
    pipe = Pipeline(p)
    pipe.start_background_learning()
    for img, t in frames(calib, mtv.leave_time(calib), seed):
        r = pipe.process(img, t)
        if any(e[0] == "background_done" for e in r.calibration):
            pipe.start_sample_learning(8)
    assert p.expectedArea > 0
    return p


@pytest.mark.parametrize("seed", [7, 23])
def test_rendered_eggs_with_touching_pairs(seed: int) -> None:
    rng = random.Random(seed)
    p = calibrated_profile(seed)
    eggs = mtv.layout(14, 6, 3, rng, lead_px=mtv.SPEED * 0.5, gap_lengths=(0.9, 1.6))   # 32 yumurta
    pipe = Pipeline(p)
    it = frames(eggs, mtv.leave_time(eggs), seed + 1)
    for img, t in it:                       # ilk yarım saniye boş bant: arka planı kur
        pipe.process(img, t)
        if t >= 0.4:
            break
    pipe.reset_count()
    for img, t in it:
        pipe.process(img, t)
    assert pipe.total == len(eggs) == 32
