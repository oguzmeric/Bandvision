"use client";

import { useCallback, useId, useMemo, useState } from "react";
import { api, type Source } from "@/lib/live";
import { cellBox, retile, type TileRef, type ViewLayout, type ViewTemplate } from "@/lib/views";
import CameraList, { refKey } from "./CameraList";

const droppedNote = (n: number) => `${n} kamera düzene sığmadı ve şablondan çıkarıldı.`;

/** İlk boş kutu (yoksa null): seçili kutu boştur, listeden seçilen kamera bir kamerayı sessizce ezmez */
const firstEmpty = (tiles: Array<TileRef | null>): number | null => {
  const i = tiles.findIndex((t) => !t);
  return i < 0 ? null : i;
};
/** `from`'dan sonraki ilk boş kutu (başa sararak); boş kalmadıysa null */
const nextEmpty = (tiles: Array<TileRef | null>, from: number): number | null => {
  for (let k = 1; k < tiles.length; k++) {
    const j = (from + k) % tiles.length;
    if (!tiles[j]) return j;
  }
  return null;
};

/**
 * Şablon düzenleyici: ad, düzen, kutulara kamera, kutu boşalt/yer değiştir, kaydet.
 * Kutu seçimi: bir kutu seçilidir (tıklanan/odaklanıp Enter-Boşluk basılan; yeni kamera onda yerleşir, sonra sıradaki boş
 * kutu seçilir). DOLU bir kutu seçiliyken başka bir kutuya tıklamak ikisinin yerini değiştirir (boş kutuya tıklamak
 * kamerayı oraya taşır) ve seçim hedefte kalır; aynı kutuya yeniden tıklamak seçimi korur. Fare ile sürükle-bırak da var
 * (listeden kutuya, kutudan kutuya; kutudan kutuya sürükleyince seçim ilk boş kutuya geçer, listeden seçilen kamera
 * dolu kutuyu ezmez); dokunmatik ve klavye için tıklama yolu yeter.
 */
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
  /** Kutu etiketleri: sunucunun kutu adıyla aynı biçim (tek kamera "Kapı", kanal "Ofis NVR · Kasa") */
  const [labels, setLabels] = useState<Record<string, string>>(names);
  /** Kaynak adları (kamera listesi alınınca): adı bilinmeyen kutular için yedek etiket */
  const [sourceNames, setSourceNames] = useState<Record<string, string> | null>(null);
  const [selected, setSelected] = useState<number | null>(() => firstEmpty(start.tiles));
  const [note, setNote] = useState<string | null>(start.dropped ? droppedNote(start.dropped) : null);
  const [pickHint, setPickHint] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const uid = useId();
  const layout = layouts.find((l) => l.id === layoutId);
  const used = useMemo(() => new Set(tiles.filter((t): t is TileRef => !!t).map(refKey)), [tiles]);
  const onSources = useCallback((s: Source[]) => setSourceNames(Object.fromEntries(s.map((x) => [x.id, x.name]))), []);
  if (!layout) return <p className="card p-6 text-sm text-muted">Düzen listesi alınamadı; sayfayı yenileyin.</p>;

  const labelOf = (t: TileRef): string => {
    const known = labels[refKey(t)];
    if (known) return known;
    if (!sourceNames) return "Kamera";
    const n = sourceNames[t.sourceId];
    if (n === undefined) return "Silinmiş kamera";
    return t.channelId ? `${n} · ${t.channelId}` : n;
  };
  const chooseLayout = (l: ViewLayout) => {
    const r = retile(tiles, l.cells.length);
    setLayoutId(l.id);
    setTiles(r.tiles);
    setSelected(firstEmpty(r.tiles));
    setPickHint(null);
    setNote(r.dropped ? droppedNote(r.dropped) : null);
  };
  const place = (i: number, ref: TileRef, label: string) => {
    if (used.has(refKey(ref))) return;
    const next = tiles.map((x, j) => (j === i ? ref : x));
    setTiles(next);
    setLabels((m) => ({ ...m, [refKey(ref)]: label }));
    setSelected(nextEmpty(next, i));
    setPickHint(null);
  };
  const pick = (ref: TileRef, label: string) => {
    if (selected === null) { setPickHint("Bütün kutular dolu: değiştirmek istediğiniz kutuyu seçin ya da önce bir kutuyu boşaltın."); return; }
    place(selected, ref, label);
  };
  const swap = (a: number, b: number) => setTiles((t) => { const n = [...t]; [n[a], n[b]] = [n[b], n[a]]; return n; });
  /** Sürükleyerek yer değiştirme: seçili kutu dolmuş olabilir, seçim ilk boş kutuya geçer */
  const dragSwap = (a: number, b: number) => {
    const n = [...tiles];
    [n[a], n[b]] = [n[b], n[a]];
    setTiles(n);
    setSelected(firstEmpty(n));
    setPickHint(null);
  };
  const clickTile = (i: number) => {
    setPickHint(null);
    if (selected !== null && selected !== i && tiles[selected]) swap(selected, i);   // dolu seçiliyken başka kutu: yer değiştir/taşı
    setSelected(i);
  };
  const empty = (i: number) => { setTiles((t) => t.map((x, j) => (j === i ? null : x))); setSelected(i); setPickHint(null); };
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
        {pickHint && <p role="status" className="rounded-xl bg-warn-50 px-3 py-2 text-sm text-warn-700">{pickHint}</p>}
        <div className="relative w-full overflow-hidden rounded-2xl bg-ink/90" style={{ aspectRatio: `${layout.cols * 16} / ${layout.rows * 9}` }}>
          {layout.cells.map((_, i) => {
            const t = tiles[i];
            const on = selected === i;
            return (
              <div key={i} data-testid="edit-tile" style={cellBox(layout, i)} className="absolute p-1"
                   draggable={!!t} onDragStart={(e) => e.dataTransfer.setData("application/x-bv-tile", String(i))}
                   onDragOver={(e) => e.preventDefault()}
                   onDrop={(e) => {
                     e.preventDefault();
                     const from = e.dataTransfer.getData("application/x-bv-tile");
                     if (from !== "") return dragSwap(Number(from), i);
                     const cam = e.dataTransfer.getData("application/x-bv-camera");
                     if (cam) { const { ref, name: n } = JSON.parse(cam) as { ref: TileRef; name: string }; place(i, ref, n); }
                   }}>
                {/* Seçme düğmesi; kamera adı açıklaması (ad, "Kutu 3" ile birlikte okunur ama adı değiştirmez) */}
                <div role="button" tabIndex={0} aria-label={`Kutu ${i + 1}`} aria-pressed={on} aria-describedby={t ? `${uid}-${i}` : undefined}
                     onClick={() => clickTile(i)}
                     onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); clickTile(i); } }}
                     className={`flex h-full w-full cursor-pointer flex-col items-center justify-center gap-1 rounded-md border-2 p-1 text-center text-[12px] text-white outline-none focus-visible:ring-2 focus-visible:ring-white ${on ? "border-brand-500" : "border-white/20"}`}>
                  {t ? (
                    <>
                      <span id={`${uid}-${i}`} className="max-w-full truncate">{labelOf(t)}</span>
                      {on && <span className="max-w-full text-[11px] text-white/60">Yer değiştirmek için başka bir kutuya tıklayın</span>}
                    </>
                  ) : <span className="text-white/50">{on ? "Listeden kamera seçin" : "Boş"}</span>}
                </div>
                {t && (
                  <button type="button" aria-label={`Kutu ${i + 1}'i boşalt`} onClick={() => empty(i)}
                          className="absolute right-2 top-2 rounded bg-white/15 px-1.5 text-[11px] text-white">Boşalt</button>
                )}
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
      <CameraList used={used} onPick={pick} onSources={onSources} />
    </section>
  );
}
