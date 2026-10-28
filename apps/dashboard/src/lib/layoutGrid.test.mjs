import assert from "node:assert/strict";
import test from "node:test";
import { MAX_TILES, gridId, layoutFor, parseGrid } from "./layoutGrid.mjs";

test("parseGrid geçerli N×M kimliklerini çözer", () => {
  assert.deepEqual(parseGrid("6x8"), { rows: 6, cols: 8 });
  assert.deepEqual(parseGrid("1x1"), { rows: 1, cols: 1 });
  assert.deepEqual(parseGrid("8x16"), { rows: 8, cols: 16 });
  assert.equal(MAX_TILES, 128);
});

test("parseGrid sınır dışı ve bozuk kimlikleri reddeder", () => {
  for (const bad of ["0x5", "17x2", "12x12", "6X8", " 6x8", "6x8 ", "6x", "x8", "06x8", "5", "", "6x8\n"]) {
    assert.equal(parseGrid(bad), null, JSON.stringify(bad));
  }
});

test("layoutFor N×M geometrisini üretir, katalog kimliğini katalogdan alır", () => {
  const g = layoutFor("6x8", []);
  assert.ok(g);
  assert.equal(g.name, "6×8");
  assert.equal(g.rows, 6);
  assert.equal(g.cols, 8);
  assert.equal(g.cells.length, 48);
  assert.deepEqual(g.cells[9], [1, 1, 1, 1]);
  const entry = { id: "3", name: "3'lü", cols: 3, rows: 2, cells: [[0, 0, 2, 2], [2, 0, 1, 1], [2, 1, 1, 1]] };
  assert.equal(layoutFor("3", [entry]), entry);
  assert.equal(layoutFor("3", []), null);
  assert.equal(layoutFor("12x12", []), null);
});

test("gridId kimlik üretir", () => {
  assert.equal(gridId(5, 5), "5x5");
});
