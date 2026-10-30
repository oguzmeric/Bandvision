"use client";

import Link from "next/link";
import { memo } from "react";
import { stateLines, tileSize, tileTier } from "@/lib/layoutGrid.mjs";
import { ALARM_TITLES } from "@/lib/live";
import { badge, cellBox, liveHref, stateText, type TileStatus, type ViewLayout } from "@/lib/views";
import { CAMERA_MIME } from "./CameraList";
import { isMenuKey, menuPoint } from "./ContextMenu";

const TONE = { ok: "bg-ok-600 text-white", warn: "bg-warn-700 text-white", info: "bg-black/60 text-white" } as const;
/** Nokta, kamera canlıyken: analiz rozetinin rengi, dolu */
const DOT = { ok: "bg-ok-600", warn: "bg-warn-700", info: "bg-white/85" } as const;
/**
 * Nokta, kamera canlı değilken: kamera listesindeki bağlantı rengi (gri bağlanıyor, turuncu bağlantı yok), HALKA (içi boş):
 * biçim de "canlı değil"i söyler (yalnız renge kalmaz); rozet ya da alarm rengi öne geçmez
 */
const RING = { connecting: "border-pl-ctl", error: "border-warn-700" } as const;
/*
 * Bütün ölçüler rem (layoutGrid.mjs eşikleri de rem; tarayıcının yazı boyutuyla birlikte büyürler). Yerleşimi etkilemeyen
 * çizgiler (odak çerçevesi, noktanın 1 px gölge halkası) px kalabilir.
 */
/** Ad, rozet ve alarm etiketi: tek satır, 1.25 rem */
const PILL = "rounded-[0.125rem] px-1.5 py-0.5 text-[0.6875rem] leading-4";
/** Kutu düğmesi: yalnız simge; erişilebilir adı ve ipucu yazılı adıdır */
const ACT = "grid h-6 w-6 place-items-center rounded-[0.125rem] bg-black/60 text-white hover:bg-black/80";
/** "⋯" (Kutu işlemleri): dokunmatikte seçili ya da alarmlı kutuda; yüksekliği yoğunluğa göre */
const MORE = "hidden shrink-0 place-items-center rounded-[0.125rem] bg-black/70 text-[0.9375rem] leading-none text-white";
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
 *   - çift tık (dokunmatikte seçili kutuya yeniden dokunma) tek kamerayı açar; kutunun içindeki düğmede/bağlantıda değil;
 *   - klavye: ızgara tek sekme durağıdır (`active` kutu); ok tuşları / Home / End kutudan kutuya gezdirir (`onMove`),
 *     seçim odağı izlemez: Enter/Boşluk kutuyu seçer, seçili dolu kutuda tek kamerayı açar; seçim odak ızgaradan
 *     çıkınca da kalır (kamera listesine geçip kamera seçilebilsin);
 *   - listeden kamera ya da başka kutu buraya sürüklenip bırakılır;
 *   - sağ tık / Shift+F10 / menü tuşu menüyü açar (Tek kamera, Boşalt); Delete kutuyu boşaltır; dokunmatikte seçili dolu
 *     kutuda görünen "⋯" düğmesi aynı menüyü açar (iOS'ta uzun basış sağ tık vermez).
 * Katman yoğunluğu (kutunun boyutundan ve kök yazı boyutundan; kameranın durumundan DEĞİL: durum değişince kutu yoğunluk
 * değiştirmez; layoutGrid.mjs `tileTier`): parçalar hiçbir boyutta ve yazı boyutunda üst üste binmez, kutudan taşmaz:
 *   - "full": sütun: üst şeritte ad (kısalır) ve rozet; orta alanda durum metni (ortada, sığdığı kadar en çok 2 satır,
 *     tamamı kutunun ipucunda); alt şeritte alarm etiketi, dokunmatikte "⋯", fareyle üstüne gelince ya da klavye odağında
 *     tek satır simge düğmeler (Tam ekran, Canlı sayıma git, Boşalt). Orta alan bir satır almıyorsa durum, üst şeritte
 *     addan sonra, rozetten önce noktadır;
 *   - "small": tek şerit: alarm etiketi (alarmlı kutuda) ya da ad, nokta, "⋯" (dokunmatikte seçili/alarmlı kutuda, fareyle
 *     üstüne gelince); düğmelerin işleri "⋯" ve sağ tık menüsünde (Canlı sayıma git: tek kamerada);
 *   - "tiny": yalnız köşede nokta; "micro" (köşedeki nokta kutudan taşardı): küçük nokta kutunun ortasında.
 * Nokta: kamera canlı değilken bağlantı rengi halka (kamera listesindeki gibi gri bağlanıyor, turuncu bağlantı yok;
 * dokunmatikte ipucu yok, bağlantısı kopan kutu karanlık bir görüntüyle karışmasın), canlıyken analiz rozetinin rengi dolu.
 * Alarm kırmızı çerçeve ve alarm etiketiyle görünür. Küçük kutularda ad, alarm ve durum kutunun ipucunda; noktanın ipucu ve
 * ekran okuyucu metni rozeti ve durumu söyler.
 * `filled`: şablonda bu kutuya kamera atanmış; `tile`: kameranın canlı durumu (ilk yanıt gelene dek null: "Bağlanıyor…");
 * `label`: durum gelmeden gösterilecek ad (kamera listesinden); `grid`: ızgaranın ölçülen boyutu, `rem`: ölçülen kök yazı
 * boyutu (px; yoğunluk için). İşleyiciler kutu sırasını alır (128 kutuda tek işlev).
 */
function TileOverlay({ layout, index, grid, rem, filled, tile, label, selected, active, onOpen, onAlarm, onSelect, onDropped, onEmpty,
  onMenu, onFocusTile, onMove }: {
  layout: ViewLayout; index: number; grid: { w: number; h: number } | null; rem: number; filled: boolean; tile: TileStatus | null;
  label: string | null; selected: boolean;
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
  const tier = tileTier(layout, index, grid, rem);
  const full = tier === "full";
  const size = tileSize(layout, index, grid);
  /** Normal kutunun orta alanına sığan durum satırı (ızgara ölçülmeden önce 2) */
  const lines = size ? stateLines(size.h, rem) : 2;
  /** Normal kutuda durum metni orta alana sığmıyor: durum üst şeritte nokta */
  const stateDot = full && state !== null && lines < 1;
  // Normal kutuda durum metninin tamamı; küçük kutularda gizlenen bilgiler kutunun ipucunda
  const hint = (full ? state : [name, alarmTitle, state].filter(Boolean).join(" — ")) || undefined;
  // Nokta: canlı değilken bağlantı rengi halka, canlıyken rozet rengi dolu; ipucu ve ekran okuyucu metni ikisini de söyler
  const conn = state === null ? null : tile?.state === "error" ? "error" : "connecting";
  const dotLook = conn ? `border-[0.125rem] bg-transparent ${RING[conn]}` : b ? DOT[b.tone] : null;
  const dotText = [b && (badgeTitle ? `${b.text} — ${badgeTitle}` : b.text), state].filter((t): t is string => !!t);

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
  const dot = (cls: string) => dotLook && (
    <span data-part="dot" title={dotText.join("\n")} className={`shrink-0 rounded-full ring-1 ring-black/40 ${dotLook} ${cls}`}>
      <span className="sr-only">{dotText.join(", ")}</span>
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
         // İç düğme/bağlantıdaki çift tık (ör. "⋯"ye art arda dokunmak, alarm etiketine çift tık) kutuyu açmaz
         onDoubleClick={(e) => {
           if (e.target !== e.currentTarget && (e.target as Element).closest("button, a")) return;
           if (filled) onOpen(index);
         }}
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
      <div className={`relative h-full w-full rounded-[0.1875rem] ${selected
        ? "outline outline-2 -outline-offset-2 outline-[#5aa9ff]"
        : "group-focus-visible:outline group-focus-visible:outline-2 group-focus-visible:-outline-offset-2 group-focus-visible:outline-white"}`}>
        {alarm && (
          // Yalnız kırmızı çerçeve yanıp söner (yazılar ve düğmeler okunur kalır)
          <span aria-hidden="true" className="pointer-events-none absolute inset-0 rounded-[0.1875rem] ring-[0.25rem] ring-nok-600 motion-safe:animate-pulse" />
        )}
        {full && filled && (
          // Normal kutu: sütun. Şeritlerin yüksekliği sabittir (layoutGrid.mjs FULL_CHROME_H): orta alan üstüne gelince ya da
          // odakta değişmez, durum metni şeritlerin alanına girmez
          <div className="absolute inset-1.5 flex flex-col gap-1">
            {/* Üst şerit: ad solda (kısalır), durum metni orta alana sığmıyorsa nokta, rozet sağda (en geniş hâli ad ve noktaya
                yer bırakır); aynı satırın öğeleri olduklarından üst üste binmezler */}
            <div className="flex h-5 shrink-0 items-start gap-1">
              {nameTag}
              {stateDot && dot("mt-1.5 h-2 w-2")}
              {b && (
                <span data-part="badge" title={badgeTitle}
                      className={`ml-auto shrink-0 truncate font-semibold ${stateDot ? "max-w-[calc(100%-1.75rem)]" : "max-w-[calc(100%-1rem)]"} ${PILL} ${TONE[b.tone]}`}>
                  {b.text}
                </span>
              )}
            </div>
            {/* Orta alan: durum metni ortada, sığan satır kadar (en çok 2; kısalırsa tamamı kutunun ipucunda) */}
            <div className="flex min-h-0 flex-1 items-center justify-center overflow-hidden">
              {state && !stateDot && (
                <span data-part="state"
                      className={`${lines >= 2 ? "line-clamp-2" : "line-clamp-1"} max-h-full min-w-0 break-words text-center text-[0.75rem] leading-4 text-white/90`}>
                  {state}
                </span>
              )}
            </div>
            {/* Alt şerit: alarm etiketi, dokunmatikte "⋯" ve kutu düğmeleri aynı satırın öğeleridir, biri ötekinin altında
                kalmaz. Etiket tek başınayken ortadadır; sağda "⋯" ya da kutu düğmeleri görününce (ml-auto boşluğu alır) sola
                yaslanır ve kısalır (…). Düğmeler tek satır simgedir (sarılmaz). "⋯" ile düğmeler hiçbir zaman birlikte
                görünmez */}
            <div className="flex h-6 shrink-0 items-end justify-center gap-1">
              {alarmButton("rounded-[0.125rem] px-2 py-0.5 text-[0.75rem] leading-4")}
              {(selected || alarm) && (
                // Dokunmatik (üstüne gelinemeyen) ekranda seçili kutunun işlemleri: sağ tık / uzun basış yerine. Alarmlı kutuda da
                // görünür: ona dokunmak alarmı açtığından kutu bu menüdeki "Seç" ile seçilir. Klavye odağında kutu düğmeleri
                // çıkınca gizlenir (aynı işler orada; menü Shift+F10 ile açılır); kendisi odaktayken gizlenmez
                moreButton("ml-auto h-6 min-w-9 px-2 [@media(hover:none)]:grid group-focus-visible:hidden group-has-[:focus-visible:not([aria-haspopup])]:hidden")
              )}
              {/* Fareyle üstüne gelince ya da klavye odağında: büyüt, canlı sayıma git, boşalt. Dokunmatikte yalnız klavye
                  odağında (dokunuş kutuyu seçer, ikinci dokunuş açar); odak "⋯"deyken (menü Esc ile kapandı) çıkmaz */}
              <span data-part="actions" className="ml-auto hidden shrink-0 gap-1 group-focus-visible:flex group-has-[:focus-visible:not([aria-haspopup])]:flex [@media(hover:hover)]:group-hover:flex [@media(hover:hover)]:group-focus-within:flex">
                <button type="button" aria-label="Tam ekran" title="Tam ekran" tabIndex={active ? 0 : -1}
                        onClick={(e) => { e.stopPropagation(); onOpen(index); }} className={ACT}><Icon d={ICON.open} /></button>
                <Link href={liveHref(tile?.analysis)} aria-label="Canlı sayıma git" title="Canlı sayıma git" tabIndex={active ? 0 : -1}
                      onClick={(e) => e.stopPropagation()} draggable={false} className={ACT}><Icon d={ICON.live} /></Link>
                <button type="button" aria-label="Boşalt" title="Boşalt" tabIndex={active ? 0 : -1}
                        onClick={(e) => { e.stopPropagation(); onEmpty(index); }} className={ACT}><Icon d={ICON.empty} /></button>
              </span>
            </div>
          </div>
        )}
        {tier === "small" && filled && (
          // Küçük kutu: tek şerit (alarm etiketi ya da ad, nokta, "⋯"); düğmeler yalnız "⋯" ve sağ tık menüsünde. "⋯" odaktayken
          // (menü Esc ile kapandı) fare kutudan çıksa da görünür kalır: odak sayfaya düşmez
          <div className="absolute inset-x-1 top-1 flex items-start gap-1">
            {alarm ? alarmButton(PILL) : nameTag}
            {dot("ml-auto mt-1.5 h-2 w-2")}
            {moreButton(`h-7 min-w-7 px-1 ${dotLook ? "" : "ml-auto"} ${selected || alarm ? "[@media(hover:none)]:grid" : ""} [@media(hover:hover)]:group-hover:grid focus-visible:grid`)}
          </div>
        )}
        {tier === "tiny" && dot("absolute right-1 top-1 h-2 w-2")}
      </div>
      {/* En küçük kutu: köşedeki nokta kutudan taşardı; küçük nokta (0.375 rem) kutunun tam ortasında, kutu o kadar oldukça içinde */}
      {tier === "micro" && dot("absolute left-1/2 top-1/2 h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2")}
    </div>
  );
}

export default memo(TileOverlay);
