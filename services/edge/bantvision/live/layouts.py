"""Çoklu izleme düzenleri. Sözleşme: contracts/view-layouts.json (web ve iPhone birebir aynı; tests/test_layouts.py
dosyayla eşitliği denetler). Hücre (x, y, w, h) birim ızgarada; sıra kutu sırasıdır; tuval herhangi boyutta olabilir."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

Cell = tuple[int, int, int, int]


@dataclass(frozen=True)
class Layout:
    id: str
    name: str
    cols: int
    rows: int
    cells: tuple[Cell, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "cols": self.cols, "rows": self.rows,
                "cells": [list(c) for c in self.cells]}


def _grid(cols: int, rows: int) -> tuple[Cell, ...]:
    return tuple((x, y, 1, 1) for y in range(rows) for x in range(cols))


LAYOUTS: tuple[Layout, ...] = (
    Layout("1", "Tek", 1, 1, _grid(1, 1)),
    Layout("2", "2'li (yan yana)", 2, 1, _grid(2, 1)),
    Layout("3", "3'lü (1 büyük + 2)", 3, 2, ((0, 0, 2, 2), (2, 0, 1, 1), (2, 1, 1, 1))),
    Layout("4", "4'lü", 2, 2, _grid(2, 2)),
    Layout("6", "6'lı (1 büyük + 5)", 3, 3,
           ((0, 0, 2, 2), (2, 0, 1, 1), (2, 1, 1, 1), (0, 2, 1, 1), (1, 2, 1, 1), (2, 2, 1, 1))),
    Layout("8", "8'li (1 büyük + 7)", 4, 4,
           ((0, 0, 3, 3), (3, 0, 1, 1), (3, 1, 1, 1), (3, 2, 1, 1), (0, 3, 1, 1), (1, 3, 1, 1), (2, 3, 1, 1),
            (3, 3, 1, 1))),
    Layout("9", "9'lu", 3, 3, _grid(3, 3)),
    Layout("12", "12'li", 4, 3, _grid(4, 3)),
    Layout("16", "16'lı", 4, 4, _grid(4, 4)),
)
_BY_ID = {lay.id: lay for lay in LAYOUTS}
MAX_TILES = 16


def layout_by_id(layout_id: str) -> Layout | None:
    return _BY_ID.get(layout_id)


def smallest_for(n: int) -> Layout:
    """`n` kameranın sığdığı en küçük düzen (16'dan fazlası için 16)."""
    for lay in LAYOUTS:
        if len(lay.cells) >= n:
            return lay
    return LAYOUTS[-1]


def cell_rects(layout: Layout, w: int, h: int) -> list[tuple[int, int, int, int]]:
    """Hücrelerin `w×h` tuvaldeki piksel dikdörtgenleri (x0, y0, x1, y1); kenarlar komşu hücreyle örtüşür, boşluk yok."""
    out = []
    for x, y, cw, ch in layout.cells:
        out.append((round(x * w / layout.cols), round(y * h / layout.rows),
                    round((x + cw) * w / layout.cols), round((y + ch) * h / layout.rows)))
    return out
