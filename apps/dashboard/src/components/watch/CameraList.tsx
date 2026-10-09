"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Channel, type Source } from "@/lib/live";
import type { TileRef } from "@/lib/views";
import Thumb from "@/components/live/Thumb";

export const refKey = (r: TileRef) => `${r.sourceId}|${r.channelId ?? ""}`;

/** Düzenleyicinin kamera listesi: tek kameralar ve kayıt cihazlarının kanalları (aç/kapa), küçük resim ve adla.
 * Şablonda zaten olan kamera pasif. Öğe sürüklenebilir (kutuya bırakılır) ya da tıklanır (seçili kutuya gider).
 * `onPick`/sürükleme etiketi sunucunun kutu adıyla aynı biçimdedir: tek kamera "Kapı", kanal "Ofis NVR · Kasa". */
export default function CameraList({ used, onPick, onSources }: {
  used: Set<string>; onPick: (ref: TileRef, label: string) => void;
  /** Kaynak listesi alınınca (kutu etiketleri için kaynak adları) */
  onSources?: (sources: Source[]) => void;
}) {
  /** null: henüz alınmadı (alınamazsa `error` dolar; "Henüz kaynak yok" yanlışı söylenmesin) */
  const [sources, setSources] = useState<Source[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  /** Kayıt cihazı → kanallar, hata iletisi ya da (undefined) alınıyor */
  const [channels, setChannels] = useState<Record<string, Channel[] | string | undefined>>({});
  /** Kanal isteği sürenler: kapatıp yeniden açmak ikinci istek göndermez */
  const pending = useRef(new Set<string>());
  const load = useCallback(() => {
    setError(null);
    api<Source[]>("sources").then((s) => { setSources(s); onSources?.(s); }).catch((e: Error) => setError(e.message));
  }, [onSources]);
  useEffect(() => { load(); }, [load]);
  const toggle = async (s: Source) => {
    if (open === s.id) { setOpen(null); return; }
    setOpen(s.id);
    if (Array.isArray(channels[s.id]) || pending.current.has(s.id)) return;
    pending.current.add(s.id);
    setChannels((x) => ({ ...x, [s.id]: undefined }));                 // önceki hata iletisi kalkar, "yükleniyor" görünür
    try { const c = await api<Channel[]>(`sources/${s.id}/channels`); setChannels((x) => ({ ...x, [s.id]: c })); }
    catch (e) { setChannels((x) => ({ ...x, [s.id]: (e as Error).message })); }
    finally { pending.current.delete(s.id); }
  };
  const item = (ref: TileRef, name: string, label: string, thumb: string) => (
    <li key={refKey(ref)}>
      <button type="button" draggable disabled={used.has(refKey(ref))}
              onDragStart={(e) => e.dataTransfer.setData("application/x-bv-camera", JSON.stringify({ ref, name: label }))}
              onClick={() => onPick(ref, label)}
              className="flex w-full items-center gap-2 rounded-xl border border-line p-1.5 text-left text-[13px] hover:border-brand-100 disabled:opacity-40">
        <span className="w-20 shrink-0"><Thumb src={thumb} alt="" /></span>
        <span className="min-w-0 truncate">{name}</span>
      </button>
    </li>
  );
  const channelList = (s: Source) => {
    const c = channels[s.id];
    if (typeof c === "string") return <p className="px-2 py-1 text-[12px] text-nok-600">{c}</p>;
    if (c === undefined) return <p className="px-2 py-1 text-[12px] text-faint">Kanallar yükleniyor…</p>;
    if (c.length === 0) return <p className="px-2 py-1 text-[12px] text-faint">Bu kayıt cihazında kamera yok.</p>;
    return (
      <ul className="mt-1.5 grid gap-1.5 pl-2">
        {c.map((ch) => item({ sourceId: s.id, channelId: ch.id }, ch.title, `${s.name} · ${ch.title.trim()}`,
                            `/api/live/sources/${s.id}/snapshot?channel=${encodeURIComponent(ch.id)}`))}
      </ul>
    );
  };
  return (
    <aside aria-label="Kameralar" className="grid content-start gap-2 lg:max-h-[75vh] lg:overflow-y-auto">
      {error && (
        <div role="alert" className="flex flex-wrap items-center gap-2 rounded-xl bg-nok-50 px-3 py-2 text-[13px] text-nok-600">
          <span className="min-w-0 flex-1">{error}</span>
          <button type="button" onClick={load} className="h-8 rounded-[9px] border border-line bg-white px-3 text-[12.5px] font-medium text-ink">Yeniden dene</button>
        </div>
      )}
      {sources === null && !error && <p className="text-[13px] text-faint">Kameralar yükleniyor…</p>}
      {sources?.length === 0 && <p className="text-[13px] text-faint">Henüz kaynak yok. Kameralar sayfasından ekleyin.</p>}
      <ul className="grid gap-1.5">
        {(sources ?? []).map((s) => s.kind === "camera"
          ? item({ sourceId: s.id, channelId: null }, s.name, s.name, `/api/live/sources/${s.id}/snapshot`)
          : (
            <li key={s.id}>
              <button type="button" aria-expanded={open === s.id} onClick={() => toggle(s)}
                      className="w-full rounded-xl bg-canvas px-2 py-1.5 text-left text-[13px] font-medium">{s.name} {open === s.id ? "▾" : "▸"}</button>
              {open === s.id && channelList(s)}
            </li>
          ))}
      </ul>
    </aside>
  );
}
