"""Sözleşme şemaları ve örnekleri (F0.3).

Olumlu testler: her örnek kendi şemasına uyuyor, her olay tipi en az bir örnekte var.
Olumsuz testler: geçerli bir örneği tek noktadan bozunca şema doğru kuraldan (keyword + yol) reddediyor.
Böylece şemadaki bir kısıt yanlışlıkla gevşerse test kırılır.
"""
from __future__ import annotations

import copy
import json
import pathlib
from collections.abc import Callable
from typing import Any

import pytest
import validate_contracts as vc
from jsonschema import Draft202012Validator, ValidationError

EXAMPLES = sorted(vc.EXAMPLES.glob("*.json"))


def load(name: str) -> Any:
    return json.loads((vc.EXAMPLES / name).read_text(encoding="utf-8"))


def all_errors(instance: Any, ref: str) -> list[ValidationError]:
    """Tüm hatalar, iç içe (`context`) olanlar dahil."""
    out: list[ValidationError] = []
    stack = list(vc.validator_for(ref).iter_errors(instance))
    while stack:
        e = stack.pop()
        out.append(e)
        stack.extend(e.context)
    return out


@pytest.mark.parametrize("schema_name", sorted(vc.load_schemas()))
def test_schema_is_valid_draft_2020_12(schema_name: str) -> None:
    Draft202012Validator.check_schema(vc.load_schemas()[schema_name])


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.name)
def test_example_matches_schema(example: pathlib.Path) -> None:
    ref = vc.schema_ref_for(example)
    assert ref is not None, f"{example.name} hiçbir şemaya eşlenmemiş"
    assert vc.errors_for(json.loads(example.read_text(encoding="utf-8")), ref) == []


def test_every_event_type_has_an_example() -> None:
    types: set[str] = set()
    for ex in EXAMPLES:
        doc = json.loads(ex.read_text(encoding="utf-8"))
        if ex.name.startswith("event-"):
            types.add(doc["type"])
        elif ex.name.startswith("batch"):
            types.update(e["type"] for e in doc["events"])
    enum = vc.load_schemas()["event.schema.json"]["properties"]["type"]["enum"]
    assert types == set(enum)


def test_validator_main_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert vc.main() == 0
    assert "0 hata" in capsys.readouterr().out


# (açıklama, örnek dosya, şema ref, bozma işlemi, beklenen keyword, beklenen yol)
Mutation = Callable[[Any], None]


def _set(path: list[Any], value: Any) -> Mutation:
    def f(doc: Any) -> None:
        for k in path[:-1]:
            doc = doc[k]
        doc[path[-1]] = value
    return f


def _del(path: list[Any]) -> Mutation:
    def f(doc: Any) -> None:
        for k in path[:-1]:
            doc = doc[k]
        del doc[path[-1]]
    return f


def _many_events(doc: Any) -> None:
    doc["events"] = [copy.deepcopy(doc["events"][0]) for _ in range(501)]


PROFILE = ("profile-egg.json", "product-profile.schema.json")
POLY = ("profile-box-polygon.json", "product-profile.schema.json")
JOB = ("analysis-job-done.json", "analysis-job.schema.json")
EVENT = ("event-state.json", "event.schema.json")
BATCH = ("batch.json", "batch.schema.json")
PAIR = ("device-pair-request.json", "device.schema.json#/$defs/pairRequest")

NEGATIVE_CASES = [
    ("profil şema sürümü", *PROFILE, _set(["schema"], "bantvision.profile.v2"), "const", ["schema"]),
    ("profil id uuid değil", *PROFILE, _set(["id"], "yumurta-1"), "format", ["id"]),
    ("profil yön eksik", *PROFILE, _del(["direction"]), "required", []),
    ("profil yön geçersiz", *PROFILE, _set(["direction"], "diagonal"), "enum", ["direction"]),
    ("profil ROI 1'den büyük", *PROFILE, _set(["roi", "x"], 1.5), "maximum", ["roi", "x"]),
    ("profil ROI genişliği 0", *PROFILE, _set(["roi", "width"], 0), "exclusiveMinimum", ["roi", "width"]),
    ("profil eşik tamsayı değil", *PROFILE, _set(["diffThreshold"], 28.5), "type", ["diffThreshold"]),
    ("profil döndürme açısı", *PROFILE, _set(["source", "rotation"], 45), "enum", ["source", "rotation"]),
    ("profil io kanalı", *PROFILE, _set(["io", "eject", "channel"], 5), "maximum", ["io", "eject", "channel"]),
    ("profil çokgen 3 köşeden az", *POLY, _set(["roiPolygon"], [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.9}]),
     "minItems", ["roiPolygon"]),
    ("profil çokgen köşesi 1'den büyük", *POLY, _set(["roiPolygon", 2, "x"], 1.2), "maximum", ["roiPolygon", 2, "x"]),
    ("profil çokgen köşesinde y yok", *POLY, _del(["roiPolygon", 0, "y"]), "required", ["roiPolygon", 0]),
    ("profil sayım çizgisinde b yok", *POLY, _del(["countLine", "b"]), "required", ["countLine"]),
    ("profil sayım çizgisi ucu 1'den büyük", *POLY, _set(["countLine", "a", "x"], 1.4), "maximum",
     ["countLine", "a", "x"]),
    ("profil sayım çizgisinde bilinmeyen alan", *POLY, _set(["countLine", "renk"], "mor"), "additionalProperties",
     ["countLine"]),
    ("profil çokgen 12 köşeden çok", *POLY, _set(["roiPolygon"], [{"x": 0.5, "y": i / 20} for i in range(13)]),
     "maxItems", ["roiPolygon"]),
    ("iş durumu geçersiz", *JOB, _set(["status"], "paused"), "enum", ["status"]),
    ("biten işte sonuç yok", *JOB, _del(["result"]), "required", []),
    ("başarısız işte hata yok", *JOB, _set(["status"], "failed"), "required", []),
    ("iş ilerlemesi 1'den büyük", *JOB, _set(["progress"], 1.5), "maximum", ["progress"]),
    ("iş sonuç dosyası bilinmiyor", *JOB, _set(["result", "files"], ["../etc/passwd"]), "enum", ["result", "files", 0]),
    ("iş seçeneğinde çokgen bozuk", *JOB, _set(["options", "roiPolygon"], [{"x": 0.1, "y": 0.1}]), "minItems",
     ["options", "roiPolygon"]),
    ("iş bilinmeyen alan", *JOB, _set(["sahibi"], "x"), "additionalProperties", []),
    ("olay ts tarih-saat değil", *EVENT, _set(["ts"], "2026-10-01"), "format", ["ts"]),
    ("olay eventId uuid değil", *EVENT, _set(["eventId"], "42"), "format", ["eventId"]),
    ("olay tipi geçersiz", *EVENT, _set(["type"], "pause"), "enum", ["type"]),
    ("state olayında state yok", *EVENT, _del(["state"]), "required", []),
    ("state nedeni geçersiz", *EVENT, _set(["state", "reason"], "lunch"), "enum", ["state", "reason"]),
    ("count olayında count yok", "event-count-edge.json", "event.schema.json", _del(["count"]), "required", []),
    ("count delta 0", "event-count-edge.json", "event.schema.json", _set(["count", "delta"], 0), "minimum",
     ["count", "delta"]),
    ("batch içinde NOK nedeni geçersiz", *BATCH, _set(["events", 1, "inspection", "reasons"], ["dirty"]), "enum",
     ["events", 1, "inspection", "reasons", 0]),
    ("batch içinde olay uuid bozuk", *BATCH, _set(["events", 0, "eventId"], "x"), "format",
     ["events", 0, "eventId"]),
    ("batch 500'den fazla olay", *BATCH, _many_events, "maxItems", ["events"]),
    ("batch sentAt eksik", *BATCH, _del(["sentAt"]), "required", []),
    ("eşleme kodu biçimi", *PAIR, _set(["code"], "abc123"), "pattern", ["code"]),
    ("eşleme cihaz türü", *PAIR, _set(["deviceInfo", "kind"], "android"), "enum", ["deviceInfo", "kind"]),
    ("eşleme yanıtında anahtar yok", "device-pair-response.json", "device.schema.json#/$defs/pairResponse",
     _del(["deviceKey"]), "required", []),
]


@pytest.mark.parametrize(
    ("example", "ref", "mutate", "keyword", "path"),
    [c[1:] for c in NEGATIVE_CASES],
    ids=[c[0] for c in NEGATIVE_CASES],
)
def test_schema_rejects_mutation(example: str, ref: str, mutate: Mutation, keyword: str, path: list[Any]) -> None:
    doc = load(example)
    assert vc.errors_for(doc, ref) == [], "başlangıç örneği geçerli olmalı"
    mutate(doc)
    errs = all_errors(doc, ref)
    found = {(e.validator, tuple(e.absolute_path)) for e in errs}
    assert (keyword, tuple(path)) in found, f"beklenen ({keyword}, {path}) yok; bulunan: {sorted(found, key=str)}"


def test_unmapped_example_is_reported(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                      capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "mystery.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(vc, "EXAMPLES", tmp_path)
    assert vc.main() == 1
    assert "mystery.json" in capsys.readouterr().out


def _layouts() -> list[dict[str, Any]]:
    return json.loads((vc.CONTRACTS / "view-layouts.json").read_text(encoding="utf-8"))["layouts"]


def test_view_layouts_file_matches_schema() -> None:
    data = json.loads((vc.CONTRACTS / "view-layouts.json").read_text(encoding="utf-8"))
    assert vc.errors_for(data, "view-layouts.schema.json") == []


@pytest.mark.parametrize("lay", _layouts(), ids=lambda d: d["id"])
def test_view_layout_cells_tile_the_grid_exactly(lay: dict[str, Any]) -> None:
    cover = [[0] * lay["cols"] for _ in range(lay["rows"])]
    for x, y, w, h in lay["cells"]:
        assert w >= 1 and h >= 1 and x + w <= lay["cols"] and y + h <= lay["rows"], (lay["id"], x, y, w, h)
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                cover[yy][xx] += 1
    assert all(c == 1 for row in cover for c in row), f"{lay['id']}: boşluk ya da çakışma"   # tam ve çakışmasız
    assert len(lay["cells"]) == int(lay["id"])                                             # ad = kutu sayısı


def test_view_layout_ids_are_the_agreed_set() -> None:
    assert [d["id"] for d in _layouts()] == ["1", "2", "3", "4", "6", "8", "9", "12", "16"]
