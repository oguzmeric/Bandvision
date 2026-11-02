import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { CROSS_SITE_REFUSED, crossSiteRefused, hostName, isApiPath, isLoopbackHost, isLoopbackOrigin } from "./hostCheck.mjs";

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

// Analiz sunucusuyla ORTAK tablo (services/edge/tests/test_crosssite.py aynı dosyayı okur): aynı girdi → aynı sonuç.
const SHARED = JSON.parse(readFileSync(new URL("../../../../contracts/loopback-origins.json", import.meta.url), "utf8"));

test("isLoopbackOrigin: analiz sunucusunun is_loopback_origin tablosuyla aynı (ortak dosya)", () => {
  assert.ok(SHARED.loopbackOrigins.length >= 70);
  for (const { origin, loopback } of SHARED.loopbackOrigins) assert.equal(isLoopbackOrigin(origin), loopback, JSON.stringify(origin));
});

test("crossSiteRefused: Sec-Fetch-Site ortak tablosu (virgüllü tek satır dahil), analiz sunucusuyla aynı sonuç", () => {
  assert.ok(SHARED.secFetchSite.length >= 20);
  for (const { lines, refused } of SHARED.secFetchSite) {
    // Headers.get birden çok satırı ", " ile birleştirir; satır yoksa null
    const value = lines.length === 0 ? null : lines.join(", ");
    assert.equal(crossSiteRefused(null, value), refused, JSON.stringify(lines));
  }
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

test("isApiPath: /api/ ve Next'in /_next/data/ veri yolları API kapısından geçer; sayfalar ve Next iç dosyaları geçmez", () => {
  for (const p of ["/api/jobs", "/api/live/views", "/api/jobs/abc", "/_next/data/BUILD/api/live/views.json",
    "/_next/data/development/api/jobs/abc.json", "/_next/data/BUILD/watch.json", "/_next/data/x"]) {
    assert.equal(isApiPath(p), true, p);
  }
  for (const p of ["/", "/watch", "/api", "/apix/y", "/login", "/_next/static/chunks/a.js", "/_next/data", "/_next/datax/y",
    "/_next/image", "/brand/logo.png", "/x/api/jobs", "//api/jobs", "", undefined, null]) {
    assert.equal(isApiPath(p), false, String(p));
  }
});
