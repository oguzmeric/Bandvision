import assert from "node:assert/strict";
import net from "node:net";
import test from "node:test";
import { canListen, classifyListenError, isFree } from "./portFree.mjs";

function occupy(host, extra = {}) {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.once("error", reject);
    srv.listen({ port: 0, host, ...extra }, () => resolve(srv));
  });
}
const close = (srv) => new Promise((r) => srv.close(r));

const v6 = await occupy("::1").then(close, () => null).then((r) => r !== null);   // ::1 bağlanabiliyor mu

const cases = [["127.0.0.1", {}], ["0.0.0.0", {}], ["::", {}], ["::", { ipv6Only: true }], ["::1", {}]];
for (const [host, extra] of cases) {
  const skip = host.includes(":") && !v6 ? "bu bilgisayarda IPv6 (::1) bağlanamıyor" : false;
  test(`${host}${extra.ipv6Only ? " (yalnız IPv6)" : ""} üzerinde dinleyen başka uygulama varken isFree false`, { skip }, async () => {
    const srv = await occupy(host, extra);
    try {
      assert.equal(await isFree(srv.address().port), false);
    } finally { await close(srv); }
  });
}

test("kapatılmış port boş", async () => {
  const srv = await occupy("127.0.0.1");
  const { port } = srv.address();
  await close(srv);
  assert.equal(await isFree(port), true);
});

test("canListen: kullanılamayan adres (EADDRNOTAVAIL) sorun sayılmaz", async () => {
  assert.equal(await canListen(0, "203.0.113.77"), true);
});

test("classifyListenError: yalnızca adres-yok hataları boş; geri kalan her şey dolu", () => {
  assert.equal(classifyListenError("EADDRNOTAVAIL"), "free");
  assert.equal(classifyListenError("EAFNOSUPPORT"), "free");
  for (const code of ["EADDRINUSE", "EACCES", "EPERM", "EWHATEVER", undefined]) assert.equal(classifyListenError(code), "busy", String(code));
});
