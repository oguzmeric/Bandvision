"""Düzen kataloğu: sözleşme dosyasıyla birebir; piksel dikdörtgenleri tuvali tam kaplar."""
from __future__ import annotations

import json
import pathlib

import pytest

from bantvision.live.layouts import (
    LAYOUTS,
    MAX_TILES,
    cell_rects,
    layout_by_id,
    parse_grid,
    recorder_layout,
    smallest_for,
)

CONTRACT = pathlib.Path(__file__).resolve().parents[3] / "contracts" / "view-layouts.json"


def test_python_catalog_equals_contract_file() -> None:
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert [lay.to_dict() for lay in LAYOUTS] == data["layouts"]


@pytest.mark.parametrize(("n", "want"), [(0, "1"), (1, "1"), (2, "2"), (3, "3"), (4, "4"), (5, "6"), (7, "8"),
                                         (9, "9"), (10, "12"), (13, "16"), (40, "16"), (500, "16")])
def test_smallest_layout_for_channel_count(n: int, want: str) -> None:
    assert smallest_for(n).id == want


@pytest.mark.parametrize(("n", "want"), [(1, "1"), (10, "12"), (16, "16"), (17, "3x6"), (32, "4x8"), (64, "8x8"),
                                         (100, "10x10"), (120, "10x12"), (127, "8x16"), (128, "8x16")])
def test_recorder_layout_catalog_up_to_16_then_smallest_grid(n: int, want: str) -> None:
    """"NVR'dan şablon": 16 kanala kadar katalogdaki en küçük düzen; üstünde bütün kanalları alan en küçük N×M (en az
    kutu; eşitse en kare, o da eşitse sütunu fazla olan)."""
    assert recorder_layout(n).id == want


def test_recorder_grid_is_the_smallest_most_square_wider_one_for_every_count() -> None:
    for n in range(17, MAX_TILES + 1):
        lay = recorder_layout(n)
        rows, cols = parse_grid(lay.id) or (0, 0)
        assert rows * cols >= n and len(lay.cells) == rows * cols, n
        fits = [(r, c) for r in range(1, 17) for c in range(1, 17) if n <= r * c <= MAX_TILES]
        best = min(fits, key=lambda rc: (rc[0] * rc[1], abs(rc[0] - rc[1]), -rc[1]))
        assert (rows, cols) == best, n
        assert cols >= rows, n                                 # eşitlikte sütun fazla: yatay ekrana uyar


def test_recorder_layout_over_128_is_rejected() -> None:
    with pytest.raises(ValueError, match="128"):
        recorder_layout(129)


@pytest.mark.parametrize("lay", LAYOUTS, ids=lambda x: x.id)
def test_cell_rects_cover_canvas_without_overlap(lay: object) -> None:
    w, h = 1280, 720
    rects = cell_rects(lay, w, h)  # type: ignore[arg-type]
    area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in rects)
    assert area == w * h
    assert all(0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h for x0, y0, x1, y1 in rects)


def test_unknown_layout_is_none() -> None:
    assert layout_by_id("5") is None and layout_by_id("16") is not None


def test_grid_id_resolves() -> None:
    lay = layout_by_id("6x8")
    assert lay is not None
    assert (lay.rows, lay.cols, lay.name) == (6, 8, "6×8")
    assert len(lay.cells) == 48 and lay.cells[9] == (1, 1, 1, 1)
    assert MAX_TILES == 128 and parse_grid("6x8") == (6, 8)


def test_grid_4x4_matches_catalog_16() -> None:
    g, c = layout_by_id("4x4"), layout_by_id("16")
    assert g is not None and c is not None
    assert (g.cells, g.cols, g.rows) == (c.cells, c.cols, c.rows)


@pytest.mark.parametrize("bad", ["0x5", "17x2", "12x12", "6X8", " 6x8", "6x", "x8", "06x8", "6x8 ", "6x8" + chr(10), "5", ""])
def test_grid_rejects(bad: str) -> None:
    assert parse_grid(bad) is None
    assert layout_by_id(bad) is None


def test_catalog_ids_unchanged() -> None:
    assert [lay.id for lay in LAYOUTS] == ["1", "2", "3", "4", "6", "8", "9", "12", "16"]
