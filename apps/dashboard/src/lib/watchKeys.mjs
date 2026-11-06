// Canlı izleme klavye kısayolları ve sekme sırası: saf mantık (DOM'a dokunmaz; bekçi sahte nesnelerle de denenir).

/** Kısayolları kapatan odak: yazı kutusu, seçim kutusu, metin alanı, düzenlenebilir öğe */
const TYPING = "input, select, textarea, [contenteditable]";
/** Kısayolları kapatan açık pencere ya da menü (Şablon editörü kipsiz `role="dialog"`, bağlam menüsü `role="menu"`) */
const OVERLAY = "dialog[open], [role=dialog], [role=menu]";

/** Odak yazı alanındaysa ya da bir pencere/menü açıksa kısayollar çalışmaz */
export function shortcutsBlocked(target, doc) {
  if (target && (target.isContentEditable || (typeof target.closest === "function" && target.closest(TYPING)))) return true;
  return !!doc.querySelector(OVERLAY);
}

/**
 * Tuş → kısayol işi; çalışmayacaksa null. `ctx`: `blocked` (bekçi), `single` (tek kamera görünümü), `touring` (sıralı
 * gösterim), `control` (odak bir düğme ya da bağlantıda: Boşluk onundur).
 *   F: ızgarada büyüt / tek kamerada ızgaraya dön ("toggle-single"); Esc: tek kameradan (ve sıralı gösterimden) çık;
 *   Boşluk: sıralı gösterimde duraklat/sürdür, yoksa yutulur ("swallow": sayfa kaymaz); ←/→: tek kamerada önceki/sonraki
 *   dolu kutu; 1–9: n. sekme; ?: yardım. Ctrl/Alt/Cmd ile basılan tuşlar tarayıcınındır; basılı tutulan tuş (ok tuşları
 *   dışında) yinelenmez.
 */
export function shortcutFor(e, ctx) {
  if (ctx.blocked || e.ctrlKey || e.metaKey || e.altKey) return null;
  const k = e.key;
  if (k === "ArrowLeft" || k === "ArrowRight") return ctx.single ? { type: "step", dir: k === "ArrowRight" ? 1 : -1 } : null;
  if (e.repeat) return null;
  if (k === "f" || k === "F") return { type: "toggle-single" };
  if (k === "Escape") return ctx.single ? { type: "escape" } : null;
  if (k === " ") return ctx.control ? null : ctx.touring ? { type: "pause" } : { type: "swallow" };
  if (k === "?") return { type: "help" };
  if (/^[1-9]$/.test(k)) return { type: "tab", index: Number(k) - 1 };
  return null;
}

/**
 * Sekme sırası: `id` sekmesi `target` sekmesinin yerine geçer (sürükle-bırak; Sola/Sağa taşı komşunun yerine).
 * Değişiklik yoksa (aynı yer, bilinmeyen kimlik) aynı dizi döner.
 */
export function moveTab(ids, id, target) {
  const from = ids.indexOf(id);
  const to = ids.indexOf(target);
  if (from < 0 || to < 0 || from === to) return ids;
  const next = ids.filter((x) => x !== id);
  next.splice(to, 0, id);
  return next;
}
