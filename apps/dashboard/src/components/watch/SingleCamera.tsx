"use client";

import { useEffect, useState } from "react";
import { useStreamKey } from "./useStreamKey";

/** Tek kamera (çift tık): ham akış; "Net görüntü" ana akışa geçer. Esc/Geri ile ızgaraya dönülür. */
export default function SingleCamera({ sourceId, channelId, name, onClose }: {
  sourceId: string; channelId: string | null; name: string; onClose: () => void;
}) {
  const [quality, setQuality] = useState<"sub" | "main">("sub");
  const { streamKey, onError } = useStreamKey();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const q = new URLSearchParams({ source: sourceId, quality, k: String(streamKey) });
  if (channelId) q.set("channel", channelId);
  return (
    <section className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={onClose} className="h-9 rounded-[10px] border border-line px-3 text-sm">← Izgaraya dön</button>
        <h2 className="min-w-0 flex-1 truncate text-lg font-semibold">{name}</h2>
        <button type="button" aria-pressed={quality === "main"} onClick={() => setQuality(quality === "sub" ? "main" : "sub")}
                className="h-9 rounded-[10px] border border-line px-3 text-sm">{quality === "sub" ? "Net görüntü" : "Hızlı görüntü"}</button>
      </div>
      {/* eslint-disable-next-line @next/next/no-img-element -- canlı MJPEG akışı */}
      <img alt={`${name} canlı görüntü`} src={`/api/live/cameras/stream?${q}`} className="w-full rounded-2xl bg-black object-contain"
           onError={onError} />
    </section>
  );
}
