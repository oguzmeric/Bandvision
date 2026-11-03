import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";
import v8 from "node:v8";
import vm from "node:vm";
import { STREAM_BODY_INIT } from "./streamUpload.mjs";

const MB = 1024 * 1024;

/** Sahte analiz sunucusu: gövdeyi okuyup atar, sonunda `status` döner */
async function upstream(t, status) {
  let received = 0;
  const server = createServer((req, res) => {
    req.on("data", (c) => { received += c.length; });
    req.on("end", () => { res.statusCode = status; res.end("{}"); });
  });
  t.after(() => server.close());
  await new Promise((done) => server.listen(0, "127.0.0.1", done));
  return { url: `http://127.0.0.1:${server.address().port}/`, received: () => received };
}

/** Çöp toplanmış olarak süreçteki ArrayBuffer MB'ı */
function arrayBuffersMb() {
  v8.setFlagsFromString("--expose-gc");
  vm.runInNewContext("gc")();
  return process.memoryUsage().arrayBuffers / MB;
}

/** `total` MB'lık akan gövde; bitmeden hemen önce bellekte kaç ArrayBuffer MB olduğunu bildirir */
function measuredBody(total, onLast) {
  let sent = 0;
  return new ReadableStream({
    pull(controller) {
      if (sent === total) {
        onLast(arrayBuffersMb());
        controller.close();
        return;
      }
      sent += 1;
      controller.enqueue(new Uint8Array(MB));
    },
  }, { highWaterMark: 0 });
}

test("STREAM_BODY_INIT: akan gövde bellekte birikmez (fetch `tee` ile kopyalamaz)", async (t) => {
  const { url, received } = await upstream(t, 202);
  const total = 256;
  // Mutlak değer ortama göre oynar: başlangıca göre artış ölçülür. Yoldaki tamponlar (sahte sunucu aynı süreçte) birkaç on MB
  // tutabilir; hata (tee) ise gövdenin tamamını tutar: eşik ikisini ayırır.
  const before = arrayBuffersMb();
  let held = Infinity;
  const body = measuredBody(total, (mb) => { held = mb - before; });
  const res = await fetch(url, { method: "POST", body, ...STREAM_BODY_INIT });
  await res.arrayBuffer();
  assert.equal(res.status, 202);
  assert.equal(received(), total * MB);
  assert.ok(held < total / 2, `gövde bitmeden bellekte ${held.toFixed(0)} MB birikti`);
});

test("STREAM_BODY_INIT: akan gövdeye 401 ağ hatası olmaz, yanıt olarak döner", async (t) => {
  const { url } = await upstream(t, 401);
  const body = new ReadableStream({ start(c) { c.enqueue(new Uint8Array(16)); c.close(); } });
  const res = await fetch(url, { method: "POST", body, ...STREAM_BODY_INIT });
  await res.arrayBuffer();
  assert.equal(res.status, 401);
});
