from __future__ import annotations

import importlib.util
import json
import pathlib
import types
from typing import Any

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CLIP = ROOT / "apps" / "ios" / "BantSayacUITests" / "ui_test_clip.mp4"

spec = importlib.util.spec_from_file_location("eval_staff", pathlib.Path(__file__).resolve().parents[1] / "eval_staff.py")
ev = importlib.util.module_from_spec(spec)                      # type: ignore[arg-type]
spec.loader.exec_module(ev)                                     # type: ignore[union-attr]

# Profil/video testleri edge bağımlılıkları (numpy, OpenCV) ister: CI'da edge-core işinde koşar, contracts işinde atlanır
needs_edge = pytest.mark.skipif(importlib.util.find_spec("cv2") is None, reason="edge bağımlılıkları yok")


def lab(t: float, d: str, staff: bool) -> dict[str, Any]:
    return {"t": t, "dir": d, "staff": staff}


def test_match_counts_capture_and_false_exclusion() -> None:
    labels = [lab(2.0, "in", True), lab(5.0, "in", False), lab(9.0, "out", True), lab(12.0, "out", False)]
    preds = [(2.4, "in", True), (5.2, "in", True), (9.1, "out", False)]        # 12.0 kaçırıldı
    r = ev.match(labels, preds)
    assert r == {"staff": 2, "staff_ok": 1, "staff_as_customer": 1, "staff_missed": 0,
                 "customer": 2, "customer_ok": 0, "customer_excluded": 1, "customer_missed": 1,
                 "extra_staff": 0, "extra_customer": 0}
    assert ev.rates(r) == (0.5, 0.5)                    # kaçan müşteri hariç tutma sayılmaz, paydada kalır


def test_tolerance_boundary_is_inclusive() -> None:
    r = ev.match([lab(10.0, "in", True), lab(20.0, "in", True)], [(11.5, "in", True), (18.4, "in", True)])
    assert (r["staff_ok"], r["staff_missed"], r["extra_staff"]) == (1, 1, 1)      # 1,5 sn eşleşir; 1,6 sn eşleşmez
    r = ev.match([lab(10.0, "out", False)], [(8.5, "out", False)])
    assert r["customer_ok"] == 1


def test_direction_mismatch_is_not_matched() -> None:
    r = ev.match([lab(5.0, "in", True)], [(5.0, "out", True)])
    assert (r["staff_ok"], r["staff_missed"], r["extra_staff"]) == (0, 1, 1)


def test_nearest_prediction_is_chosen() -> None:
    r = ev.match([lab(5.0, "in", True)], [(4.0, "in", False), (5.3, "in", True), (6.2, "in", False)])
    assert (r["staff_ok"], r["staff_as_customer"]) == (1, 0)
    assert (r["extra_staff"], r["extra_customer"]) == (0, 2)      # eşlenmeyen iki tahmin müşteri fazlası


def test_extra_predictions_reported_per_class() -> None:
    r = ev.match([lab(1.0, "in", False)], [(1.0, "in", False), (30.0, "in", True), (31.0, "out", True),
                                            (40.0, "out", False)])
    assert (r["customer_ok"], r["extra_staff"], r["extra_customer"]) == (1, 2, 1)


def test_missed_staff_lowers_capture() -> None:
    labels = [lab(10.0 * i, "in", True) for i in range(20)] + [lab(10.0 * i + 5, "out", False) for i in range(20)]
    preds = [(10.0 * i, "in", True) for i in range(19)] + [(10.0 * i + 5, "out", False) for i in range(20)]
    r = ev.match(labels, preds)
    assert r["staff_missed"] == 1 and ev.rates(r) == (0.95, 0.0)
    preds = [(10.0 * i, "in", True) for i in range(18)] + [(10.0 * i + 5, "out", False) for i in range(20)]
    assert ev.rates(ev.match(labels, preds))[0] == 0.9                # iki kaçak: %90 → kalır


def write(tmp: pathlib.Path, name: str, data: Any) -> str:
    p = tmp / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def staff_profile() -> dict[str, Any]:
    from bantvision.core import Profile

    p = Profile.people()
    p.staffColors = [(60.0, 40.0, 60.0)]
    return p.to_dict()


@needs_edge
def test_too_few_labels_refused(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    labels = [lab(i, "in", True) for i in range(19)] + [lab(i, "out", False) for i in range(25)]
    args = ["yok.mp4", "--profile", write(tmp_path, "p.json", staff_profile()), "--angle", "tepeden",
            "--labels", write(tmp_path, "l.json", labels)]
    assert ev.main(args) == 2
    assert "yetersiz etiket: 19 personel, 25 müşteri" in capsys.readouterr().err
    labels = [lab(i, "in", True) for i in range(20)] + [lab(i, "out", False) for i in range(19)]
    args[-1] = write(tmp_path, "l.json", labels)
    assert ev.main(args) == 2


@needs_edge
def test_unopenable_video_and_profile_forms(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    labels = [lab(i, "in", True) for i in range(20)] + [lab(i, "out", False) for i in range(20)]
    lp = write(tmp_path, "l.json", labels)
    session_view = {"id": "x", "profile": staff_profile()}                  # GET /api/v1/live/sessions/{id}
    assert ev.main([str(tmp_path / "yok.mp4"), "--profile", write(tmp_path, "s.json", session_view),
                    "--labels", lp, "--angle", "yandan"]) == 2
    assert "Video açılamadı" in capsys.readouterr().err

    cams = {"src1||p1": staff_profile(), "src2|ch2|p1": staff_profile()}  # camera_profiles.json
    cp = write(tmp_path, "c.json", cams)
    with pytest.raises(ev.InputError, match="2 kamera kaydı"):
        ev.load_profile(cp)
    assert ev.load_profile(cp, "src2").staffColors == [(60.0, 40.0, 60.0)]
    no_colors = dict(staff_profile())
    no_colors.pop("staffColors")
    with pytest.raises(ev.InputError, match="staffColors"):
        ev.load_profile(write(tmp_path, "n.json", no_colors))


@needs_edge
def test_run_every_nth_frame_and_releases(monkeypatch: pytest.MonkeyPatch) -> None:
    import cv2

    import bantvision.core

    seen: list[float] = []

    class FakePipeline:
        def __init__(self, _p: Any) -> None:
            self.detect = types.SimpleNamespace(enable_gate=lambda: None)
            self.counting = False

        def process(self, _frame: Any, ts: float) -> Any:
            seen.append(ts)
            return types.SimpleNamespace(counts=[], counts_out=[], staff_events=[(1, 1)] if len(seen) == 2 else [])

    released: list[bool] = []
    real = cv2.VideoCapture

    class Cap:
        def __init__(self, path: str) -> None:
            self._c = real(path)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._c, name)

        def release(self) -> None:
            released.append(True)
            self._c.release()

    monkeypatch.setattr(bantvision.core, "Pipeline", FakePipeline)
    monkeypatch.setattr(cv2, "VideoCapture", Cap)
    preds = ev.run(str(CLIP), None, every=3)
    c = real(str(CLIP))
    fps, n = c.get(cv2.CAP_PROP_FPS), 0
    while c.read()[0]:
        n += 1
    c.release()
    assert len(seen) == (n + 2) // 3 and seen[:3] == pytest.approx([0.0, 3 / fps, 6 / fps])
    assert preds == [(seen[1], "in", True)] and released == [True]
