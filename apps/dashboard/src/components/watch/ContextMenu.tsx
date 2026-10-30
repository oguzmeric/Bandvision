"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";

export interface MenuAction { label: string; onSelect: () => void; disabled?: boolean }

/** Sağ tık / Shift+F10 menüsünü açan olaydan konum: fareyle imleç, klavyeyle öğenin sol altı */
export function menuPoint(e: { clientX?: number; clientY?: number; currentTarget: EventTarget }, keyboard: boolean): { x: number; y: number } {
  if (!keyboard && e.clientX !== undefined && e.clientY !== undefined) return { x: e.clientX, y: e.clientY };
  const r = (e.currentTarget as Element).getBoundingClientRect();
  return { x: r.left, y: r.bottom };
}

/** Bağlam menüsünü açan tuş: Shift+F10 ya da menü tuşu */
export const isMenuKey = (e: React.KeyboardEvent) => (e.key === "F10" && e.shiftKey) || e.key === "ContextMenu";

/**
 * Küçük bağlam menüsü (sekme ve kutu sağ tık menüsü): `role="menu"`, açılınca ilk etkin öğeye (hepsi pasifse menüye) odak, ↑/↓/Home/End ile
 * gezinme, Esc ya da Tab ile kapanır, dışarı tıklayınca kapanır; kapanınca odak menüyü açan öğeye döner.
 * Ekrandan taşmaması için konum pencereye sığdırılır.
 */
export default function ContextMenu({ label, x, y, actions, onClose }: {
  label: string; x: number; y: number; actions: MenuAction[]; onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);
  const [pos, setPos] = useState({ left: x, top: y });

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    setPos({ left: Math.max(4, Math.min(x, window.innerWidth - r.width - 4)), top: Math.max(4, Math.min(y, window.innerHeight - r.height - 4)) });
  }, [x, y]);

  useEffect(() => {
    const el = ref.current;
    opener.current = document.activeElement;
    // İlk etkin öğeye; hepsi pasifse (ör. şablon işlemi sürerken) menünün kendisine: Esc / Tab yine kapatır
    (el?.querySelector<HTMLButtonElement>("button:not(:disabled)") ?? el)?.focus();
    const onDown = (e: PointerEvent) => { if (!el?.contains(e.target as Node)) onClose(); };
    const onResize = () => onClose();
    document.addEventListener("pointerdown", onDown, true);
    window.addEventListener("resize", onResize);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("resize", onResize);
      const back = opener.current;
      // odak menüdeydi (ya da menüyle birlikte kayboldu): menüyü açan öğeye döner; başka yere tıklandıysa orada kalır
      const at = document.activeElement;
      if (back instanceof HTMLElement && back.isConnected && (!at || at === document.body || el?.contains(at))) back.focus();
    };
  }, [onClose]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    const items = [...(ref.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? [])];
    const i = items.indexOf(document.activeElement as HTMLButtonElement);
    const go = (n: number) => { e.preventDefault(); items[(n + items.length) % items.length]?.focus(); };
    if (e.key === "ArrowDown") go(i + 1);
    else if (e.key === "ArrowUp") go(i - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(items.length - 1);
    else if (e.key === "Escape" || e.key === "Tab") { e.preventDefault(); e.stopPropagation(); onClose(); }
  };

  return (
    <div ref={ref} role="menu" aria-label={label} tabIndex={-1} onKeyDown={onKeyDown} onContextMenu={(e) => e.preventDefault()}
         style={{ left: pos.left, top: pos.top }}
         className="fixed z-[60] min-w-[170px] border border-pl-ctl bg-pl-bg py-1 text-[13px] text-pl-ink">
      {actions.map((a) => (
        <button key={a.label} type="button" role="menuitem" disabled={a.disabled}
                onClick={() => { onClose(); a.onSelect(); }}
                className="block w-full px-3 py-1 text-left hover:bg-pl-sel focus:bg-pl-sel focus:outline-none disabled:text-pl-faint">
          {a.label}
        </button>
      ))}
    </div>
  );
}
