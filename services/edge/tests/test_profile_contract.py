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


@pytest.mark.parametrize("factory", [Profile, Profile.egg, Profile.flour_sack, Profile.box],
                         ids=["default", "egg", "flour", "box"])
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
