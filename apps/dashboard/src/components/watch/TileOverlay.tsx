"use client";

import Link from "next/link";
import { memo } from "react";
import type { TileTier } from "@/lib/layoutGrid.mjs";
import { ALARM_TITLES } from "@/lib/live";
import { badge, cellBox, liveHref, stateText, type TileStatus, type ViewLayout } from "@/lib/views";
import { CAMERA_MIME } from "./CameraList";
import { isMenuKey, menuPoint } from "./ContextMenu";

const TONE = { ok: "bg-ok-600 text-white", warn: "bg-warn-700 text-white", info: "bg-black/60 text-white" } as const;
/** Küçük kutuda rozetin yerine renkli nokta (ipucu ve ekran okuyucu metni rozetin kendisi) */
const DOT = { ok: "bg-ok-600", warn: "bg-warn-700", info: "bg-white/85" } as const;
/** Ad, rozet ve alarm etiketi: tek satır, 20 px */
const PILL = "rounded-[2px] px-1.5 py-0.5 text-[11px] leading-4";
/** Kutu düğmesi: yalnız simge; erişilebilir adı ve ipucu yazılı adıdır */
const ACT = "grid h-6 w-6 place-items-center rounded-[2px] bg-black/60 text-white hover:bg-black/80";
/** "⋯" (Kutu işlemleri): dokunmatikte seçili ya da alarmlı kutuda */
const MORE = "hidden h-7 shrink-0 place-items-center rounded-[2px] bg-black/70 text-[15px] leading-none text-white";
const ICON = {
  open: "M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5",
  live: "M4 20h16M7 16v-4M12 16V8M17 16v-7",
  empty: "M6 6l12 12M18 6 6 18",
} as const;

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round"
         className="h-3.5 w-3.5" aria-hidden="true"><path d={d} /></svg>
  );
}

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
 * Katman yoğunluğu (`tier`, kutunun boyutundan; layoutGrid.mjs `tileTier`): parçalar hiçbir boyutta üst üste binmez,
 * kutudan taşmaz:
 *   - "full": üst şeritte ad (kısalır) ve rozet; alt şeritte alarm etiketi, dokunmatikte "⋯", fareyle üstüne gelince ya da
 *     klavye odağında tek satır simge düğmeler (Tam ekran, Canlı sayıma git, Boşalt);
 *   - "small": tek şerit: alarm etiketi (alarmlı kutuda) ya da ad, rozet noktası, "⋯" (dokunmatikte seçili/alarmlı kutuda,
 *     fareyle üstüne gelince); düğmelerin işleri "⋯" ve sağ tık menüsünde (Canlı sayıma git: tek kamerada);
 *   - "tiny": yalnız rozet noktası. Küçük kutuda ad, alarm ve durum kutunun ipucunda (durum ekran okuyucuda da).
 * `filled`: şablonda bu kutuya kamera atanmış; `tile`: kameranın canlı durumu (ilk yanıt gelene dek null: "Bağlanıyor…");
 * `label`: durum gelmeden gösterilecek ad (kamera listesinden). İşleyiciler kutu sırasını alır (128 kutuda tek işlev).
 */
function TileOverlay({ layout, index, tier, filled, tile, label, selected, active, onOpen, onAlarm, onSelect, onDropped, onEmpty,
  onMenu, onFocusTile, onMove }: {
  layout: ViewLayout; index: number; tier: TileTier; filled: boolean; tile: TileStatus | null; label: string | null;
  selected: boolean;
  /** Izgaranın tek sekme durağı bu kutu mu (gezici sekme sırası) */
  active: boolean;
  onOpen: (i: number) => void; onAlarm: (alarmId: string) => void; onSelect: (i: number) => void;
  onDropped: (i: number, d: TileDrop) => void; onEmpty: (i: number) => void; onMenu: (i: number, x: number, y: number) => void;
  onFocusTile: (i: number) => void; onMove: (i: number, to: TileMove) => void;
}) {
  const alarm = tile?.analysis?.alarm ?? null;
  const alarmTitle = alarm ? ALARM_TITLES[alarm.type] : null;
  const state = !filled ? null : tile ? (tile.state === "live" ? null : stateText(tile)) : "Bağlanıyor…";
  const name = tile?.name ?? (filled ? label : null);
  const b = tile?.analysis ? badge(tile.analysis) : null;
  const badgeTitle = tile?.analysis ? tile.analysis.reason ?? tile.analysis.name : undefined;
  const full = tier === "full";
  // Küçük kutuda gizlenen bilgiler kutunun ipucunda
  const hint = full ? undefined : [name, alarmTitle, state].filter(Boolean).join(" — ") || undefined;

  const alarmButton = (cls: string) => alarm && (
    <button type="button" data-part="alarm" aria-label={`Alarmı aç: ${alarmTitle}`}
            tabIndex={active ? 0 : -1} onClick={(e) => { e.stopPropagation(); onAlarm(alarm.id); }}
            className={`min-w-0 truncate bg-nok-600 font-bold text-white ${cls}`}>
      {alarmTitle}
    </button>
  );
  const moreButton = (cls: string) => (
    <button type="button" data-part="more" aria-label="Kutu işlemleri" aria-haspopup="menu" tabIndex={-1}
            onClick={(e) => { e.stopPropagation(); const p = menuPoint(e, true); onMenu(index, p.x, p.y); }}
            className={`${MORE} ${cls}`}>⋯</button>
  );
  const nameTag = name && (
    <span data-part="name" title={name} className={`min-w-0 truncate bg-black/55 font-medium text-white ${PILL}`}>{name}</span>
  );
  const dot = (cls: string) => b && (
    <span data-part="badge" title={badgeTitle ? `${b.text} — ${badgeTitle}` : b.text}
          className={`h-2 w-2 shrink-0 rounded-full ring-1 ring-black/40 ${DOT[b.tone]} ${cls}`}>
      <span className="sr-only">{b.text}</span>
    </span>
  );

  return (
    <div data-testid="watch-tile" data-empty={filled ? undefined : "true"} data-alarm={alarm ? "true" : undefined}
         data-selected={selected ? "true" : undefined} data-tier={tier} title={hint}
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
        {state && (
          // Küçük kutuda yazı sığmaz: durum kutunun ipucunda ve ekran okuyucuda
          <span className={full ? "pointer-events-none absolute inset-0 grid place-items-center p-2 text-center text-[12px] text-white/90" : "sr-only"}>
            {state}
          </span>
        )}
        {full && (name || b) && (
          // Üst şerit: ad solda (kısalır), rozet sağda; aynı satırın öğeleri olduklarından üst üste binmezler
          <div className="absolute inset-x-1.5 top-1.5 flex items-start gap-1">
            {nameTag}
            {b && (
              <span data-part="badge" title={badgeTitle}
                    className={`ml-auto max-w-[calc(100%-1rem)] shrink-0 truncate font-semibold ${PILL} ${TONE[b.tone]}`}>
                {b.text}
              </span>
            )}
          </div>
        )}
        {full && filled && (
          // Alt şerit: alarm etiketi, dokunmatikte "⋯" ve kutu düğmeleri aynı satırın öğeleridir, biri ötekinin altında
          // kalmaz. Etiket tek başınayken ortadadır; sağda "⋯" ya da kutu düğmeleri görününce (ml-auto boşluğu alır) sola
          // yaslanır ve kısalır (…). Düğmeler tek satır simgedir (sarılmaz), üst şeride uzanmaz.
          <div className="absolute inset-x-1.5 bottom-1.5 flex items-end justify-center gap-1">
            {alarmButton("rounded-[2px] px-2 py-0.5 text-[12px] leading-4")}
            {(selected || alarm) && (
              // Dokunmatik (üstüne gelinemeyen) ekranda seçili kutunun işlemleri: sağ tık / uzun basış yerine. Alarmlı kutuda da
              // görünür: ona dokunmak alarmı açtığından kutu bu menüdeki "Seç" ile seçilir. Klavye odağında kutu düğmeleri
              // çıkınca gizlenir (aynı işler orada; menü Shift+F10 ile açılır); kendisi odaktayken gizlenmez
              moreButton("ml-auto min-w-9 px-2 [@media(hover:none)]:grid group-focus-visible:hidden group-has-[:focus-visible:not([aria-haspopup])]:hidden")
            )}
            {/* Fareyle üstüne gelince ya da klavye odağında: büyüt, canlı sayıma git, boşalt. Dokunmatikte yalnız klavye
                odağında (dokunuş kutuyu seçer, ikinci dokunuş açar; küçük kutuda düğmeler dokunuşun altına girmesin) */}
            <span data-part="actions" className="ml-auto hidden shrink-0 gap-1 group-focus-visible:flex group-has-[:focus-visible]:flex [@media(hover:hover)]:group-hover:flex [@media(hover:hover)]:group-focus-within:flex">
              <button type="button" aria-label="Tam ekran" title="Tam ekran" tabIndex={active ? 0 : -1}
                      onClick={(e) => { e.stopPropagation(); onOpen(index); }} className={ACT}><Icon d={ICON.open} /></button>
              <Link href={liveHref(tile?.analysis)} aria-label="Canlı sayıma git" title="Canlı sayıma git" tabIndex={active ? 0 : -1}
                    onClick={(e) => e.stopPropagation()} draggable={false} className={ACT}><Icon d={ICON.live} /></Link>
              <button type="button" aria-label="Boşalt" title="Boşalt" tabIndex={active ? 0 : -1}
                      onClick={(e) => { e.stopPropagation(); onEmpty(index); }} className={ACT}><Icon d={ICON.empty} /></button>
            </span>
          </div>
        )}
        {tier === "small" && filled && (
          // Küçük kutu: tek şerit (alarm etiketi ya da ad, rozet noktası, "⋯"); düğmeler yalnız "⋯" ve sağ tık menüsünde
          <div className="absolute inset-x-1 top-1 flex items-start gap-1">
            {alarm ? alarmButton(`${PILL}`) : nameTag}
            {dot("ml-auto mt-1.5")}
            {moreButton(`min-w-7 px-1 ${b ? "" : "ml-auto"} ${selected || alarm ? "[@media(hover:none)]:grid" : ""} [@media(hover:hover)]:group-hover:grid`)}
          </div>
        )}
        {tier === "tiny" && dot("absolute right-1 top-1")}
      </div>
    </div>
  );
}

export default memo(TileOverlay);
