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

/** Küçük resim: kayıt cihazının görüntü API'si ya da RTSP'den ilk kare */
export default function Thumb({ src, alt }: { src: string; alt: string }) {
  const [state, setState] = useState<"waiting" | "loading" | "ok" | "error">("waiting");
  const release = useRef<(() => void) | null>(null);
  useEffect(() => {
    let cancelled = false;
    thumbSlot().then((r) => {
      if (cancelled) { r(); return; }
      release.current = r;
      setState("loading");
    });
    return () => { cancelled = true; release.current?.(); release.current = null; };
  }, [src]);
  const done = (ok: boolean) => { setState(ok ? "ok" : "error"); release.current?.(); release.current = null; };
  return (
    <div className="relative aspect-video overflow-hidden rounded-xl bg-[#111]">
      {(state === "loading" || state === "ok") && (
        // eslint-disable-next-line @next/next/no-img-element -- kamera küçük resmi (yerel sunucudan)
        <img src={src} alt={alt} onLoad={() => done(true)} onError={() => done(false)}
             className={`h-full w-full object-cover transition-opacity ${state === "ok" ? "opacity-100" : "opacity-0"}`} />
      )}
      {(state === "waiting" || state === "loading") && <div className="absolute inset-0 animate-pulse bg-white/5" />}
      {state === "error" && <p className="absolute inset-0 grid place-items-center px-3 text-center text-xs text-white/60">Görüntü yok</p>}
    </div>
  );
}
