"""tools/convert_movenet.py doğrulama kapısı: saf yardımcılar (TensorFlow gerekmez; numpy yoksa atlanır)."""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

np = pytest.importorskip("numpy")

spec = importlib.util.spec_from_file_location("convert_movenet", pathlib.Path(__file__).resolve().parents[1] / "convert_movenet.py")
cm = importlib.util.module_from_spec(spec)                      # type: ignore[arg-type]
spec.loader.exec_module(cm)                                     # type: ignore[union-attr]

OK_IN = [("input", "tensor(int32)", [1, 256, 256, 3])]
OK_OUT = [("output_0", "tensor(float)", [1, 1, 17, 3])]


def test_compare_returns_max_abs_diff() -> None:
    ref = np.zeros((1, 1, 17, 3), dtype=np.float32)
    got = ref.copy()
    got[0, 0, 4, 1] = -0.25
    assert cm.compare(ref, got, "k") == pytest.approx(0.25)
    assert cm.compare(ref, ref, "k") == 0.0


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_compare_rejects_non_finite(bad: float) -> None:
    ref = np.zeros((1, 1, 17, 3), dtype=np.float32)
    got = ref.copy()
    got[0, 0, 0, 0] = bad
    with pytest.raises(ValueError, match="sonlu değil"):
        cm.compare(ref, got, "k")
    with pytest.raises(ValueError, match="sonlu değil"):
        cm.compare(got, got, "k")                               # ikisi de NaN olsa da geçmemeli


def test_compare_rejects_wrong_shape() -> None:
    ok = np.zeros((1, 1, 17, 3), dtype=np.float32)
    with pytest.raises(ValueError, match="biçimi"):
        cm.compare(ok, np.zeros((1, 17, 3), dtype=np.float32), "k")
    with pytest.raises(ValueError, match="biçimi"):
        cm.compare(np.zeros((1, 6, 56, 3), dtype=np.float32), ok, "k")


def test_io_error_contract() -> None:
    assert cm.io_error(OK_IN, OK_OUT) is None
    assert cm.io_error([("x", "tensor(int32)", [1, 256, 256, 3])], OK_OUT)
    assert cm.io_error([("input", "tensor(float)", [1, 256, 256, 3])], OK_OUT)
    assert cm.io_error([("input", "tensor(int32)", [1, 192, 192, 3])], OK_OUT)
    assert cm.io_error(OK_IN, [("output", "tensor(float)", [1, 1, 17, 3])])
    assert cm.io_error(OK_IN, OK_OUT + OK_OUT)
