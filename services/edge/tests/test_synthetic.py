"""Çekirdek davranış testleri. Swift tarafı aynı senaryolarda aynı sayıları vermelidir (F0.2)."""
import pytest

from bantvision import sim
from bantvision.core import Pipeline, Profile


def calibrated_egg_profile(fps: float = 60.0) -> Profile:
    """Boş bant + 8 örnekle kalibre edilmiş yumurta profili."""
    p = Profile.egg()
    pipe = Pipeline(p)
    calib = sim.single_file(n=8, fps=fps)
    pipe.start_background_learning()
    done = False
    for img, ts in calib.empty_frames():
        r = pipe.process(img, ts)
        done = done or any(e[0] == "background_done" for e in r.calibration)
    assert done, "boş bant kalibrasyonu bitmedi"
    assert 12 <= p.diffThreshold <= 40
    pipe.start_sample_learning(8)
    for img, ts in calib.frames():
        pipe.process(img, ts)
    assert p.expectedArea > 0, "örnek kalibrasyonu bitmedi"
    return p


@pytest.fixture(scope="module")
def egg_profile() -> Profile:
    return calibrated_egg_profile()


def run(profile: Profile, scenario: sim.Scenario) -> int:
    pipe = Pipeline(profile)
    for img, ts in scenario.empty_frames(0.5):
        pipe.process(img, ts)
    pipe.reset_count()
    for img, ts in scenario.frames():
        pipe.process(img, ts)
    return pipe.total


@pytest.mark.parametrize("make", sim.ALL, ids=lambda f: f.__name__)
def test_counts_60fps(egg_profile: Profile, make) -> None:
    sc = make()
    assert run(egg_profile, sc) == sc.expected_count


@pytest.mark.parametrize("make", [sim.single_file, sim.touching_vertical], ids=lambda f: f.__name__)
def test_counts_25fps_rtsp_like(egg_profile: Profile, make) -> None:
    """§7: aynı profil 25 fps kaynakta da doğru saymalı."""
    sc = make(fps=25.0)
    assert run(egg_profile, sc) == sc.expected_count


def test_qc_geometry_and_spots(egg_profile: Profile) -> None:
    p = Profile.from_dict(egg_profile.to_dict())
    p.qc.enabled = True
    p.qc.geometry.solidityMin = 0.93
    p.qc.geometry.aspectMin, p.qc.geometry.aspectMax = 1.1, 1.6
    p.qc.spots.enabled = True
    p.mmPerPixel = 0.6
    items = [sim.Item(-120 - i * 270, 360, spot=(i in (2, 7)), bite=(i in (4, 9))) for i in range(12)]
    sc = sim.Scenario("qc", items)
    pipe = Pipeline(p)
    for img, ts in sc.empty_frames(0.5):
        pipe.process(img, ts)
    pipe.reset_count()
    results = []
    for img, ts in sc.frames():
        results += pipe.process(img, ts).inspections
    assert pipe.total == 12
    assert len(results) == 12
    order = sorted(results, key=lambda r: r.track_id)
    flags = [(r.result, tuple(r.reasons)) for r in order]
    nok_idx = [i for i, r in enumerate(order) if r.result == "nok"]
    assert nok_idx == [2, 4, 7, 9], flags
    assert "spots" in order[2].reasons and "spots" in order[7].reasons
    assert "solidity_low" in order[4].reasons or "area_low" in order[4].reasons
    assert all(r.metrics.get("minorMm", 0) > 0 for r in order)


def test_profile_roundtrip_matches_contract() -> None:
    import json
    import pathlib

    import jsonschema

    root = pathlib.Path(__file__).resolve().parents[3] / "contracts"
    schema = json.loads((root / "product-profile.schema.json").read_text())
    example = json.loads((root / "examples" / "profile-egg.json").read_text())
    p = Profile.from_dict(example)
    jsonschema.validate(p.to_dict(), schema)
    assert p.expectedArea == example["expectedArea"]
    assert p.qc.spots.enabled is True


@pytest.mark.parametrize("gap", [190, 160, 152], ids=["doluluk76", "doluluk90", "doluluk95"])
def test_dense_flow_background_does_not_drift(egg_profile: Profile, gap: int) -> None:
    """§2.4: ürün altındaki arka plan güncellemesi çok yavaş olmalı.

    Katsayı 0,05 iken %76 dolulukta denge kayması ≈ 0,05·(0,76/0,24)·130 ≈ 20 gri seviye eşiği (12) aşıyor,
    boşluklar ön plana geçiyor, şerit tek lekeye dönüşüp sayım duruyordu (60 üründen 26).
    """
    sc = sim.Scenario(f"dense{gap}", [sim.Item(-120 - i * gap, 360) for i in range(60)])
    assert run(egg_profile, sc) == sc.expected_count


def test_background_learning_with_products_keeps_threshold() -> None:
    """§5: boş bant öğrenirken bantta ürün varsa eşik 100'e kaçmaz, eski eşik korunur (uyarı olayı);
    video başındaki otomatik öğrenme (yalnızca arka plan) kaydedilmiş eşiği hiç değiştirmez."""
    sc = sim.touching_vertical(8)
    busy = [(g, t) for g, t in sc.frames() if (g > 150).mean() > 0.05][:90]   # bantta ürün varken (60 fps: 60 kare)
    assert len(busy) >= 70
    p = Profile.egg()
    p.diffThreshold = 33
    pipe = Pipeline(p)
    pipe.start_background_learning()
    events = []
    for g, t in busy:
        events += pipe.process(g, t).calibration
    done = [e for e in events if e[0] in ("background_done", "background_rejected")]
    assert done and done[-1][0] == "background_rejected" and p.diffThreshold == 33
    pipe = Pipeline(p)                            # yeni oturum (zaman damgaları baştan)
    pipe.start_background_learning(update_threshold=False)
    events = []
    for g, t in busy:
        events += pipe.process(g, t).calibration
    assert ("background_done", 33) in events and p.diffThreshold == 33
