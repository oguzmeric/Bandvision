"""Python `Profile` modeli ile `contracts/product-profile.schema.json` uyumu (F0.3)."""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from bantvision.core import Profile

CONTRACTS = pathlib.Path(__file__).resolve().parents[3] / "contracts"
PROFILE_EXAMPLES = sorted((CONTRACTS / "examples").glob("profile-*.json"))


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = json.loads((CONTRACTS / "product-profile.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def assert_valid(v: Draft202012Validator, doc: dict[str, Any]) -> None:
    errs = ["/".join(map(str, e.absolute_path)) + ": " + e.message for e in v.iter_errors(doc)]
    assert errs == []


@pytest.mark.parametrize("factory", [Profile, Profile.egg, Profile.flour_sack, Profile.box, Profile.people,
                                     Profile.vehicles, Profile.animals],
                         ids=["default", "egg", "flour", "box", "people", "vehicle", "animal"])
def test_builtin_profiles_serialize_to_valid_contract(validator: Draft202012Validator, factory: Any) -> None:
    assert_valid(validator, factory().to_dict())


@pytest.mark.parametrize("example", PROFILE_EXAMPLES, ids=lambda p: p.name)
def test_example_round_trips_through_model(validator: Draft202012Validator, example: pathlib.Path) -> None:
    src = json.loads(example.read_text(encoding="utf-8"))
    p = Profile.from_dict(src)
    out = p.to_dict()
    assert_valid(validator, out)
    # Zorunlu alanlar ve kaynak/ölçek ayarları kayıpsız taşınmalı.
    required = json.loads((CONTRACTS / "product-profile.schema.json").read_text(encoding="utf-8"))["required"]
    for key in required:
        assert out[key] == src[key], key
    assert out["source"]["rotation"] == src.get("source", {}).get("rotation", 0)
    assert out["scale"]["mmPerPixel"] == src.get("scale", {}).get("mmPerPixel")
    assert out["io"] == src.get("io", {})
    assert Profile.from_dict(out) == p


def test_staff_colors_round_trip_and_validate(validator: Draft202012Validator) -> None:
    p = Profile.people()
    assert "staffColors" not in p.to_dict()                       # boşsa yazılmaz
    p.staffColors = [(62.5, 48.25, 63.0), (30.0, -12.5, -40.0)]
    d = p.to_dict()
    assert d["staffColors"] == [{"L": 62.5, "a": 48.25, "b": 63.0}, {"L": 30.0, "a": -12.5, "b": -40.0}]
    assert_valid(validator, d)
    assert Profile.from_dict(d).staffColors == p.staffColors
    d["staffColors"] = d["staffColors"] * 2                         # 4 renk: şema reddeder
    assert list(validator.iter_errors(d))


def test_safety_profile_round_trip_and_validate(validator: Draft202012Validator) -> None:
    p = Profile.jeweler()
    d = p.to_dict()
    assert d["countMode"] == "safety" and d["safety"] == {
        "handsUp": {"enabled": True, "seconds": 3.0}, "lying": {"enabled": True, "seconds": 10.0}, "sendImage": False}
    assert d["detectClasses"] == ["person"] and d["countAnchor"] == "bottom"
    assert_valid(validator, d)
    q = Profile.from_dict({**d, "safety": {"handsUp": {"enabled": False, "seconds": 5}, "lying": {"enabled": True,
                                                                                               "seconds": 30},
                                          "sendImage": True}})
    assert (q.safety.handsUp.enabled, q.safety.handsUp.seconds, q.safety.lying.seconds, q.safety.sendImage) == \
        (False, 5.0, 30.0, True)
    bad = {**d, "safety": {**d["safety"], "handsUp": {"enabled": True, "seconds": 6}}}
    assert list(validator.iter_errors(bad))
