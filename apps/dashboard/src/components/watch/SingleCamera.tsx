"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/live";
import { FAILS_BEFORE_WARNING } from "@/components/live/AlarmCenter";
import { problemOf, STATUS_POLL_MS, STUCK_REBUMP_MS, stateText, type CameraStatus, type Problem } from "@/lib/views";
import ConnectionProblem from "./ConnectionProblem";
import { useStreamKey } from "./useStreamKey";

/** Sayfada olduğu gibi ("page"), video duvarında tam ekran kapsayıcıyı doldurur ("wall"), telefon yatayken ekranı kaplar ("phone") */
export type SingleMode = "page" | "wall" | "phone";

/** Kamera/kaynak silinmiş (durum isteği 404): "Kamera silinmiş." yazılır */
const GONE: CameraStatus = { name: "", state: "error", message: "Kamera silinmiş.", fps: 0, analysis: null };

/**
 * Tek kamera (çift tık / dokunuş): ham akış; "Net görüntü" ana akışa geçer. Esc, "← Izgaraya dön" ya da görüntüye
 * çift tık ile ızgaraya dönülür.
 * Kamera durumu (`cameras/status`) yoklanır: bağlı değilse görüntünün üstünde yazar. Akış şu durumlarda baştan açılır:
 * yoklama koptuktan sonra düzelince (sunucu yeniden başladı); kamera bağlı değilken 30 sn'de bir (sunucu 60 sn'den uzun
 * kesintide kamera akışını bitirir, durum yoklaması sağlıklı kalsa da görüntü kendiliğinden dönmez); bağlı değilden
 * bağlıya geçince hemen. Yoklama üst üste `FAILS_BEFORE_WARNING` kez koparsa görüntünün üstünde sunucuya ulaşılamadığı
 * (ya da oturumun dolduğu, 401) yazar; eski "canlı" durumu gösterilmez. `liveHref`: analizi varsa o oturum, yoksa Kameralar sayfası.
 * Gizli sekmede `<img>` çizilmez (akış bırakılır); silinmiş kamerada akış hatası yeniden açmayı tetiklemez.
 */
export default function SingleCamera({ sourceId, channelId, name, liveHref, mode, onClose }: {
  sourceId: string; channelId: string | null; name: string; liveHref: string; mode: SingleMode; onClose: () => void;
}) {
  const [quality, setQuality] = useState<"sub" | "main">("sub");
  const [cam, setCam] = useState<CameraStatus | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);
  const { streamKey, onError, bump, visible } = useStreamKey();
  /** Görüntüye açıldıktan sonra basılma sayısı: kutuyu açan çift tıkın artığı (ilk basışı açılıştan önce) kapatmasın */
  const presses = useRef(0);

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
    let fails = 0;                                      // üst üste başarısız yoklama
    let wasLive: boolean | null = null;                 // son bilinen durum canlı mıydı (henüz bilinmiyor: null)
    const qs = new URLSearchParams({ source: sourceId, quality });
    if (channelId) qs.set("channel", channelId);
    const poll = async () => {
      try {
        const s = await api<CameraStatus | null>(`cameras/status?${qs}`);
        if (!alive) return;
        fails = 0;
        setProblem(null);
        let live = wasLive;
        if (s && typeof s === "object" && typeof s.state === "string") {   // boş/bozuk gövde yok sayılır
          setCam(s);
          live = s.state === "live";
        }
        // Bağlı değilden bağlıya geçiş ya da yoklama düzelmesi: akış baştan (tek kez)
        if (failed || (live === true && wasLive === false)) bump();
        failed = false;
        wasLive = live;
      } catch (e) {
        if (!alive) return;
        failed = true;
        if (e instanceof ApiError && e.status === 404) {   // kamera/kaynak silinmiş
          fails = 0;
          setProblem(null);
          setCam(GONE);
          wasLive = false;
        } else {
          fails += 1;
          if (fails >= FAILS_BEFORE_WARNING) setProblem(problemOf(e));
        }
      }
      if (alive) timer = setTimeout(poll, STATUS_POLL_MS);
    };
    poll();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [sourceId, channelId, quality, bump]);

  // Kamera bağlı değilken (ya da durumu hiç alınamamışken) akış 30 sn'de bir baştan açılır; silinmiş kamerada boşuna değil
  const live = cam?.state === "live";
  const gone = cam?.message === GONE.message;
  useEffect(() => {
    if (live || gone) return;
    const t = setInterval(bump, STUCK_REBUMP_MS);
    return () => clearInterval(t);
  }, [live, gone, bump]);

  const q = new URLSearchParams({ source: sourceId, quality, k: String(streamKey) });
  if (channelId) q.set("channel", channelId);
  const overlay = mode !== "page";
  const btn = overlay
    ? "inline-flex h-8 shrink-0 items-center rounded-[2px] border border-white/40 px-2.5 text-[13px] text-white"
    : "pl-btn shrink-0";
  const state = problem ? null : cam && cam.state !== "live" ? stateText(cam) : null;
  const frame = {
    page: "relative aspect-video w-full overflow-hidden bg-black",
    wall: "relative h-screen w-screen bg-black",
    phone: "fixed inset-0 z-50 bg-black",
  }[mode];
  const header = (
    <div className={overlay ? "absolute inset-x-0 top-0 z-10 flex flex-wrap items-center gap-2 bg-black/55 p-2 text-white" : "flex flex-wrap items-center gap-1.5"}>
      <button type="button" onClick={onClose} className={btn}>← Izgaraya dön</button>
      <h2 className="min-w-0 flex-1 truncate text-[15px] font-semibold">{name}</h2>
      <Link href={liveHref} className={btn}>Canlı sayıma git</Link>
      <button type="button" aria-pressed={quality === "main"} onClick={() => setQuality(quality === "sub" ? "main" : "sub")}
              className={btn}>{quality === "sub" ? "Net görüntü" : "Hızlı görüntü"}</button>
    </div>
  );
  return (
    <section className={mode === "page" ? "grid gap-2" : undefined}>
      {!overlay && header}
      {/* Görüntüye çift tıklamak ızgaraya döner (düğme ve bağlantıdaki çift tık sayılmaz) */}
      <div className={frame} data-testid="single-camera"
           onPointerDown={() => { presses.current += 1; }}
           onDoubleClick={(e) => {
             if (presses.current < 2) return;
             if (!(e.target instanceof Element && e.target.closest("button, a"))) onClose();
           }}>
        {visible && (
          // eslint-disable-next-line @next/next/no-img-element -- canlı MJPEG akışı
          <img alt={`${name} canlı görüntü`} src={`/api/live/cameras/stream?${q}`} className="absolute inset-0 h-full w-full object-contain"
               onError={gone ? undefined : onError} />
        )}
        {(state || problem) && (
          <span role="status" className="pointer-events-none absolute inset-0 grid place-items-center p-4 text-center text-sm text-white/90">
            {problem ? <ConnectionProblem problem={problem} /> : state}
          </span>
        )}
        {overlay && header}
      </div>
    </section>
  );
}
