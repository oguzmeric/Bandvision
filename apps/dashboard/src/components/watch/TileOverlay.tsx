"use client";

import Link from "next/link";
import { ALARM_TITLES } from "@/lib/live";
import { badge, cellBox, liveHref, stateText, type TileStatus, type ViewLayout } from "@/lib/views";

const TONE = { ok: "bg-ok-600 text-white", warn: "bg-warn-700 text-white", info: "bg-black/60 text-white" } as const;

/** Dokunmatik (üstüne gelinemeyen) cihaz: kutuya dokunmak tek kamerayı açar (hover düğmelerine ulaşılamaz) */
function touchOnly(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(hover: none)").matches;
}

/**
 * Birleşik görüntünün üstünde tek kutunun HTML katmanı: ad, durum, rozet, alarm çerçevesi.
 * `filled`: şablonda bu kutuya kamera atanmış (boşluk/açılabilirlik şablondan gelir); `tile`: sunucunun canlı durumu,
 * ilk yanıt gelene dek ya da kutu şablonla eşleşmiyorsa null (kutu "Bağlanıyor…" gösterir).
 */
export default function TileOverlay({ layout, index, filled, tile, onOpen, onAlarm }: {
  layout: ViewLayout; index: number; filled: boolean; tile: TileStatus | null;
  onOpen: () => void; onAlarm: (alarmId: string) => void;
}) {
  const alarm = tile?.analysis?.alarm ?? null;
  const state = !filled ? null : tile ? (tile.state === "live" ? null : stateText(tile)) : "Bağlanıyor…";
  return (
    <div data-testid="watch-tile" data-empty={filled ? undefined : "true"} data-alarm={alarm ? "true" : undefined}
         style={cellBox(layout, index)}
         className="group absolute p-1"
         onDoubleClick={() => filled && onOpen()}
         onClick={() => {
           if (alarm) onAlarm(alarm.id);
           else if (filled && touchOnly()) onOpen();
         }}
         role={filled ? "group" : "img"} tabIndex={filled ? 0 : undefined}
         aria-label={filled ? (tile?.name ?? "Kamera") : "Boş kutu"}
         onKeyDown={(e) => {
           if (!filled || e.target !== e.currentTarget) return;       // iç düğme/bağlantıdaki tuş kutuyu açmaz
           if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(); }
         }}>
      <div className="relative h-full w-full rounded-[6px]">
        {alarm && (
          // Yalnız kırmızı çerçeve yanıp söner (yazılar ve düğmeler okunur kalır)
          <span aria-hidden="true" className="pointer-events-none absolute inset-0 rounded-[6px] ring-4 ring-nok-600 motion-safe:animate-pulse" />
        )}
        {tile && (
          <span className="absolute left-1.5 top-1.5 max-w-[70%] truncate rounded-md bg-black/55 px-1.5 py-0.5 text-[11px] font-medium text-white">
            {tile.name}
          </span>
        )}
        {tile?.analysis && (
          <span className={`absolute right-1.5 top-1.5 rounded-md px-1.5 py-0.5 text-[11px] font-semibold ${TONE[badge(tile.analysis).tone]}`}
                title={tile.analysis.reason ?? tile.analysis.name}>
            {badge(tile.analysis).text}
          </span>
        )}
        {alarm && (
          <button type="button" aria-label={`Alarmı aç: ${ALARM_TITLES[alarm.type]}`}
                  onClick={(e) => { e.stopPropagation(); onAlarm(alarm.id); }}
                  className="absolute inset-x-0 bottom-2 mx-auto w-max rounded-md bg-nok-600 px-2 py-1 text-[12px] font-bold text-white">
            {ALARM_TITLES[alarm.type]}
          </button>
        )}
        {state && (
          <span className="pointer-events-none absolute inset-0 grid place-items-center p-2 text-center text-[12px] text-white/90">
            {state}
          </span>
        )}
        {filled && (
          // Üstüne gelince (klavye/odakla da) küçük düğmeler: büyüt, canlı sayıma git
          <span className="absolute bottom-1.5 right-1.5 hidden gap-1 group-hover:flex group-focus-within:flex">
            <button type="button" onClick={(e) => { e.stopPropagation(); onOpen(); }}
                    className="rounded-md bg-black/60 px-1.5 py-0.5 text-[11px] text-white">Tam ekran</button>
            <Link href={liveHref(tile?.analysis)} onClick={(e) => e.stopPropagation()}
                  className="rounded-md bg-black/60 px-1.5 py-0.5 text-[11px] text-white">Canlı sayıma git</Link>
          </span>
        )}
      </div>
    </div>
  );
}
