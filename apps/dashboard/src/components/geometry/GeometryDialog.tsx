"use client";

import { useEffect, useRef, useState } from "react";
import { DEFAULT_GEOMETRY, type Geometry } from "@/lib/geometry";
import GeometryControls from "./GeometryControls";
import RoiEditor from "./RoiEditor";

/** Videonun bir karesini tarayıcıda çıkarır (yükleme öncesi; video sunucuya gitmeden). */
export function useVideoFrame(file: File | null, at = 1.0): { src: string | null; aspect: number; error: string | null } {
  const [state, setState] = useState<{ src: string | null; aspect: number; error: string | null }>(
    { src: null, aspect: 16 / 9, error: null });
  useEffect(() => {
    if (!file) return;
    let cancelled = false;
    const url = URL.createObjectURL(file);
    const v = document.createElement("video");
    v.muted = true;
    v.preload = "auto";
    v.src = url;
    const fail = () => !cancelled && setState({ src: null, aspect: 16 / 9,
      error: "Bu video tarayıcıda önizlenemiyor (kodek). Alanı ayarlamadan da analiz edebilirsin: tüm görüntü kullanılır." });
    v.onerror = fail;
    v.onloadedmetadata = () => { v.currentTime = Math.min(at, Math.max(0, (v.duration || 0) / 2)); };
    v.onseeked = () => {
      if (cancelled) return;
      const c = document.createElement("canvas");
      c.width = v.videoWidth;
      c.height = v.videoHeight;
      const ctx = c.getContext("2d");
      if (!ctx || !c.width || !c.height) return fail();
      ctx.drawImage(v, 0, 0);
      setState({ src: c.toDataURL("image/jpeg", 0.85), aspect: c.width / c.height, error: null });
    };
    return () => { cancelled = true; URL.revokeObjectURL(url); v.removeAttribute("src"); };
  }, [file, at]);
  return file ? state : { src: null, aspect: 16 / 9, error: null };
}

export default function GeometryDialog({ file, initial, twoWay, allowAngled, onSave, onClose }: {
  file: File; initial: Geometry | null; twoWay: boolean; allowAngled: boolean;
  onSave: (g: Geometry) => void; onClose: () => void;
}) {
  const frame = useVideoFrame(file);
  const [g, setG] = useState<Geometry>(initial ?? DEFAULT_GEOMETRY);
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    dialog.current?.showModal();
  }, []);

  return (
    <dialog ref={dialog} onClose={onClose} aria-labelledby="geom-title"
            className="m-auto w-[min(1100px,96vw)] rounded-[3px] border border-pl-line bg-white p-0 text-[13px] text-pl-ink backdrop:bg-black/30">
      <div className="border-b border-pl-line bg-pl-head px-4 py-2">
        <p id="geom-title" className="text-[14px] font-semibold">Alanı ve sayım çizgisini ayarla</p>
        <p className="text-[12.5px] text-pl-muted">
          Sarı alan sayılacak bölge, turuncu çizgi sayım çizgisi; ok {twoWay ? "giriş" : "akış"} yönünü gösterir.
        </p>
      </div>
      <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0">
          {frame.error ? (
            <p className="rounded-[2px] border border-warn-line bg-warn-50 px-3 py-2 text-[13px] text-warn-700">{frame.error}</p>
          ) : (
            <RoiEditor src={frame.src} aspect={frame.aspect} value={g} onChange={setG} twoWay={twoWay} />
          )}
        </div>
        <div className="flex flex-col">
          <GeometryControls value={g} onChange={setG} aspect={frame.aspect} twoWay={twoWay} allowAngled={allowAngled} />
          {twoWay && (
            <p className="mt-3 rounded-[2px] border border-pl-sel-line bg-pl-sel px-2.5 py-1.5 text-[12px] text-pl-ink">
              Çizgiyi kişilerin tamamen geçtiği yere, yürüme alanının ortasına koy — kapı eşiğine değil.
            </p>
          )}
          <div className="mt-auto flex gap-2 pt-4">
            <button type="button" onClick={() => setG(DEFAULT_GEOMETRY)} className="pl-btn h-8">Sıfırla</button>
            <button type="button" onClick={() => dialog.current?.close()} className="pl-btn h-8 flex-1 justify-center">Vazgeç</button>
            <button type="button" disabled={!!frame.error}
                    onClick={() => { onSave(g); dialog.current?.close(); }}
                    className="pl-btn pl-btn-primary h-8 flex-1 justify-center">Kaydet</button>
          </div>
        </div>
      </div>
    </dialog>
  );
}
