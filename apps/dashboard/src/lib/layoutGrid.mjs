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
