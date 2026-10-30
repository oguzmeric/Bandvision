import assert from "node:assert/strict";
import test from "node:test";
import { classify, parseStatus } from "./systemStatus.mjs";

test("classify: 200 up; 401/403 auth; 5xx, diğer hatalar ve ağ hatası down", () => {
  assert.equal(classify({ ok: true, status: 200 }), "up");
  assert.equal(classify({ ok: false, status: 401 }), "auth");
  assert.equal(classify({ ok: false, status: 403 }), "auth");
  assert.equal(classify({ ok: false, status: 500 }), "down");
  assert.equal(classify({ ok: false, status: 404 }), "down");
  assert.equal(classify({ error: new Error("ECONNREFUSED") }), "down");
});

test("parseStatus: işlemci yükü bilinmiyorsa (psutil'siz eski kurulum) null kabul edilir", () => {
  const body = { cpuPercent: null, uptimeS: 90, version: "0.1.0", commit: "abc1234" };
  assert.deepEqual(parseStatus(body), body);
});

test("parseStatus: geçerli gövde; türü bozuk ya da eksik gövde null", () => {
  const ok = { cpuPercent: 12.5, uptimeS: 90, version: "0.1.0", commit: "abc1234" };
  assert.deepEqual(parseStatus({ ...ok, fazla: 1 }), ok);
  for (const bad of [null, undefined, "x", 5, {}, { ...ok, cpuPercent: "1" }, { ...ok, uptimeS: null },
    { ...ok, version: 1 }, { ...ok, commit: undefined }, { ...ok, cpuPercent: NaN }]) {
    assert.equal(parseStatus(bad), null, JSON.stringify(bad));
  }
});
