import assert from "node:assert/strict";
import test from "node:test";
import { CROSS_SITE_REFUSED, crossSiteRefused, hostName, isLoopbackHost, isLoopbackOrigin } from "./hostCheck.mjs";

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

// Analiz sunucusunun tablosu (services/edge/tests/test_crosssite.py LOOPBACK_ORIGINS): aynı girdi → aynı sonuç.
const LOOPBACK_ORIGINS = [
  // http ya da https, kabul edilen ad, port olsun olmasın
  ["http://localhost", true],
  ["https://localhost", true],
  ["http://localhost:3000", true],
  ["https://localhost:8443", true],
  ["http://127.0.0.1", true],
  ["https://127.0.0.1", true],
  ["http://127.0.0.1:3000", true],
  ["http://[::1]", true],
  ["https://[::1]", true],
  ["http://[::1]:3000", true],
  ["http://localhost:65535", true],
  ["http://localhost:99999", true],   // Host kuralı gibi: 5 haneye kadar her port
  ["HTTP://LOCALHOST:3000", true],   // büyük/küçük harf fark etmez
  ["HttpS://LocalHost", true],
  // yok, boş, `null`
  [null, false],
  [42, false],
  ["", false],
  ["null", false],
  ["NULL", false],
  // başka şema
  ["file://", false],
  ["file:///C:/sayfa.html", false],
  ["chrome-extension://abc", false],
  ["ftp://localhost", false],
  ["ws://localhost:3000", false],
  ["wss://localhost", false],
  // şema biçimi bozuk ya da yok
  ["localhost", false],
  ["localhost:3000", false],
  ["127.0.0.1:3000", false],
  ["//localhost", false],
  ["http:/localhost", false],
  ["http//localhost", false],
  ["http:localhost", false],
  ["http://", false],
  ["https://", false],
  // yol, sorgu, parça
  ["http://localhost/", false],
  ["http://localhost/x", false],
  ["http://localhost:3000/", false],
  ["http://localhost?x=1", false],
  ["http://localhost#x", false],
  // bozuk port
  ["http://localhost:", false],
  ["http://localhost:abc", false],
  ["http://localhost:123456", false],
  ["http://localhost:3000:1", false],
  ["http://localhost:+80", false],
  // başka ad, benzer görünenler dahil
  ["https://evil.example", false],
  ["http://evil.example", false],
  ["https://localhost.evil.example", false],
  ["http://127.0.0.1.evil.example", false],
  ["http://localhost.", false],
  ["http://127.0.0.2", false],
  ["http://0.0.0.0", false],
  ["http://evil.example#localhost", false],
  ["http://evil.example/localhost", false],
  // kullanıcı bilgisi
  ["http://user@localhost", false],
  ["http://user:sifre@localhost:3000", false],
  ["http://localhost@evil.example", false],
  // IPv6 biçimleri: yalnızca köşeli parantezli kısa yazım
  ["http://::1", false],
  ["http://[::1", false],
  ["http://::1]", false],
  ["http://[::2]", false],
  ["http://[0:0:0:0:0:0:0:1]", false],
  ["http://[localhost]", false],   // Host ayrıştırıcısının kabul ettiği biçim Origin'de bozuktur
  ["http://[127.0.0.1]:3000", false],
  // boşluk ve satır sonu: kırpılmaz
  [" http://localhost", false],
  ["http://localhost ", false],
  ["http://localhost\n", false],
  ["http:// localhost", false],
  ["http://local host", false],
  // ASCII dışı: büyük/küçük harf eşlemesiyle ASCII'ye benzeyen harf kabul edilmez
  ["http://localhoſt", false],
  ["httpſ://localhost", false],
];

test("isLoopbackOrigin: analiz sunucusunun is_loopback_origin tablosuyla aynı", () => {
  for (const [origin, want] of LOOPBACK_ORIGINS) assert.equal(isLoopbackOrigin(origin), want, JSON.stringify(origin));
});

test("crossSiteRefused: Origin varsa karar onundur; geri döngü kaynağı geçer, başka her değer reddedilir", () => {
  for (const origin of ["http://127.0.0.1:3000", "http://localhost:3000", "http://[::1]:3000"]) {
    assert.equal(crossSiteRefused(origin, null), false, origin);
    assert.equal(crossSiteRefused(origin, "cross-site"), false, `${origin} + cross-site`);
  }
  for (const origin of ["https://evil.example", "null", "NULL", "", "file://", "http://localhost/",
    "http://localhost:3000, https://evil.example"]) {     // iki Origin satırı Headers.get ile virgülle birleşir: reddedilir
    assert.equal(crossSiteRefused(origin, null), true, JSON.stringify(origin));
    assert.equal(crossSiteRefused(origin, "same-origin"), true, `${JSON.stringify(origin)} + same-origin`);
  }
});

test("crossSiteRefused: Origin yoksa yalnızca Sec-Fetch-Site: cross-site reddedilir", () => {
  for (const site of ["cross-site", "CROSS-SITE", " cross-site ", "same-origin, cross-site", "cross-site, cross-site"]) {
    assert.equal(crossSiteRefused(null, site), true, site);
    assert.equal(crossSiteRefused(undefined, site), true, site);
  }
  for (const site of [null, undefined, "", "same-origin", "same-site", "none", "cross-site-x"]) {
    assert.equal(crossSiteRefused(null, site), false, String(site));
  }
});

test("CROSS_SITE_REFUSED: panelin ret metni", () => {
  assert.equal(CROSS_SITE_REFUSED, "Bu istek başka bir siteden geldiği için kabul edilmedi.");
});
