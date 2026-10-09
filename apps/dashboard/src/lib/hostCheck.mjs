// `Host` başlığı denetimi (DNS yeniden bağlama savunması). Saf ve içe aktarmasız: hem Edge (middleware) hem Node
// (API rotası, accessCore.mjs) kullanır; `node --test` ile sınanır.

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
