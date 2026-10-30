import assert from "node:assert/strict";
import test from "node:test";
import {
  FULL_CHROME_H, MAX_TILES, STATE_LINE_H, TILE_FULL, TILE_SMALL, TILE_TINY, gridId, layoutFor, parseGrid, stateLines, tileSize, tileTier,
} from "./layoutGrid.mjs";

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

test("tileTier: kutu katmanının yoğunluğu kutunun dış boyutundan (CSS px)", () => {
  assert.deepEqual([TILE_FULL, TILE_SMALL, TILE_TINY], [{ w: 128, h: 72 }, { w: 72, h: 44 }, { w: 24, h: 22 }]);
  const at = (id, w, h, i = 0) => tileTier(layoutFor(id, []), i, { w, h });
  // ölçülen ızgaralar (e2e): masaüstü 1280 px ve telefon 390 px
  assert.equal(at("2x2", 740, 416.3), "full");            // 370×208
  assert.equal(at("4x4", 740, 416.3), "full");            // 185×104
  assert.equal(at("5x5", 740, 416.3), "full");            // 148×83
  assert.equal(at("8x8", 740, 416.3), "small");           // 92.5×52
  assert.equal(at("8x16", 740, 208.1), "tiny");           // 46×26
  assert.equal(at("3x3", 350, 196.9), "small");           // 117×66 (alçak)
  assert.equal(at("4x4", 350, 196.9), "small");           // 87.5×49
  assert.equal(at("5x5", 350, 196.9), "tiny");            // 70×39
  assert.equal(at("8x8", 350, 196.9), "tiny");            // 43.75×24.6
  assert.equal(at("8x16", 350, 98.4), "micro");           // 21.9×12.3: köşedeki nokta kutudan taşardı
  assert.equal(at("1x16", 350, 12.3), "micro");           // 21.9×12.3
  // sınırlar: eşik dahil
  assert.equal(at("1x1", 128, 72), "full");
  assert.equal(at("1x1", 127.9, 72), "small");
  assert.equal(at("1x1", 128, 71.9), "small");
  assert.equal(at("1x1", 72, 44), "small");
  assert.equal(at("1x1", 71.9, 44), "tiny");
  assert.equal(at("1x1", 72, 43.9), "tiny");
  assert.equal(at("1x1", 24, 22), "tiny");
  assert.equal(at("1x1", 23.9, 22), "micro");
  assert.equal(at("1x1", 24, 21.9), "micro");
  // birden çok hücre kaplayan kutu (1+5'in büyüğü) kapladığı alanla ölçülür
  const one5 = { id: "6", name: "1+5", cols: 3, rows: 3, cells: [[0, 0, 2, 2], [2, 0, 1, 1], [2, 1, 1, 1], [0, 2, 1, 1], [1, 2, 1, 1], [2, 2, 1, 1]] };
  assert.equal(tileTier(one5, 0, { w: 300, h: 150 }), "full");     // 200×100
  assert.equal(tileTier(one5, 1, { w: 300, h: 150 }), "small");    // 100×50
  assert.equal(tileTier(one5, 0, null), "full");                   // ölçülmeden önce
  assert.deepEqual(tileSize(one5, 0, { w: 300, h: 150 }), { w: 200, h: 100 });
  assert.equal(tileSize(one5, 0, null), null);
});

test("tileTier: durum metni olan normal kutunun orta alanı en az bir satır almalı; almıyorsa küçük kutu", () => {
  // orta alan = kutu yüksekliği − şeritler ve boşluklar (FULL_CHROME_H); satır STATE_LINE_H
  assert.deepEqual([FULL_CHROME_H, STATE_LINE_H], [72, 16]);
  const at = (id, w, h, i = 0) => tileTier(layoutFor(id, []), i, { w, h }, true);
  assert.equal(at("2x2", 740, 416.3), "full");            // 370×208
  assert.equal(at("4x4", 740, 416.3), "full");            // 185×104: iki satır
  assert.equal(at("5x5", 740, 416.3), "small");           // 148×83: orta alan 11 px, bir satır sığmaz
  assert.equal(at("2x2", 350, 196.9), "full");            // 175×98: bir satır
  assert.equal(at("2x2", 260, 146), "small");             // 130×73 (dokunmatik 300 px)
  assert.equal(at("4x4", 518, 291.4), "small");           // 129.5×72.8 (tablet 820 px)
  assert.equal(at("8x8", 740, 416.3), "small");           // küçük kutu durumdan etkilenmez
  assert.equal(at("8x16", 350, 98.4), "micro");
  // canlı (durum metni yok) kutu eskisi gibi: 148×83 normal
  assert.equal(tileTier(layoutFor("5x5", []), 0, { w: 740, h: 416.3 }, false), "full");
  // sınır: 128×88 bir satır alır
  assert.equal(at("1x1", 128, 88), "full");
  assert.equal(at("1x1", 128, 87.9), "small");
  assert.equal(at("1x1", 127.9, 88), "small");
  assert.equal(tileTier(layoutFor("1x1", []), 0, null, true), "full");   // ölçülmeden önce
});

test("stateLines: normal kutunun orta alanına sığan durum satırı (en çok 2)", () => {
  assert.equal(stateLines(87.9), 0);
  assert.equal(stateLines(88), 1);
  assert.equal(stateLines(98.4), 1);
  assert.equal(stateLines(103.9), 1);
  assert.equal(stateLines(104), 2);
  assert.equal(stateLines(104.1), 2);
  assert.equal(stateLines(416), 2);
  assert.equal(stateLines(10), 0);
});
