"""Sözleşme doğrulayıcı (F0.3).

Kullanım: python tools/validate_contracts.py

Kontroller:
- `contracts/*.schema.json` dosyalarının kendisi geçerli Draft 2020-12 şeması mı,
- `contracts/examples/` altındaki her örnek, dosya adı önekine karşılık gelen şemaya uyuyor mu.

Formatlar (uuid, date-time) da denetlenir; bunun için `jsonschema[format-nongpl]` kurulu olmalıdır.
Eşlemesi olmayan bir örnek dosyası hata sayılır, böylece hiçbir örnek doğrulanmadan kalmaz.
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
EXAMPLES = CONTRACTS / "examples"

# Örnek dosya adı öneki → şema (gerekirse `#/$defs/...` ile alt tanım). İlk eşleşen kazanır.
EXAMPLE_SCHEMAS: list[tuple[str, str]] = [
    ("profile-", "product-profile.schema.json"),
    ("event-", "event.schema.json"),
    ("batch", "batch.schema.json"),
    ("device-pair-request", "device.schema.json#/$defs/pairRequest"),
    ("device-pair-response", "device.schema.json#/$defs/pairResponse"),
    ("analysis-job", "analysis-job.schema.json"),
]


def load_schemas() -> dict[str, dict[str, Any]]:
    return {p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(CONTRACTS.glob("*.schema.json"))}


def build_registry(schemas: dict[str, dict[str, Any]]) -> Registry:
    """Şemaları hem dosya adıyla (`event.schema.json`) hem `$id` ile (`bantvision.event.v1`) kaydeder."""
    reg = Registry()
    for name, contents in schemas.items():
        res = Resource.from_contents(contents)
        reg = reg.with_resource(name, res)
        if "$id" in contents:
            reg = reg.with_resource(contents["$id"], res)
    return reg


def validator_for(ref: str, schemas: dict[str, dict[str, Any]] | None = None) -> Draft202012Validator:
    """`ref` (ör. `device.schema.json#/$defs/pairRequest`) için format denetimli doğrulayıcı."""
    schemas = schemas if schemas is not None else load_schemas()
    return Draft202012Validator(
        {"$ref": ref}, registry=build_registry(schemas), format_checker=Draft202012Validator.FORMAT_CHECKER
    )


def schema_ref_for(example: pathlib.Path) -> str | None:
    for prefix, ref in EXAMPLE_SCHEMAS:
        if example.name.startswith(prefix):
            return ref
    return None


def errors_for(instance: Any, ref: str, schemas: dict[str, dict[str, Any]] | None = None) -> list[str]:
    v = validator_for(ref, schemas)
    out = []
    for e in sorted(v.iter_errors(instance), key=lambda e: list(map(str, e.absolute_path))):
        where = "/".join(map(str, e.absolute_path)) or "(kök)"
        out.append(f"{where}: {e.message}")
    return out


def main() -> int:
    schemas = load_schemas()
    failures = 0

    for name, contents in schemas.items():
        try:
            Draft202012Validator.check_schema(contents)
        except Exception as exc:  # noqa: BLE001 - tüm şema hatalarını raporla
            print(f"HATA şema {name}: {exc}")
            failures += 1

    examples = sorted(EXAMPLES.glob("*.json"))
    if not examples:
        print(f"HATA: {EXAMPLES} altında örnek yok")
        return 1

    for ex in examples:
        ref = schema_ref_for(ex)
        if ref is None:
            print(f"HATA {ex.name}: hangi şemaya ait olduğu bilinmiyor (EXAMPLE_SCHEMAS'a ekle)")
            failures += 1
            continue
        errs = errors_for(json.loads(ex.read_text(encoding="utf-8")), ref, schemas)
        if errs:
            failures += 1
            for msg in errs:
                print(f"HATA {ex.name} ({ref}) {msg}")
        else:
            print(f"ok   {ex.name} ({ref})")

    print(f"{len(schemas)} şema, {len(examples)} örnek, {failures} hata")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
