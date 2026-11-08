// Kayıttan izleme klavye kısayolları: saf mantık (DOM'a dokunmaz; bekçi sahte nesnelerle de denenir).
import { shortcutsBlocked } from "./watchKeys.mjs";

/** ←/→ ile sarma (sn) */
export const STEP_S = 10;
/** Shift+←/→ ile sarma (sn) */
export const BIG_STEP_S = 60;

/** Odak yazı alanında, seçim kutusunda (hız) ya da bir pencere/menü açıkken kısayollar çalışmaz (Canlı izleme kuralı) */
export function archiveKeysBlocked(target, doc) {
  return shortcutsBlocked(target, doc);
}

/**
 * Tuş → kısayol işi; çalışmayacaksa null. `ctx`: `blocked` (bekçi), `control` (odak bir düğme ya da bağlantıda: Boşluk
 * onundur).
 *   ←/→: 10 sn geri/ileri ("step"); Shift ile 1 dk; Boşluk: duraklat/sürdür ("toggle"; basılı tutulunca yinelenmez ama
 *   yutulur: sayfa kaymaz); ?: kısayol listesi ("help"). Ctrl/Alt/Cmd ile basılan tuşlar tarayıcınındır.
 */
export function archiveShortcut(e, ctx) {
  if (ctx.blocked || e.ctrlKey || e.metaKey || e.altKey) return null;
  const k = e.key;
  if (k === "ArrowLeft" || k === "ArrowRight") {
    return { type: "step", seconds: (k === "ArrowRight" ? 1 : -1) * (e.shiftKey ? BIG_STEP_S : STEP_S) };
  }
  if (k === " ") return ctx.control ? null : e.repeat ? { type: "swallow" } : { type: "toggle" };
  if (e.repeat) return null;
  if (k === "?") return { type: "help" };
  return null;
}
