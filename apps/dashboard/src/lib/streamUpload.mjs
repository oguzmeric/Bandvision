// Akan gövdeyi `fetch` ile iletirken gereken seçenekler (video yükleme vekili). Saf; `node --test` gerçek `fetch` ile sınar.

/**
 * - `duplex`: Node fetch akan gövde için ister.
 * - `credentials: "omit"`: yoksa Node fetch 401'de gövdeyi kimlikle yeniden göndermeye kalkar, akan gövde tekrarlanamadığı için
 *   ağ hatası verir ("expected non-null body source"): erişim anahtarı reddi "analiz sunucusuna ulaşılamadı" görünürdü.
 * - `redirect: "error"` ve `window: null` birlikte: yoksa Node fetch yönlendirme ve kimlik için isteği kopyalar (gövdeyi `tee`
 *   ile ikiye böler), okunmayan kol bütün videoyu bellekte biriktirirdi. Analiz sunucusu bu uçta yönlendirme yapmaz.
 */
export const STREAM_BODY_INIT = { duplex: "half", credentials: "omit", redirect: "error", window: null };
