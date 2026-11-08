"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, type Channel, type Source } from "@/lib/live";
import type { ArchiveCamera } from "@/lib/archive";
import { useRetryWhileFailed } from "@/lib/useRetryWhileFailed";

interface Entry { sourceId: string; channelId: string; label: string }
type Loaded = { entries: Entry[]; problems: string[] };

/** Kayıt cihazları ve kanalları: `GET sources` (yalnız `kind === "recorder"`), her biri için `GET sources/{id}/channels` */
async function loadEntries(): Promise<Loaded> {
  const recorders = (await api<Source[]>("sources")).filter((s) => s.kind === "recorder");
  const lists = await Promise.all(recorders.map((s) => api<Channel[]>(`sources/${s.id}/channels`)
    .then((chs) => ({ entries: chs.map((c) => ({ sourceId: s.id, channelId: c.id, label: `${s.name} · ${c.title}` })), problem: null }))
    .catch((e: Error) => ({ entries: [] as Entry[], problem: `${s.name}: ${e.message}` }))));
  return {
    entries: lists.flatMap((l) => l.entries),
    problems: lists.map((l) => l.problem).filter((p): p is string => p !== null),
  };
}

/**
 * Kamera seçici: kayıt cihazlarının kanalları "kaynak adı · kanal adı" diye, aramalı liste. Tek kameralar (IP kamera)
 * listelenmez: kayıttan izleme kayıt cihazının arşivini oynatır.
 */
export default function CameraPicker({ selected, onSelect }: {
  selected: ArchiveCamera | null; onSelect: (cam: ArchiveCamera, label: string) => void;
}) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const load = useCallback(() => loadEntries().then((l) => { setLoaded(l); setError(null); }).catch((e: Error) => setError(e.message)), []);
  useEffect(() => { void load(); }, [load]);
  useRetryWhileFailed(error !== null && loaded === null, load);

  const needle = query.toLocaleLowerCase("tr");
  const shown = (loaded?.entries ?? []).filter((e) => e.label.toLocaleLowerCase("tr").includes(needle));
  const isSel = (e: Entry) => selected?.sourceId === e.sourceId && selected.channelId === e.channelId;

  return (
    <section className="pl-section mb-0 min-w-0" aria-labelledby="archive-cameras-title">
      <h2 id="archive-cameras-title">Kamera</h2>
      <input aria-label="Kamera ara" placeholder="Kamera ara" value={query} onChange={(e) => setQuery(e.target.value)}
             className="pl-input mb-2 h-8 w-full" />
      {error && <p role="alert" className="mb-2 rounded-[2px] border border-nok-line bg-nok-50 px-3 py-2 text-nok-ink">{error}</p>}
      {loaded?.problems.map((p) => <p key={p} className="mb-1 text-nok-ink">{p}</p>)}
      {loaded === null && !error && <div className="h-16 animate-pulse rounded-[2px] bg-pl-side" />}
      {loaded && loaded.entries.length === 0 && loaded.problems.length === 0 && (
        <p className="text-pl-muted">
          Kayıt cihazı yok. <Link href="/cameras" className="font-semibold text-pl-accent underline">Kameralar ve kayıt cihazları</Link>{" "}
          sayfasından ekleyin.
        </p>
      )}
      {loaded && loaded.entries.length > 0 && shown.length === 0 && <p className="text-pl-muted">Aramayla eşleşen kamera yok.</p>}
      {shown.length > 0 && (
        <ul aria-label="Kayıt cihazı kameraları" className="grid max-h-48 gap-px overflow-y-auto border border-pl-line-soft sm:grid-cols-2 xl:grid-cols-3">
          {shown.map((e) => (
            <li key={`${e.sourceId}|${e.channelId}`} className="min-w-0">
              <button type="button" aria-pressed={isSel(e)} onClick={() => onSelect({ sourceId: e.sourceId, channelId: e.channelId }, e.label)}
                      className={`block w-full truncate px-2 py-1.5 text-left ${isSel(e) ? "bg-pl-sel font-semibold text-pl-ink" : "bg-white hover:bg-pl-side"}`}>
                {e.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
