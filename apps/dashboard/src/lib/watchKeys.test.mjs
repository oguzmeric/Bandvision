import assert from "node:assert/strict";
import test from "node:test";
import { moveTab, shortcutFor, shortcutsBlocked } from "./watchKeys.mjs";

const key = (k, extra = {}) => ({ key: k, ctrlKey: false, metaKey: false, altKey: false, repeat: false, ...extra });
const GRID = { blocked: false, single: false, touring: false, control: false };
const SINGLE = { ...GRID, single: true };
const TOUR = { ...SINGLE, touring: true };

test("F: ızgarada büyüt, tek kamerada ızgaraya dön (aynı iş); büyük F de", () => {
  assert.deepEqual(shortcutFor(key("f"), GRID), { type: "toggle-single" });
  assert.deepEqual(shortcutFor(key("F"), SINGLE), { type: "toggle-single" });
  assert.deepEqual(shortcutFor(key("f"), TOUR), { type: "toggle-single" });
});

test("Esc: yalnız tek kamerada (ve sıralı gösterimde); ızgarada yok", () => {
  assert.deepEqual(shortcutFor(key("Escape"), SINGLE), { type: "escape" });
  assert.deepEqual(shortcutFor(key("Escape"), TOUR), { type: "escape" });
  assert.equal(shortcutFor(key("Escape"), GRID), null);
});

test("Boşluk: sıralı gösterimde duraklat/sürdür; yoksa yutulur (sayfa kaymaz); düğme odaktayken düğmenin", () => {
  assert.deepEqual(shortcutFor(key(" "), TOUR), { type: "pause" });
  assert.deepEqual(shortcutFor(key(" "), GRID), { type: "swallow" });
  assert.deepEqual(shortcutFor(key(" "), SINGLE), { type: "swallow" });
  assert.equal(shortcutFor(key(" "), { ...TOUR, control: true }), null);
  assert.equal(shortcutFor(key(" ", { repeat: true }), TOUR), null);
});

test("←/→: tek kamerada önceki/sonraki; ızgarada yok (kutular kendi gezinir)", () => {
  assert.deepEqual(shortcutFor(key("ArrowRight"), SINGLE), { type: "step", dir: 1 });
  assert.deepEqual(shortcutFor(key("ArrowLeft"), TOUR), { type: "step", dir: -1 });
  assert.equal(shortcutFor(key("ArrowRight"), GRID), null);
  assert.equal(shortcutFor(key("ArrowUp"), SINGLE), null);
});

test("1–9: n. sekme; 0 yok", () => {
  assert.deepEqual(shortcutFor(key("1"), GRID), { type: "tab", index: 0 });
  assert.deepEqual(shortcutFor(key("9"), SINGLE), { type: "tab", index: 8 });
  assert.equal(shortcutFor(key("0"), GRID), null);
});

test("?: yardım", () => {
  assert.deepEqual(shortcutFor(key("?", { shiftKey: true }), GRID), { type: "help" });
});

test("bekçi: yazı kutusu, açık pencere/menü ya da Ctrl/Alt/Cmd ile hiçbir kısayol çalışmaz", () => {
  for (const k of ["f", "Escape", " ", "ArrowRight", "1", "?"]) {
    assert.equal(shortcutFor(key(k), { ...TOUR, blocked: true }), null, k);
    assert.equal(shortcutFor(key(k, { ctrlKey: true }), TOUR), null, k);
    assert.equal(shortcutFor(key(k, { metaKey: true }), TOUR), null, k);
    assert.equal(shortcutFor(key(k, { altKey: true }), TOUR), null, k);
  }
  assert.equal(shortcutFor(key("f", { repeat: true }), GRID), null);             // basılı tutmak art arda açıp kapatmaz
  assert.deepEqual(shortcutFor(key("ArrowRight", { repeat: true }), SINGLE), { type: "step", dir: 1 });
  assert.equal(shortcutFor(key("x"), GRID), null);
});

/** Sahte DOM öğesi: `closest` verilen seçicilerden biri eşleşirse kendini döndürür */
const el = (matches = [], isContentEditable = false) => ({
  isContentEditable,
  closest: (sel) => (sel.split(",").map((s) => s.trim()).some((s) => matches.includes(s)) ? {} : null),
});
const doc = (open) => ({ querySelector: (sel) => (open && sel.includes(open) ? {} : null) });

test("shortcutsBlocked: input/select/textarea/contenteditable içinde ya da açık pencere/menü varken", () => {
  assert.equal(shortcutsBlocked(el(), doc(null)), false);
  assert.equal(shortcutsBlocked(null, doc(null)), false);
  for (const tag of ["input", "select", "textarea", "[contenteditable]"]) assert.equal(shortcutsBlocked(el([tag]), doc(null)), true, tag);
  assert.equal(shortcutsBlocked(el([], true), doc(null)), true);
  for (const sel of ["dialog[open]", "[role=dialog]", "[role=menu]"]) assert.equal(shortcutsBlocked(el(), doc(sel)), true, sel);
});

test("moveTab: sürüklenen sekme bırakıldığı yere geçer; diğerleri sırasını korur", () => {
  assert.deepEqual(moveTab(["a", "b", "c", "d"], "d", "a"), ["d", "a", "b", "c"]);
  assert.deepEqual(moveTab(["a", "b", "c", "d"], "a", "c"), ["b", "c", "a", "d"]);
  assert.deepEqual(moveTab(["a", "b", "c"], "b", "c"), ["a", "c", "b"]);
  assert.deepEqual(moveTab(["a", "b", "c"], "b", "a"), ["b", "a", "c"]);
});

test("moveTab: aynı yere ya da bilinmeyen kimlikle değişmez (aynı dizi)", () => {
  const ids = ["a", "b", "c"];
  assert.equal(moveTab(ids, "b", "b"), ids);
  assert.equal(moveTab(ids, "x", "a"), ids);
  assert.equal(moveTab(ids, "a", "x"), ids);
});

test("moveTab ile Sola/Sağa taşı: komşunun yerine; uçlarda değişmez", () => {
  const ids = ["a", "b", "c"];
  assert.deepEqual(moveTab(ids, "b", ids[0]), ["b", "a", "c"]);
  assert.deepEqual(moveTab(ids, "b", ids[2]), ["a", "c", "b"]);
});
