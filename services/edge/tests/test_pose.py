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
