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

test("tileTier: kutu katmanının yoğunluğu kutunun dış boyutundan (CSS px) ve kök yazı boyutundan (eşikler rem)", () => {
  // eşikler rem cinsinden (TileOverlay'in Tailwind ölçüleri); kök 16 px'te 128×72, 72×44, 24×22
  assert.deepEqual([TILE_FULL, TILE_SMALL, TILE_TINY], [{ w: 8, h: 4.5 }, { w: 4.5, h: 2.75 }, { w: 1.5, h: 1.375 }]);
  const at = (id, w, h, i = 0) => tileTier(layoutFor(id, []), i, { w, h });
  // ölçülen ızgaralar (e2e, kök 16 px): masaüstü 1280 px ve telefon 390 px
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
  // sınırlar: eşik dahil (kök 16 px)
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

test("tileTier: kök yazı boyutu 16, 20, 24 px; eşikler onunla büyür (ölçülen kutular)", () => {
  const tier = (w, h, rem) => tileTier(layoutFor("1x1", []), 0, { w, h }, rem);
  for (const rem of [16, 20, 24]) {
    // sınırlar: 8×4.5 rem normal, 4.5×2.75 rem küçük, 1.5×1.375 rem çok küçük
    assert.equal(tier(8 * rem, 4.5 * rem, rem), "full", `kök ${rem}`);
    assert.equal(tier(8 * rem - 0.1, 4.5 * rem, rem), "small", `kök ${rem}`);
    assert.equal(tier(8 * rem, 4.5 * rem - 0.1, rem), "small", `kök ${rem}`);
    assert.equal(tier(4.5 * rem, 2.75 * rem, rem), "small", `kök ${rem}`);
    assert.equal(tier(4.5 * rem - 0.1, 2.75 * rem, rem), "tiny", `kök ${rem}`);
    assert.equal(tier(1.5 * rem, 1.375 * rem, rem), "tiny", `kök ${rem}`);
    assert.equal(tier(1.5 * rem, 1.375 * rem - 0.1, rem), "micro", `kök ${rem}`);
  }
  // ölçülen kutular (e2e, Chrome yazı boyutu 20 / 24 px)
  assert.equal(tier(180, 101.25, 20), "full");            // masaüstü 4×4
  assert.equal(tier(144, 81, 20), "small");               // masaüstü 5×5 (16 px'te normaldi: alarm etiketi taşardı)
  assert.equal(tier(170, 95.63, 20), "full");             // telefon 2×2
  assert.equal(tier(113.33, 63.75, 20), "small");         // telefon 3×3
  assert.equal(tier(235.5, 132.47, 24), "full");          // masaüstü 4×4
  assert.equal(tier(188.39, 105.97, 24), "small");        // masaüstü 5×5
  assert.equal(tier(165, 92.81, 24), "small");            // telefon 2×2
  assert.equal(tier(110, 61.88, 24), "tiny");             // telefon 3×3
});

test("tileTier: kameranın durumuna bağlı değil (yalnız boyut ve kök yazı boyutu)", () => {
  // 148×83 (masaüstü 5×5): orta alan bir satır almaz ama kutu yine normaldir; durum orada noktaya döner (stateLines 0)
  assert.equal(tileTier(layoutFor("5x5", []), 0, { w: 740, h: 416.3 }), "full");
  assert.equal(stateLines(83.3), 0);
});

test("stateLines: normal kutunun orta alanına sığan durum satırı (en çok 2), kök yazı boyutuyla", () => {
  // orta alan = kutu yüksekliği − FULL_CHROME_H rem; satır STATE_LINE_H rem
  assert.deepEqual([FULL_CHROME_H, STATE_LINE_H], [4.5, 1]);
  assert.equal(stateLines(87.9), 0);
  assert.equal(stateLines(88), 1);
  assert.equal(stateLines(98.4), 1);
  assert.equal(stateLines(103.9), 1);
  assert.equal(stateLines(104), 2);
  assert.equal(stateLines(104.1), 2);
  assert.equal(stateLines(416), 2);
  assert.equal(stateLines(10), 0);
  for (const rem of [16, 20, 24]) {
    assert.equal(stateLines(5.5 * rem - 0.1, rem), 0, `kök ${rem}`);
    assert.equal(stateLines(5.5 * rem, rem), 1, `kök ${rem}`);
    assert.equal(stateLines(6.5 * rem - 0.1, rem), 1, `kök ${rem}`);
    assert.equal(stateLines(6.5 * rem, rem), 2, `kök ${rem}`);
  }
  assert.equal(stateLines(101.25, 20), 0);                 // masaüstü 4×4, 20 px: durum noktaya döner (eskiden ince şerit)
  assert.equal(stateLines(95.63, 20), 0);                  // telefon 2×2, 20 px
  assert.equal(stateLines(132.47, 24), 1);                 // masaüstü 4×4, 24 px
});
