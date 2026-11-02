import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";
import { ANALYZER_REFUSALS, bearerHeader, problemFrom, refusalFor, refusalText } from "./analyzerRefusal.mjs";

const KEY_TEXT = "Analiz sunucusu erişim anahtarı uyuşmuyor — panelde ve analiz sunucusunda aynı ANALYZER_TOKEN ayarlanmalı.";
const HOST_TEXT = "Analiz sunucusu panelin bağlandığı adresi reddetti — erişim anahtarı yokken ANALYZER_URL 127.0.0.1 ya da localhost olmalı.";

test("ANALYZER_REFUSALS: kodlar ve metinler kuraldaki gibi", () => {
  assert.deepEqual(ANALYZER_REFUSALS, { analyzer_key: KEY_TEXT, analyzer_host: HOST_TEXT });
});

test("refusalFor: 401 anahtar, 403 adres; başka her durum null", () => {
  assert.deepEqual(refusalFor(401), { code: "analyzer_key", detail: KEY_TEXT });
  assert.deepEqual(refusalFor(403), { code: "analyzer_host", detail: HOST_TEXT });
  for (const status of [200, 204, 400, 404, 500, 502, 503]) assert.equal(refusalFor(status), null, String(status));
});

test("problemFrom: 'auth' yalnızca panelin kendi 401'i (reddetme kodu yok); kod durumdan önce gelir", () => {
  assert.equal(problemFrom(401, null), "auth");
  assert.equal(problemFrom(401, undefined), "auth");
  assert.equal(problemFrom(401, "bilinmeyen"), "auth");          // reddetme kodu değil: panelin 401'i (yeniden giriş işe yarar)
  assert.equal(problemFrom(502, "analyzer_key"), "key");
  assert.equal(problemFrom(502, "analyzer_host"), "host");
  assert.equal(problemFrom(401, "analyzer_key"), "key");
  assert.equal(problemFrom(401, "analyzer_host"), "host");
  assert.equal(problemFrom(502, null), "down");
  assert.equal(problemFrom(503, null), "down");
  assert.equal(problemFrom(502, "bilinmeyen"), "down");
  assert.equal(problemFrom(500, "toString"), "down");            // nesne özelliği kod sayılmaz
});

test("refusalText: 'key' ve 'host' metni; öteki sorunlarda null", () => {
  assert.equal(refusalText("key"), KEY_TEXT);
  assert.equal(refusalText("host"), HOST_TEXT);
  assert.equal(refusalText("auth"), null);
  assert.equal(refusalText("down"), null);
});

/** Değerin kod birimleri: her biri tek bayt olmalı (ByteString) */
const bytesOf = (s) => Array.from(s, (c) => c.charCodeAt(0));

test("bearerHeader: ASCII anahtar değişmez", () => {
  assert.equal(bearerHeader("e2e-dogru-anahtar"), "Bearer e2e-dogru-anahtar");
});

test("bearerHeader: Türkçe karakterli anahtar UTF-8 baytlarıyla (ByteString)", () => {
  const value = bearerHeader("gizlişifre");
  assert.deepEqual(bytesOf(value), [...Buffer.from("Bearer gizlişifre", "utf8")]);
  assert.ok(bytesOf(value).every((b) => b <= 255));
  assert.doesNotThrow(() => new Headers().set("Authorization", value));
  // Karşılaştırma: dizgenin kendisi başlığa konamaz (ş = U+015F > 255)
  assert.throws(() => new Headers().set("Authorization", "Bearer gizlişifre"), TypeError);
});

test("bearerHeader: çevresindeki boşluk atılır, içindeki kalır; geriye bir şey kalmazsa null (Authorization gönderilmez)", () => {
  assert.equal(bearerHeader("abc "), "Bearer abc");
  assert.equal(bearerHeader("\t abc\r\n"), "Bearer abc");
  assert.equal(bearerHeader(" a b "), "Bearer a b");
  assert.equal(bearerHeader(" gizlişifre "), bearerHeader("gizlişifre"));
  for (const empty of ["", " ", " \t\r\n ", " 　", undefined, null]) assert.equal(bearerHeader(empty), null, JSON.stringify(empty));
});

test("bearerHeader: fetch anahtarın UTF-8 baytlarını olduğu gibi gönderir (analiz sunucusu bu baytlarla karşılaştırır)", async (t) => {
  let raw = "";
  const server = createServer((req, res) => {
    raw = req.rawHeaders[req.rawHeaders.findIndex((n) => n.toLowerCase() === "authorization") + 1];
    res.end();
  });
  t.after(() => server.close());
  await new Promise((done) => server.listen(0, "127.0.0.1", done));
  const res = await fetch(`http://127.0.0.1:${server.address().port}/`, { headers: { Authorization: bearerHeader("gizlişifre") } });
  await res.arrayBuffer();
  assert.deepEqual([...Buffer.from(raw, "latin1")], [...Buffer.from("Bearer gizlişifre", "utf8")]);
});
