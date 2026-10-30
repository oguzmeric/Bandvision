"use client";

import { useEffect, useRef, useState } from "react";

/** Sunucunun şablon adı sınırı (Unicode kod noktası); `maxLength` UTF-16 birimi sayar, ayrıca denetlenir */
const MAX_NAME = 60;

/**
 * Şablon adı sorusu ("Yeniden adlandır", "Farklı kaydet…"): kipli `<dialog>`; Esc ya da Vazgeç kapatır. `onSubmit`
 * başarısız olursa ileti pencerede kalır, başarılıysa çağıran pencereyi kapatır.
 */
export default function NameDialog({ title, initial, onSubmit, onCancel }: {
  title: string; initial: string; onSubmit: (name: string) => Promise<void>; onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const d = ref.current;
    const back = document.activeElement;
    if (d && !d.open) d.showModal();
    return () => { if (back instanceof HTMLElement && back.isConnected) back.focus(); };
  }, []);

  const trimmed = name.trim();
  const tooLong = [...trimmed].length > MAX_NAME;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!trimmed || tooLong || busy) return;
    setBusy(true);
    setError(null);
    try { await onSubmit(trimmed); } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  return (
    <dialog ref={ref} aria-label={title} onCancel={(e) => { e.preventDefault(); onCancel(); }}
            className="m-auto w-[min(360px,calc(100vw-32px))] border border-pl-ctl bg-pl-bg p-0 text-[13px] text-pl-ink backdrop:bg-black/30">
      <form onSubmit={submit}>
        <h2 className="border-b border-pl-line bg-pl-head px-3 py-1.5 font-semibold">{title}</h2>
        <div className="grid gap-2 p-3">
          <label className="grid gap-1">
            <span className="text-pl-muted">Şablon adı</span>
            <input autoFocus value={name} maxLength={MAX_NAME * 2} onChange={(e) => setName(e.target.value)} className="pl-input" />
          </label>
          {tooLong && <p role="alert" className="text-nok-ink">Ad en çok {MAX_NAME} karakter olabilir.</p>}
          {error && <p role="alert" className="text-nok-ink">{error}</p>}
          <div className="flex justify-end gap-1.5">
            <button type="button" onClick={onCancel} className="pl-btn">Vazgeç</button>
            <button type="submit" disabled={!trimmed || tooLong || busy} className="pl-btn pl-btn-primary">Tamam</button>
          </div>
        </div>
      </form>
    </dialog>
  );
}
