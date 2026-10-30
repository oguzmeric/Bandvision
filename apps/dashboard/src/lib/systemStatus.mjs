/** Durum şeridi: analiz sunucusunun yanıtını sınıflandıran işlevler (route.ts ve birim testi kullanır). */

/**
 * `/api/v1/system/status` yanıtı/hatası → "up" (çalışıyor), "auth" (erişim anahtarı yanlış/eksik: 401/403), "old" (404:
 * bu ucu olmayan eski analiz sunucusu; çağıran `/healthz`'e bakar), "down" (ağ hatası, zaman aşımı, 5xx ya da başka bir
 * hata kodu). "auth" asla "down" diye bildirilmez: kullanıcı ANALYZER_TOKEN'ı düzeltmeli.
 */
export function classify(r) {
  if (!r || "error" in r) return "down";
  if (r.status === 401 || r.status === 403) return "auth";
  if (r.status === 404) return "old";
  return r.ok === true ? "up" : "down";
}

/**
 * Analiz sunucusu gövdesini doğrular; tür uymuyorsa null (çağıran "down" sayar). `cpuPercent` null olabilir: psutil'siz
 * eski kurulumda işlemci yükü bilinmez (şerit "—" yazar). `commit` alanı olmayan (eski) gövdede git özeti "?".
 */
export function parseStatus(json) {
  if (!json || typeof json !== "object") return null;
  const { cpuPercent, uptimeS, version } = json;
  const commit = "commit" in json ? json.commit : "?";
  if (cpuPercent !== null && (typeof cpuPercent !== "number" || !Number.isFinite(cpuPercent))) return null;
  if (typeof uptimeS !== "number" || !Number.isFinite(uptimeS)) return null;
  if (typeof version !== "string" || typeof commit !== "string") return null;
  return { cpuPercent, uptimeS, version, commit };
}

/** Durum ucu olmayan ama çalışan analiz sunucusu: ölçümler ve sürüm bilinmiyor */
const UNKNOWN = { cpuPercent: null, uptimeS: null, version: "?", commit: "?" };

/**
 * Analiz sunucusunun özeti. `get(yol)` analiz sunucusuna istek atar ({ok, status, json()} döndürür; ağ hatasında atar:
 * hata çağırana gider). Sonuç `{analyzer, cpuPercent?, uptimeS?, version?, commit?, log}`; `log` günlüğe yazılacak
 * `{message, what}` ya da null.
 *   - 200 ve geçerli gövde: "up" ve ölçümler;
 *   - 401/403: "auth";
 *   - 404 (durum ucu yok: eski analiz sunucusu): `/healthz` `{ok: true}` derse "up" ve bilinmeyen alanlar (işlemci, süre
 *     null; sürüm, özet "?"), demezse "down";
 *   - başka hata kodu ya da geçersiz gövde: "down".
 */
export async function analyzerSummary(get) {
  const res = await get("/api/v1/system/status");
  const state = classify(res);
  if (state === "auth") {
    return { analyzer: "auth", log: { message: `HTTP ${res.status}: ANALYZER_TOKEN yanlış ya da eksik`, what: "analiz sunucusu erişimi reddetti" } };
  }
  if (state === "old") {
    const h = await get("/healthz");
    const body = h.ok ? await h.json().catch(() => null) : null;
    if (body && typeof body === "object" && body.ok === true) {
      return { analyzer: "up", ...UNKNOWN,
        log: { message: "HTTP 404: /api/v1/system/status yok", what: "analiz sunucusu eski (işlemci yükü ve sürüm bilinmiyor)" } };
    }
    return { analyzer: "down", log: { message: `HTTP 404, /healthz HTTP ${h.status}`, what: "analiz sunucusu hata döndürdü" } };
  }
  if (state === "down") return { analyzer: "down", log: { message: `HTTP ${res.status}`, what: "analiz sunucusu hata döndürdü" } };
  const s = parseStatus(await res.json().catch(() => null));
  if (!s) return { analyzer: "down", log: { message: "beklenmeyen gövde", what: "analiz sunucusu durum yanıtı geçersiz" } };
  return { analyzer: "up", ...s, log: null };
}
