// `Host` başlığı (DNS yeniden bağlama savunması) ve başka site denetimi. Saf ve içe aktarmasız: hem Edge (middleware) hem
// Node (API rotası, accessCore.mjs) kullanır; `node --test` ile sınanır.

/**
 * `Host` başlığındaki ana makine adı: küçük harf, port atılmış, IPv6 köşeli parantezsiz. Geçersiz başlık (boş, bozuk
 * port, kapanmamış köşeli parantez, köşeli parantezsiz IPv6…) null.
 */
export function hostName(hostHeader) {
  if (typeof hostHeader !== "string") return null;
  const h = hostHeader.trim().toLowerCase();
  let name, port = "";
  if (h.startsWith("[")) {
    const end = h.indexOf("]");
    if (end < 0) return null;
    name = h.slice(1, end);
    const rest = h.slice(end + 1);
    if (rest !== "") { if (!rest.startsWith(":")) return null; port = rest.slice(1); }
  } else {
    const parts = h.split(":");
    if (parts.length > 2) return null;
    name = parts[0];
    port = parts[1] ?? "";
  }
  if (!name || (port !== "" && !/^\d{1,5}$/.test(port))) return null;
  return name;
}

/** Geri döngü adı mı (localhost, 127.0.0.1, [::1]): şifresiz kipte panel yalnızca bu adlarla açılır. */
export function isLoopbackHost(hostHeader) {
  const n = hostName(hostHeader);
  return n === "127.0.0.1" || n === "localhost" || n === "::1";
}

// Origin tarayıcının ürettiği biçimdedir: şema://ad[:port]; yol, kullanıcı bilgisi ve boşluk içermez. Bu yüzden `hostName`in
// hoş gördüğü biçimler (`[localhost]`, boş port, çevredeki boşluk) burada bozuktur. `u` bayrağı yok: büyük/küçük harf
// eşlemesi `ſ`'yi `s` saymasın.
const ORIGIN = /^https?:\/\/((?:[a-z0-9.]+|\[::1\])(?::[0-9]{1,5})?)$/i;

/** `Origin` bu bilgisayarın bir kaynağı mı: `http` ya da `https`, geri döngü adı, port olsun olmasın, yol yok. `null`, başka
 * şema ve bozuk değer false. Analiz sunucusunun `is_loopback_origin` işleviyle aynıdır (ortak tablo: contracts/loopback-origins.json). */
export function isLoopbackOrigin(origin) {
  const m = typeof origin === "string" ? ORIGIN.exec(origin) : null;
  return m !== null && isLoopbackHost(m[1]);
}

export const CROSS_SITE_REFUSED = "Bu istek başka bir siteden geldiği için kabul edilmedi.";

/**
 * Şifresiz kipte API isteği başka siteden mi geliyor (`Host` denetimi bunu durdurmaz: her site 127.0.0.1'e geçerli `Host`
 * ile istek atabilir, çok parçalı `POST` ön uçuş gerektirmez; vekil de sunucu tarafından, `Origin`'siz iletir). `Origin`
 * varsa karar onundur: geri döngü kaynağı olmalı (iki `Origin` satırı `Headers.get` ile birleşir, bozuk sayılır). Yoksa
 * yalnızca `Sec-Fetch-Site: cross-site` reddedilir: curl ve sunucu tarafı istekler bu başlığı göndermez.
 */
export function crossSiteRefused(origin, secFetchSite) {
  if (origin !== null && origin !== undefined) return !isLoopbackOrigin(origin);
  return typeof secFetchSite === "string" && secFetchSite.split(",").some((v) => v.trim().toLowerCase() === "cross-site");
}

/**
 * Ara katmanın API kapısından (`apiRefusal`) geçirdiği yol mu: `/api/` ve Next'in veri yolu `/_next/data/<yapı kimliği>/…`.
 * İkincisi Next'te ara katmanda eşlenir ve API işleyicilerine ulaşır (`/_next/data/<id>/api/jobs/<iş>.json` bir `DELETE`i
 * işleyiciye taşır), ama `skipMiddlewareUrlNormalize` ile ara katman önekli yolu görür; `/api/` öneki aranırsa sayfa koluna
 * düşer ve Origin denetimi atlanırdı. Uygulama App Router kullanır (`pages/` yok): meşru hiçbir istek bu yolu kullanmaz.
 */
export function isApiPath(pathname) {
  return typeof pathname === "string" && (pathname.startsWith("/api/") || pathname.startsWith("/_next/data/"));
}
