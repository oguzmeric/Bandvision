"use client";

import { useEffect, useState } from "react";
import { api, type Channel, type Source } from "@/lib/live";
import type { TileRef } from "@/lib/views";
import Thumb from "@/components/live/Thumb";

export const refKey = (r: TileRef) => `${r.sourceId}|${r.channelId ?? ""}`;

/** Düzenleyicinin kamera listesi: tek kameralar ve kayıt cihazlarının kanalları (aç/kapa), küçük resim ve adla.
 * Şablonda zaten olan kamera pasif. Öğe sürüklenebilir (kutuya bırakılır) ya da tıklanır (seçili kutuya gider). */
export default function CameraList({ used, onPick }: { used: Set<string>; onPick: (ref: TileRef, name: string) => void }) {
  /** null: henüz alınmadı (alınamazsa `error` dolar; "Henüz kaynak yok" yanlışı söylenmesin) */
  const [sources, setSources] = useState<Source[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [channels, setChannels] = useState<Record<string, Channel[] | string>>({});
  useEffect(() => { api<Source[]>("sources").then(setSources).catch((e: Error) => setError(e.message)); }, []);
  const toggle = async (s: Source) => {
    setOpen(open === s.id ? null : s.id);
    if (open === s.id || Array.isArray(channels[s.id])) return;       // kapanırken ya da kanallar zaten alınmışken istek yok
    try { const c = await api<Channel[]>(`sources/${s.id}/channels`); setChannels((x) => ({ ...x, [s.id]: c })); }
    catch (e) { setChannels((x) => ({ ...x, [s.id]: (e as Error).message })); }
  };
  const item = (ref: TileRef, name: string, thumb: string) => (
    <li key={refKey(ref)}>
      <button type="button" draggable disabled={used.has(refKey(ref))}
              onDragStart={(e) => e.dataTransfer.setData("application/x-bv-camera", JSON.stringify({ ref, name }))}
              onClick={() => onPick(ref, name)}
              className="flex w-full items-center gap-2 rounded-xl border border-line p-1.5 text-left text-[13px] hover:border-brand-100 disabled:opacity-40">
        <span className="w-20 shrink-0"><Thumb src={thumb} alt="" /></span>
        <span className="min-w-0 truncate">{name}</span>
      </button>
    </li>
  );
  return (
    <aside aria-label="Kameralar" className="grid content-start gap-2 lg:max-h-[75vh] lg:overflow-y-auto">
      {error && <p role="alert" className="rounded-xl bg-nok-50 px-3 py-2 text-[13px] text-nok-600">{error}</p>}
      {sources === null && !error && <p className="text-[13px] text-faint">Kameralar yükleniyor…</p>}
      {sources?.length === 0 && <p className="text-[13px] text-faint">Henüz kaynak yok. Kameralar sayfasından ekleyin.</p>}
      <ul className="grid gap-1.5">
        {(sources ?? []).map((s) => s.kind === "camera"
          ? item({ sourceId: s.id, channelId: null }, s.name, `/api/live/sources/${s.id}/snapshot`)
          : (
            <li key={s.id}>
              <button type="button" aria-expanded={open === s.id} onClick={() => toggle(s)}
                      className="w-full rounded-xl bg-canvas px-2 py-1.5 text-left text-[13px] font-medium">{s.name} {open === s.id ? "▾" : "▸"}</button>
              {open === s.id && (typeof channels[s.id] === "string"
                ? <p className="px-2 py-1 text-[12px] text-nok-600">{channels[s.id] as string}</p>
                : <ul className="mt-1.5 grid gap-1.5 pl-2">{((channels[s.id] as Channel[] | undefined) ?? []).map((c) =>
                    item({ sourceId: s.id, channelId: c.id }, c.title,
                         `/api/live/sources/${s.id}/snapshot?channel=${encodeURIComponent(c.id)}`))}</ul>)}
            </li>
          ))}
      </ul>
    </aside>
  );
}
