import assert from "node:assert/strict";
import test from "node:test";
import { LIVE_REQUEST_HEADERS, LIVE_RESPONSE_HEADERS } from "./liveProxy.mjs";

test("canlı vekil: küçük resmin x-sub-dead başlığı tarayıcıya geçer", () => {
  assert.ok(LIVE_RESPONSE_HEADERS.includes("x-sub-dead"));
});

test("canlı vekil: video sarma başlıkları iki yönde de, erişim anahtarı ve çerez hiç geçmez", () => {
  for (const h of ["range", "if-range"]) assert.ok(LIVE_REQUEST_HEADERS.includes(h), h);
  for (const h of ["content-range", "accept-ranges", "content-type"]) assert.ok(LIVE_RESPONSE_HEADERS.includes(h), h);
  for (const h of ["authorization", "cookie", "set-cookie", "x-analyzer-key"]) {
    assert.ok(!LIVE_REQUEST_HEADERS.includes(h) && !LIVE_RESPONSE_HEADERS.includes(h), h);
  }
  for (const h of [...LIVE_REQUEST_HEADERS, ...LIVE_RESPONSE_HEADERS]) assert.equal(h, h.toLowerCase(), h);
  assert.ok(Object.isFrozen(LIVE_RESPONSE_HEADERS) && Object.isFrozen(LIVE_REQUEST_HEADERS));
});
