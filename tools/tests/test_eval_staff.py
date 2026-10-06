from __future__ import annotations

import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location("eval_staff", pathlib.Path(__file__).resolve().parents[1] / "eval_staff.py")
ev = importlib.util.module_from_spec(spec)                      # type: ignore[arg-type]
spec.loader.exec_module(ev)                                     # type: ignore[union-attr]


def test_match_counts_capture_and_false_exclusion() -> None:
    labels = [{"t": 2.0, "dir": "in", "staff": True}, {"t": 5.0, "dir": "in", "staff": False},
              {"t": 9.0, "dir": "out", "staff": True}, {"t": 12.0, "dir": "out", "staff": False}]
    preds = [(2.4, "in", True), (5.2, "in", True), (9.1, "out", False)]        # 12.0 kaçırıldı
    r = ev.match(labels, preds)
    assert r == {"staff": 2, "staff_ok": 1, "customer": 2, "customer_excluded": 1, "missed": 1, "extra": 0}
