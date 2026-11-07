/**
 * Canlı sayım API vekilinin (`src/app/api/live/[...path]/route.ts`) başlık izin listeleri (birim testli).
 */

/** Analiz sunucusuna giden istek başlıkları: gövde türü ve video sarma (`Range`, alarm kaydı) */
export const LIVE_REQUEST_HEADERS = Object.freeze(["content-type", "range", "if-range"]);

/** Tarayıcıya dönen yanıt başlıkları: video parçası (206) için `content-range` ve `accept-ranges` de; küçük resimde
 * `x-sub-dead` (kanalın alt akışı görüntü vermiyor, resim ana akıştan; panel kanal listesini yalnız bununla yeniden okur) */
export const LIVE_RESPONSE_HEADERS = Object.freeze(["content-type", "content-length", "content-disposition", "cache-control",
  "content-range", "accept-ranges", "x-sub-dead"]);
