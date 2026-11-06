"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Küçük resimler sırayla (en çok 3 aynı anda): tarayıcı aynı adrese 6 bağlantı açar; görüntüsü gelmeyen kameralar
 * hepsini tutunca profil listesi, kaydet gibi istekler sırada bekliyordu.
 */
const MAX_THUMBS = 3;
let activeThumbs = 0;
const waitingThumbs: Array<() => void> = [];

function thumbSlot(): Promise<() => void> {
  return new Promise((resolve) => {
    const go = () => {
      activeThumbs++;
      let released = false;
      resolve(() => {
        if (released) return;
        released = true;
        activeThumbs--;
        waitingThumbs.shift()?.();
      });
    };
    if (activeThumbs < MAX_THUMBS) go();
    else waitingThumbs.push(go);
  });
}

/**
 * Küçük resim: kayıt cihazının görüntü API'si ya da RTSP'den ilk kare. Resim `fetch` ile alınır (yanıt başlığı
 * okunabilsin): sunucu `X-Sub-Dead: 1` derse (kanalın alt akışı görüntü vermiyor, resim ana akıştan) `onSubDead`.
 */
export default function Thumb({ src, alt, onSubDead }: { src: string; alt: string; onSubDead?: () => void }) {
  const [state, setState] = useState<"waiting" | "loading" | "ok" | "error">("waiting");
  const [url, setUrl] = useState<string | null>(null);
  const subDead = useRef(onSubDead);
  useEffect(() => { subDead.current = onSubDead; }, [onSubDead]);
  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    let release: (() => void) | null = null;
    const ctrl = new AbortController();
    thumbSlot().then(async (r) => {
      if (cancelled) { r(); return; }
      release = r;
      setState("loading");
      try {
        const res = await fetch(src, { cache: "no-store", signal: ctrl.signal });
        if (!res.ok) throw new Error(String(res.status));
        const blob = await res.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
        if (res.headers.get("x-sub-dead") === "1") subDead.current?.();
      } catch {
        if (!cancelled) setState("error");
      } finally {
        release?.();
        release = null;
      }
    });
    return () => {
      cancelled = true;
      ctrl.abort();
      release?.();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src]);
  return (
    <div className="relative aspect-video overflow-hidden rounded-[2px] bg-[#111]">
      {url && (state === "loading" || state === "ok") && (
        // eslint-disable-next-line @next/next/no-img-element -- kamera küçük resmi (yerel sunucudan, nesne adresi)
        <img src={url} alt={alt} onLoad={() => setState("ok")} onError={() => setState("error")}
             className={`h-full w-full object-cover transition-opacity ${state === "ok" ? "opacity-100" : "opacity-0"}`} />
      )}
      {(state === "waiting" || state === "loading") && <div className="absolute inset-0 animate-pulse bg-white/5" />}
      {state === "error" && <p className="absolute inset-0 grid place-items-center px-3 text-center text-xs text-white/60">Görüntü yok</p>}
    </div>
  );
}
