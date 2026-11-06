"use client";

import { useEffect, useRef } from "react";

/** Canlı izleme kısayolları (watchKeys.mjs `shortcutFor` ile aynı) */
const KEYS: Array<[string, string]> = [
  ["F", "Fareyle üstüne gelinen ya da son tıklanan kutuyu büyütür; tek kamerada ızgaraya döner"],
  ["Esc", "Tek kameradan ızgaraya döner, sıralı gösterimi durdurur"],
  ["Boşluk", "Sıralı gösterimi duraklatır ya da sürdürür"],
  ["← / →", "Tek kamerada önceki ya da sonraki kamera"],
  ["1–9", "O sıradaki şablon sekmesine geçer"],
  ["?", "Bu listeyi açar ya da kapatır"],
];

/**
 * Klavye kısayolları listesi: kipli `<dialog>`; Esc, "?" ya da Kapat kapatır, odak açan öğeye döner.
 */
export default function ShortcutHelp({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const d = ref.current;
    const back = document.activeElement;
    if (d && !d.open) d.showModal();
    return () => { if (back instanceof HTMLElement && back.isConnected) back.focus(); };
  }, []);

  return (
    <dialog ref={ref} aria-labelledby="bv-shortcuts-title" onCancel={(e) => { e.preventDefault(); onClose(); }}
            onKeyDown={(e) => { if (e.key === "?") { e.preventDefault(); onClose(); } }}
            className="m-auto w-[min(440px,calc(100vw-32px))] border border-pl-ctl bg-pl-bg p-0 text-[13px] text-pl-ink backdrop:bg-black/30">
      <h2 id="bv-shortcuts-title" className="border-b border-pl-line bg-pl-head px-3 py-1.5 font-semibold">Klavye kısayolları</h2>
      <div className="grid gap-2 p-3">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5">
          {KEYS.map(([k, text]) => (
            <div key={k} className="contents">
              <dt><kbd className="inline-block min-w-8 border border-pl-ctl bg-pl-side px-1.5 text-center font-semibold">{k}</kbd></dt>
              <dd>{text}</dd>
            </div>
          ))}
        </dl>
        <p className="text-pl-muted">Yazı kutusundayken ya da bir pencere veya menü açıkken kısayollar çalışmaz.</p>
        <div className="flex justify-end">
          <button type="button" autoFocus onClick={onClose} className="pl-btn">Kapat</button>
        </div>
      </div>
    </dialog>
  );
}
