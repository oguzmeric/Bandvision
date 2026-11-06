// Port bu bilgisayarda boş mu. `node:net` kullandığı için accessCore.mjs'ye KONMAZ (Next kodu onu içe aktarır, middleware uç
// ortamda çalışabilir); yalnızca başlatıcı (tools/panel_run.mjs) ve testler bunu kullanır.
import net from "node:net";

/** Yalnızca bu hatalar "o adres ailesi bu bilgisayarda yok" demektir (ör. IPv6 kapalı): o adres için sorun değil.
 * Başka HER hata (EADDRINUSE, EACCES, EPERM, bilinmeyen…) dolu sayılır: bilinmeyen hatada yanlışlıkla "boş" demek
 * paneli başka uygulamanın portuna bindirirdi. */
const ABSENT = new Set(["EADDRNOTAVAIL", "EAFNOSUPPORT"]);

/** Dinleme hata koduna göre: "free" (adres ailesi yok, sorun değil) ya da "busy" */
export function classifyListenError(code) {
  return ABSENT.has(code) ? "free" : "busy";
}

/** `host:port` dinlenebilir mi (denemeden sonra hemen kapatılır). Adres ailesi yoksa (EADDRNOTAVAIL/EAFNOSUPPORT) true, başka her hata false.
 * `ipv6Only`: yalnızca `::` için anlamlı (çift yığın olmayan bağlama). */
export function canListen(port, host, ipv6Only = false) {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.once("error", (e) => resolve(classifyListenError(e.code) === "free"));
    srv.listen({ port, host, exclusive: true, ...(ipv6Only ? { ipv6Only: true } : {}) }, () => srv.close(() => resolve(true)));
  });
}

/** Port bu bilgisayarda boş mu: 127.0.0.1, 0.0.0.0, ::1 ve `::` (çift yığın VE yalnız IPv6 olarak) hepsinde dinlenebilmeli.
 * Başka uygulama yalnızca birinde dinliyor olabilir. Windows'ta ölçüldü: `::`/`::1` dinleyicisi 127.0.0.1 ve 0.0.0.0
 * bağlamasını engellemez (tarayıcı `localhost`u önce `::1`e çözer, yani diğer uygulamayı açardı); çift yığın `::`
 * dinleyicisini (Node'un `listen(port)` varsayılanı) yalnız çift yığın deneme, yalnız-IPv6 `::` dinleyicisini yalnız
 * `ipv6Only` deneme yakalar. */
export async function isFree(port) {
  const probes = [["127.0.0.1", false], ["0.0.0.0", false], ["::1", false], ["::", false], ["::", true]];
  for (const [host, only] of probes) {
    if (!(await canListen(port, host, only))) return false;
  }
  return true;
}
