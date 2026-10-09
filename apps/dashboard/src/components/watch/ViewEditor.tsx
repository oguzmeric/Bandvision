"use client";

import { useMemo, useState } from "react";
import { api } from "@/lib/live";
import { cellBox, retile, type TileRef, type ViewLayout, type ViewTemplate } from "@/lib/views";
import CameraList, { refKey } from "./CameraList";

const droppedNote = (n: number) => `${n} kamera düzene sığmadı ve şablondan çıkarıldı.`;

/** Şablon düzenleyici: ad, düzen, kutulara kamera (tıkla-seç ya da sürükle-bırak), kutu boşalt/yer değiştir, kaydet */
export default function ViewEditor({ initial, layouts, names, onSaved, onCancel, onDeleted }: {
  initial: ViewTemplate | null; layouts: ViewLayout[]; names: Record<string, string>;
  onSaved: (v: ViewTemplate) => void; onCancel: () => void; onDeleted: (id: string) => void;
}) {
  // Başlangıç: şablonun düzeni (tanınmıyorsa 4'lü, o da yoksa ilk düzen); kutular o düzene sığdırılır
  const [start] = useState(() => {
    const l = layouts.find((x) => x.id === initial?.layout) ?? layouts.find((x) => x.id === "4") ?? layouts[0];
    const r = retile(initial?.tiles ?? [], l?.cells.length ?? 0);
    return { layoutId: l?.id ?? "", tiles: r.tiles, dropped: r.dropped };
  });
  const [name, setName] = useState(initial?.name ?? "");
  const [layoutId, setLayoutId] = useState(start.layoutId);
  const [tiles, setTiles] = useState<Array<TileRef | null>>(start.tiles);
  const [labels, setLabels] = useState<Record<string, string>>(names);
  const [selected, setSelected] = useState(0);
  const [note, setNote] = useState<string | null>(start.dropped ? droppedNote(start.dropped) : null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const layout = layouts.find((l) => l.id === layoutId);
  const used = useMemo(() => new Set(tiles.filter((t): t is TileRef => !!t).map(refKey)), [tiles]);
  if (!layout) return <p className="card p-6 text-sm text-muted">Düzen listesi alınamadı; sayfayı yenileyin.</p>;

  const chooseLayout = (l: ViewLayout) => {
    const r = retile(tiles, l.cells.length);
    setLayoutId(l.id);
    setTiles(r.tiles);
    setSelected(0);
    setNote(r.dropped ? droppedNote(r.dropped) : null);
  };
  const place = (i: number, ref: TileRef, label: string) => {
    if (used.has(refKey(ref))) return;
    setTiles((t) => t.map((x, j) => (j === i ? ref : x)));
    setLabels((m) => ({ ...m, [refKey(ref)]: label }));
    setSelected(Math.min(i + 1, tiles.length - 1));
  };
  const swap = (a: number, b: number) => setTiles((t) => { const n = [...t]; [n[a], n[b]] = [n[b], n[a]]; return n; });
  const save = async () => {
    setBusy(true); setError(null);
    try {
      const body = { name: name.trim(), layout: layoutId, tiles };
      const v = initial ? await api<ViewTemplate>(`views/${initial.id}`, { method: "PUT", json: body })
                        : await api<ViewTemplate>("views", { method: "POST", json: body });
      onSaved(v);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const remove = async () => {
    if (!initial || !window.confirm(`"${initial.name}" şablonu silinsin mi?`)) return;
    setBusy(true); setError(null);
    try { await api(`views/${initial.id}`, { method: "DELETE" }); onDeleted(initial.id); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <section aria-label="Şablon düzenleyici" className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
      <div className="grid content-start gap-3">
        <label className="text-sm font-medium">Şablon adı
          <input aria-label="Şablon adı" value={name} maxLength={60} onChange={(e) => setName(e.target.value)}
                 className="mt-1.5 h-10 w-full rounded-[10px] border border-line bg-white px-3 text-sm" />
        </label>
        <div role="group" aria-label="Düzen" className="flex flex-wrap gap-1.5">
          {layouts.map((l) => (
            <button key={l.id} type="button" aria-pressed={l.id === layoutId} onClick={() => chooseLayout(l)}
                    className={`h-9 rounded-[9px] border px-2.5 text-[13px] ${l.id === layoutId ? "border-brand-500 bg-brand-50" : "border-line"}`}>{l.name}</button>
          ))}
        </div>
        {note && <p role="status" className="rounded-xl bg-warn-50 px-3 py-2 text-sm text-warn-700">{note}</p>}
        <div className="relative w-full overflow-hidden rounded-2xl bg-ink/90" style={{ aspectRatio: `${layout.cols * 16} / ${layout.rows * 9}` }}>
          {layout.cells.map((_, i) => {
            const t = tiles[i];
            return (
              <div key={i} data-testid="edit-tile" style={cellBox(layout, i)} className="absolute p-1"
                   draggable={!!t} onDragStart={(e) => e.dataTransfer.setData("application/x-bv-tile", String(i))}
                   onDragOver={(e) => e.preventDefault()}
                   onDrop={(e) => {
                     e.preventDefault();
                     const from = e.dataTransfer.getData("application/x-bv-tile");
                     if (from !== "") return swap(Number(from), i);
                     const cam = e.dataTransfer.getData("application/x-bv-camera");
                     if (cam) { const { ref, name: n } = JSON.parse(cam) as { ref: TileRef; name: string }; place(i, ref, n); }
                   }}
                   tabIndex={0} aria-current={selected === i ? "true" : undefined}
                   onKeyDown={(e) => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); setSelected(i); } }}
                   onClick={() => setSelected(i)}>
                <div className={`flex h-full w-full items-center justify-center rounded-md border-2 text-center text-[12px] text-white ${selected === i ? "border-brand-500" : "border-white/20"}`}>
                  {t ? (
                    <span className="grid gap-1 p-1">
                      <span className="truncate">{labels[refKey(t)] ?? "Kamera"}</span>
                      <button type="button" onClick={(e) => { e.stopPropagation(); setTiles((x) => x.map((y, j) => (j === i ? null : y))); }}
                              className="mx-auto rounded bg-white/15 px-1.5 text-[11px]">Boşalt</button>
                    </span>
                  ) : <span className="text-white/50">{selected === i ? "Listeden kamera seçin" : "Boş"}</span>}
                </div>
              </div>
            );
          })}
        </div>
        {error && <p role="alert" className="rounded-xl bg-nok-50 px-3 py-2 text-sm text-nok-600">{error}</p>}
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={save} disabled={busy || !name.trim()} className="brand-gradient h-10 rounded-[10px] px-4 text-sm font-semibold text-white disabled:opacity-50">Kaydet</button>
          <button type="button" onClick={onCancel} className="h-10 rounded-[10px] border border-line px-4 text-sm">Vazgeç</button>
          {initial && <button type="button" onClick={remove} disabled={busy} className="ml-auto h-10 rounded-[10px] px-3 text-sm text-nok-600 disabled:opacity-50">Şablonu sil</button>}
        </div>
      </div>
      <CameraList used={used} onPick={(ref, n) => place(selected, ref, n)} />
    </section>
  );
}
