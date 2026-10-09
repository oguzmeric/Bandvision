import assert from "node:assert/strict";
import test from "node:test";
import { MIN_PASSWORD, accessFile, hashPassword, newSecret, panelPlan, updateAccess, verifyPassword } from "./accessCore.mjs";

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
  assert.equal(again.secret, a.secret);
  const changed = updateAccess(a, { enabled: true, password: "baska-sifre-456" }, false).next;
  assert.notEqual(changed.secret, a.secret);                                               // yeni şifre: eski oturumlar düşer
  assert.notEqual(changed.hash, a.hash);
  assert.notEqual(changed.salt, a.salt);
  assert.ok(verifyPassword("baska-sifre-456", changed.salt, changed.hash));
  assert.ok(!verifyPassword("uzun-sifre-123", changed.salt, changed.hash));
});
