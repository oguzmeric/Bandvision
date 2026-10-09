"use client";

import Link from "next/link";
import { ALARM_TITLES } from "@/lib/live";
import { badge, cellBox, type TileStatus, type ViewLayout } from "@/lib/views";

const TONE = { ok: "bg-ok-600 text-white", warn: "bg-warn-700 text-white", info: "bg-black/60 text-white" } as const;

/** Birleşik görüntünün üstünde tek kutunun HTML katmanı: ad, durum, rozet, alarm çerçevesi */
export default function TileOverlay({ layout, index, tile, onOpen, onAlarm }: {
  layout: ViewLayout; index: number; tile: TileStatus | null;
  onOpen: () => void; onAlarm: (alarmId: string) => void;
}) {
  const alarm = tile?.analysis?.alarm ?? null;
  return (
    <div data-testid="watch-tile" data-empty={tile ? undefined : "true"} data-alarm={alarm ? "true" : undefined}
         style={cellBox(layout, index)}
         className={`group absolute p-1 ${alarm ? "animate-pulse" : ""}`}
         onDoubleClick={() => tile && onOpen()}
         onClick={() => (alarm ? onAlarm(alarm.id) : undefined)}
         role={tile ? "button" : undefined} tabIndex={tile ? 0 : -1}
         aria-label={tile ? `${tile.name}: büyütmek için çift tıklayın` : "Boş kutu"}
         onKeyDown={(e) => { if (tile && e.key === "Enter" && e.target === e.currentTarget) onOpen(); }}>
      <div className={`relative h-full w-full rounded-[6px] ${alarm ? "ring-4 ring-nok-600" : ""}`}>
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
          <span className="absolute inset-x-0 bottom-2 mx-auto w-max rounded-md bg-nok-600 px-2 py-1 text-[12px] font-bold text-white">
            {ALARM_TITLES[alarm.type]}
          </span>
        )}
        {tile && tile.state !== "live" && (
          <span className="absolute inset-0 grid place-items-center p-2 text-center text-[12px] text-white/90">
            {tile.state === "connecting" ? "Bağlanıyor…" : tile.message || "Bağlantı yok"}
          </span>
        )}
        {tile && (
          // Üstüne gelince (telefonda dokununca odakla) küçük düğmeler: büyüt, canlı sayıma git
          <span className="absolute bottom-1.5 right-1.5 hidden gap-1 group-hover:flex group-focus-within:flex">
            <button type="button" onClick={(e) => { e.stopPropagation(); onOpen(); }}
                    className="rounded-md bg-black/60 px-1.5 py-0.5 text-[11px] text-white">Tam ekran</button>
            <Link href={tile.analysis ? `/live?s=${tile.analysis.sessionId}` : "/cameras"} onClick={(e) => e.stopPropagation()}
                  className="rounded-md bg-black/60 px-1.5 py-0.5 text-[11px] text-white">Canlı sayıma git</Link>
          </span>
        )}
      </div>
    </div>
  );
}
