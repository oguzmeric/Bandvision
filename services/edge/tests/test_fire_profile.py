"""Yangın/duman profili (`countMode = "fire"`): ayrıştırma, serileştirme, şema, katalog (R1, R2)."""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from bantvision.core import Profile
from bantvision.core.profile import FireConfig, SafetyRule
from bantvision.live.store import CATALOG, make_preset

CONTRACTS = pathlib.Path(__file__).resolve().parents[3] / "contracts"
TRI = [[0.1, 0.1], [0.4, 0.1], [0.25, 0.4]]


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = json.loads((CONTRACTS / "product-profile.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def errors(v: Draft202012Validator, doc: dict[str, Any]) -> list[str]:
    return ["/".join(map(str, e.absolute_path)) + ": " + e.message for e in v.iter_errors(doc)]


def test_fire_config_defaults() -> None:
    c = FireConfig()
    assert c.fire == SafetyRule(True, 3.0) and c.smoke == SafetyRule(True, 8.0)
    assert c.sensitivity == "normal" and c.ignoreZones == [] and c.sendImage is False


def test_fire_watch_preset(validator: Draft202012Validator) -> None:
    p = Profile.fire_watch()
    assert p.name == "Yangın / duman" and p.countMode == "fire" and p.processingWidth == 640
    assert p.fire == FireConfig()
    d = p.to_dict()
    assert d["fire"] == {"fire": {"enabled": True, "seconds": 3.0}, "smoke": {"enabled": True, "seconds": 8.0},
                         "sensitivity": "normal", "ignoreZones": [], "sendImage": False}
    assert errors(validator, d) == []


def test_round_trip_with_zones(validator: Draft202012Validator) -> None:
    d = Profile.fire_watch().to_dict()
    d["fire"] = {"fire": {"enabled": False, "seconds": 5}, "smoke": {"enabled": True, "seconds": 20},
                 "sensitivity": "high", "ignoreZones": [TRI, [[0, 0], [1, 0], [1, 1], [0, 1]]], "sendImage": True}
    p = Profile.from_dict(d)
    assert p.fire.fire == SafetyRule(False, 5.0) and p.fire.smoke == SafetyRule(True, 20.0)
    assert p.fire.sensitivity == "high" and p.fire.sendImage is True
    assert p.fire.ignoreZones[0] == [(0.1, 0.1), (0.4, 0.1), (0.25, 0.4)]
    out = p.to_dict()
    assert errors(validator, out) == []
    assert Profile.from_dict(out).to_dict()["fire"] == out["fire"]
    assert out["fire"]["ignoreZones"][0] == TRI


def test_empty_and_broken_blocks_use_defaults() -> None:
    base = Profile.fire_watch().to_dict()
    for blk in ({}, None, [], "x", {"fire": 3, "smoke": None, "sensitivity": 7, "ignoreZones": "x"}):
        p = Profile.from_dict({**base, "fire": blk})
        assert p.fire == FireConfig(), blk
    p = Profile.from_dict({**base, "fire": {"sensitivity": "extreme", "ignoreZones": [[[0.1, 0.1]], "x", TRI]}})
    assert p.fire.sensitivity == "normal"                      # bilinmeyen değer varsayılan
    assert p.fire.ignoreZones == [[(0.1, 0.1), (0.4, 0.1), (0.25, 0.4)]]   # bozuk bölgeler atlanır


def test_out_of_range_numbers_are_not_clamped() -> None:
    p = Profile.from_dict({**Profile.fire_watch().to_dict(), "fire": {"fire": {"enabled": True, "seconds": 99},
                                                                      "smoke": {"enabled": True, "seconds": 1}}})
    assert (p.fire.fire.seconds, p.fire.smoke.seconds) == (99.0, 1.0)


def test_to_dict_writes_fire_only_in_fire_mode() -> None:
    p = Profile.fire_watch()
    p.countMode = "blob"
    assert "fire" not in p.to_dict()
    assert "fire" not in Profile.jeweler().to_dict() and "fire" not in Profile.egg().to_dict()
    assert "safety" not in Profile.fire_watch().to_dict()


def test_schema_zones(validator: Draft202012Validator) -> None:
    d = Profile.fire_watch().to_dict()
    ok = {**d, "fire": {**d["fire"], "ignoreZones": [TRI]}}
    assert errors(validator, ok) == []
    for zones in ([[[0.1, 0.1], [0.4, 0.1]]],                                  # 2 nokta
                  [[[i / 20, 0.5] for i in range(13)]],                        # 13 nokta
                  [[[0.1, 0.1], [0.4, 1.2], [0.2, 0.3]]],                      # aralık dışı
                  [TRI] * 9,                                                   # 9 bölge
                  [[[0.1, 0.1, 0.2], [0.4, 0.1], [0.2, 0.3]]]):                # 3 değerli nokta
        assert errors(validator, {**d, "fire": {**d["fire"], "ignoreZones": zones}}), zones
    assert errors(validator, {**d, "fire": {**d["fire"], "sensitivity": "extreme"}})
    assert errors(validator, {**d, "fire": {**d["fire"], "extra": 1}})
    assert errors(validator, {**d, "fire": {"fire": {"enabled": True}}})        # seconds zorunlu
    assert errors(validator, {**d, "fire": {}}) == []                           # {} geçerli


def test_catalog_and_make_preset() -> None:
    cat = next(c for c in CATALOG if c["id"] == "fire")
    assert cat["title"] == "Yangın / duman" and cat["subtitle"] == "Alev ve duman için erken uyarı"
    assert cat["presets"] == [{"key": "fire", "name": "Yangın / duman"}]
    assert cat.get("available", True) is True
    p = make_preset("fire")
    assert p.countMode == "fire" and p.name == "Yangın / duman"
