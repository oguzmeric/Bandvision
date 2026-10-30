/** Durum şeridi: analiz sunucusunun yanıtını sınıflandıran saf işlevler (route.ts ve birim testi kullanır). */

/** Yanıt/hata → "up" (çalışıyor), "auth" (erişim anahtarı yanlış/eksik: 401/403), "down" (ağ hatası, zaman aşımı, 5xx ya da
 * beklenmeyen durum). "auth" asla "down" diye bildirilmez: kullanıcı ANALYZER_TOKEN'ı düzeltmeli. */
export function classify(r) {
  if (!r || "error" in r) return "down";
  if (r.status === 401 || r.status === 403) return "auth";
  return r.ok === true ? "up" : "down";
}

/**
 * Analiz sunucusu gövdesini doğrular; tür uymuyorsa null (çağıran "down" sayar). `cpuPercent` null olabilir: psutil'siz
 * eski kurulumda işlemci yükü bilinmez (şerit "—" yazar).
 */
export function parseStatus(json) {
  if (!json || typeof json !== "object") return null;
  const { cpuPercent, uptimeS, version, commit } = json;
  if (cpuPercent !== null && (typeof cpuPercent !== "number" || !Number.isFinite(cpuPercent))) return null;
  if (typeof uptimeS !== "number" || !Number.isFinite(uptimeS)) return null;
  if (typeof version !== "string" || typeof commit !== "string") return null;
  return { cpuPercent, uptimeS, version, commit };
}
