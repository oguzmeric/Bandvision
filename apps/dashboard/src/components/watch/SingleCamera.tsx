"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/live";
import { STATUS_POLL_MS, stateText, type CameraStatus } from "@/lib/views";
import { useStreamKey } from "./useStreamKey";

/** Sayfada olduğu gibi ("page"), video duvarında tam ekran kapsayıcıyı doldurur ("wall"), telefon yatayken ekranı kaplar ("phone") */
export type SingleMode = "page" | "wall" | "phone";

/**
 * Tek kamera (çift tık / dokunuş): ham akış; "Net görüntü" ana akışa geçer. Esc/Geri ile ızgaraya dönülür.
 * Kamera durumu (`cameras/status`) yoklanır: bağlı değilse görüntünün üstünde yazar; yoklama koptuktan sonra düzelirse
 * (sunucu yeniden başladı) akış baştan açılır. `liveHref`: analizi varsa o oturum, yoksa Kameralar sayfası.
 */
export default function SingleCamera({ sourceId, channelId, name, liveHref, mode, onClose }: {
  sourceId: string; channelId: string | null; name: string; liveHref: string; mode: SingleMode; onClose: () => void;
}) {
  const [quality, setQuality] = useState<"sub" | "main">("sub");
  const [cam, setCam] = useState<CameraStatus | null>(null);
  const { streamKey, onError, bump } = useStreamKey();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      // Üstteki pencere (ör. alarm penceresi) kendi Esc'ini işler; altındaki tek kamera kapanmaz
      if (e.target instanceof Element && e.target.closest("dialog")) return;
      onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failed = false;
    const qs = new URLSearchParams({ source: sourceId, quality });
    if (channelId) qs.set("channel", channelId);
    const poll = async () => {
      try {
        const s = await api<CameraStatus | null>(`cameras/status?${qs}`);
        if (!alive) return;
        if (s && typeof s === "object" && typeof s.state === "string") setCam(s);   // boş/bozuk gövde yok sayılır
        if (failed) { failed = false; bump(); }
      } catch {
        if (alive) failed = true;
      }
      if (alive) timer = setTimeout(poll, STATUS_POLL_MS);
    };
    poll();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [sourceId, channelId, quality, bump]);

  const q = new URLSearchParams({ source: sourceId, quality, k: String(streamKey) });
  if (channelId) q.set("channel", channelId);
  const overlay = mode !== "page";
  const btn = `h-9 shrink-0 rounded-[10px] border px-3 text-sm ${overlay ? "border-white/40 text-white" : "border-line"}`;
  const state = cam && cam.state !== "live" ? stateText(cam) : null;
  const frame = {
    page: "relative aspect-video w-full overflow-hidden rounded-2xl bg-black",
    wall: "relative h-screen w-screen bg-black",
    phone: "fixed inset-0 z-50 bg-black",
  }[mode];
  const header = (
    <div className={overlay ? "absolute inset-x-0 top-0 z-10 flex flex-wrap items-center gap-2 bg-black/55 p-2 text-white" : "flex flex-wrap items-center gap-2"}>
      <button type="button" onClick={onClose} className={btn}>← Izgaraya dön</button>
      <h2 className="min-w-0 flex-1 truncate text-lg font-semibold">{name}</h2>
      <Link href={liveHref} className={`${btn} inline-flex items-center`}>Canlı sayıma git</Link>
      <button type="button" aria-pressed={quality === "main"} onClick={() => setQuality(quality === "sub" ? "main" : "sub")}
              className={btn}>{quality === "sub" ? "Net görüntü" : "Hızlı görüntü"}</button>
    </div>
  );
  return (
    <section className={mode === "page" ? "grid gap-3" : undefined}>
      {!overlay && header}
      <div className={frame}>
        {/* eslint-disable-next-line @next/next/no-img-element -- canlı MJPEG akışı */}
        <img alt={`${name} canlı görüntü`} src={`/api/live/cameras/stream?${q}`} className="absolute inset-0 h-full w-full object-contain" onError={onError} />
        {state && (
          <span role="status" className="pointer-events-none absolute inset-0 grid place-items-center p-4 text-center text-sm text-white/90">
            {state}
          </span>
        )}
        {overlay && header}
      </div>
    </section>
  );
}
