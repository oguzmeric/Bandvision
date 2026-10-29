// Şablon editörünün saf mantığı (Canlı izleme): düzen düğmeleri, kamera atama, geri al/yinele, kaydedilmedi mi, N×M denetimi.
// Taslak (Draft) = { layout, tiles, name }; girdiler hiç değiştirilmez, her işlem yeni nesne döndürür.
import { MAX_TILES, layoutFor } from "./layoutGrid.mjs";

/** Editördeki 10 düzen düğmesi (spec sırası): 1, 2×2, 3×3, 4×4, 1+5, 1+7, 4×3, 5×5, 8×8, N×M */
export const EDITOR_LAYOUTS = ["1", "4", "9", "16", "6", "8", "12", "5x5", "8x8", "nxm"];
/** Geri alınabilecek en çok adım */
export const HISTORY_LIMIT = 50;
/** Yeni şablon 2×2 açılır */
const NEW_LAYOUT = "4";
const NEW_NAME = "Yeni şablon";
/** N×M satır/sütun sınırı (sözleşme: 1–16) */
const GRID_MAX_SIDE = 16;

export const refKey = (ref) => `${ref.sourceId}|${ref.channelId ?? ""}`;

const sameRef = (a, b) => (!a || !b ? !a && !b : refKey(a) === refKey(b));

/** Düzen ve kutular aynı mı (ad sayılmaz: ad "Yeniden adlandır" ile doğrudan kaydedilir) */
export function sameContent(a, b) {
  return a.layout === b.layout && a.tiles.length === b.tiles.length && a.tiles.every((t, i) => sameRef(t, b.tiles[i]));
}

/** Düzen değişince kutular sırasıyla korunur; sığmayanlar düşer (kaç kamera düştüğü uyarı için döner) */
export function retile(tiles, count) {
  const next = tiles.slice(0, count);
  while (next.length < count) next.push(null);
  return { tiles: next, dropped: tiles.slice(count).filter(Boolean).length };
}

export function newDraft(catalog) {
  const n = layoutFor(NEW_LAYOUT, catalog)?.cells.length ?? 4;
  return { layout: NEW_LAYOUT, tiles: Array.from({ length: n }, () => null), name: NEW_NAME };
}

/** Yeni şablonun adı: "Yeni şablon", doluysa "Yeni şablon 2", "… 3" */
export function newName(taken) {
  const used = new Set(taken);
  if (!used.has(NEW_NAME)) return NEW_NAME;
  for (let n = 2; ; n++) if (!used.has(`${NEW_NAME} ${n}`)) return `${NEW_NAME} ${n}`;
}

export function applyLayout(draft, layoutId, catalog) {
  const layout = layoutFor(layoutId, catalog);
  if (!layout) return { draft, dropped: 0 };
  const r = retile(draft.tiles, layout.cells.length);
  return { draft: { ...draft, layout: layoutId, tiles: r.tiles }, dropped: r.dropped };
}

/** Kutuya kamera koyar (null: boşaltır). Kamera başka kutudaysa oradan TAŞINIR: bir şablonda aynı kamera bir kez. */
export function assign(draft, index, ref) {
  if (index < 0 || index >= draft.tiles.length || sameRef(draft.tiles[index], ref)) return draft;
  const tiles = draft.tiles.map((t) => (ref && t && refKey(t) === refKey(ref) ? null : t));
  tiles[index] = ref ? { sourceId: ref.sourceId, channelId: ref.channelId ?? null } : null;
  return { ...draft, tiles };
}

/** İki kutunun yerini değiştirir (kutudan kutuya sürükleme) */
export function swap(draft, a, b) {
  if (a === b || a < 0 || b < 0 || a >= draft.tiles.length || b >= draft.tiles.length) return draft;
  const tiles = [...draft.tiles];
  [tiles[a], tiles[b]] = [tiles[b], tiles[a]];
  return { ...draft, tiles };
}

// ---- Geri al / yinele: { past, present, future }

export function initHistory(draft) {
  return { past: [], present: draft, future: [] };
}

/** Yeni hâl; içerik aynıysa geçmiş değişmez. İleri (yinelenebilir) adımlar silinir; geçmiş en çok HISTORY_LIMIT adım. */
export function push(h, draft) {
  if (sameContent(h.present, draft) && h.present.name === draft.name) return h;
  return { past: [...h.past, h.present].slice(-HISTORY_LIMIT), present: draft, future: [] };
}

export function undo(h) {
  if (!h.past.length) return h;
  return { past: h.past.slice(0, -1), present: h.past[h.past.length - 1], future: [h.present, ...h.future] };
}

export function redo(h) {
  if (!h.future.length) return h;
  return { past: [...h.past, h.present], present: h.future[0], future: h.future.slice(1) };
}

export const canUndo = (h) => h.past.length > 0;
export const canRedo = (h) => h.future.length > 0;

/** Kaydedilmemiş değişiklik var mı; `saved` null: sunucuda hiç kaydedilmemiş yeni şablon (hep kaydedilmedi) */
export function isDirty(h, saved) {
  return saved === null || !sameContent(h.present, saved);
}

/** N×M girişi: geçerliyse null, değilse Türkçe ileti */
export function validateGrid(rows, cols) {
  const ok = (v) => Number.isInteger(v) && v >= 1 && v <= GRID_MAX_SIDE;
  if (!ok(rows) || !ok(cols)) return `Satır ve sütun 1–${GRID_MAX_SIDE} arasında olmalı.`;
  if (rows * cols > MAX_TILES) return `En çok ${MAX_TILES} kutu (${rows}×${cols} = ${rows * cols}).`;
  return null;
}

/**
 * Klavyeyle kutular arası gezinme (ızgara tek sekme durağıdır, ok tuşları kutudan kutuya): `dir` yönündeki en yakın
 * kutu. Kutu merkezleri karşılaştırılır; ana eksende ilerlemeyen kutular sayılmaz, yan eksendeki sapma iki kat cezalıdır
 * (1 büyük + 5 gibi düzensiz düzenlerde de doğal komşu). O yönde kutu yoksa aynı kutu döner.
 */
export function neighbor(layout, index, dir) {
  const center = ([x, y, w, h]) => [x + w / 2, y + h / 2];
  const [cx, cy] = center(layout.cells[index]);
  let best = index;
  let bestScore = Infinity;
  layout.cells.forEach((cell, i) => {
    if (i === index) return;
    const [x, y] = center(cell);
    const main = { right: x - cx, left: cx - x, down: y - cy, up: cy - y }[dir];
    if (!(main > 0)) return;
    const side = dir === "left" || dir === "right" ? Math.abs(y - cy) : Math.abs(x - cx);
    const score = main + 2 * side;
    if (score < bestScore) { bestScore = score; best = i; }
  });
  return best;
}
