import assert from "node:assert/strict";
import test from "node:test";
import { analyzerSummary, classify, parseStatus } from "./systemStatus.mjs";

test("classify: 200 up; 401/403 auth; 404 old (durum ucu olmayan eski analiz sunucusu); 5xx, diğer hatalar ve ağ hatası down", () => {
  assert.equal(classify({ ok: true, status: 200 }), "up");
  assert.equal(classify({ ok: false, status: 401 }), "auth");
  assert.equal(classify({ ok: false, status: 403 }), "auth");
  assert.equal(classify({ ok: false, status: 404 }), "old");
  assert.equal(classify({ ok: false, status: 500 }), "down");
  assert.equal(classify({ ok: false, status: 400 }), "down");
  assert.equal(classify({ error: new Error("ECONNREFUSED") }), "down");
});

test("parseStatus: işlemci yükü bilinmiyorsa (psutil'siz eski kurulum) null kabul edilir", () => {
  const body = { cpuPercent: null, uptimeS: 90, version: "0.1.0", commit: "abc1234" };
  assert.deepEqual(parseStatus(body), body);
});

test("parseStatus: git özeti olmayan (eski) gövde kabul edilir, özet '?'", () => {
  assert.deepEqual(parseStatus({ cpuPercent: 3, uptimeS: 9, version: "0.1.0" }),
    { cpuPercent: 3, uptimeS: 9, version: "0.1.0", commit: "?" });
});

test("parseStatus: geçerli gövde; türü bozuk ya da eksik gövde null", () => {
  const ok = { cpuPercent: 12.5, uptimeS: 90, version: "0.1.0", commit: "abc1234" };
  assert.deepEqual(parseStatus({ ...ok, fazla: 1 }), ok);
  for (const bad of [null, undefined, "x", 5, {}, { ...ok, cpuPercent: "1" }, { ...ok, uptimeS: null },
    { ...ok, version: 1 }, { ...ok, version: undefined }, { ...ok, commit: 5 }, { ...ok, commit: null },
    { ...ok, cpuPercent: NaN }, { ...ok, cpuPercent: undefined }]) {
    assert.equal(parseStatus(bad), null, JSON.stringify(bad));
  }
});

/** Sahte analiz sunucusu: yol → yanıt ({status, body}) ya da atılacak hata; istenen yollar kaydedilir */
function fake(routes) {
  const asked = [];
  const get = async (path) => {
    asked.push(path);
    const r = routes[path];
    if (r instanceof Error) throw r;
    if (!r) return { ok: false, status: 404, json: async () => ({ detail: "Not Found" }) };
    return { ok: r.status >= 200 && r.status < 300, status: r.status, json: async () => r.body };
  };
  return { get, asked };
}
const STATUS = "/api/v1/system/status";
const FULL = { cpuPercent: 7.5, uptimeS: 12, version: "0.1.0", commit: "abc1234" };

test("analyzerSummary: güncel analiz sunucusu → up ve ölçümler; /healthz sorulmaz", async () => {
  const { get, asked } = fake({ [STATUS]: { status: 200, body: FULL } });
  assert.deepEqual(await analyzerSummary(get), { analyzer: "up", ...FULL, log: null });
  assert.deepEqual(asked, [STATUS]);
});

test("analyzerSummary: durum ucu yok (404) ama /healthz çalışıyor → up, alanlar bilinmiyor", async () => {
  const { get, asked } = fake({ "/healthz": { status: 200, body: { ok: true, retentionDays: 7 } } });
  const s = await analyzerSummary(get);
  assert.deepEqual({ ...s, log: null },
    { analyzer: "up", cpuPercent: null, uptimeS: null, version: "?", commit: "?", log: null });
  assert.match(s.log.what, /eski/);
  assert.deepEqual(asked, [STATUS, "/healthz"]);
});

test("analyzerSummary: 404 ve /healthz de çalışmıyor (ya da analiz sunucusu değil) → down", async () => {
  for (const healthz of [undefined, { status: 500, body: null }, { status: 200, body: { ok: false } }, { status: 200, body: "<html>" },
    new Error("ECONNRESET")]) {
    const { get } = fake(healthz === undefined ? {} : { "/healthz": healthz });
    const run = analyzerSummary(get);
    if (healthz instanceof Error) await assert.rejects(run, /ECONNRESET/);          // ağ hatası çağırana (yol günlüğe yazar)
    else assert.equal((await run).analyzer, "down", JSON.stringify(healthz));
  }
});

test("analyzerSummary: 401/403 auth, 5xx down, bozuk gövde down; hepsinde günlük iletisi var", async () => {
  for (const [status, body, want] of [[401, null, "auth"], [403, null, "auth"], [500, null, "down"], [200, { cpuPercent: "x" }, "down"]]) {
    const s = await analyzerSummary(fake({ [STATUS]: { status, body } }).get);
    assert.equal(s.analyzer, want, String(status));
    assert.ok(s.log && s.log.message && s.log.what, String(status));
  }
});
