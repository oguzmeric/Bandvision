"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type CatalogCategory, type LiveSession, type Profile } from "@/lib/live";

/** Profil hangi sayım türünde (telefondaki ProductCatalog.contains ile aynı) */
export function categoryOf(p: Profile): string {
  return p.countMode === "detect" ? "people" : "belt";
}

export function profileStatus(p: Profile): string {
  if (p.countMode === "detect") return "Giriş / çıkış sayımı";
  if (p.countMode === "linescan") return "Bitişik / hacimli ürün";
  return p.expectedArea > 0 ? "Kalibre edildi" : "Kalibre edilmedi";
}

/** Alt akış (hızlı, sayım için yeterli) / ana akış (net, uzak ya da küçük nesne) seçimi */
export function StreamChoice({ value, onChange }: { value: boolean; onChange: (sub: boolean) => void }) {
  const opt = (sub: boolean, title: string, hint: string) => (
    <button type="button" role="radio" aria-checked={value === sub} onClick={() => onChange(sub)}
            className={`rounded-[8px] px-3 py-2 text-left transition ${value === sub ? "bg-white shadow-sm" : "hover:bg-white/60"}`}>
      <span className={`block text-[13px] font-semibold ${value === sub ? "text-ink" : "text-muted"}`}>{title}</span>
      <span className="block text-[11.5px] text-faint">{hint}</span>
    </button>
  );
  return (
    <div role="radiogroup" aria-label="Görüntü akışı" className="grid grid-cols-2 gap-0.5 rounded-[10px] border border-line bg-canvas p-0.5">
      {opt(true, "Alt akış", "Hızlı, önerilen")}
      {opt(false, "Ana akış", "Net; daha yavaş")}
    </div>
  );
}

/** Kamera seçildi: profil seç (ya da hazır profilden ekle) → canlı oturum başlar, canlı sayfaya geçilir */
export default function StartSessionDialog({ sourceId, channelId, title, substream, streamChoice, onClose }: {
  sourceId: string; channelId: string | null; title: string; substream: boolean; streamChoice: boolean; onClose: () => void;
}) {
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [catalog, setCatalog] = useState<CatalogCategory[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [sub, setSub] = useState(substream);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    dialog.current?.showModal();
    Promise.all([api<Profile[]>("profiles"), api<CatalogCategory[]>("catalog")])
      .then(([p, c]) => { setProfiles(p); setCatalog(c); })
      .catch((e: Error) => setError(e.message));
  }, []);

  async function addPreset(key: string) {
    try {
      const p = await api<Profile>("profiles", { method: "POST", json: { preset: key } });
      setProfiles((x) => [...(x ?? []), p]);
      setSelected(p.id);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function start() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const s = await api<LiveSession>("sessions", { method: "POST", json: { sourceId, channelId, profileId: selected, substream: streamChoice ? sub : null } });
      dialog.current?.close();
      router.push(`/live?s=${s.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <dialog ref={dialog} onClose={onClose} aria-labelledby="start-title"
            className="m-auto w-[min(560px,94vw)] rounded-3xl border border-line bg-white p-0 text-ink shadow-2xl backdrop:bg-black/40">
      <div className="p-5">
        <p id="start-title" className="text-lg font-semibold">Canlı sayımı başlat</p>
        <p className="mb-4 truncate text-[13px] text-muted">{title}</p>
        <p className="eyebrow mb-2">Ne sayacaksın?</p>
        {profiles === null && !error && <div className="h-24 animate-pulse rounded-xl bg-canvas" />}
        <div className="grid max-h-[50vh] gap-4 overflow-y-auto pr-1">
          {catalog.filter((c) => c.available).map((cat) => {
            const list = (profiles ?? []).filter((p) => categoryOf(p) === cat.id);
            return (
              <div key={cat.id}>
                <p className="mb-1.5 text-sm font-semibold">{cat.title}</p>
                <div className="grid gap-1.5">
                  {list.map((p) => (
                    <button key={p.id} type="button" onClick={() => setSelected(p.id)} aria-pressed={selected === p.id}
                            className={`flex items-center justify-between rounded-xl border px-3 py-2.5 text-left transition ${selected === p.id
                              ? "border-brand-500 bg-brand-50" : "border-line hover:border-brand-100"}`}>
                      <span>
                        <span className="block text-sm font-medium">{p.name}</span>
                        <span className="block text-xs text-faint">{profileStatus(p)}</span>
                      </span>
                      <span aria-hidden="true" className={`h-4 w-4 rounded-full border-2 ${selected === p.id ? "border-brand-500 bg-brand-500" : "border-line"}`} />
                    </button>
                  ))}
                  {cat.presets.map((pr) => (
                    <button key={pr.key} type="button" onClick={() => addPreset(pr.key)}
                            className="rounded-xl border border-dashed border-line px-3 py-2 text-left text-[13px] text-muted hover:border-brand-100 hover:text-brand-500">
                      + {pr.name} profili ekle
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
          {catalog.filter((c) => !c.available).length > 0 && (
            <p className="text-xs text-faint">Yakında: {catalog.filter((c) => !c.available).map((c) => c.title).join(", ")}</p>
          )}
        </div>
        {streamChoice && (
          <div className="mt-4">
            <p className="eyebrow mb-2">Görüntü</p>
            <StreamChoice value={sub} onChange={setSub} />
          </div>
        )}
        {error && <p role="alert" className="mt-3 rounded-xl bg-nok-50 px-3 py-2 text-sm text-nok-600">{error}</p>}
        <div className="mt-5 flex gap-2">
          <button type="button" onClick={() => dialog.current?.close()}
                  className="h-11 flex-1 rounded-[11px] border border-line text-sm font-medium hover:border-brand-100">Vazgeç</button>
          <button type="button" onClick={start} disabled={!selected || busy}
                  className="brand-gradient h-11 flex-1 rounded-[11px] text-sm font-semibold text-white disabled:opacity-50">
            {busy ? "Bağlanıyor…" : "Başlat"}
          </button>
        </div>
      </div>
    </dialog>
  );
}
