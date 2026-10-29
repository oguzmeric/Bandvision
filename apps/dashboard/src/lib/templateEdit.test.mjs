import assert from "node:assert/strict";
import test from "node:test";
import {
  EDITOR_LAYOUTS, HISTORY_LIMIT, applyLayout, assign, canRedo, canUndo, initHistory, isDirty, neighbor, newDraft, newName, parseUnsaved, push,
  redo, refKey, retile, sameContent, swap, undo, validateGrid,
} from "./templateEdit.mjs";

const CATALOG = [
  { id: "1", name: "Tek", cols: 1, rows: 1, cells: [[0, 0, 1, 1]] },
  { id: "3", name: "3'lü", cols: 3, rows: 2, cells: [[0, 0, 2, 2], [2, 0, 1, 1], [2, 1, 1, 1]] },
  { id: "4", name: "4'lü", cols: 2, rows: 2, cells: [[0, 0, 1, 1], [1, 0, 1, 1], [0, 1, 1, 1], [1, 1, 1, 1]] },
];
const cam = (s, c = null) => ({ sourceId: s, channelId: c });
const draft = (tiles, layout = "4") => ({ layout, tiles, name: "Ş" });

test("EDITOR_LAYOUTS: 10 düğme, spec sırası, sonuncusu N×M", () => {
  assert.deepEqual(EDITOR_LAYOUTS, ["1", "4", "9", "16", "6", "8", "12", "5x5", "8x8", "nxm"]);
});

test("newDraft: 2×2 ('4'), 4 boş kutu, ad 'Yeni şablon'", () => {
  assert.deepEqual(newDraft(CATALOG), { layout: "4", tiles: [null, null, null, null], name: "Yeni şablon" });
  assert.deepEqual(newDraft([]).tiles, [null, null, null, null]);   // katalog gelmeden de 4 kutu
});

test("newName: dolu adlar atlanır", () => {
  assert.equal(newName([]), "Yeni şablon");
  assert.equal(newName(["Yeni şablon"]), "Yeni şablon 2");
  assert.equal(newName(["Yeni şablon", "Yeni şablon 2"]), "Yeni şablon 3");
});

test("retile: sırayla korur, sığmayan kamerayı sayar", () => {
  assert.deepEqual(retile([cam("a"), null, cam("b")], 2), { tiles: [cam("a"), null], dropped: 1 });
  assert.deepEqual(retile([cam("a")], 3), { tiles: [cam("a"), null, null], dropped: 0 });
});

test("applyLayout('8x8') ilk 4 kamerayı korur, 64 kutu; küçülünce düşenler sayılır", () => {
  const d = draft([cam("a"), cam("b"), cam("c"), cam("d")]);
  const big = applyLayout(d, "8x8", CATALOG);
  assert.equal(big.draft.layout, "8x8");
  assert.equal(big.draft.tiles.length, 64);
  assert.deepEqual(big.draft.tiles.slice(0, 4), d.tiles);
  assert.ok(big.draft.tiles.slice(4).every((t) => t === null));
  assert.equal(big.dropped, 0);
  const small = applyLayout(d, "1", CATALOG);
  assert.deepEqual(small, { draft: { layout: "1", tiles: [cam("a")], name: "Ş" }, dropped: 3 });
  assert.deepEqual(d.tiles, [cam("a"), cam("b"), cam("c"), cam("d")]);                  // girdi değişmez
  // bilinmeyen kimlik: değişiklik yok
  assert.deepEqual(applyLayout(d, "17x2", CATALOG), { draft: d, dropped: 0 });
});

test("assign: yerleştirir, boşaltır; başka kutudaki kamera taşınır (kopya olmaz)", () => {
  const d = draft([cam("a"), null, cam("b", "2"), null]);
  assert.deepEqual(assign(d, 1, cam("c")).tiles, [cam("a"), cam("c"), cam("b", "2"), null]);
  assert.deepEqual(assign(d, 0, null).tiles, [null, null, cam("b", "2"), null]);
  assert.deepEqual(assign(d, 3, cam("b", "2")).tiles, [cam("a"), null, null, cam("b", "2")]);   // taşındı
  assert.deepEqual(assign(d, 0, cam("b", "2")).tiles, [cam("b", "2"), null, null, null]);       // eskisini ezip taşındı
  assert.deepEqual(assign(d, 2, cam("b", "2")), d);                                           // aynı yere: değişmez
  assert.deepEqual(assign(d, 3, cam("b", null)).tiles, [cam("a"), null, cam("b", "2"), cam("b")]);   // kanal farklı: ayrı kamera
  assert.deepEqual(d.tiles, [cam("a"), null, cam("b", "2"), null]);                          // girdi değişmez
});

test("swap: iki kutu yer değiştirir", () => {
  const d = draft([cam("a"), null, cam("b"), null]);
  assert.deepEqual(swap(d, 0, 1).tiles, [null, cam("a"), cam("b"), null]);
  assert.deepEqual(swap(d, 0, 2).tiles, [cam("b"), null, cam("a"), null]);
  assert.equal(swap(d, 1, 1), d);
});

test("refKey ve sameContent: ad sayılmaz, düzen ve kutular sayılır", () => {
  assert.equal(refKey(cam("a")), "a|");
  assert.equal(refKey(cam("a", "2")), "a|2");
  assert.ok(sameContent(draft([cam("a")]), { ...draft([cam("a")]), name: "Başka" }));
  assert.ok(sameContent(draft([{ sourceId: "a" }]), draft([cam("a")])));                     // channelId yok = null
  assert.ok(!sameContent(draft([cam("a")]), draft([cam("a")], "1")));
  assert.ok(!sameContent(draft([cam("a")]), draft([null])));
});

test("geçmiş: geri al / yinele sırası; yeni değişiklik ileriyi siler", () => {
  const d0 = draft([null]);
  const d1 = draft([cam("a")]);
  const d2 = draft([cam("b")]);
  let h = initHistory(d0);
  assert.ok(!canUndo(h) && !canRedo(h));
  h = push(h, d1);
  h = push(h, d2);
  assert.equal(h.present, d2);
  h = undo(h);
  assert.equal(h.present, d1);
  assert.ok(canRedo(h));
  h = undo(h);
  assert.equal(h.present, d0);
  assert.ok(!canUndo(h));
  assert.equal(undo(h), h);                                // başta geri al: değişmez
  h = redo(h);
  assert.equal(h.present, d1);
  h = redo(h);
  assert.equal(h.present, d2);
  assert.equal(redo(h), h);                                // sonda yinele: değişmez
  h = undo(h);
  h = push(h, d0);
  assert.ok(!canRedo(h));                                  // yeni değişiklik ileriyi siler
  assert.equal(push(h, { ...d0 }), h);                     // aynı içerik: geçmişe yazılmaz
});

test("geçmiş: en çok 50 adım geri alınır", () => {
  assert.equal(HISTORY_LIMIT, 50);
  let h = initHistory(draft([null]));
  for (let i = 1; i <= 60; i++) h = push(h, draft([cam(`c${i}`)]));
  let n = 0;
  while (canUndo(h)) { h = undo(h); n += 1; }
  assert.equal(n, 50);
  assert.deepEqual(h.present.tiles, [cam("c10")]);
});

test("isDirty: kayıtlı hâlden farklıysa; geri alıp kayıtlı hâle dönünce değil; yeni şablon hep", () => {
  const saved = draft([cam("a"), null, null, null]);
  let h = initHistory(saved);
  assert.equal(isDirty(h, saved), false);
  h = push(h, assign(h.present, 1, cam("b")));
  assert.equal(isDirty(h, saved), true);
  h = undo(h);
  assert.equal(isDirty(h, saved), false);
  assert.equal(isDirty(initHistory(newDraft(CATALOG)), null), true);
});

test("validateGrid: 1–16 ve en çok 128 kutu, Türkçe ileti", () => {
  assert.equal(validateGrid(6, 8), null);
  assert.equal(validateGrid(16, 8), null);
  assert.equal(validateGrid(1, 1), null);
  assert.equal(validateGrid(16, 9), "En çok 128 kutu (16×9 = 144).");
  assert.equal(validateGrid(12, 11), "En çok 128 kutu (12×11 = 132).");
  for (const [r, c] of [[0, 5], [17, 2], [5, 0], [2.5, 3], [Number.NaN, 2]]) {
    assert.equal(validateGrid(r, c), "Satır ve sütun 1–16 arasında olmalı.", `${r}×${c}`);
  }
});

test("neighbor: ok tuşlarıyla geometrik komşu kutu; kenarda yerinde kalır", () => {
  const four = CATALOG.find((l) => l.id === "4");
  assert.equal(neighbor(four, 0, "right"), 1);
  assert.equal(neighbor(four, 0, "down"), 2);
  assert.equal(neighbor(four, 3, "left"), 2);
  assert.equal(neighbor(four, 3, "up"), 1);
  assert.equal(neighbor(four, 0, "left"), 0);
  assert.equal(neighbor(four, 1, "up"), 1);
  // 1 büyük + 2: büyük kutudan sağa üstteki küçük, alttakinden sola büyük kutu
  const three = CATALOG.find((l) => l.id === "3");
  assert.equal(neighbor(three, 0, "right"), 1);
  assert.equal(neighbor(three, 2, "left"), 0);
  assert.equal(neighbor(three, 1, "down"), 2);
  assert.equal(neighbor(three, 2, "down"), 2);
});

test("parseUnsaved: geçerli kaydı okur; bozuk ya da geçersiz içerik yok sayılır", () => {
  const ok = { v: 1, origin: "v1", name: "Giriş katı", layout: "6x8", tiles: [cam("a"), null, cam("b", "2")], updatedAt: 5 };
  assert.deepEqual(parseUnsaved(JSON.stringify(ok)), ok);
  assert.deepEqual(parseUnsaved(JSON.stringify({ ...ok, layout: "4", updatedAt: null, tiles: [{ sourceId: "a" }] })),
    { ...ok, layout: "4", updatedAt: null, tiles: [cam("a")] });                       // channelId yoksa null
  for (const bad of [
    "", "{", "null", "[]", "5",
    JSON.stringify({ ...ok, v: 2 }),
    JSON.stringify({ ...ok, origin: "" }),
    JSON.stringify({ ...ok, origin: 7 }),
    JSON.stringify({ ...ok, name: 3 }),
    JSON.stringify({ ...ok, layout: "16x9" }),                                         // 144 kutu
    JSON.stringify({ ...ok, layout: "0x4" }),
    JSON.stringify({ ...ok, layout: "abc" }),
    JSON.stringify({ ...ok, layout: "123456" }),
    JSON.stringify({ ...ok, tiles: "x" }),
    JSON.stringify({ ...ok, tiles: Array.from({ length: 129 }, () => null) }),
    JSON.stringify({ ...ok, tiles: [{ sourceId: 5 }] }),
    JSON.stringify({ ...ok, tiles: [{ sourceId: "" }] }),
    JSON.stringify({ ...ok, tiles: [{ sourceId: "a", channelId: 2 }] }),
    JSON.stringify({ ...ok, tiles: ["a"] }),
    JSON.stringify({ ...ok, updatedAt: "dün" }),
  ]) assert.equal(parseUnsaved(bad), null, bad);
  assert.equal(parseUnsaved(null), null);
});
