// Sıralı gösterim (Canlı izleme): tek kamera görünümü şablonun dolu kutularını kutu sırasıyla gezer; boş kutular atlanır.
// Aralık bu tarayıcıda çerezde hatırlanır (localStorage değil: panelin portu değişebilir; bkz. nav.ts).

/** Seçilebilen aralıklar (sn) */
export const TOUR_INTERVALS = [5, 10, 20, 30, 60];
export const DEFAULT_TOUR_S = 10;
export const TOUR_COOKIE = "bv_watch_tour_s";

/** Dolu kutuların sırası (kutu sırasıyla) */
export function filledIndexes(tiles) {
  const out = [];
  tiles.forEach((t, i) => { if (t) out.push(i); });
  return out;
}

/**
 * `from`'dan `dir` yönünde (1: sonraki, -1: önceki) ilk dolu kutu; uçta başa/sona sarar. Tek dolu kutu varsa kendisi
 * (from oysa), hiç dolu kutu yoksa null. `from` boş bir kutu da olabilir.
 */
export function stepFilled(tiles, from, dir) {
  const n = tiles.length;
  for (let k = 1; k <= n; k++) {
    const j = (((from + dir * k) % n) + n) % n;
    if (tiles[j]) return j;
  }
  return null;
}

/** Kutunun dolu kutular arasındaki sırası (1'den; boş kutuda 0) ve dolu kutu sayısı: "n/toplam" */
export function tourPosition(tiles, index) {
  const filled = filledIndexes(tiles);
  return { n: filled.indexOf(index) + 1, total: filled.length };
}

/** Çerez dizgisinden (`document.cookie`) bir değer; yoksa null */
export function readCookie(cookies, name) {
  for (const part of (cookies ?? "").split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k === name) return v.join("=");
  }
  return null;
}

/** Çerezdeki aralık; yoksa ya da seçeneklerden biri değilse varsayılan */
export function parseTourInterval(raw) {
  if (raw === null || raw === undefined || !/^\d+$/.test(raw)) return DEFAULT_TOUR_S;
  const s = Number(raw);
  return TOUR_INTERVALS.includes(s) ? s : DEFAULT_TOUR_S;
}

/** `document.cookie`'ye yazılacak çerez (1 yıl, tüm panel) */
export function tourCookie(seconds) {
  return `${TOUR_COOKIE}=${seconds}; Path=/; Max-Age=31536000; SameSite=Lax`;
}
