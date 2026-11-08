import assert from "node:assert/strict";
import test from "node:test";
import { archiveKeysBlocked, archiveShortcut } from "./archiveKeys.mjs";

const key = (k, extra = {}) => ({ key: k, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, repeat: false, ...extra });
const FREE = { blocked: false, control: false };

test("←/→: 10 sn geri/ileri; Shift ile 1 dk", () => {
  assert.deepEqual(archiveShortcut(key("ArrowLeft"), FREE), { type: "step", seconds: -10 });
  assert.deepEqual(archiveShortcut(key("ArrowRight"), FREE), { type: "step", seconds: 10 });
  assert.deepEqual(archiveShortcut(key("ArrowLeft", { shiftKey: true }), FREE), { type: "step", seconds: -60 });
  assert.deepEqual(archiveShortcut(key("ArrowRight", { shiftKey: true }), FREE), { type: "step", seconds: 60 });
});

test("ok tuşu basılı tutulunca yinelenir (sarma sürer); düğme odaktayken de çalışır", () => {
  assert.deepEqual(archiveShortcut(key("ArrowRight", { repeat: true }), FREE), { type: "step", seconds: 10 });
  assert.deepEqual(archiveShortcut(key("ArrowLeft"), { ...FREE, control: true }), { type: "step", seconds: -10 });
});

test("Boşluk: duraklat/sürdür; basılı tutulunca yalnız yutulur; düğme odaktayken düğmenin", () => {
  assert.deepEqual(archiveShortcut(key(" "), FREE), { type: "toggle" });
  assert.deepEqual(archiveShortcut(key(" ", { repeat: true }), FREE), { type: "swallow" });
  assert.equal(archiveShortcut(key(" "), { ...FREE, control: true }), null);
});

test("?: kısayol listesi (Shift ile basılır); basılı tutulunca yinelenmez", () => {
  assert.deepEqual(archiveShortcut(key("?", { shiftKey: true }), FREE), { type: "help" });
  assert.equal(archiveShortcut(key("?", { shiftKey: true, repeat: true }), FREE), null);
});

test("Ctrl/Alt/Cmd ile basılan tuşlar ve bilinmeyen tuşlar tarayıcınındır", () => {
  for (const mod of ["ctrlKey", "metaKey", "altKey"]) {
    assert.equal(archiveShortcut(key("ArrowLeft", { [mod]: true }), FREE), null, mod);
    assert.equal(archiveShortcut(key(" ", { [mod]: true }), FREE), null, mod);
  }
  assert.equal(archiveShortcut(key("a"), FREE), null);
  assert.equal(archiveShortcut(key("Enter"), FREE), null);
});

test("bekçi: yazı kutusu, seçim kutusu (hız) ya da açık pencerede hiçbir kısayol çalışmaz", () => {
  const blocked = { blocked: true, control: false };
  for (const k of ["ArrowLeft", "ArrowRight", " ", "?"]) assert.equal(archiveShortcut(key(k), blocked), null, k);

  const el = (match) => ({ isContentEditable: false, closest: (sel) => (match && sel.includes(match) ? {} : null) });
  const doc = (open) => ({ querySelector: () => (open ? {} : null) });
  assert.equal(archiveKeysBlocked(el("input"), doc(false)), true);
  assert.equal(archiveKeysBlocked(el("select"), doc(false)), true);
  assert.equal(archiveKeysBlocked(el(null), doc(true)), true);
  assert.equal(archiveKeysBlocked(el(null), doc(false)), false);
  assert.equal(archiveKeysBlocked(null, doc(false)), false);
});
