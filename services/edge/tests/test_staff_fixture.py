"""iOS eşdeğerlik dosyası (apps/ios/BantSayacTests/staff_parity.json) Python'un güncel davranışını mı gösteriyor?"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_staff_parity_fixture_is_current() -> None:
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "make_staff_fixture.py"), "--check"],
                       capture_output=True, text=True, encoding="utf-8", check=False)
    assert r.returncode == 0, r.stdout + r.stderr


def _image(img: dict, palette: list[list[int]]) -> np.ndarray:
    from make_staff_fixture import ALPHABET

    idx = np.array([ALPHABET.index(ch) for ch in img["px"]]).reshape(img["h"], img["w"])
    return np.asarray(palette, np.uint8)[idx][:, :, ::-1].copy()          # BGR


def test_frame_entry_points_replay_and_cover_required_cases() -> None:
    """Fikstürdeki kare girişleri vote_bgr/teach_bgr ile yeniden oynanır; Swift'in de koşacağı zorunlu durumlar var."""
    sys.path.insert(0, str(ROOT / "tools"))
    from make_staff_fixture import OUT

    from bantvision.core import staff_color as sc

    data = json.loads(OUT.read_text(encoding="utf-8"))
    images = [_image(i, data["palette"]) for i in data["images"]]
    votes = {v["name"]: v for v in data["voteFrames"]}
    teach = {t["name"]: t for t in data["teachFrames"]}
    for v in data["voteFrames"]:
        got = sc.vote_bgr(images[v["image"]], tuple(v["box"]), [tuple(o) for o in v["others"]], v["anchor"],
                          [tuple(c) for c in v["colors"]])
        assert got == v["vote"], v["name"]
    for t in data["teachFrames"]:
        got = sc.teach_bgr(images[t["image"]], [tuple(b) for b in t["boxes"]], tuple(t["point"]), t["anchor"])
        assert (got is None) == (t["lab"] is None), t["name"]
        if got is not None:
            assert got == pytest.approx(t["lab"], abs=1e-5), t["name"]

    assert votes["komşu-örter-az-nokta"]["vote"] is None and votes["komşu-yok-aynı-kutu"]["vote"] is True
    assert votes["komşusuz-az-turuncu"]["vote"] is False and votes["komşu-sonrası-kalan-noktalar"]["vote"] is True
    assert votes["küçük-kutu"]["vote"] is None
    assert teach["iç-içe-en-küçük-kutu"]["lab"] != teach["yalnız-dış-kutu"]["lab"]
    assert teach["kutusuz-kenarda-kırpılan-kare"]["lab"] is not None and teach["çok-karanlık"]["lab"] is None
    assert {v["vote"] for v in data["voteFrames"]} == {True, False, None}
