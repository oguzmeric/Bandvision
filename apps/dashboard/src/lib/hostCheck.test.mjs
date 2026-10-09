import assert from "node:assert/strict";
import test from "node:test";
import { hostName, isLoopbackHost } from "./hostCheck.mjs";

test("hostName: ana makine adı (küçük harf, port ve IPv6 köşeli parantezi atılır); bozuk başlık null", () => {
  assert.equal(hostName("LOCALHOST:3000"), "localhost");
  assert.equal(hostName(" 127.0.0.1 "), "127.0.0.1");
  assert.equal(hostName("[::1]:3000"), "::1");
  assert.equal(hostName("ofis.example.com"), "ofis.example.com");
  for (const bad of ["", ":3000", "[::1", "[::1]x", "::1", "127.0.0.1:abc", "127.0.0.1:3000:1", "127.0.0.1:123456", undefined, null, 42]) {
    assert.equal(hostName(bad), null, String(bad));
  }
});

test("isLoopbackHost: şifresiz (yalnızca bu bilgisayar) kipte yalnızca geri döngü adları (DNS yeniden bağlama savunması)", () => {
  for (const h of ["127.0.0.1", "127.0.0.1:3000", "localhost", "localhost:3000", "LocalHost:3000", "[::1]", "[::1]:3000"]) {
    assert.equal(isLoopbackHost(h), true, h);
  }
  for (const h of ["evil.example.com", "evil.example.com:3000", "localhost.evil.com:3000", "127.0.0.1.nip.io:3000",
    "127.0.0.2:3000", "0.0.0.0:3000", "192.168.1.20:3000", "10.0.0.5", "[::2]:3000", "::1", "attacker@127.0.0.1",
    "127.0.0.1/", "", undefined, null]) {
    assert.equal(isLoopbackHost(h), false, String(h));
  }
});
