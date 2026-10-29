"use client";

import { useEffect, useRef } from "react";
import { isMenuKey, menuPoint } from "./ContextMenu";

export interface TabItem { id: string; name: string; unsaved: boolean }

/** Sekmenin DOM kimliği (ızgara bölmesi `aria-labelledby` ile buna bağlanır) */
export const tabDomId = (id: string) => `bv-tab-${id}`;
export const PANEL_ID = "bv-watch-panel";
/** "+" (Yeni şablon) düğmesinin DOM kimliği (sekme kalmayınca odak buraya) */
export const ADD_ID = "bv-tab-add";

/**
 * Şablon sekmeleri (TRASSIR gibi üstte yan yana; taslak duzen.html): tıklayınca o şablona geçilir, sonda "+" yeni şablon,
 * sağ tık (ya da Shift+F10 / menü tuşu, ya da "⋯" düğmesi) Yeniden adlandır / Kopyala / Sil menüsünü açar.
 * Klavye: ←/→/Home/End sekmeler arasında odak gezdirir, Enter/Boşluk seçer (seçim kaydedilmemiş değişiklikte soru
 * çıkarabildiği için otomatik değil). Dar ekranda çubuk yatay kaydırılır; seçili sekme görünür alana kaydırılır.
 */
export default function TemplateTabs({ tabs, current, onSelect, onAdd, onMenu, addDisabled }: {
  tabs: TabItem[]; current: string | null;
  onSelect: (id: string) => void; onAdd: () => void; onMenu: (id: string, x: number, y: number) => void; addDisabled: boolean;
}) {
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!current) return;
    document.getElementById(tabDomId(current))?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [current]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>, id: string) => {
    if (isMenuKey(e)) { e.preventDefault(); const p = menuPoint(e, true); onMenu(id, p.x, p.y); return; }
    const all = [...(listRef.current?.querySelectorAll<HTMLButtonElement>("[role=tab]") ?? [])];
    const i = all.indexOf(e.currentTarget);
    const to = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? all.length - 1 : null;
    if (to === null || !all.length) return;
    e.preventDefault();
    all[(to + all.length) % all.length].focus();
  };
  const currentTab = tabs.find((t) => t.id === current);

  return (
    <div className="flex min-w-0 items-stretch border border-pl-line bg-pl-head">
      <div className="flex min-w-0 flex-1 overflow-x-auto" data-testid="watch-tabs">
        <div ref={listRef} role="tablist" aria-label="Şablonlar" className="flex">
          {tabs.map((t) => {
            const on = t.id === current;
            return (
              <button key={t.id} id={tabDomId(t.id)} type="button" role="tab" aria-selected={on}
                      aria-controls={on ? PANEL_ID : undefined} tabIndex={on || (!currentTab && t === tabs[0]) ? 0 : -1}
                      onClick={() => onSelect(t.id)} onKeyDown={(e) => onKeyDown(e, t.id)}
                      onContextMenu={(e) => { e.preventDefault(); const p = menuPoint(e, false); onMenu(t.id, p.x, p.y); }}
                      className={`shrink-0 whitespace-nowrap border-r border-pl-line px-4 py-1.5 text-[13px] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-pl-accent ${on
                        ? "bg-pl-accent font-semibold text-white focus-visible:outline-white"
                        : "text-pl-ink hover:bg-pl-sel"}`}>
                {t.name}
                {t.unsaved && <span title="Kaydedilmedi"> *<span className="sr-only"> (kaydedilmedi)</span></span>}
              </button>
            );
          })}
        </div>
        <button type="button" id={ADD_ID} aria-label="Yeni şablon" title="Yeni şablon" onClick={onAdd} disabled={addDisabled}
                className="shrink-0 px-3 text-[15px] font-bold leading-none text-pl-accent hover:bg-pl-sel disabled:opacity-50">+</button>
      </div>
      {currentTab && (
        <button type="button" aria-label={`Şablon işlemleri: ${currentTab.name}`} title="Şablon işlemleri" aria-haspopup="menu"
                onClick={(e) => { const p = menuPoint(e, true); onMenu(currentTab.id, p.x, p.y); }}
                className="shrink-0 border-l border-pl-line px-2.5 text-pl-muted hover:bg-pl-sel">⋯</button>
      )}
    </div>
  );
}
