// Port bu bilgisayarda boş mu. `node:net` kullandığı için accessCore.mjs'ye KONMAZ (Next kodu onu içe aktarır, middleware uç
// ortamda çalışabilir); yalnızca başlatıcı (tools/panel_run.mjs) ve testler bunu kullanır.
import net from "node:net";

/** Yalnızca bu hatalar "dolu" demektir; adres yok (IPv6 kapalı) gibi diğerleri o adres için sorun değildir. */
const BUSY = new Set(["EADDRINUSE", "EACCES"]);

/** `host:port` dinlenebilir mi (denemeden sonra hemen kapatılır). Dolu/izinsiz → false; adres yok → true.
 * `ipv6Only`: yalnızca `::` için anlamlı (çift yığın olmayan bağlama). */
export function canListen(port, host, ipv6Only = false) {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.once("error", (e) => resolve(!BUSY.has(e.code)));
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
