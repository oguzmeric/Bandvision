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
 * Kutu katmanının yoğunluğu, kutunun dış boyutuna (CSS px) göre; böylece hiçbir boyutta ad, rozet, alarm etiketi ve
 * düğmeler üst üste binmez ya da kutudan taşmaz:
 *   - "full": üstte ad ve rozet, altta alarm etiketi ile dokunmatikte "⋯" ya da (üstüne gelince/klavye odağında) düğmeler;
 *   - "small": tek şerit: alarm etiketi ya da ad, rozet noktası, "⋯" (düğmeler yalnız "⋯" ve sağ tık menüsünde);
 *   - "tiny": yalnız rozet noktası.
 * `grid`: ızgaranın boyutu; henüz ölçülmediyse null ("full").
 */
export const TILE_FULL = Object.freeze({ w: 128, h: 72 });
export const TILE_SMALL = Object.freeze({ w: 72, h: 44 });

export function tileTier(layout, index, grid) {
  if (!grid) return "full";
  const [, , w, h] = layout.cells[index];
  const tw = (grid.w * w) / layout.cols;
  const th = (grid.h * h) / layout.rows;
  if (tw >= TILE_FULL.w && th >= TILE_FULL.h) return "full";
  if (tw >= TILE_SMALL.w && th >= TILE_SMALL.h) return "small";
  return "tiny";
}
