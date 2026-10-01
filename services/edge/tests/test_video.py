"""Video dosyasından sayım (bantvision.video): sentetik senaryolar MP4'e yazılıp araçla sayılır.

Kalibrasyon tamamen otomatik: videoda boş bant yok, yön ve tek ürün alanı da videodan bulunur.
"""
from __future__ import annotations

import json
import pathlib

import cv2
import pytest

from bantvision import sim, video


def write_video(sc: sim.Scenario, path: pathlib.Path, rotate: int | None = None) -> pathlib.Path:
    w = None
    for img, _ in sc.frames():
        bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        if rotate is not None:
            bgr = cv2.rotate(bgr, rotate)
        if w is None:
            w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), sc.fps, (bgr.shape[1], bgr.shape[0]))
        w.write(bgr)
    assert w is not None
    w.release()
    return path


def analyze(path: pathlib.Path, *extra: str) -> dict:
    out = path.with_suffix("")
    assert video.main([str(path), "--out", str(out), "--no-video", *extra]) == 0
    return json.loads((out / "ozet.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("make", [sim.single_file, sim.three_lanes], ids=lambda f: f.__name__)
def test_counts_from_video_fully_automatic(tmp_path: pathlib.Path, make) -> None:
    sc = make(fps=30.0)
    s = analyze(write_video(sc, tmp_path / f"{sc.name}.mp4"), "--preset", "egg")
    assert s["calibration"]["direction"] == "down"
    assert s["count"] == sc.expected_count, s


def test_mixed_singles_and_pairs_learn_single_area(tmp_path: pathlib.Path) -> None:
    # Tek ürünler azınlıkta (%40): düz medyan çifte kayardı, alt küme tahmini tekli alanı bulmalı
    items: list[sim.Item] = []
    y = -120.0
    for i in range(10):
        items.append(sim.Item(y, 360))
        if i % 5 in (1, 2, 4):                       # 10 lekenin 6'sı çift
            items.append(sim.Item(y - 141, 360))
            y -= 141
        y -= 330
    sc = sim.Scenario("mixed", items, fps=30.0)
    s = analyze(write_video(sc, tmp_path / "karisik.mp4"), "--preset", "egg")
    assert s["count"] == sc.expected_count == 16, s
    assert any("değişken" in n for n in s["calibration"]["notes"])


@pytest.mark.parametrize("make", [sim.touching_vertical, sim.touching_side], ids=lambda f: f.__name__)
def test_dense_video_with_profile_from_single_file_video(tmp_path: pathlib.Path, make) -> None:
    """Sahadaki akış: önce tek tek geçen ürünlerle kısa kalibrasyon videosu, sonra yoğun video o profille.

    Yalnızca çiftlerden oluşan videoda alan tek başına belirsizdir (çift = büyük tek ürün), bu yüzden
    tam otomatik mod burada bilerek 2 kat az sayar; profil verilince doğru sayar.
    """
    calib = analyze(write_video(sim.single_file(fps=30.0), tmp_path / "kalibrasyon.mp4"), "--preset", "egg")
    profile = tmp_path / "kalibrasyon" / "profil.json"
    assert calib["calibration"]["expectedArea"] > 0

    sc = make(fps=30.0)
    path = write_video(sc, tmp_path / f"{sc.name}.mp4")
    assert analyze(path)["count"] == sc.expected_count // 2          # belirsizlik belgelensin
    assert analyze(path, "--profile", str(profile))["count"] == sc.expected_count


def test_horizontal_flow_direction_is_detected(tmp_path: pathlib.Path) -> None:
    # Saat yönünde 90° döndürünce aşağı akış sola akışa dönüşür
    sc = sim.single_file(fps=30.0)
    s = analyze(write_video(sc, tmp_path / "yatay.mp4", cv2.ROTATE_90_CLOCKWISE))
    assert s["calibration"]["direction"] == "left"
    assert s["count"] == sc.expected_count, s


def test_low_fps_video(tmp_path: pathlib.Path) -> None:
    sc = sim.single_file(fps=25.0)
    s = analyze(write_video(sc, tmp_path / "fps25.mp4"), "--preset", "egg", "--truth", str(sc.expected_count))
    assert s["count"] == sc.expected_count
    assert s["errorPct"] == 0.0


def test_outputs_annotated_video_and_valid_profile(tmp_path: pathlib.Path) -> None:
    from jsonschema import Draft202012Validator

    sc = sim.single_file(n=4, fps=30.0)
    src = write_video(sc, tmp_path / "kisa.mp4")
    out = tmp_path / "cikti"
    assert video.main([str(src), "--out", str(out), "--out-width", "360"]) == 0

    cap = cv2.VideoCapture(str(out / "isaretli.mp4"))
    assert cap.isOpened() and int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) == 360
    cap.release()

    schema_path = pathlib.Path(__file__).resolve().parents[3] / "contracts" / "product-profile.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    prof = json.loads((out / "profil.json").read_text(encoding="utf-8"))
    errs = [e.message for e in Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
            .iter_errors(prof)]
    assert errs == []
    assert prof["expectedArea"] > 0

    rows = (out / "sayimlar.csv").read_text(encoding="utf-8").splitlines()
    assert rows[0] == "zaman_sn;iz;delta;toplam" and len(rows) == 1 + 4


def test_manual_overrides_skip_auto_calibration(tmp_path: pathlib.Path) -> None:
    sc = sim.single_file(n=5, fps=30.0)
    s = analyze(write_video(sc, tmp_path / "elle.mp4"), "--direction", "down", "--expected-area", "0.014",
                "--roi", "0.05,0.05,0.9,0.9", "--line", "0.6")
    assert s["calibration"]["flow"] == [0.0, 0.0]          # yön tahmini çalışmadı
    assert s["calibration"]["areaSamples"] == 0            # alan tahmini çalışmadı
    assert s["count"] == 5


def dense(gap: float, n: int = 25, lead: float = 0.0) -> sim.Scenario:
    """Tek şeritte sık akış: doluluk ≈ 144 / gap. lead > 0 ise video başında o kadar piksel boş bant."""
    return sim.Scenario(f"dense{gap:.0f}", [sim.Item(-120 - lead - i * gap, 360) for i in range(n)], fps=30.0)


def test_threshold_not_inflated_when_belt_mostly_covered(tmp_path: pathlib.Path) -> None:
    # %65 doluluk: eski tahmin (|kare - medyan| haritasının %99,5'i) eşiği 43'e çıkarıyordu
    sc = dense(220)
    s = analyze(write_video(sc, tmp_path / "d220.mp4"), "--preset", "egg")
    assert s["calibration"]["threshold"] <= 20, s["calibration"]
    assert s["count"] == sc.expected_count


def test_mostly_covered_belt_needs_bg_range(tmp_path: pathlib.Path) -> None:
    """%76 doluluk: her pikselde ürün çoğunlukta olduğu için medyan arka plan ürünün kendisi olur ve
    boşluklar ürün sanılır. Bu, videonun kendisinden ayırt edilemez (şekil, doluluk oranı ölçüldü; ayırt
    etmiyor). Çözüm: videoda boş bandın göründüğü aralığı vermek. Bilinen sınır olarak belgelenir."""
    sc = dense(190, n=60, lead=700)                  # ilk ~0,6 sn boş bant, sonra ~11 sn %76 dolu
    path = write_video(sc, tmp_path / "d190.mp4")
    auto = analyze(path, "--preset", "egg")
    assert auto["count"] != sc.expected_count        # bilinen sınır
    assert auto["calibration"]["background"] == "medyan"
    fixed = analyze(path, "--preset", "egg", "--bg-range", "0,0.4")
    assert fixed["calibration"]["background"] == "aralık 0.0-0.4 sn"
    assert fixed["count"] == sc.expected_count
    assert (tmp_path / "d190" / "arka_plan.png").exists()
