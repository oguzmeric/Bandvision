from __future__ import annotations

import numpy as np
import pytest

from bantvision.core import pose


def test_square_crop_is_centered_and_padded() -> None:
    x0, y0, side = pose.square_crop((100, 50, 140, 210))                     # 40×160 kutu
    assert side == pytest.approx(160 * 1.25)
    assert (x0 + side / 2, y0 + side / 2) == pytest.approx((120, 130))


def test_make_input_pads_outside_with_black_and_is_rgb_int32() -> None:
    img = np.zeros((100, 100, 3), np.uint8)
    img[:, :] = (255, 0, 0)                                                  # BGR mavi
    x = pose.make_input(img, (-50.0, -50.0, 200.0))                         # sol üst görüntü dışında
    assert x.shape == (1, 256, 256, 3) and x.dtype == np.int32
    assert (x[0, 10, 10] == 0).all()                                         # dışarısı siyah
    assert tuple(x[0, 128, 128]) == (0, 0, 255)                              # görüntü içi; RGB'de mavi


def test_to_image_maps_back_including_crop_off_image() -> None:
    out = np.zeros((17, 3))
    out[0] = (0.5, 0.25, 0.8)                                                # y, x, güven
    kp = pose.to_image(out, (-40.0, 10.0, 200.0))
    assert tuple(kp[0]) == pytest.approx((-40 + 0.25 * 200, 10 + 0.5 * 200, 0.8))


def test_estimator_runs_with_fake_session() -> None:
    class FakeSession:
        def get_inputs(self) -> list[object]:
            from types import SimpleNamespace
            return [SimpleNamespace(name="input")]

        def run(self, _o: object, feed: dict[str, np.ndarray]) -> list[np.ndarray]:
            assert feed["input"].shape == (1, 256, 256, 3)
            r = np.zeros((1, 1, 17, 3), np.float32)
            r[0, 0, :, 2] = 0.9
            r[0, 0, 5] = (0.5, 0.5, 0.9)
            return [r]

    est = pose.PoseEstimator.__new__(pose.PoseEstimator)
    est._session, est._input = FakeSession(), "input"
    kp = est.estimate(np.zeros((480, 640, 3), np.uint8), (300, 100, 340, 260))
    side = 160 * 1.25
    assert kp.shape == (17, 3) and kp[5, :2] == pytest.approx((320, 180))   # kare merkezi = kutu merkezi
    assert side > 0


def _make_input_reference(bgr: np.ndarray, crop: pose.Crop) -> np.ndarray:
    """Eski uygulama (tam side×side siyah tuval + kopya + ölçekleme): yeni uygulamanın bire bir eşdeğeri olmalı."""
    import cv2

    x0, y0, side = crop
    s = max(1, round(side))
    canvas = np.zeros((s, s, 3), np.uint8)
    h, w = bgr.shape[:2]
    ix0, iy0 = round(x0), round(y0)
    sx0, sy0, sx1, sy1 = max(0, ix0), max(0, iy0), min(w, ix0 + s), min(h, iy0 + s)
    if sx1 > sx0 and sy1 > sy0:
        canvas[sy0 - iy0:sy1 - iy0, sx0 - ix0:sx1 - ix0] = bgr[sy0:sy1, sx0:sx1]
    img = cv2.resize(canvas, (256, 256), interpolation=cv2.INTER_LINEAR)
    return img[:, :, ::-1].astype(np.int32)[None]


@pytest.mark.parametrize("box", [
    (300, 100, 340, 260),            # içeride
    (0, 0, 60, 200),                 # sol üst köşeye değiyor
    (600, 300, 640, 480),            # sağ alt köşeye değiyor
    (-80, 200, 40, 520),             # kısmen dışarıda (sol ve alt)
    (560, -50, 700, 120),            # kısmen dışarıda (sağ ve üst)
    (10, 10, 630, 470),              # karenin tamamından büyük kırpma
    (320, 240, 321, 241),            # çok küçük kutu
    (-500, -500, -400, -300),        # tamamen dışarıda: siyah
])
def test_make_input_equals_full_canvas_reference(box: tuple[float, float, float, float]) -> None:
    rng = np.random.default_rng(7)
    img = rng.integers(0, 256, (480, 640, 3), dtype=np.uint8)
    crop = pose.square_crop(box)
    new, old = pose.make_input(img, crop), _make_input_reference(img, crop)
    assert new.shape == old.shape == (1, 256, 256, 3) and new.dtype == np.int32
    assert np.array_equal(new, old)
