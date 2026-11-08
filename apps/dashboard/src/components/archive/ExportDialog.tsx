"use client";

import { useEffect, useRef, useState } from "react";
import { exportClip, type ArchiveCamera } from "@/lib/archive";
import { exportProblem, fromLocalInput, toLocalInput } from "@/lib/archiveTime.mjs";

/**
 * "Dışa aktar…" penceresi (kipli `<dialog>`): başlangıç/bitiş `datetime-local`, varsayılan imleç −1 dk / +1 dk; süre
 * 30 dakikayı aşarsa düğme pasif. İndirme `fetch` → `Blob` → `<a download>` (ad sunucunun `Content-Disposition`'ından);
 * sürerken düğme "Hazırlanıyor…" der, hata iletisi sunucudan gelir. İptal ya da Esc süren indirmeyi de keser.
 */
export default function ExportDialog({ cam, name, at, onClose }: {
  cam: ArchiveCamera; name: string; at: number; onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const abort = useRef<AbortController | null>(null);
  const [start, setStart] = useState(() => toLocalInput(at - 60));
  const [end, setEnd] = useState(() => toLocalInput(at + 60));
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const d = ref.current;
    const back = document.activeElement;
    if (d && !d.open) d.showModal();
    return () => {
      abort.current?.abort();
      if (back instanceof HTMLElement && back.isConnected) back.focus();
    };
  }, []);

  const s = fromLocalInput(start);
  const e = fromLocalInput(end);
  const problem = exportProblem(s, e);

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    if (problem || running || s === null || e === null) return;
    const ctl = new AbortController();
    abort.current = ctl;
    setRunning(true);
    setError(null);
    try {
      const { blob, filename } = await exportClip(cam, s, e, ctl.signal);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.hidden = true;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
      onClose();
    } catch (err) {
      if (!ctl.signal.aborted) setError(err instanceof Error ? err.message : "Dışa aktarılamadı.");
    } finally {
      if (!ctl.signal.aborted) setRunning(false);
    }
  }

  return (
    <dialog ref={ref} aria-labelledby="bv-export-title" onCancel={(ev) => { ev.preventDefault(); onClose(); }}
            className="m-auto w-[min(400px,calc(100vw-32px))] border border-pl-ctl bg-pl-bg p-0 text-[13px] text-pl-ink backdrop:bg-black/30">
      <form onSubmit={submit}>
        <h2 id="bv-export-title" className="border-b border-pl-line bg-pl-head px-3 py-1.5 font-semibold">Dışa aktar</h2>
        <div className="grid gap-2 p-3">
          <p className="text-pl-muted">{name}: seçilen aralık MP4 dosyası olarak bu bilgisayara iner (süre en çok yarım saat).</p>
          <label className="grid gap-1">
            <span className="text-pl-muted">Başlangıç</span>
            <input type="datetime-local" step={1} required autoFocus value={start} onChange={(ev) => setStart(ev.target.value)}
                   className="pl-input h-8" />
          </label>
          <label className="grid gap-1">
            <span className="text-pl-muted">Bitiş</span>
            <input type="datetime-local" step={1} required value={end} onChange={(ev) => setEnd(ev.target.value)} className="pl-input h-8" />
          </label>
          <div aria-live="polite" data-testid="export-message">
            {problem && <p className="font-semibold text-nok-ink">{problem}</p>}
            {!problem && error && <p role="alert" className="font-semibold text-nok-ink">{error}</p>}
          </div>
          <div className="flex justify-end gap-1.5">
            <button type="button" onClick={onClose} className="pl-btn">İptal</button>
            <button type="submit" disabled={problem !== null || running} className="pl-btn pl-btn-primary">
              {running ? "Hazırlanıyor…" : "Dışa aktar"}
            </button>
          </div>
        </div>
      </form>
    </dialog>
  );
}
