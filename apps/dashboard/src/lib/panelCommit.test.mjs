import assert from "node:assert/strict";
import test from "node:test";
import { commitReader } from "./panelCommit.mjs";

test("panel git özeti: BV_COMMIT varsa git çalıştırılmaz", async () => {
  let runs = 0;
  const read = commitReader({ env: { BV_COMMIT: " abc1234 " }, run: async () => { runs += 1; return "x"; } });
  assert.equal(await read(), "abc1234");
  assert.equal(runs, 0);
});

test("panel git özeti: eşzamansız ve süreç başına bir kez (aynı anda gelenler aynı sonucu bekler)", async () => {
  let runs = 0;
  let finish;
  const read = commitReader({ env: {}, run: () => { runs += 1; return new Promise((res) => { finish = res; }); } });
  const first = read();
  const second = read();
  assert.ok(first instanceof Promise, "okuma olay döngüsünü bekletmez: söz (Promise) döner");
  // git sürerken olay döngüsü serbest: zamanlayıcı çalışır
  let ticked = false;
  await new Promise((res) => setTimeout(() => { ticked = true; res(); }, 5));
  assert.ok(ticked);
  finish("def5678\n");
  assert.equal(await first, "def5678");
  assert.equal(await second, "def5678");
  assert.equal(await read(), "def5678");
  assert.equal(runs, 1);
});

test("panel git özeti: git yoksa, hata verirse ya da boş dönerse '?' (bir kez denenir)", async () => {
  let runs = 0;
  const failing = commitReader({ env: {}, run: async () => { runs += 1; throw new Error("ENOENT"); } });
  assert.equal(await failing(), "?");
  assert.equal(await failing(), "?");
  assert.equal(runs, 1);
  assert.equal(await commitReader({ env: {}, run: async () => "  \n" })(), "?");
});

test("panel git özeti: gerçek git (bu depo) kısa özet verir", async () => {
  const sha = await commitReader({ env: {} })();
  assert.match(sha, /^([0-9a-f]{4,40}|\?)$/);
});
