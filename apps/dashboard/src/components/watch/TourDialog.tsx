"use client";

import { useEffect, useRef, useState } from "react";
import { DEFAULT_TOUR_S, TOUR_COOKIE, TOUR_INTERVALS, parseTourInterval, readCookie, tourCookie } from "@/lib/watchTour.mjs";

/**
 * "Sıralı gösterim…" sorusu: kipli `<dialog>`; geçiş aralığı (5, 10, 20, 30, 60 sn; varsayılan 10) bu tarayıcıda çerezde
 * hatırlanır. Başlat aralığı yazıp `onStart` çağırır; Esc ya da İptal kapatır.
 */
export default function TourDialog({ onStart, onCancel }: { onStart: (seconds: number) => void; onCancel: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [seconds, setSeconds] = useState(DEFAULT_TOUR_S);

  useEffect(() => {
    const d = ref.current;
    const back = document.activeElement;
    setSeconds(parseTourInterval(readCookie(document.cookie, TOUR_COOKIE)));
    if (d && !d.open) d.showModal();
    return () => { if (back instanceof HTMLElement && back.isConnected) back.focus(); };
  }, []);

  const start = (e: React.FormEvent) => {
    e.preventDefault();
    document.cookie = tourCookie(seconds);
    onStart(seconds);
  };

  return (
    <dialog ref={ref} aria-label="Sıralı gösterim" onCancel={(e) => { e.preventDefault(); onCancel(); }}
            className="m-auto w-[min(320px,calc(100vw-32px))] border border-pl-ctl bg-pl-bg p-0 text-[13px] text-pl-ink backdrop:bg-black/30">
      <form onSubmit={start}>
        <h2 className="border-b border-pl-line bg-pl-head px-3 py-1.5 font-semibold">Sıralı gösterim</h2>
        <div className="grid gap-2 p-3">
          <p className="text-pl-muted">Şablondaki kameralar tek kamera görünümünde sırayla gösterilir.</p>
          <label className="grid gap-1">
            <span className="text-pl-muted">Geçiş aralığı</span>
            <select autoFocus value={seconds} onChange={(e) => setSeconds(Number(e.target.value))} className="pl-input">
              {TOUR_INTERVALS.map((s) => <option key={s} value={s}>{s} sn</option>)}
            </select>
          </label>
          <div className="flex justify-end gap-1.5">
            <button type="button" onClick={onCancel} className="pl-btn">İptal</button>
            <button type="submit" className="pl-btn pl-btn-primary">Başlat</button>
          </div>
        </div>
      </form>
    </dialog>
  );
}
