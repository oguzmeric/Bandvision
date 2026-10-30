"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { Source } from "@/lib/live";
import { gridId, parseGrid } from "@/lib/layoutGrid.mjs";
import { EDITOR_LAYOUTS, validateGrid } from "@/lib/templateEdit.mjs";

/** Düğme yazıları (spec "Hazır düzenler"): katalog kimliği ya da N×M kimliği → görünen ad */
const LABELS: Record<string, string> = {
  "1": "1", "4": "2×2", "9": "3×3", "16": "4×4", "6": "1+5", "8": "1+7", "12": "4×3", "5x5": "5×5", "8x8": "8×8", nxm: "N×M",
};
/** Düğme simgeleri: hücreler [x, y, w, h] ızgara birimiyle (cols × rows) */
const ICONS: Record<string, { cols: number; rows: number; cells?: Array<[number, number, number, number]> }> = {
  "1": { cols: 1, rows: 1 }, "4": { cols: 2, rows: 2 }, "9": { cols: 3, rows: 3 }, "16": { cols: 4, rows: 4 },
  "6": { cols: 3, rows: 3, cells: [[0, 0, 2, 2], [2, 0, 1, 1], [2, 1, 1, 1], [0, 2, 1, 1], [1, 2, 1, 1], [2, 2, 1, 1]] },
  "8": { cols: 4, rows: 4, cells: [[0, 0, 3, 3], [3, 0, 1, 1], [3, 1, 1, 1], [3, 2, 1, 1], [0, 3, 1, 1], [1, 3, 1, 1], [2, 3, 1, 1], [3, 3, 1, 1]] },
  "12": { cols: 4, rows: 3 }, "5x5": { cols: 5, rows: 5 }, "8x8": { cols: 8, rows: 8 },
};
const DEFAULT_GRID = { rows: 6, cols: 8 };

/**
 * Hazır düzen düğmesinin erişilebilir adı ve ipucu: sütun ve satır sayısı sözle (görünen "4×3" sütun × satırdır, N×M girişi
 * ise satır × sütun: ikisi karışmasın). Hep aynı sıra: önce sütun, sonra satır.
 */
function presetName(id: string): string {
  if (id === "nxm") return "N×M: satır ve sütun sayısını aşağıya girin (en çok 128 kutu)";
  const icon = ICONS[id];
  const n = icon.cells?.length ?? icon.cols * icon.rows;
  const grid = `${icon.cols} sütun, ${icon.rows} satır`;
  return icon.cells ? `${LABELS[id]}: 1 büyük + ${n - 1} küçük kutu (${grid})` : `${LABELS[id]}: ${grid} (${n} kutu)`;
}
/** "Şablon editörü" düğmesinin DOM kimliği ("+" pasifken odak buraya) */
export const EDITOR_ID = "bv-editor";

function LayoutIcon({ id }: { id: string }) {
  const icon = ICONS[id];
  if (!icon) return null;
  const cells = icon.cells ?? Array.from({ length: icon.cols * icon.rows }, (_, i) => [i % icon.cols, Math.floor(i / icon.cols), 1, 1] as [number, number, number, number]);
  return (
    <svg viewBox={`0 0 ${icon.cols * 16} ${icon.rows * 9}`} aria-hidden="true" className="h-[18px] w-8">
      {cells.map(([x, y, w, h], i) => (
        <rect key={i} x={x * 16 + 0.75} y={y * 9 + 0.75} width={w * 16 - 1.5} height={h * 9 - 1.5}
              fill="none" stroke="currentColor" strokeWidth={id === "8x8" ? 1 : 1.5} />
      ))}
    </svg>
  );
}

/**
 * "Şablon editörü" düğmesi ve açılan menü (taslak sayfalar.html): Yeni şablon, Geri al, Yinele, Kaydet, Farklı kaydet…,
 * NVR'dan şablon; 10 düzen düğmesi ve N×M (satır × sütun, en çok 128 kutu). Menü kipsiz bir pencere (`role="dialog"`):
 * içinde sayı kutuları da olduğundan `role="menu"` değil. Esc ya da dışarı tıklama kapatır, odak düğmeye döner.
 * Düzen, N×M, Geri al, Yinele ve "Seçili kutuyu boşalt" menüyü açık bırakır (art arda denenebilsin); diğerleri kapatır.
 * Odak menünün dışına çıkınca (Tab ile ya da başka bir öğeye) menü kapanır.
 */
export default function EditorMenu({ layoutId, canUndo, canRedo, canSave, canSaveAs, canClearSelected, busy, disabled, recorders,
  onNew, onUndo, onRedo, onSave, onSaveAs, onClearSelected, onLayout, onFromRecorder }: {
  layoutId: string | null; canUndo: boolean; canRedo: boolean; canSave: boolean; canSaveAs: boolean; canClearSelected: boolean;
  busy: boolean; disabled: boolean; recorders: Source[];
  onNew: () => void; onUndo: () => void; onRedo: () => void; onSave: () => void; onSaveAs: () => void; onClearSelected: () => void;
  onLayout: (id: string) => void; onFromRecorder: (sourceId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [grid, setGrid] = useState<{ rows: string; cols: string }>({ rows: String(DEFAULT_GRID.rows), cols: String(DEFAULT_GRID.cols) });
  const wrapRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const rowsRef = useRef<HTMLInputElement>(null);
  /** Menüde en son odaklanan öğe: pasifleşirse (Geri al/Yinele bitti) odak menünün kendisine alınır */
  const lastFocused = useRef<HTMLElement | null>(null);
  const uid = useId();

  const close = (focusButton: boolean) => {
    lastFocused.current = null;
    setOpen(false);
    if (focusButton) buttonRef.current?.focus();
  };

  useEffect(() => {
    if (!open) return;
    // Açılınca N×M kutuları şablonun N×M düzeninden doldurulur (değilse son girilen kalır); ilk etkin öğeye odak
    const g = layoutId ? parseGrid(layoutId) : null;
    if (g) setGrid({ rows: String(g.rows), cols: String(g.cols) });
    wrapRef.current?.querySelector<HTMLElement>("[role=dialog] button:not(:disabled)")?.focus();
    const onDown = (e: PointerEvent) => { if (!wrapRef.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", onDown, true);
    return () => document.removeEventListener("pointerdown", onDown, true);
    // yalnız açılışta: düzen değişince kutular yeniden doldurulmaz (kullanıcının girdiği kalır)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Odaktaki öğe menü açıkken pasifleşti (ör. son Geri al): odak sayfaya (body) düşmesin, menüde kalsın (Esc, Tab çalışır)
  useLayoutEffect(() => {
    const el = lastFocused.current;
    if (!open || !el || !(el as HTMLButtonElement).disabled) return;
    const at = document.activeElement;
    if (at === el || !at || at === document.body) menuRef.current?.focus();
  });

  const rows = Number(grid.rows);
  const cols = Number(grid.cols);
  const gridCheck = grid.rows.trim() && grid.cols.trim() ? validateGrid(rows, cols) : "Satır ve sütun 1–16 arasında olmalı.";
  /** Geçersiz girişte hiçbir şey değişmez; neden kutuların altında zaten yazıyor */
  const applyGrid = () => { if (!gridCheck) onLayout(gridId(rows, cols)); };
  /** Menüyü kapatan öğe: odak önce "Şablon editörü" düğmesine döner (sayfaya düşmez; açılan ad penceresi kapanınca da
   * oraya döner), sonra işlem çalışır */
  const act = (fn: () => void) => () => { close(true); fn(); };
  const pressed = (id: string) => (id === "nxm"
    ? !!layoutId && parseGrid(layoutId) !== null && !EDITOR_LAYOUTS.includes(layoutId)
    : layoutId === id);
  const item = "block w-full px-3 py-1 text-left hover:bg-pl-sel focus-visible:bg-pl-sel focus-visible:outline-none disabled:text-pl-faint disabled:hover:bg-transparent";

  return (
    <div ref={wrapRef} className="relative"
         onKeyDown={(e) => { if (open && e.key === "Escape") { e.stopPropagation(); close(true); } }}
         onFocus={(e) => { if (menuRef.current?.contains(e.target) && e.target !== menuRef.current) lastFocused.current = e.target; }}
         // Odak dışarıdaki bir öğeye geçti: kapanır (odak kaybolduysa, ör. düğme pasifleşti, açık kalır)
         onBlur={(e) => { if (open && e.relatedTarget instanceof Node && !e.currentTarget.contains(e.relatedTarget)) setOpen(false); }}>
      <button ref={buttonRef} id={EDITOR_ID} type="button" aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? `${uid}-menu` : undefined}
              disabled={disabled} onClick={() => setOpen((o) => !o)} className="pl-btn">
        Şablon editörü <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div ref={menuRef} id={`${uid}-menu`} role="dialog" aria-label="Şablon editörü" tabIndex={-1}
             className="absolute left-0 top-full z-40 mt-1 w-[300px] max-w-[calc(100vw-32px)] border border-pl-ctl bg-pl-bg py-1 text-[13px] text-pl-ink">
          <button type="button" className={item} disabled={busy} onClick={act(onNew)}>Yeni şablon</button>
          <button type="button" className={item} disabled={!canUndo} onClick={onUndo}>Geri al <span className="float-right text-pl-faint">Ctrl+Z</span></button>
          <button type="button" className={item} disabled={!canRedo} onClick={onRedo}>Yinele <span className="float-right text-pl-faint">Ctrl+Y</span></button>
          <button type="button" className={item} disabled={!canSave || busy} onClick={act(onSave)}>Kaydet</button>
          <button type="button" className={item} disabled={!canSaveAs || busy} onClick={act(onSaveAs)}>Farklı kaydet…</button>
          <button type="button" className={item} disabled={!canClearSelected} onClick={onClearSelected}>Seçili kutuyu boşalt</button>
          {recorders.length > 0 && (
            <label className="flex items-center gap-2 px-3 py-1">
              <span className="shrink-0">NVR&apos;dan şablon</span>
              <select aria-label="NVR'dan şablon" value="" disabled={busy}
                      onChange={(e) => { const id = e.target.value; if (id) { close(true); onFromRecorder(id); } }}
                      className="pl-input min-w-0 flex-1">
                <option value="">Kayıt cihazı seçin…</option>
                {recorders.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            </label>
          )}
          <div className="my-1 border-t border-pl-line-soft" />
          <p id={`${uid}-layouts`} className="px-3 py-0.5 text-pl-muted">Düzenler:</p>
          <div role="group" aria-labelledby={`${uid}-layouts`} className="grid grid-cols-5 gap-1.5 px-3 py-1.5">
            {EDITOR_LAYOUTS.map((id) => (
              <button key={id} type="button" aria-pressed={pressed(id)} disabled={!layoutId}
                      aria-label={presetName(id)} title={presetName(id)}
                      onClick={() => (id === "nxm" ? rowsRef.current?.focus() : onLayout(id))}
                      className={`grid h-11 place-items-center border text-[11px] leading-none disabled:opacity-50 ${pressed(id)
                        ? "border-pl-sel-line bg-pl-sel font-semibold" : "border-pl-ctl bg-pl-side hover:bg-pl-head"}`}>
                {id === "nxm" ? <span className="text-[12px] font-bold">N×M</span> : <><LayoutIcon id={id} />{LABELS[id]}</>}
              </button>
            ))}
          </div>
          <div className="my-1 border-t border-pl-line-soft" />
          <form className="flex flex-wrap items-center gap-1.5 px-3 py-1" onSubmit={(e) => { e.preventDefault(); applyGrid(); }}>
            <span>N×M:</span>
            <label htmlFor={`${uid}-rows`} className="flex items-center gap-1">Satır</label>
            <input ref={rowsRef} id={`${uid}-rows`} type="number" inputMode="numeric" min={1} max={16} value={grid.rows}
                   disabled={!layoutId} onChange={(e) => setGrid((g) => ({ ...g, rows: e.target.value }))} className="pl-input w-14" />
            <span aria-hidden="true">×</span>
            <label htmlFor={`${uid}-cols`} className="flex items-center gap-1">Sütun</label>
            <input id={`${uid}-cols`} type="number" inputMode="numeric" min={1} max={16} value={grid.cols}
                   disabled={!layoutId} onChange={(e) => setGrid((g) => ({ ...g, cols: e.target.value }))} className="pl-input w-14" />
            <button type="submit" disabled={!layoutId} className="pl-btn">Uygula</button>
            <p aria-live="polite" data-testid="grid-check" className={`w-full ${gridCheck ? "text-nok-ink" : "text-pl-muted"}`}>
              {gridCheck ?? `= ${rows} satır × ${cols} sütun = ${rows * cols} kutu (en çok 128)`}
            </p>
          </form>
        </div>
      )}
    </div>
  );
}
