"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { KIND_CATEGORY, type AnalysisKind } from "@/lib/analysisKind";
import { api, type CatalogCategory, type LiveSession, type Profile } from "@/lib/live";

/** Profil hangi sayım türünde (telefondaki ProductCatalog.contains ile aynı) */
export function categoryOf(p: Profile): string {
  if (p.countMode === "safety") return "safety";
  return p.countMode === "detect" ? "people" : "belt";
}

export function profileStatus(p: Profile): string {
  if (p.countMode === "safety") return "Eller yukarı / yerde yatan kişi";
  if (p.countMode === "detect") return "Giriş / çıkış sayımı";
  if (p.countMode === "linescan") return "Bitişik / hacimli ürün";
  return p.expectedArea > 0 ? "Kalibre edildi" : "Kalibre edilmedi";
}

/** Alt akış (hızlı, sayım için yeterli) / ana akış (net, uzak ya da küçük nesne) seçimi */
export function StreamChoice({ value, onChange }: { value: boolean; onChange: (sub: boolean) => void }) {
  const opt = (sub: boolean, title: string, hint: string) => (
    <button type="button" role="radio" aria-checked={value === sub} onClick={() => onChange(sub)}
            className={`px-3 py-1.5 text-left focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-pl-accent ${value === sub ? "bg-pl-sel" : "bg-[#f7f8fa] hover:bg-pl-head"}`}>
      <span className={`block text-[13px] font-semibold ${value === sub ? "text-pl-ink" : "text-pl-muted"}`}>{title}</span>
      <span className="block text-[11.5px] text-pl-faint">{hint}</span>
    </button>
  );
  return (
    <div role="radiogroup" aria-label="Görüntü akışı" className="grid grid-cols-2 divide-x divide-pl-ctl overflow-hidden rounded-[2px] border border-pl-ctl">
      {opt(true, "Alt akış", "Hızlı, önerilen")}
      {opt(false, "Ana akış", "Net; daha yavaş")}
    </div>
  );
}

/** Kamera seçildi: profil seç (ya da hazır profilden ekle) → canlı oturum başlar, canlı sayfaya geçilir */
export default function StartSessionDialog({ sourceId, channelId, title, substream, streamChoice, kind, onClose }: {
  sourceId: string; channelId: string | null; title: string; substream: boolean; streamChoice: boolean;
  /** Süzülmüş analiz sayfasından gelindiyse yalnızca o türün profilleri sunulur */
  kind: AnalysisKind | null; onClose: () => void;
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

  const [renaming, setRenaming] = useState<string | null>(null);
  const [newName, setNewName] = useState("");

  async function rename(p: Profile, name: string) {
    if (!name.trim() || name.trim() === p.name) { setRenaming(null); return; }
    try {
      const saved = await api<Profile>(`profiles/${p.id}`, { method: "PUT", json: { ...p, name: name.trim() } });
      setProfiles((x) => (x ?? []).map((q) => (q.id === p.id ? saved : q)));
      setRenaming(null);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function remove(p: Profile) {
    if (!confirm(`"${p.name}" profili silinsin mi? Bu profille kameralarda kaydedilen alan ve çizgi ayarları da silinir.`)) return;
    try {
      await api(`profiles/${p.id}`, { method: "DELETE" });
      setProfiles((x) => (x ?? []).filter((q) => q.id !== p.id));
      if (selected === p.id) setSelected(null);
      setError(null);
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
      router.push(`/live?s=${s.id}${kind ? `&tur=${kind}` : ""}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <dialog ref={dialog} onClose={onClose} aria-labelledby="start-title"
            className="m-auto w-[min(560px,94vw)] rounded-[3px] border border-pl-line bg-white p-0 text-[13px] text-pl-ink backdrop:bg-black/30">
      <div className="border-b border-pl-line bg-pl-head px-4 py-2">
        <p id="start-title" className="text-[14px] font-semibold">Canlı sayımı başlat</p>
        <p className="truncate text-[12.5px] text-pl-muted">{title}</p>
      </div>
      <div className="p-4">
        <p className="mb-1.5 text-xs font-semibold text-pl-muted">Ne sayacaksın?</p>
        {profiles === null && !error && (
          <div className="grid h-24 place-items-center rounded-[2px] border border-pl-line-soft bg-pl-side text-[13px] text-pl-muted" aria-live="polite">
            <span className="animate-pulse">Profiller yükleniyor…</span>
          </div>
        )}
        <div className="grid max-h-[50vh] gap-3 overflow-y-auto pr-1">
          {catalog.filter((c) => c.available && (!kind || c.id === KIND_CATEGORY[kind])).map((cat) => {
            const list = (profiles ?? []).filter((p) => categoryOf(p) === cat.id);
            return (
              <div key={cat.id}>
                <p className="mb-1 text-[13px] font-semibold">{cat.title}</p>
                <div className="grid gap-1">
                  {list.map((p) => (
                    <div key={p.id} data-testid="profile-row"
                         className={`flex items-center gap-1 rounded-[2px] border pr-1 ${selected === p.id
                           ? "border-pl-sel-line bg-pl-sel" : "border-pl-line-soft hover:bg-pl-side"}`}>
                      {renaming === p.id ? (
                        <form className="flex flex-1 items-center gap-1.5 py-1 pl-1.5" onSubmit={(e) => { e.preventDefault(); rename(p, newName); }}>
                          <input autoFocus aria-label="Profil adı" value={newName} maxLength={80}
                                 onChange={(e) => setNewName(e.target.value)} onKeyDown={(e) => e.key === "Escape" && setRenaming(null)}
                                 className="pl-input h-7 flex-1" />
                          <button type="submit" className="pl-btn pl-btn-primary h-7">Kaydet</button>
                          <button type="button" onClick={() => setRenaming(null)} className="pl-btn h-7">Vazgeç</button>
                        </form>
                      ) : (
                        <>
                          <button type="button" onClick={() => setSelected(p.id)} aria-pressed={selected === p.id}
                                  className="flex flex-1 items-center gap-2.5 px-2.5 py-1.5 text-left">
                            <span aria-hidden="true" className={`h-3.5 w-3.5 shrink-0 rounded-full bg-white ${selected === p.id ? "border-4 border-pl-accent" : "border border-pl-ctl"}`} />
                            <span className="min-w-0">
                              <span className="block truncate text-[13px] font-medium">{p.name}</span>
                              <span className="block text-xs text-pl-faint">{profileStatus(p)}</span>
                            </span>
                          </button>
                          <button type="button" aria-label={`Yeniden adlandır: ${p.name}`} title="Yeniden adlandır"
                                  onClick={() => { setRenaming(p.id); setNewName(p.name); }}
                                  className="grid h-7 w-7 place-items-center rounded-[2px] text-pl-muted hover:bg-pl-head hover:text-pl-ink">
                            <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 20h4L19 9l-4-4L4 16zM14 6l4 4" /></svg>
                          </button>
                          <button type="button" aria-label={`Sil: ${p.name}`} title="Sil" onClick={() => remove(p)}
                                  className="grid h-7 w-7 place-items-center rounded-[2px] text-pl-muted hover:bg-nok-50 hover:text-nok-ink">
                            <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" /></svg>
                          </button>
                        </>
                      )}
                    </div>
                  ))}
                  {cat.presets.map((pr) => (
                    <button key={pr.key} type="button" onClick={() => addPreset(pr.key)}
                            className="rounded-[2px] border border-dashed border-pl-line px-2.5 py-1.5 text-left text-[13px] text-pl-muted hover:bg-pl-side hover:text-pl-accent">
                      + {pr.name} profili ekle
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
          {!kind && catalog.filter((c) => !c.available).length > 0 && (
            <p className="text-xs text-pl-faint">Yakında: {catalog.filter((c) => !c.available).map((c) => c.title).join(", ")}</p>
          )}
        </div>
        {streamChoice && (
          <div className="mt-3">
            <p className="mb-1.5 text-xs font-semibold text-pl-muted">Görüntü</p>
            <StreamChoice value={sub} onChange={setSub} />
          </div>
        )}
        {error && <p role="alert" className="mt-3 rounded-[2px] border border-nok-line bg-nok-50 px-3 py-2 text-[13px] text-nok-ink">{error}</p>}
        <div className="-mx-4 -mb-4 mt-4 flex gap-2 border-t border-pl-line-soft bg-pl-side px-4 py-2.5">
          <button type="button" onClick={() => dialog.current?.close()} className="pl-btn h-8 flex-1 justify-center">Vazgeç</button>
          <button type="button" onClick={start} disabled={!selected || busy} className="pl-btn pl-btn-primary h-8 flex-1 justify-center">
            {busy ? "Bağlanıyor…" : "Başlat"}
          </button>
        </div>
      </div>
    </dialog>
  );
}
