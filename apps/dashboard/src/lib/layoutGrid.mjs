// N×M düzen kimliği: "<satır>x<sütun>" (1–16 × 1–16, çarpım ≤ 128). Python karşılığı: live/layouts.py (parse_grid).
export const MAX_TILES = 128;

const GRID_RE = /^([1-9]|1[0-6])x([1-9]|1[0-6])$/;

export function parseGrid(id) {
  const m = GRID_RE.exec(id);
  if (!m) return null;
  const rows = Number(m[1]);
  const cols = Number(m[2]);
  return rows * cols <= MAX_TILES ? { rows, cols } : null;
}

export function gridId(rows, cols) {
  return `${rows}x${cols}`;
}

/** Katalog kimliği ya da N×M kimliği için düzen; bilinmeyen kimlik için null. */
export function layoutFor(id, catalog) {
  const found = catalog.find((l) => l.id === id);
  if (found) return found;
  const g = parseGrid(id);
  if (!g) return null;
  const cells = [];
  for (let y = 0; y < g.rows; y++) for (let x = 0; x < g.cols; x++) cells.push([x, y, 1, 1]);
  return { id, name: `${g.rows}×${g.cols}`, cols: g.cols, rows: g.rows, cells };
}

/**
 * Kutu katmanının yoğunluğu, kutunun dış boyutuna (CSS px) ve kök yazı boyutuna göre (kameranın durumuna göre DEĞİL: durum
 * değişince kutu yoğunluk değiştirmez); böylece hiçbir boyutta ve tarayıcının hiçbir yazı boyutunda ad, rozet, nokta,
 * durum metni, alarm etiketi ve düğmeler üst üste binmez ya da kutudan taşmaz:
 *   - "full": sütun: üst şeritte ad, rozet (ve aşağıdaki durumda nokta); orta alanda durum metni; alt şeritte alarm etiketi
 *     ile dokunmatikte "⋯" ya da (üstüne gelince/klavye odağında) düğmeler. Orta alan bir satır almıyorsa durum, üst
 *     şeritte addan sonra noktadır;
 *   - "small": tek şerit: alarm etiketi ya da ad, nokta, "⋯" (düğmeler yalnız "⋯" ve sağ tık menüsünde);
 *   - "tiny": yalnız köşede nokta;
 *   - "micro": köşedeki nokta kutudan taşardı: küçük nokta kutunun ortasında.
 * Bütün ölçüler rem cinsindendir (TileOverlay'in Tailwind sınıflarıyla aynı; 1 rem = 4 Tailwind aralık birimi): katman
 * tarayıcının yazı boyutuyla büyür, eşikler de. `rem`: kök yazı boyutu (px; sayfada ölçülür, varsayılan 16).
 * `grid`: ızgaranın boyutu; henüz ölçülmediyse null ("full").
 */
export const ROOT_PX = 16;
/** Normal kutu: alt şerit (etiket 1 rem + boşluk + üç düğme 5 rem) ve kenarlar sığar; yükseklik FULL_CHROME_H */
export const TILE_FULL = Object.freeze({ w: 8, h: 4.5 });
/** Küçük kutu: şerit (etiket 0.75 + nokta 0.5 + "⋯" 1.75 + aralıklar) ve kenarlar sığar; şerit 1.75 rem yüksek */
export const TILE_SMALL = Object.freeze({ w: 4.5, h: 2.75 });
/** Çok küçük kutu: köşedeki 0.5 rem nokta (kenardan 0.5 rem içeride) payıyla sığar */
export const TILE_TINY = Object.freeze({ w: 1.5, h: 1.375 });
/**
 * Normal kutuda orta alanın dışında kalan yükseklik (rem): kutu boşluğu 0.25 + şerit boşluğu 0.375 (iki kenar: 1.25), üst
 * şerit 1.25, alt şerit 1.5, iki aralık 0.25.
 */
export const FULL_CHROME_H = 4.5;
/** Durum metninin satır yüksekliği (rem; `leading-4`) */
export const STATE_LINE_H = 1;

/** Kutunun dış boyutu (CSS px); ızgara ölçülmediyse null */
export function tileSize(layout, index, grid) {
  if (!grid) return null;
  const [, , w, h] = layout.cells[index];
  return { w: (grid.w * w) / layout.cols, h: (grid.h * h) / layout.rows };
}

/** Normal kutunun orta alanına sığan durum metni satırı (en çok 2): kutu yüksekliğinden (px) ve kök yazı boyutundan */
export function stateLines(h, rem = ROOT_PX) {
  return Math.max(0, Math.min(2, Math.floor((h - FULL_CHROME_H * rem) / (STATE_LINE_H * rem))));
}

export function tileTier(layout, index, grid, rem = ROOT_PX) {
  const size = tileSize(layout, index, grid);
  if (!size) return "full";
  const fits = (t) => size.w >= t.w * rem && size.h >= t.h * rem;
  if (fits(TILE_FULL)) return "full";
  if (fits(TILE_SMALL)) return "small";
  if (fits(TILE_TINY)) return "tiny";
  return "micro";
}
