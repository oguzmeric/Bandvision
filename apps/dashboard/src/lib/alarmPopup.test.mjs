import test from "node:test";
import assert from "node:assert/strict";
import { alarmSeverity, sortAlarms, liveStreamUrl, insetCrop, insetSide, agoText } from "./alarmPopup.mjs";

test("alarmSeverity: telefon uyarı, diğerleri kritik", () => {
  assert.equal(alarmSeverity("phone"), "warning");
  for (const t of ["fire", "smoke", "hands_up", "lying", "test"]) assert.equal(alarmSeverity(t), "critical");
});

test("sortAlarms: kritikler önce, yeni üstte, girdi değişmez", () => {
  const input = [
    { type: "phone", firedAt: 300 }, { type: "fire", firedAt: 100 },
    { type: "lying", firedAt: 200 }, { type: "phone", firedAt: 400 },
  ];
  const copy = input.map((x) => ({ ...x }));
  const out = sortAlarms(input);
  assert.deepEqual(out.map((a) => `${a.type}@${a.firedAt}`), ["lying@200", "fire@100", "phone@400", "phone@300"]);
  assert.deepEqual(input, copy);
  assert.notEqual(out, input);
});

test("sortAlarms: eşitlikte giriş sırası korunur", () => {
  const a = { type: "fire", firedAt: 5, n: 1 }, b = { type: "lying", firedAt: 5, n: 2 };
  assert.deepEqual(sortAlarms([a, b]).map((x) => x.n), [1, 2]);
});

test("liveStreamUrl", () => {
  const a = { sessionId: "s1", sourceId: "r1", channelId: "c2" };
  assert.equal(liveStreamUrl(a, new Set(["s1"])), "/api/live/sessions/s1/stream");
  assert.equal(liveStreamUrl(a, new Set()), "/api/live/cameras/stream?source=r1&channel=c2&quality=sub");
  assert.equal(liveStreamUrl({ sessionId: "s1", sourceId: "r1" }, new Set()), "/api/live/cameras/stream?source=r1&quality=sub");
  assert.equal(liveStreamUrl({ sessionId: "s1" }, new Set()), null);
  assert.equal(liveStreamUrl({ sessionId: null, sourceId: null }, new Set()), null);
  assert.equal(liveStreamUrl({ sessionId: "a/b" }, new Set(["a/b"])), "/api/live/sessions/a%2Fb/stream");
});

test("insetCrop", () => {
  assert.deepEqual(insetCrop([0.4, 0.4, 0.6, 0.6]), { scale: 3.125, left: -106.25, top: -106.25 });
  assert.deepEqual(insetCrop([0.9, 0.1, 1.0, 0.2]), { scale: 4, left: -300, top: -10 });
  assert.deepEqual(insetCrop([0, 0, 1, 1]), { scale: 1, left: 0, top: 0 });
  for (const bad of [null, [0.5, 0.5, 0.4, 0.6], [0, 0, 1], ["a", 0, 1, 1], undefined, "x"]) assert.equal(insetCrop(bad), null);
  assert.ok(!Object.is(insetCrop([0, 0, 1, 1]).left, -0));
});

test("insetSide", () => {
  assert.equal(insetSide([0.6, 0, 0.9, 0.5]), "left");
  assert.equal(insetSide([0.1, 0, 0.3, 0.5]), "right");
  assert.equal(insetSide(null), "right");
});

test("agoText", () => {
  assert.equal(agoText(-5), "0 sn önce");
  assert.equal(agoText(38), "38 sn önce");
  assert.equal(agoText(60), "1 dk önce");
  assert.equal(agoText(599), "9 dk önce");
  assert.equal(agoText(7200), "2 sa önce");
});
