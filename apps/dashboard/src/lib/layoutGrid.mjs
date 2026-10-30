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
 * Kutu katmanının yoğunluğu, kutunun dış boyutuna (CSS px) göre; böylece hiçbir boyutta ad, rozet, durum metni, alarm
 * etiketi ve düğmeler üst üste binmez ya da kutudan taşmaz:
 *   - "full": sütun: üst şeritte ad ve rozet, orta alanda durum metni, alt şeritte alarm etiketi ile dokunmatikte "⋯" ya da
 *     (üstüne gelince/klavye odağında) düğmeler. Durum metni olan kutuda orta alan en az bir satır almalı, yoksa "small";
 *   - "small": tek şerit: alarm etiketi ya da ad, nokta (rozet ya da bağlantı durumu), "⋯" (düğmeler yalnız "⋯" ve sağ
 *     tık menüsünde);
 *   - "tiny": yalnız köşede nokta;
 *   - "micro": köşedeki nokta kutudan taşardı: küçük nokta kutunun ortasında.
 * `grid`: ızgaranın boyutu; henüz ölçülmediyse null ("full"). `withState`: kutuda durum metni var (canlı değil).
 */
export const TILE_FULL = Object.freeze({ w: 128, h: 72 });
export const TILE_SMALL = Object.freeze({ w: 72, h: 44 });
export const TILE_TINY = Object.freeze({ w: 24, h: 22 });
/**
 * Normal kutuda orta alanın dışında kalan yükseklik (TileOverlay ile aynı ölçüler): kutu boşluğu 4 + şerit boşluğu 6 (iki
 * kenar: 20), üst şerit 20, alt şerit 24, iki aralık 4.
 */
export const FULL_CHROME_H = 72;
/** Durum metninin satır yüksekliği (12 px yazı, 16 px satır) */
export const STATE_LINE_H = 16;

/** Kutunun dış boyutu (CSS px); ızgara ölçülmediyse null */
export function tileSize(layout, index, grid) {
  if (!grid) return null;
  const [, , w, h] = layout.cells[index];
  return { w: (grid.w * w) / layout.cols, h: (grid.h * h) / layout.rows };
}

/** Normal kutunun orta alanına sığan durum metni satırı (en çok 2): kutu yüksekliğinden */
export function stateLines(h) {
  return Math.max(0, Math.min(2, Math.floor((h - FULL_CHROME_H) / STATE_LINE_H)));
}

export function tileTier(layout, index, grid, withState = false) {
  const size = tileSize(layout, index, grid);
  if (!size) return "full";
  const { w, h } = size;
  if (w >= TILE_FULL.w && h >= TILE_FULL.h && (!withState || stateLines(h) >= 1)) return "full";
  if (w >= TILE_SMALL.w && h >= TILE_SMALL.h) return "small";
  if (w >= TILE_TINY.w && h >= TILE_TINY.h) return "tiny";
  return "micro";
}
