"""Şerit tarama sayımı (§4.9): tek sıra, bitişik/aralıklı hacimli ürünler (torba, koli)."""
from __future__ import annotations

import json
import pathlib
from collections.abc import Callable

import cv2
import numpy as np
import pytest

from bantvision import sim_bulk as sb
from bantvision import video
from bantvision.core.linescan import LineScanCounter
from bantvision.core.pipeline import Pipeline
from bantvision.core.profile import Profile, Roi

SCENARIOS: dict[str, Callable[[], sb.BulkScenario]] = {
    "bags_touching": lambda: sb.BulkScenario("bags_touching", sb.sequence(30, 110, 0), frames_n=900),
    "bags_shingled": lambda: sb.BulkScenario("bags_shingled", sb.sequence(30, 110, -14), frames_n=900),
    "bags_irregular_gaps": lambda: sb.BulkScenario(
        "bags_irregular_gaps", sb.sequence(25, 110, 0, gaps=[30, 0, 80, 5, 0, 150]), frames_n=900),
    "dark_boxes_gapped": lambda: sb.BulkScenario(
        "dark_boxes_gapped", sb.sequence(25, 90, 40, kind="box"), belt_level=170, box_level=95, frames_n=900),
    "light_boxes_touching": lambda: sb.BulkScenario(
        "light_boxes_touching", sb.sequence(30, 90, 0, kind="box"), belt_level=60, box_level=180, frames_n=900),
    "screen_recording_slow": lambda: sb.BulkScenario(      # tekrarlanan kareler (ekran kaydı), yavaş bant
        "screen_recording_slow", sb.sequence(20, 110, 0), frames_n=1500, speed=lambda k: 1.1, dup_pattern=(1, 2, 1)),
    "belt_stops": lambda: sb.BulkScenario(
        "belt_stops", sb.sequence(20, 110, 0), frames_n=1000, speed=lambda k: 0.0 if 300 <= k < 450 else 2.4),
    "belt_accelerates": lambda: sb.BulkScenario(
        "belt_accelerates", sb.sequence(30, 110, 0), frames_n=800, speed=lambda k: 1.5 + 2.5 * k / 800),
    "belt_joints": lambda: sb.BulkScenario(               # banttaki enine ek yerleri boşluklarda ürün sanılmasın
        "belt_joints", sb.sequence(20, 100, 60), frames_n=900, belt_joint_every=170),
}


def belt_roi(sc: sb.BulkScenario) -> Roi:
    return Roi(sc.belt_x[0] / sc.width, 0.05, (sc.belt_x[1] - sc.belt_x[0]) / sc.width, 0.9)


def run(sc: sb.BulkScenario, profile: Profile,
        transform: Callable[[np.ndarray], np.ndarray] = lambda g: g) -> tuple[int, LineScanCounter]:
    lc = LineScanCounter()
    total = 0
    for g, _ in sc.frames():
        total += sum(e.delta for e in lc.process(np.ascontiguousarray(transform(g)), profile))
    total += sum(e.delta for e in lc.flush(profile))
    return total, lc


def ls_profile(roi: Roi, direction: str = "down", line: float = 0.5, plen: float = 0.0) -> Profile:
    return Profile(roi=roi, linePosition=line, direction=direction, countMode="linescan", productLength=plen)


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_counts_exactly(name: str) -> None:
    sc = SCENARIOS[name]()
    got, lc = run(sc, ls_profile(belt_roi(sc)))
    assert not lc.failed
    assert got == sc.truth(0.5), f"{name}: {got} ≠ {sc.truth(0.5)} (ürün boyu {lc.product_length:.3f})"


@pytest.mark.parametrize("line", [0.35, 0.65])
def test_line_position(line: float) -> None:
    sc = SCENARIOS["bags_touching"]()
    got, _ = run(sc, ls_profile(belt_roi(sc), line=line))
    assert got == sc.truth(line)


@pytest.mark.parametrize("direction", ["up", "right", "left"])
def test_flow_directions(direction: str) -> None:
    """Aynı sahne döndürülüp/çevrilip verilir; çizgi 0,5 simetrik olduğundan doğru sayı aynıdır."""
    sc = SCENARIOS["bags_touching"]()
    r = belt_roi(sc)
    if direction == "up":
        tf, roi = (lambda g: g[::-1]), Roi(r.x, 1 - r.y - r.height, r.width, r.height)
    elif direction == "right":
        tf, roi = (lambda g: g.T), Roi(r.y, r.x, r.height, r.width)
    else:
        tf, roi = (lambda g: g.T[:, ::-1]), Roi(1 - r.y - r.height, r.x, r.height, r.width)
    got, _ = run(sc, ls_profile(roi, direction=direction), tf)
    assert got == sc.truth(0.5)


def test_polygon_roi_same_as_rect() -> None:
    sc = SCENARIOS["bags_shingled"]()
    r = belt_roi(sc)
    p = ls_profile(r)
    p.set_polygon([(r.x, r.y), (r.x + r.width, r.y), (r.x + r.width, r.y + r.height), (r.x, r.y + r.height)])
    got, _ = run(sc, p)
    assert got == sc.truth(0.5)


def test_known_product_length_counts_without_learning() -> None:
    """Kaydedilmiş ürün boyuyla öğrenme beklenmez; sonuç aynı ve sayılar akış boyunca gelir (sonda yığılmaz)."""
    sc = SCENARIOS["bags_touching"]()
    _, learned = run(sc, ls_profile(belt_roi(sc)))
    plen = learned.product_length
    assert 0.25 < plen < 0.35                   # 110 px ürün / 360 px alan ≈ 0,31
    p = ls_profile(belt_roi(sc), plen=plen)
    lc = LineScanCounter()
    per_frame: list[int] = []
    for g, _ in sc.frames():
        per_frame.append(sum(e.delta for e in lc.process(g, p)))
    tail = sum(e.delta for e in lc.flush(p))
    assert sum(per_frame) + tail == sc.truth(0.5)
    assert tail <= 1
    assert sum(per_frame[: len(per_frame) // 2]) >= sc.truth(0.5) // 2 - 2


def test_markers_follow_counted_products() -> None:
    sc = SCENARIOS["bags_touching"]()
    p = ls_profile(belt_roi(sc), plen=0.3)
    lc = LineScanCounter()
    seen: set[int] = set()
    for g, _ in sc.frames():
        ids = {e.seg_id for e in lc.process(g, p)}
        ms = lc.markers(g.shape, p)
        for m in ms:
            assert 0 <= m.x <= 1 and p.linePosition - 0.05 <= m.y <= 1
        if seen:                                  # ilk karar anındaki toplu yetişme hariç:
            assert ids <= {m.id for m in ms}     # sayıldığı karede numarası ekranda (işaret kimliği = olay kimliği)
        seen |= ids
    assert len(seen) >= sc.truth(0.5) - 1


def test_empty_belt_counts_nothing() -> None:
    sc = sb.BulkScenario("empty", [sb.Bulk(10_000, 100)], frames_n=400)
    got, _ = run(sc, ls_profile(belt_roi(sc)))
    assert got == 0


def test_pipeline_linescan_mode_and_finish() -> None:
    sc = SCENARIOS["bags_irregular_gaps"]()
    p = Profile.flour_sack()
    p.roi, p.processingWidth = belt_roi(sc), sc.width
    pipe = Pipeline(p)
    for g, t in sc.frames():
        r = pipe.process(g, t)
        assert r.blobs == [] and all(e.is_first_crossing and e.delta == 1 for e in r.counts)
    pipe.finish(0.0)
    assert pipe.total == sc.truth(0.5)


def test_pipeline_linescan_calibration() -> None:
    """Şerit taramada boş bant öğrenme hemen biter (eşik değişmez); örnek öğrenme ürün boyunu öğrenir."""
    sc = SCENARIOS["bags_touching"]()
    p = Profile.flour_sack()
    p.roi, p.processingWidth = belt_roi(sc), sc.width
    th = p.diffThreshold
    pipe = Pipeline(p)
    pipe.start_background_learning()
    frames = list(sc.frames())
    r = pipe.process(*frames[0])
    assert r.calibration == [("background_done", th)] and p.diffThreshold == th
    pipe.start_sample_learning()
    done = None
    for g, t in frames[1:]:
        for ev in pipe.process(g, t).calibration:
            if ev[0] == "sample_done":
                done = ev[1]
        if done:
            break
    assert done is not None and 0.25 < p.productLength < 0.35 and pipe.total == 0


def test_video_tool_end_to_end(tmp_path: pathlib.Path) -> None:
    """Video aracı: un torbası hazır profili şerit taramayla sayar, yön ve ürün boyunu kendisi bulur."""
    sc = SCENARIOS["bags_shingled"]()
    path = tmp_path / "torba.mp4"
    wr = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25, (sc.width, sc.height))
    for g, _ in sc.frames():
        wr.write(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR))
    wr.release()
    r = belt_roi(sc)
    out = tmp_path / "out"
    rc = video.main([str(path), "--out", str(out), "--preset", "flour", "--width", str(sc.width),
                     "--roi", f"{r.x},{r.y},{r.width},{r.height}", "--line", "0.5", "--no-video"])
    assert rc == 0
    summary = json.loads((out / "ozet.json").read_text(encoding="utf-8"))
    assert summary["calibration"]["countMode"] == "linescan"
    assert summary["calibration"]["direction"] == "down"
    assert summary["count"] == sc.truth(0.5)
    prof = json.loads((out / "profil.json").read_text(encoding="utf-8"))
    assert prof["countMode"] == "linescan" and prof["productLength"] > 0


# ---------------------------------------------------------------- Swift eşdeğerliği
# Swift `LineScanTests` aynı tam sayılı üreticiyi kullanır ve aynı sayıları bekler (gürültüsüz, alt piksel yok).

PARITY_W, PARITY_H = 96, 160


def parity_frames(n_frames: int = 380, speed: int = 3) -> list[np.ndarray]:
    items: list[tuple[int, int]] = []
    z = 20
    for k in range(40):
        ln = 40 + (k * 7) % 9
        items.append((z, ln))
        z += ln + (0 if k % 3 == 0 else (k * 5) % 13)

    def value(zz: int, x: int) -> int:
        if x < 16 or x >= 80:
            return 30
        if 24 <= x < 72:
            for zk, ln in items:
                u = zz - zk
                if 0 <= u < ln:
                    if u < 2:
                        return 90
                    tail = ln - 1 - u
                    return 200 - ((6 - u) * 10 if u < 6 else 0) - ((4 - tail) * 10 if tail < 4 else 0)
        return 60 + (zz * 37) % 11 + (x * 13) % 5

    zmax = speed * n_frames + PARITY_H
    strip = np.array([[value(zz, x) for x in range(PARITY_W)] for zz in range(zmax)], dtype=np.uint8)
    out = []
    for t in range(n_frames):
        rows = [speed * t + (PARITY_H - 1 - y) for y in range(PARITY_H)]
        out.append(strip[rows])
    return out


def parity_profile(plen: float = 0.0) -> Profile:
    return Profile(roi=Roi(16 / 96, 0.05, 64 / 96, 0.9), linePosition=0.5, direction="down",
                   countMode="linescan", productLength=plen, maxMultiplicity=4)


def test_swift_parity_vectors() -> None:
    """Sayılar Swift `LineScanTests.testParityVectors` içinde birebir beklenir; değişirse ikisini birlikte güncelle."""
    frames = parity_frames()
    lc = LineScanCounter()
    total = sum(e.delta for g in frames for e in lc.process(g, parity_profile()))
    total += sum(e.delta for e in lc.flush(parity_profile()))
    plen = lc.product_length
    lc2 = LineScanCounter()
    total2 = sum(e.delta for g in frames for e in lc2.process(g, parity_profile(0.3)))
    total2 += sum(e.delta for e in lc2.flush(parity_profile(0.3)))

    assert (total, round(plen, 6), total2) == PARITY_EXPECTED


PARITY_EXPECTED = (24, 0.298611, 24)          # elle: merkezi çizgiyi geçen 24 ürün
