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


@pytest.mark.parametrize(("n", "want"), [
    (1, "1"), (10, "12"), (16, "16"),                                              # 16'ya kadar katalog (değişmez)
    (17, "4x5"), (26, "5x6"), (32, "6x6"), (37, "6x7"), (64, "8x8"), (73, "9x9"), (100, "10x10"), (120, "11x11"),
    (121, "11x11"), (122, "9x14"), (127, "8x16"), (128, "8x16")])
def test_recorder_layout_catalog_up_to_16_then_largest_tile_grid(n: int, want: str) -> None:
    """"NVR'dan şablon": 16 kanala kadar katalogdaki en küçük düzen; üstünde bütün kanalları alan N×M, kutu en büyük
    olacak biçimde: önce en küçük max(satır, sütun) (16:9 kutuda kutu genişliği = ekran / max), sonra en az kutu, sonra
    sütunu fazla olan. Şerit ızgara (37 → 3x13) çıkmaz."""
    assert recorder_layout(n).id == want


def _recorder_fits(n: int) -> list[tuple[int, int]]:
    """16'dan fazla `n` kanal için aday N×M'ler: satır ve sütun 1–16, kutu sayısı n ile 128 arasında."""
    return [(r, c) for r in range(1, 17) for c in range(1, 17) if n <= r * c <= MAX_TILES]


def test_recorder_grid_orders_by_largest_tile_then_fewest_cells_then_wider_for_every_count() -> None:
    """17..128'in her sayısı için kaba kuvvetle: seçilen düzen (1) bütün kanalları alır; (2) hiçbir adayın max(satır,
    sütun)'ü daha küçük değildir; (3) aynı max'ta hiçbir aday daha az kutulu değildir; (4) aynı max ve kutuda sütun
    satırdan fazladır (satır ≤ sütun)."""
    for n in range(17, MAX_TILES + 1):
        lay = recorder_layout(n)
        rows, cols = parse_grid(lay.id) or (0, 0)
        assert rows * cols >= n and len(lay.cells) == rows * cols, n
        assert (lay.rows, lay.cols) == (rows, cols), n
        fits = _recorder_fits(n)
        assert (rows, cols) in fits, n
        side = max(rows, cols)
        assert all(max(r, c) >= side for r, c in fits), n
        assert all(r * c >= rows * cols for r, c in fits if max(r, c) == side), n
        assert rows <= cols, n


def test_recorder_grid_is_never_a_strip_above_16() -> None:
    """37 kanal 3x13'te W/13 genişlikte kutu verirdi; 6x7'de W/7 (ekran genişliği W, 16:9 kutular)."""
    assert recorder_layout(37).id == "6x7"
    assert max(recorder_layout(37).rows, recorder_layout(37).cols) == 7


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
