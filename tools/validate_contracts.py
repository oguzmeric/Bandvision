"""Sözleşme doğrulayıcı (F0.3).

Kullanım: python tools/validate_contracts.py

Kontroller:
- `contracts/*.schema.json` dosyalarının kendisi geçerli Draft 2020-12 şeması mı,
- `contracts/examples/` altındaki her örnek, dosya adı önekine karşılık gelen şemaya uyuyor mu,
- `DATA_FILES` içindeki veri dosyaları (ör. `view-layouts.json`) kendi şemalarına uyuyor mu.

Formatlar (uuid, date-time) da denetlenir; bunun için `jsonschema[format-nongpl]` kurulu olmalıdır.
Eşlemesi olmayan bir örnek dosyası hata sayılır, böylece hiçbir örnek doğrulanmadan kalmaz.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from collections.abc import Iterator
from typing import Any

from jsonschema import Draft202012Validator, ValidationError, validators
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

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
    ("view-template", "view-template.schema.json"),
]

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"

# Veri dosyaları: kendi şemalarına uymalı (düzen kataloğu web ve iPhone'da birebir kullanılır)
DATA_FILES: list[tuple[str, str]] = [("view-layouts.json", "view-layouts.schema.json")]


def ecma_pattern(pattern: str) -> str:
    r"""JSON Schema desenleri ECMA-262'dir: `$` (çok satır kipi olmadan) dizgenin SONUDUR. Python'un `re`'sinde `$` sondaki
    satır sonundan önce de eşleşir ("6x8\n" `^…$`'e uyardı). Kaçışsız ve karakter sınıfı dışındaki her `$`, `\Z` olur."""
    out: list[str] = []
    i, in_class = 0, False
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\":                                        # kaçış: iki karakter olduğu gibi
            out.append(pattern[i:i + 2])
            i += 2
            continue
        if in_class:
            in_class = ch != "]"
        elif ch == "[":
            in_class = True
        elif ch == "$":
            ch = r"\Z"
        out.append(ch)
        i += 1
    return "".join(out)


def _pattern(validator: Any, patrn: str, instance: Any, schema: dict[str, Any]) -> Iterator[ValidationError]:
    """`pattern` anahtar sözcüğü, ECMA-262 anlamıyla (`ecma_pattern`)."""
    if validator.is_type(instance, "string") and not re.search(ecma_pattern(patrn), instance):
        yield ValidationError(f"{instance!r} does not match {patrn!r}")


# Draft 2020-12; yalnız `pattern` JSON Schema'daki gibi uygulanır (`$` = dizgenin sonu)
ContractValidator = validators.extend(Draft202012Validator, {"pattern": _pattern})


def load_schemas() -> dict[str, dict[str, Any]]:
    return {p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(CONTRACTS.glob("*.schema.json"))}


def build_registry(schemas: dict[str, dict[str, Any]]) -> Registry:
    """Şemaları hem dosya adıyla (`event.schema.json`) hem `$id` ile (`bantvision.event.v1`) kaydeder. Bütün şemalar
    Draft 2020-12'dir (`main` denetler); kayıtta `$schema` çıkarılır: yoksa jsonschema başvurulan şemanın `$schema`'sına
    bakıp standart doğrulayıcıya döner ve `ContractValidator`'ın desen kuralı o şemada uygulanmazdı."""
    reg = Registry()
    for name, contents in schemas.items():
        res = Resource(contents={k: v for k, v in contents.items() if k != "$schema"}, specification=DRAFT202012)
        reg = reg.with_resource(name, res)
        if "$id" in contents:
            reg = reg.with_resource(contents["$id"], res)
    return reg


def validator_for(ref: str, schemas: dict[str, dict[str, Any]] | None = None) -> Draft202012Validator:
    """`ref` (ör. `device.schema.json#/$defs/pairRequest`) için format denetimli doğrulayıcı (desenler `ecma_pattern`)."""
    schemas = schemas if schemas is not None else load_schemas()
    return ContractValidator(
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
        if contents.get("$schema") != DRAFT_2020_12:            # build_registry bunu varsayar
            print(f"HATA şema {name}: $schema {DRAFT_2020_12} olmalı")
            failures += 1
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

    for data_name, ref in DATA_FILES:
        errs = errors_for(json.loads((CONTRACTS / data_name).read_text(encoding="utf-8")), ref, schemas)
        if errs:
            failures += 1
            print(f"HATA: {data_name}")
            for e in errs:
                print(f"  - {e}")
        else:
            print(f"tamam: {data_name}")

    print(f"{len(schemas)} şema, {len(examples)} örnek, {failures} hata")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
