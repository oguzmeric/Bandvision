"""Çoklu izleme düzenleri. Sözleşme: contracts/view-layouts.json (web ve iPhone birebir aynı; tests/test_layouts.py
dosyayla eşitliği denetler). Hücre (x, y, w, h) birim ızgarada; sıra kutu sırasıdır; tuval herhangi boyutta olabilir."""
from __future__ import annotations

import re
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
MAX_TILES = 128   # bir şablondaki en çok kutu (N×M için satır×sütun sınırı)
_GRID_RE = re.compile(r"([1-9]|1[0-6])x([1-9]|1[0-6])")


def parse_grid(layout_id: str) -> tuple[int, int] | None:
    """`"<satır>x<sütun>"` kimliğini (satır, sütun) olarak çözer; satır/sütun 1–16, çarpım ≤ MAX_TILES. Aksi halde None."""
    m = _GRID_RE.fullmatch(layout_id)
    if m is None:
        return None
    rows, cols = int(m.group(1)), int(m.group(2))
    return (rows, cols) if rows * cols <= MAX_TILES else None


def layout_by_id(layout_id: str) -> Layout | None:
    """Katalog kimliği ya da N×M kimliği (eşit hücreler, satır sırasıyla)."""
    lay = _BY_ID.get(layout_id)
    if lay is not None:
        return lay
    grid = parse_grid(layout_id)
    return None if grid is None else _grid_layout(*grid)


def _grid_layout(rows: int, cols: int) -> Layout:
    """N×M düzeni (`"<satır>x<sütun>"`): eşit hücreler, satır sırasıyla."""
    return Layout(f"{rows}x{cols}", f"{rows}×{cols}", cols, rows, _grid(cols, rows))


def smallest_for(n: int) -> Layout:
    """`n` kameranın sığdığı en küçük katalog düzeni (16'dan fazlası için 16)."""
    for lay in LAYOUTS:
        if len(lay.cells) >= n:
            return lay
    return LAYOUTS[-1]


def recorder_layout(n: int) -> Layout:
    """"NVR'dan şablon" için `n` kanalın hepsinin sığdığı düzen: 16'ya kadar katalogdaki en küçük düzen
    (`smallest_for`); üstünde en küçük N×M: en az kutu, eşitse en kare (satır ile sütun farkı en az), o da eşitse
    sütunu fazla olan (yatay ekrana uyar). Ör. 17 → 3×6, 32 → 4×8, 64 → 8×8, 128 → 8×16. `n` > MAX_TILES ValueError."""
    if n > MAX_TILES:
        raise ValueError(f"Bir şablonda en çok {MAX_TILES} kutu olabilir; {n} kanal sığmaz.")
    if n <= len(LAYOUTS[-1].cells):
        return smallest_for(n)
    fits = [(r, c) for r in range(1, 17) for c in range(1, 17) if n <= r * c <= MAX_TILES]
    rows, cols = min(fits, key=lambda rc: (rc[0] * rc[1], abs(rc[0] - rc[1]), -rc[1]))
    return _grid_layout(rows, cols)


def cell_rects(layout: Layout, w: int, h: int) -> list[tuple[int, int, int, int]]:
    """Hücrelerin `w×h` tuvaldeki piksel dikdörtgenleri (x0, y0, x1, y1); kenarlar komşu hücreyle örtüşür, boşluk yok."""
    out = []
    for x, y, cw, ch in layout.cells:
        out.append((round(x * w / layout.cols), round(y * h / layout.rows),
                    round((x + cw) * w / layout.cols), round((y + ch) * h / layout.rows)))
    return out
