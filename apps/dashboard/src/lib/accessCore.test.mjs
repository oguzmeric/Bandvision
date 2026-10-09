import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  BUILD_MARKER, LAUNCHER_DIST, LOCK_FRESH_MS, LOCK_STALE_MS, MAX_PASSWORD, MIN_PASSWORD, accessFile, buildIsStale,
  createLoginThrottle, hashPassword, hostAllowed, isJsonContentType, lockDecision, middlewareReady, newSecret,
  panelCommand, panelPlan, panelState, panelStateFile, updateAccess, verifyPassword, verifyPasswordAsync,
} from "./accessCore.mjs";

test("şifre yalnızca özetiyle doğrulanır; düz şifre özette yok", () => {
  const { salt, hash } = hashPassword("ofis-sifre-1");
  assert.ok(verifyPassword("ofis-sifre-1", salt, hash));
  assert.ok(!verifyPassword("ofis-sifre-2", salt, hash));
  assert.ok(!hash.includes("ofis") && hash.length === 64 && salt.length === 32);
  assert.equal(MIN_PASSWORD, 8);
});

test("erişim kapalıyken ya da şifre yokken panel yalnızca bu bilgisayarda", () => {
  assert.deepEqual(panelPlan(null, {}), { host: "127.0.0.1", env: {} });
  assert.equal(panelPlan({ enabled: true }, {}).host, "127.0.0.1");                    // şifresiz yerel ağ ASLA
  const { salt, hash } = hashPassword("ofis-sifre-1");
  assert.equal(panelPlan({ enabled: false, salt, hash, secret: newSecret() }, {}).host, "127.0.0.1");
});

test("erişim açık + şifre: tüm arayüzler ve oturum sırrı ortama", () => {
  const { salt, hash } = hashPassword("ofis-sifre-1");
  const secret = newSecret();
  const p = panelPlan({ enabled: true, salt, hash, secret }, {});
  assert.equal(p.host, "0.0.0.0");
  assert.deepEqual(p.env, { PANEL_PASSWORD_HASH: hash, PANEL_PASSWORD_SALT: salt, PANEL_SESSION_SECRET: secret });
});

test("DASHBOARD_PASSWORD önceliklidir: dosyadaki özet ortama verilmez", () => {
  const { salt, hash } = hashPassword("ofis-sifre-1");
  const p = panelPlan({ enabled: true, salt, hash, secret: newSecret() }, { DASHBOARD_PASSWORD: "ortam-sifresi" });
  assert.equal(p.host, "0.0.0.0");
  assert.deepEqual(p.env, {});
});

test("erişim dosyası yolu: PANEL_ACCESS_FILE önce", () => {
  assert.equal(accessFile({ PANEL_ACCESS_FILE: "/tmp/x.json" }, "/app"), "/tmp/x.json");
  assert.match(accessFile({}, "/app"), /\.local[\\/]access\.json$/);
});

// ---- Güvenlik değişmezleri (görev 7 ek testleri) ----

test("özet: aynı şifre her seferinde farklı tuz/özet verir; sır rastgele ve 64 onaltılık karakter", () => {
  const a = hashPassword("ofis-sifre-1"), b = hashPassword("ofis-sifre-1");
  assert.notEqual(a.salt, b.salt);
  assert.notEqual(a.hash, b.hash);
  assert.ok(verifyPassword("ofis-sifre-1", b.salt, b.hash) && !verifyPassword("ofis-sifre-1", a.salt, b.hash));
  const s1 = newSecret(), s2 = newSecret();
  assert.match(s1, /^[0-9a-f]{64}$/);
  assert.notEqual(s1, s2);
});

test("verifyPassword: eksik/bozuk tuz ya da özet asla geçmez", () => {
  const { salt, hash } = hashPassword("ofis-sifre-1");
  assert.equal(verifyPassword("ofis-sifre-1", undefined, hash), false);
  assert.equal(verifyPassword("ofis-sifre-1", salt, undefined), false);
  assert.equal(verifyPassword("ofis-sifre-1", "", ""), false);
  assert.equal(verifyPassword("ofis-sifre-1", salt, "zz"), false);
  assert.equal(verifyPassword("", salt, hash), false);
  assert.equal(verifyPassword("ofis-sifre-1", salt, hash.slice(0, 62)), false);
});

test("panelPlan: yerel ağ yalnızca erişim açıkken VE şifre varken (tüm durum birleşimleri)", () => {
  const { salt, hash } = hashPassword("ofis-sifre-1");
  const secret = newSecret();
  const accesses = [
    null, {}, { enabled: false }, { enabled: true }, { enabled: "true" }, { enabled: 1 },
    { enabled: true, salt }, { enabled: true, hash }, { enabled: true, secret }, { enabled: true, salt, hash },
    { enabled: true, salt, secret }, { enabled: true, hash, secret }, { enabled: true, salt: "", hash: "", secret: "" },
    { enabled: false, salt, hash, secret }, { enabled: "true", salt, hash, secret },
    { enabled: true, salt, hash, secret },
  ];
  const envs = [{}, { DASHBOARD_PASSWORD: "" }, { DASHBOARD_PASSWORD: undefined }, { DASHBOARD_PASSWORD: "ortam-sifresi" }];
  for (const access of accesses) {
    for (const env of envs) {
      const hasPw = Boolean(env.DASHBOARD_PASSWORD)
        || Boolean(access && access.salt && access.hash && access.secret);
      const want = access && access.enabled === true && hasPw ? "0.0.0.0" : "127.0.0.1";
      assert.equal(panelPlan(access, env).host, want, JSON.stringify({ access, env }));
    }
  }
});

test("panelPlan: yalnızca ortam şifresi + erişim açık yerel ağa açar; kapalıysa açmaz", () => {
  assert.equal(panelPlan({ enabled: true }, { DASHBOARD_PASSWORD: "ortam-sifresi" }).host, "0.0.0.0");
  assert.equal(panelPlan({ enabled: false }, { DASHBOARD_PASSWORD: "ortam-sifresi" }).host, "127.0.0.1");
  assert.equal(panelPlan(null, { DASHBOARD_PASSWORD: "ortam-sifresi" }).host, "127.0.0.1");
});

test("panelPlan: erişim kapalıyken şifre özeti ortama verilmez; düz şifre hiçbir çıktıda yok", () => {
  const { salt, hash } = hashPassword("ofis-sifre-1");
  const off = panelPlan({ enabled: false, salt, hash, secret: newSecret() }, {});
  assert.deepEqual(off.env, {});
  const on = panelPlan({ enabled: true, salt, hash, secret: newSecret() }, {});
  assert.ok(!JSON.stringify(on).includes("ofis-sifre-1"));
  assert.deepEqual(Object.keys(on.env).sort(), ["PANEL_PASSWORD_HASH", "PANEL_PASSWORD_SALT", "PANEL_SESSION_SECRET"]);
});

test("updateAccess: kısa şifre reddedilir, şifresiz açılamaz, düz şifre kayıtta yok", () => {
  assert.equal(updateAccess(null, { enabled: false, password: "kisa" }, false).status, 422);
  assert.match(updateAccess(null, { enabled: false, password: "kisa" }, false).error, /en az 8/);
  assert.equal(updateAccess(null, { enabled: true }, false).status, 422);                 // şifresiz telefondan erişim ASLA
  assert.equal(updateAccess({ enabled: false }, { enabled: true, password: "" }, false).status, 422);
  assert.ok(updateAccess(null, { enabled: true }, true).next.enabled);                    // ortam şifresi varsa açılır
  const r = updateAccess(null, { enabled: true, password: "uzun-sifre-123" }, false);
  assert.equal(r.next.enabled, true);
  assert.ok(!JSON.stringify(r.next).includes("uzun-sifre-123"));
  assert.ok(verifyPassword("uzun-sifre-123", r.next.salt, r.next.hash));
  assert.match(r.next.secret, /^[0-9a-f]{64}$/);
});

test("updateAccess: yalnızca enabled === true açar; şifre değişince oturum sırrı yenilenir, değişmezse korunur", () => {
  for (const bad of ["true", 1, "evet", null, undefined, {}, []]) {
    const r = updateAccess(null, { enabled: bad }, true);
    assert.equal(r.next.enabled, false, String(bad));
  }
  assert.equal(updateAccess(null, null, true).next.enabled, false);
  const a = updateAccess(null, { enabled: true, password: "uzun-sifre-123" }, false).next;
  const kept = updateAccess(a, { enabled: false }, false).next;                            // yalnızca kapatma
  assert.equal(kept.secret, a.secret);
  assert.equal(kept.hash, a.hash);
  const again = updateAccess(kept, { enabled: true }, false).next;                         // şifre hâlâ dosyada: yeniden açılır
  assert.equal(again.enabled, true);
  assert.notEqual(again.secret, a.secret);                                                 // kapalıdan açığa geçişte sır yenilenir
  assert.equal(again.hash, a.hash);
  const stay = updateAccess(again, { enabled: true }, false).next;                         // zaten açıkken Kaydet: sır korunur
  assert.equal(stay.secret, again.secret);
  const changed = updateAccess(a, { enabled: true, password: "baska-sifre-456" }, false).next;
  assert.notEqual(changed.secret, a.secret);                                               // yeni şifre: eski oturumlar düşer
  assert.notEqual(changed.hash, a.hash);
  assert.notEqual(changed.salt, a.salt);
  assert.ok(verifyPassword("baska-sifre-456", changed.salt, changed.hash));
  assert.ok(!verifyPassword("uzun-sifre-123", changed.salt, changed.hash));
});

// ---- Düzeltme turu 1 ----

test("panelCommand: yerel ağda (0.0.0.0) HER ZAMAN next start; yerelde dev, --prod ise start", () => {
  assert.deepEqual(panelCommand({ host: "0.0.0.0" }), { mode: "start", host: "0.0.0.0" });
  assert.deepEqual(panelCommand({ host: "0.0.0.0" }, { prod: false }), { mode: "start", host: "0.0.0.0" });
  assert.deepEqual(panelCommand({ host: "0.0.0.0" }, { prod: true }), { mode: "start", host: "0.0.0.0" });
  assert.deepEqual(panelCommand({ host: "127.0.0.1" }), { mode: "dev", host: "127.0.0.1" });
  assert.deepEqual(panelCommand({ host: "127.0.0.1" }, { prod: false }), { mode: "dev", host: "127.0.0.1" });
  assert.deepEqual(panelCommand({ host: "127.0.0.1" }, { prod: true }), { mode: "start", host: "127.0.0.1" });
  // panelPlan ile birleşimi: hiçbir durumda dev + 0.0.0.0 çıkmaz
  const { salt, hash } = hashPassword("ofis-sifre-1");
  const secret = newSecret();
  for (const access of [null, { enabled: true }, { enabled: true, salt, hash, secret }, { enabled: false, salt, hash, secret }]) {
    for (const env of [{}, { DASHBOARD_PASSWORD: "ortam-sifresi" }]) {
      for (const prod of [false, true]) {
        const plan = panelPlan(access, env);
        const cmd = panelCommand(plan, { prod });
        assert.ok(!(cmd.mode === "dev" && cmd.host === "0.0.0.0"), JSON.stringify({ access, env, prod }));
        assert.equal(cmd.host, plan.host);
      }
    }
  }
});

test("buildIsStale: başarı işareti yok ya da kaynaktan eskiyse true (geçici dosyalarla)", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "bv-stale-"));
  try {
    const at = (rel, sec) => {
      const f = path.join(dir, rel);
      fs.mkdirSync(path.dirname(f), { recursive: true });
      if (!fs.existsSync(f)) fs.writeFileSync(f, "x");
      fs.utimesSync(f, sec, sec);
    };
    const T = 1_700_000_000;
    assert.equal(buildIsStale(dir), true);                                    // derleme yok
    at("src/app/page.tsx", T); at("src/lib/a.ts", T); at("public/logo.png", T);
    at("package.json", T); at("package-lock.json", T); at("next.config.ts", T);
    at(`${LAUNCHER_DIST}/BUILD_ID`, T + 100);
    at(`${LAUNCHER_DIST}/${BUILD_MARKER}`, T + 100);
    for (const d of ["src/app", "src/lib", "src", "public"]) fs.utimesSync(path.join(dir, d), T, T);
    assert.equal(buildIsStale(dir), false);                                   // derleme hepsinden yeni
    for (const rel of ["src/lib/a.ts", "src/app/page.tsx", "public/logo.png", "package.json", "package-lock.json", "next.config.ts"]) {
      at(rel, T + 200);
      assert.equal(buildIsStale(dir), true, `${rel} yeni`);
      at(rel, T);
      assert.equal(buildIsStale(dir), false, `${rel} eski`);
    }
    at("src/deep/nested/yeni.ts", T + 300);                                   // iç içe yeni dosya
    assert.equal(buildIsStale(dir), true);
    at("src/deep/nested/yeni.ts", T);
    for (const d of ["src/deep/nested", "src/deep", "src"]) fs.utimesSync(path.join(dir, d), T, T);
    assert.equal(buildIsStale(dir), false);
    at(`${LAUNCHER_DIST}/${BUILD_MARKER}`, T - 10);                           // işaret kaynaklardan eski
    assert.equal(buildIsStale(dir), true);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("verifyPasswordAsync: eşzamanlı sürümle aynı sonuç; 256 karakterden uzun şifre hiç denenmez", async () => {
  const { salt, hash } = hashPassword("ofis-sifre-1");
  assert.equal(await verifyPasswordAsync("ofis-sifre-1", salt, hash), true);
  assert.equal(await verifyPasswordAsync("ofis-sifre-2", salt, hash), false);
  assert.equal(await verifyPasswordAsync("ofis-sifre-1", undefined, hash), false);
  assert.equal(await verifyPasswordAsync("ofis-sifre-1", salt, "zz"), false);
  assert.equal(MAX_PASSWORD, 256);
  const h2 = hashPassword("a".repeat(MAX_PASSWORD));
  assert.equal(await verifyPasswordAsync("a".repeat(MAX_PASSWORD), h2.salt, h2.hash), true);
  assert.equal(await verifyPasswordAsync("a".repeat(MAX_PASSWORD + 1), h2.salt, h2.hash), false);
  assert.equal(verifyPassword("a".repeat(MAX_PASSWORD + 1), h2.salt, h2.hash), false);
  // olay döngüsü bloklanmaz: scrypt sürerken zamanlayıcı çalışabilir
  let ticks = 0;
  const timer = setInterval(() => { ticks += 1; }, 5);
  await Promise.all(Array.from({ length: 4 }, () => verifyPasswordAsync("ofis-sifre-2", salt, hash)));
  clearInterval(timer);
  assert.ok(ticks >= 1, `ticks=${ticks}`);
});

test("giriş kısıtı: 5 hatadan sonra kilit, pencere ikiye katlanır (en çok 5 dk), başarı sıfırlar", () => {
  let clock = 0;
  const t = createLoginThrottle({ now: () => clock });
  for (let i = 0; i < 5; i++) { assert.equal(t.begin(), 0, `deneme ${i + 1} serbest`); t.end(false); }
  assert.equal(t.begin(), 10_000);                    // 5. hatadan sonra 10 sn kilit; scrypt çalıştırılmaz
  clock = 9_999; assert.equal(t.begin(), 1);
  clock = 10_000; assert.equal(t.begin(), 0);         // pencere bitti: tek deneme
  assert.equal(t.begin(), 1000, "kilit açılınca da tek eşzamanlı deneme");
  t.end(false);                                       // 6. hata -> 20 sn
  clock = 10_001; assert.equal(t.begin(), 19_999);
  const windows = [10_000, 20_000];
  let lockedAt = 10_000;
  for (let i = 0; i < 6; i++) {                       // 40, 80, 160, 300 (üst sınır), 300, 300
    const wait = windows[windows.length - 1];
    clock = lockedAt + wait; assert.equal(t.begin(), 0);
    t.end(false);
    lockedAt = clock;
    windows.push(Math.min(wait * 2, 300_000));
    assert.equal(t.begin(), windows[windows.length - 1]);
  }
  assert.deepEqual(windows, [10_000, 20_000, 40_000, 80_000, 160_000, 300_000, 300_000, 300_000]);
  clock = lockedAt + 300_000; assert.equal(t.begin(), 0);
  t.end(true);                                        // başarı: her şey sıfırlanır
  for (let i = 0; i < 5; i++) { assert.equal(t.begin(), 0); t.end(false); }
  assert.equal(t.begin(), 10_000);                    // yeniden ilk pencere
});

test("giriş kısıtı: serbest haktan fazla eşzamanlı deneme başlatılamaz", () => {
  const t = createLoginThrottle({ now: () => 0 });
  const waits = Array.from({ length: 10 }, () => t.begin());
  assert.equal(waits.filter((w) => w === 0).length, 5);
  assert.equal(waits.filter((w) => w > 0).length, 5);
  for (let i = 0; i < 5; i++) t.end(false);           // 5 hata -> kilit
  assert.ok(t.begin() > 0);
});

test("giriş kısıtı: başarılı girişler hata sayacını sıfırlar (kilit tetiklenmez)", () => {
  const t = createLoginThrottle({ now: () => 0 });
  for (let round = 0; round < 10; round++) {
    for (let i = 0; i < 4; i++) { assert.equal(t.begin(), 0); t.end(false); }
    assert.equal(t.begin(), 0); t.end(true);
  }
  assert.equal(t.begin(), 0);
});

test("hostAllowed: yalnızca geri döngü adları ve bu bilgisayarın kendi IPv4 adresleri", () => {
  const own = ["192.168.1.109", "172.21.176.1"];
  for (const h of ["127.0.0.1", "127.0.0.1:3000", "localhost", "localhost:3100", "LOCALHOST:3000", "[::1]", "[::1]:3000",
    "192.168.1.109:3000", "172.21.176.1", " 127.0.0.1:3000 "]) assert.equal(hostAllowed(h, own), true, h);
  for (const h of ["", "evil.com", "evil.com:3000", "127.0.0.1.evil.com", "localhost.evil.com:3000", "evil.com:127.0.0.1",
    "192.168.1.110:3000", "0.0.0.0:3000", "10.0.0.5", "[::2]", "[::1", "[::1]x", "127.0.0.1:abc", "127.0.0.1:3000:1",
    "::1", "attacker@127.0.0.1", "127.0.0.1/", undefined, null, 42]) {
    assert.equal(hostAllowed(h, own), false, String(h));
  }
  assert.equal(hostAllowed("192.168.1.109:3000", []), false);                 // kendi adres listesi boşsa yalnızca geri döngü
  assert.equal(hostAllowed("127.0.0.1"), true);
});

test("updateAccess: boşluktan oluşan ya da 256'dan uzun şifre reddedilir; kırpılmış uzunluk sayılır", () => {
  assert.equal(updateAccess(null, { enabled: false, password: "        " }, false).status, 422);          // 8 boşluk
  assert.equal(updateAccess(null, { enabled: false, password: "   abcdefg  " }, false).status, 422);      // kırpılınca 7
  assert.match(updateAccess(null, { enabled: false, password: "        " }, false).error, /en az 8.*boşluk/);
  assert.equal(updateAccess(null, { enabled: false, password: "a".repeat(257) }, false).status, 422);
  assert.match(updateAccess(null, { enabled: false, password: "a".repeat(257) }, false).error, /256/);
  assert.ok(updateAccess(null, { enabled: false, password: "a".repeat(256) }, false).next.hash);
  const ok = updateAccess(null, { enabled: false, password: "  abcdefgh  " }, false).next;                // kırpılınca 8: geçer
  assert.ok(verifyPassword("  abcdefgh  ", ok.salt, ok.hash));                                           // yazıldığı gibi doğrulanır
});

test("updateAccess: kapalıdan açığa her geçişte oturum sırrı yenilenir; açıkken Kaydet sırrı korur", () => {
  const a = updateAccess(null, { enabled: false, password: "uzun-sifre-123" }, false).next;
  const on1 = updateAccess(a, { enabled: true }, false).next;
  assert.notEqual(on1.secret, a.secret);
  const keep = updateAccess(on1, { enabled: true }, false).next;
  assert.equal(keep.secret, on1.secret);
  const off = updateAccess(keep, { enabled: false }, false).next;
  assert.equal(off.secret, keep.secret);                                       // kapatmak sırrı değiştirmez
  const on2 = updateAccess(off, { enabled: true }, false).next;
  assert.notEqual(on2.secret, on1.secret);                                     // yeniden açılış: yeni sır
  assert.equal(on2.hash, on1.hash);
});

test("updateAccess: açmak için tam özet (tuz+özet+sır) ya da ortam şifresi gerekir", () => {
  const { salt, hash } = hashPassword("ofis-sifre-1");
  for (const cur of [{ enabled: false, hash }, { enabled: false, salt }, { enabled: false, salt: "", hash: "" }, { enabled: false }]) {
    const r = updateAccess(cur, { enabled: true }, false);
    assert.equal(r.status, 422, JSON.stringify(cur));
    assert.match(r.error, /önce panel şifresi belirleyin/);
  }
  // tuz+özet var, sır eksik (elle düzenlenmiş dosya): sır üretilir, tam özet olur, açılır
  const healed = updateAccess({ enabled: false, salt, hash }, { enabled: true }, false);
  assert.ok(healed.next.enabled && /^[0-9a-f]{64}$/.test(healed.next.secret));
  // ortam şifresi varsa özet olmadan da açılır
  assert.ok(updateAccess({ enabled: false }, { enabled: true }, true).next.enabled);
});

// ---- Son düzeltme turu: başlatıcı (tek kopya kilidi, derleme işareti, middleware denetimi, durum dosyası), giriş

test("buildIsStale: BUILD_ID olsa da başarı işareti yoksa (yarıda kesilmiş derleme) eski; işaret varsa güncel", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "bv-marker-"));
  try {
    const T = 1_700_000_000;
    const at = (rel, sec) => {
      const f = path.join(dir, rel);
      fs.mkdirSync(path.dirname(f), { recursive: true });
      fs.writeFileSync(f, "x");
      fs.utimesSync(f, sec, sec);
    };
    at("src/app/page.tsx", T);
    fs.utimesSync(path.join(dir, "src", "app"), T, T); fs.utimesSync(path.join(dir, "src"), T, T);
    at(`${LAUNCHER_DIST}/BUILD_ID`, T + 100);                                  // derleme BUILD_ID yazdı, sonra öldürüldü
    assert.equal(buildIsStale(dir), true);
    at(`${LAUNCHER_DIST}/${BUILD_MARKER}`, T + 50);                            // başarı işareti (derleme başlangıcı)
    assert.equal(buildIsStale(dir), false);
    at(`${LAUNCHER_DIST}/${BUILD_MARKER}`, T - 1);                             // en yeni kaynaktan eski işaret
    assert.equal(buildIsStale(dir), true);
    at(".next/BUILD_ID", T + 500);                                             // başka (e2e/elle) derleme sayılmaz
    at(".next/" + BUILD_MARKER, T + 500);
    assert.equal(buildIsStale(dir), true);
    assert.equal(buildIsStale(dir, ".next"), false);
    fs.rmSync(path.join(dir, LAUNCHER_DIST, "BUILD_ID"));
    at(`${LAUNCHER_DIST}/${BUILD_MARKER}`, T + 50);
    assert.equal(buildIsStale(dir), true);                                     // işaret var ama derleme yok
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("lockDecision: canlı süreç ve taze kilit → çalışıyor; ölü süreç, bayat kilit ya da bozuk içerik → devral", () => {
  assert.equal(lockDecision(1234, true), "running");
  assert.equal(lockDecision(1234, true, LOCK_STALE_MS - 1), "running");
  assert.equal(lockDecision(1234, false), "stale");                          // süreç yok: devral
  assert.equal(lockDecision(1234, true, LOCK_STALE_MS + 1), "stale");         // PID yeniden kullanılmış (yeniden başlatma)
  for (const bad of [null, undefined, NaN, 0, -5, 1.5]) {
    assert.equal(lockDecision(bad, false, LOCK_FRESH_MS + 1), "stale", String(bad));
    assert.equal(lockDecision(bad, false, 10), "running", `${bad}: başka başlatıcı tam şu an yazıyor`);
  }
});

test("middlewareReady: derlemenin middleware listesi dolu olmalı; yok, boş ya da bozuksa yerel ağa açılmaz", () => {
  const ok = { version: 3, middleware: { "/": { files: ["server/src/middleware.js"], name: "src/middleware", page: "/" } }, functions: {}, sortedMiddleware: ["/"] };
  assert.equal(middlewareReady(JSON.stringify(ok)), true);
  assert.equal(middlewareReady(JSON.stringify({ version: 3, middleware: {}, functions: {}, sortedMiddleware: [] })), false);
  for (const bad of ["", "{", "null", "[]", JSON.stringify({ version: 3 }), JSON.stringify({ middleware: [] }), null, undefined]) {
    assert.equal(middlewareReady(bad), false, String(bad));
  }
});

test("panelState: durum dosyası yalnız bilinen durumları verir; bozuk ya da yoksa null", () => {
  assert.deepEqual(panelState(JSON.stringify({ state: "building", host: "0.0.0.0", at: 1, message: "Panel derleniyor (ilk açılış 1-2 dk)…" })),
    { state: "building", message: "Panel derleniyor (ilk açılış 1-2 dk)…" });
  assert.deepEqual(panelState(JSON.stringify({ state: "failed", message: 42 })), { state: "failed", message: "" });
  assert.equal(panelState(JSON.stringify({ state: "listening", message: "x".repeat(1000) })).message.length, 300);
  for (const bad of ["", "{", "null", JSON.stringify({ state: "hacked" }), JSON.stringify([1]), undefined]) {
    assert.equal(panelState(bad), null, String(bad));
  }
  assert.equal(panelStateFile({ PANEL_STATE_FILE: "/tmp/s.json" }, "/app"), "/tmp/s.json");
  assert.match(panelStateFile({}, "/app"), /\.local[\\/]panel-state\.json$/);
});

test("isJsonContentType: giriş yalnızca application/json kabul eder (site dışı text/plain istekleri kısıtı kilitleyemesin)", () => {
  for (const ok of ["application/json", "Application/JSON", "application/json; charset=utf-8", " application/json ;charset=UTF-8"]) {
    assert.equal(isJsonContentType(ok), true, ok);
  }
  for (const bad of ["text/plain", "text/plain;charset=UTF-8", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x",
    "application/jsonx", "application/json-patch+json", "", null, undefined]) {
    assert.equal(isJsonContentType(bad), false, String(bad));
  }
});
