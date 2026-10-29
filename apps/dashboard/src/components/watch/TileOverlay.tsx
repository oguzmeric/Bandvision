"use client";

import Link from "next/link";
import { memo } from "react";
import { ALARM_TITLES } from "@/lib/live";
import { badge, cellBox, liveHref, stateText, type TileStatus, type ViewLayout } from "@/lib/views";
import { CAMERA_MIME } from "./CameraList";
import { isMenuKey, menuPoint } from "./ContextMenu";

const TONE = { ok: "bg-ok-600 text-white", warn: "bg-warn-700 text-white", info: "bg-black/60 text-white" } as const;
/** Kutudan kutuya sürükleme (yer değiştirme): kutu sırası */
export const TILE_MIME = "application/x-bv-tile";

/** Dokunmatik (üstüne gelinemeyen) cihaz: seçili kutuya yeniden dokunmak tek kamerayı açar (çift tık yerine) */
function touchOnly(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(hover: none)").matches;
}

/** Kutuya bırakılan: başka kutu (yer değiştir) ya da listeden kamera (`{ ref, name }` JSON) */
export type TileDrop = { kind: "tile"; from: number } | { kind: "camera"; payload: string };

function dropOf(dt: DataTransfer): TileDrop | null {
  const from = dt.getData(TILE_MIME);
  if (from !== "") return { kind: "tile", from: Number(from) };
  const payload = dt.getData(CAMERA_MIME);
  return payload ? { kind: "camera", payload } : null;
}
const accepts = (dt: DataTransfer) => dt.types.includes(TILE_MIME) || dt.types.includes(CAMERA_MIME);

/** Klavyeyle kutular arası gezinme: yön ya da ilk/son kutu */
export type TileMove = "up" | "down" | "left" | "right" | "home" | "end";
const MOVES: Record<string, TileMove> = {
  ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right", Home: "home", End: "end",
};

/**
 * Birleşik görüntünün üstünde tek kutunun HTML katmanı: ad, durum, rozet, alarm çerçevesi; ayrıca düzenleme:
 *   - tıklama kutuyu seçer (sonra listeden tıklanan kamera buraya gelir); alarmlı kutuya tıklamak alarmı açar;
 *   - çift tık (dokunmatikte seçili kutuya yeniden dokunma) tek kamerayı açar;
 *   - klavye: ızgara tek sekme durağıdır (`active` kutu); ok tuşları / Home / End kutudan kutuya gezdirir (`onMove`),
 *     seçim odağı izlemez: Enter/Boşluk kutuyu seçer, seçili dolu kutuda tek kamerayı açar; seçim odak ızgaradan
 *     çıkınca da kalır (kamera listesine geçip kamera seçilebilsin);
 *   - listeden kamera ya da başka kutu buraya sürüklenip bırakılır;
 *   - sağ tık / Shift+F10 / menü tuşu menüyü açar (Tek kamera, Boşalt); Delete kutuyu boşaltır; dokunmatikte seçili dolu
 *     kutuda görünen "⋯" düğmesi aynı menüyü açar (iOS'ta uzun basış sağ tık vermez).
 * `filled`: şablonda bu kutuya kamera atanmış; `tile`: kameranın canlı durumu (ilk yanıt gelene dek null: "Bağlanıyor…");
 * `label`: durum gelmeden gösterilecek ad (kamera listesinden). İşleyiciler kutu sırasını alır (128 kutuda tek işlev).
 */
function TileOverlay({ layout, index, filled, tile, label, selected, active, onOpen, onAlarm, onSelect, onDropped, onEmpty, onMenu,
  onFocusTile, onMove }: {
  layout: ViewLayout; index: number; filled: boolean; tile: TileStatus | null; label: string | null; selected: boolean;
  /** Izgaranın tek sekme durağı bu kutu mu (gezici sekme sırası) */
  active: boolean;
  onOpen: (i: number) => void; onAlarm: (alarmId: string) => void; onSelect: (i: number) => void;
  onDropped: (i: number, d: TileDrop) => void; onEmpty: (i: number) => void; onMenu: (i: number, x: number, y: number) => void;
  onFocusTile: (i: number) => void; onMove: (i: number, to: TileMove) => void;
}) {
  const alarm = tile?.analysis?.alarm ?? null;
  const state = !filled ? null : tile ? (tile.state === "live" ? null : stateText(tile)) : "Bağlanıyor…";
  const name = tile?.name ?? (filled ? label : null);
  return (
    <div data-testid="watch-tile" data-empty={filled ? undefined : "true"} data-alarm={alarm ? "true" : undefined}
         data-selected={selected ? "true" : undefined}
         style={cellBox(layout, index)}
         className="group absolute p-1 outline-none"
         draggable={filled}
         onDragStart={(e) => { if (e.target !== e.currentTarget) return; e.dataTransfer.setData(TILE_MIME, String(index)); e.dataTransfer.effectAllowed = "move"; }}
         onDragOver={(e) => { if (accepts(e.dataTransfer)) e.preventDefault(); }}
         onDrop={(e) => { const d = dropOf(e.dataTransfer); if (!d) return; e.preventDefault(); onDropped(index, d); }}
         onDoubleClick={() => filled && onOpen(index)}
         onClick={() => {
           if (alarm) { onAlarm(alarm.id); return; }
           if (selected && filled && touchOnly()) onOpen(index);
           else onSelect(index);
         }}
         // Odak seçimi değiştirmez; yalnız gezici sekme durağı bu kutuya geçer
         onFocus={(e) => { if (e.target === e.currentTarget) onFocusTile(index); }}
         onContextMenu={(e) => { if (!filled) return; e.preventDefault(); const p = menuPoint(e, false); onMenu(index, p.x, p.y); }}
         role="group" tabIndex={active ? 0 : -1}
         aria-label={`${filled ? (name ?? "Kamera") : "Boş kutu"}${selected ? " (seçili)" : ""}`}
         onKeyDown={(e) => {
           if (e.target !== e.currentTarget) return;                     // iç düğme/bağlantıdaki tuş kutuya gitmez
           const move = MOVES[e.key];
           if (move) { e.preventDefault(); onMove(index, move); }
           else if (e.key === "Enter" || e.key === " ") {
             e.preventDefault();
             if (!selected) onSelect(index);
             else if (filled) onOpen(index);
           } else if (!filled) return;
           else if (isMenuKey(e)) { e.preventDefault(); const p = menuPoint(e, true); onMenu(index, p.x, p.y); }
           else if (e.key === "Delete") { e.preventDefault(); onEmpty(index); }
         }}>
      <div className={`relative h-full w-full rounded-[3px] ${selected
        ? "outline outline-2 -outline-offset-2 outline-[#5aa9ff]"
        : "group-focus-visible:outline group-focus-visible:outline-2 group-focus-visible:-outline-offset-2 group-focus-visible:outline-white"}`}>
        {alarm && (
          // Yalnız kırmızı çerçeve yanıp söner (yazılar ve düğmeler okunur kalır)
          <span aria-hidden="true" className="pointer-events-none absolute inset-0 rounded-[3px] ring-4 ring-nok-600 motion-safe:animate-pulse" />
        )}
        {name && (
          <span className="absolute left-1.5 top-1.5 max-w-[70%] truncate rounded-[2px] bg-black/55 px-1.5 py-0.5 text-[11px] font-medium text-white">
            {name}
          </span>
        )}
        {tile?.analysis && (
          <span className={`absolute right-1.5 top-1.5 rounded-[2px] px-1.5 py-0.5 text-[11px] font-semibold ${TONE[badge(tile.analysis).tone]}`}
                title={tile.analysis.reason ?? tile.analysis.name}>
            {badge(tile.analysis).text}
          </span>
        )}
        {alarm && (
          <button type="button" aria-label={`Alarmı aç: ${ALARM_TITLES[alarm.type]}`}
                  tabIndex={active ? 0 : -1} onClick={(e) => { e.stopPropagation(); onAlarm(alarm.id); }}
                  className="absolute inset-x-0 bottom-2 mx-auto w-max rounded-[2px] bg-nok-600 px-2 py-1 text-[12px] font-bold text-white">
            {ALARM_TITLES[alarm.type]}
          </button>
        )}
        {state && (
          <span className="pointer-events-none absolute inset-0 grid place-items-center p-2 text-center text-[12px] text-white/90">
            {state}
          </span>
        )}
        {filled && selected && (
          // Dokunmatik (üstüne gelinemeyen) ekranda seçili kutunun işlemleri: sağ tık / uzun basış yerine
          <button type="button" aria-label="Kutu işlemleri" aria-haspopup="menu" tabIndex={-1}
                  onClick={(e) => { e.stopPropagation(); const p = menuPoint(e, true); onMenu(index, p.x, p.y); }}
                  className="absolute bottom-1.5 left-1.5 hidden h-7 min-w-9 place-items-center rounded-[2px] bg-black/70 px-2 text-[15px] leading-none text-white [@media(hover:none)]:grid">⋯</button>
        )}
        {filled && (
          // Fareyle üstüne gelince ya da klavye odağında küçük düğmeler: büyüt, canlı sayıma git, boşalt. Dokunmatikte
          // gösterilmez (dokunuş kutuyu seçer, ikinci dokunuş açar; küçük kutuda düğmeler dokunuşun altına girmesin)
          <span className="absolute bottom-1.5 right-1.5 hidden max-w-[calc(100%-12px)] flex-wrap justify-end gap-1 group-focus-visible:flex group-has-[:focus-visible]:flex [@media(hover:hover)]:group-hover:flex [@media(hover:hover)]:group-focus-within:flex">
            <button type="button" tabIndex={active ? 0 : -1} onClick={(e) => { e.stopPropagation(); onOpen(index); }}
                    className="rounded-[2px] bg-black/60 px-1.5 py-0.5 text-[11px] text-white">Tam ekran</button>
            <Link href={liveHref(tile?.analysis)} tabIndex={active ? 0 : -1} onClick={(e) => e.stopPropagation()} draggable={false}
                  className="rounded-[2px] bg-black/60 px-1.5 py-0.5 text-[11px] text-white">Canlı sayıma git</Link>
            <button type="button" tabIndex={active ? 0 : -1} onClick={(e) => { e.stopPropagation(); onEmpty(index); }}
                    className="rounded-[2px] bg-black/60 px-1.5 py-0.5 text-[11px] text-white">Boşalt</button>
          </span>
        )}
      </div>
    </div>
  );
}

export default memo(TileOverlay);
