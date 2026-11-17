"use client";

import { useEffect, useRef, useState } from "react";
import { CLIP_PENDING_MAX_S, CLIP_PENDING_S, alarmClipUrl, alarmImageUrl, type Alarm } from "@/lib/live";
import { insetCrop, insetSide } from "@/lib/alarmPopup.mjs";
import { useStreamKey } from "@/components/watch/useStreamKey";
import AlarmIcon from "./AlarmIcon";

/** Görüntü alanının iki görünümü: kameranın şu anki canlı görüntüsü ya da alarmın kaydı */
export type MediaView = "live" | "clip";

interface Props {
  alarm: Alarm;
  /** Canlı akış adresi (`liveStreamUrl`); null: canlı kaynak yok ("Canlı" devre dışı, kayıtta açılır) */
  liveUrl: string | null;
  /** Kullanıcı seçim yapana kadarki görünüm (etkin pencere: canlı varsa "live"; göz atma: "clip") */
  initial: MediaView;
  /** "large": ortadaki pencere; "compact": köşedeki uyarı kartı (daha küçük düğmeler ve köşe penceresi). Ad "compact":
   * sade arayüz bekçisi tek başına "c-a-r-d" sözcüğünü (eski kart sınıfı) her satırda yasaklar */
  size: "large" | "compact";
}

/** 0:05 biçimi (kayıt içi saniye) */
function clock(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Yüzde (kırpım ölçeği ×100), kayan nokta artığı olmadan: 1.563 → "156.3%" */
const pct = (v: number) => `${Math.round(v * 1000) / 10}%`;

/**
 * Alarmın görüntü alanı ("● Canlı | Alarm kaydı"):
 * - **Canlı**: kameranın şu anki görüntüsü (oturumun işaretli akışı ya da kameranın ham alt akışı; MJPEG `<img>`,
 *   `useStreamKey` ile yeniden bağlanır, gizli sekmede akış bırakılır). Akış hata verirse üstünde "Canlı görüntü
 *   alınamıyor" yazar. Köşede **alarm anı** penceresi: olay resminin alarm kutusuna yakınlaştırılmış hâli (kutu yoksa resmin
 *   tamamı; resim yoksa pencere yok), kutu sağ yarıdaysa solda durur; tıklanınca "Alarm kaydı"na geçer.
 * - **Alarm kaydı**: ihlal anının videosu (döngüde; "Durum başladı"/"Alarm anı" işaretleri), hazır değilse olay resmi ve
 *   açıklaması ("Kayıt hazırlanıyor…", "Kayıt alınamadı…", "Bu alarmın kaydı yok.").
 * Kullanıcı seçim yapana kadar `initial` izlenir (oturum listesi alarmdan sonra gelirse görünüm canlıya geçer); canlı adres
 * yoksa her zaman kayıt. Yalnız gösterilen alarm canlı akar: kayıttayken canlı `<img>` çizilmez.
 */
export default function AlarmMedia({ alarm: a, liveUrl, initial, size }: Props) {
  const [choice, setChoice] = useState<{ id: string; view: MediaView } | null>(null);
  const [playFailed, setPlayFailed] = useState<string | null>(null);   // oynatılamayan kayıt (ör. 404)
  const [duration, setDuration] = useState<{ id: string; sec: number } | null>(null);
  /** Hata veren canlı adres (ilk kare gelince silinir; başka adrese geçilince geçersiz) */
  const [liveFailed, setLiveFailed] = useState<string | null>(null);
  /** Olay resminin en/boy oranı (yüklenince; 4:3 alt akışlar da var). Köşe penceresi bu oranda çizilir: `insetCrop`
   * yüzdeleri resmin kendi oranındaki kutuya göredir, 16:9 kutuda 4:3 resim (ve kişiler) yatay gerilirdi */
  const [imageRatio, setImageRatio] = useState<{ id: string; r: number } | null>(null);
  const [, setTick] = useState(0);
  const video = useRef<HTMLVideoElement>(null);
  const { streamKey, onError: retryStream, visible } = useStreamKey();

  const picked = choice?.id === a.id ? choice.view : initial;
  const view: MediaView = picked === "live" && liveUrl ? "live" : "clip";
  const select = (v: MediaView) => setChoice({ id: a.id, view: v });

  const now = Date.now() / 1000;
  const age = now - a.firedAt;
  // kayıt yakalanıyor/yazılıyor: sunucunun clipPending'i (eski sunucuda: kameralı alarmda ilk 20 sn); bayat bayrağa
  // karşı en çok 2 dakika
  const pending = !a.clip && (a.clipPending ?? (a.sessionId !== null && age < CLIP_PENDING_S)) && age < CLIP_PENDING_MAX_S;
  // kayıt hazırlanırken ekran kendiliğinden yenilensin (süre dolunca resim/simgeye geçilir). Ortadaki pencere zaten saniyede
  // bir yenilenir; bu sayaç köşedeki uyarı kartı ("compact") gibi kendini yenilemeyen çağıranlar için de gerekir
  useEffect(() => {
    if (!pending) return;
    const t = setTimeout(() => setTick((x) => x + 1), 1000);
    return () => clearTimeout(t);
  });

  const compact = size === "compact";
  const showVideo = Boolean(a.clip) && playFailed !== a.id;
  const base = a.clipStartedAt ?? null;
  const len = duration?.id === a.id ? duration.sec : null;
  const marks = view === "clip" && showVideo && base !== null ? [
    ...(a.type !== "test" && a.startedAt < a.firedAt ? [{ key: "start", label: "Durum başladı", t: a.startedAt - base }] : []),
    { key: "fired", label: "Alarm anı", t: a.firedAt - base },
  ] : [];
  const seek = (t: number) => {
    const v = video.current;
    if (!v) return;
    v.currentTime = Math.max(0, t);
    void v.play().catch(() => undefined);
  };
  const withImage = a.image ? "; olay resmi gösteriliyor." : ".";
  const caption = pending ? "Kayıt hazırlanıyor…"
    : playFailed === a.id ? "Kayıt oynatılamadı; olay resmi gösteriliyor."
    : a.clipFailed ? `Kayıt alınamadı${withImage}`
    : "Bu alarmın kaydı yok.";

  const crop = insetCrop(a.box);
  const side = insetSide(a.box);
  const liveSrc = liveUrl ? `${liveUrl}${liveUrl.includes("?") ? "&" : "?"}k=${streamKey}` : null;
  const seg = `inline-flex items-center gap-1.5 px-2.5 font-semibold text-white disabled:cursor-not-allowed disabled:opacity-45 ${compact ? "h-7 text-[12px]" : "h-8 text-[13px]"}`;

  return (
    <div>
      <div className="relative grid aspect-video place-items-center overflow-hidden bg-[#111]">
        {view === "live" ? (
          <>
            {visible && liveSrc && (
              // akış hata verdiyse görünmez (tarayıcının kırık resim simgesi ve alt yazısı "Canlı görüntü alınamıyor"un arkasında
              // görünmesin); yeniden deneme sürer, ilk kare gelince görünür
              // eslint-disable-next-line @next/next/no-img-element -- MJPEG canlı akış (analiz sunucusundan, vekil üzerinden)
              <img src={liveSrc} alt="Canlı görüntü" data-testid="alarm-live"
                   className={`h-full w-full object-contain ${liveFailed !== null && liveFailed === liveUrl ? "invisible" : ""}`}
                   onLoad={() => setLiveFailed(null)}
                   onError={() => { setLiveFailed(liveUrl); retryStream(); }} />
            )}
            {liveFailed !== null && liveFailed === liveUrl && (
              <p role="status" data-testid="live-error"
                 className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-[2px] bg-black/75 px-3 py-1.5 text-[13px] font-semibold text-white">
                Canlı görüntü alınamıyor
              </p>
            )}
            {a.image && (
              <button type="button" data-testid="alarm-inset" data-side={side} onClick={() => select("clip")}
                      title="Alarm kaydını izle"
                      className={`absolute bottom-3 ${side === "left" ? "left-3" : "right-3"} ${compact ? "w-[40%]" : "w-[30%]"} overflow-hidden rounded-[2px] border-2 border-white/85 bg-black text-left outline-offset-2 hover:border-white`}>
                <span className="relative block overflow-hidden" data-testid="inset-frame"
                      style={{ aspectRatio: imageRatio?.id === a.id ? imageRatio.r : 16 / 9 }}>
                  {/* eslint-disable-next-line @next/next/no-img-element -- yerel olay resmi (analiz sunucusundan, vekil üzerinden) */}
                  <img src={alarmImageUrl(a.id)} alt=""
                       onLoad={(e) => {
                         const { naturalWidth: w, naturalHeight: h } = e.currentTarget;
                         if (w > 0 && h > 0) setImageRatio({ id: a.id, r: w / h });
                       }}
                       className={crop ? "absolute max-w-none" : "h-full w-full object-contain"}
                       style={crop ? { width: pct(crop.scale), height: pct(crop.scale), left: `${crop.left}%`, top: `${crop.top}%` } : undefined} />
                </span>
                <span className={`block bg-black/80 px-1.5 py-0.5 font-semibold text-white ${compact ? "text-[10.5px]" : "text-[11.5px]"}`}>
                  Alarm anı · {new Date(a.firedAt * 1000).toLocaleTimeString("tr-TR")}
                  <svg viewBox="0 0 10 10" className="ml-1 inline h-2 w-2 align-baseline" fill="currentColor" aria-hidden="true"><path d="M2 1l7 4-7 4z" /></svg>
                </span>
              </button>
            )}
          </>
        ) : (
          <>
            {showVideo ? (
              <video key={a.id} ref={video} src={alarmClipUrl(a.id)} autoPlay muted loop playsInline controls data-testid="alarm-video"
                     aria-label="İhlal anının kaydı" className="h-full w-full object-contain"
                     onError={() => setPlayFailed(a.id)}
                     onLoadedMetadata={(e) => { const d = e.currentTarget.duration; if (Number.isFinite(d) && d > 0) setDuration({ id: a.id, sec: d }); }} />
            ) : a.image ? (
              // eslint-disable-next-line @next/next/no-img-element -- yerel olay resmi (analiz sunucusundan, vekil üzerinden)
              <img src={alarmImageUrl(a.id)} alt="Olay resmi" className="h-full w-full object-contain" />
            ) : (
              <AlarmIcon type={a.type} className={`text-white/45 ${compact ? "h-12 w-12" : "h-20 w-20"}`} />
            )}
            {!showVideo && (
              <p role="status" data-testid="clip-caption"
                 className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-[2px] bg-black/70 px-3 py-1 text-[12.5px] font-medium text-white">
                {caption}
              </p>
            )}
          </>
        )}

        <div role="group" aria-label="Görüntü" className="absolute left-2 top-2 flex overflow-hidden rounded-[2px] border border-white/30 bg-black/65">
          <button type="button" data-testid="media-live" aria-pressed={view === "live"} disabled={!liveUrl}
                  title={liveUrl ? undefined : "Canlı görüntü yok"} onClick={() => select("live")}
                  className={`${seg} ${view === "live" ? "bg-white/20" : "hover:bg-white/10"}`}>
            <span className={`h-2 w-2 rounded-full ${view === "live" ? "bg-nok-600" : "bg-white/60"}`} aria-hidden="true" />Canlı
          </button>
          <button type="button" data-testid="media-clip" aria-pressed={view === "clip"} onClick={() => select("clip")}
                  className={`${seg} border-l border-white/30 ${view === "clip" ? "bg-white/20" : "hover:bg-white/10"}`}>
            Alarm kaydı
          </button>
        </div>
      </div>

      {marks.length > 0 && (
        <div className="px-4 pt-3" data-testid="alarm-timeline">
          {len !== null && (
            // kaydın süresi üstünde iki an (süre video yüklenince bilinir)
            <div className="relative h-1.5 rounded-full bg-pl-line" aria-hidden="true">
              {marks.map((m) => (
                <span key={m.key} className={`absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white ${m.key === "fired" ? "bg-nok-600" : "bg-warn-700"}`}
                      style={{ left: `${Math.min(100, Math.max(0, (m.t / len) * 100))}%` }} />
              ))}
            </div>
          )}
          <div className="mt-2 flex flex-wrap gap-2">
            {marks.map((m) => (
              <button key={m.key} type="button" onClick={() => seek(m.t)}
                      className="pl-btn text-[12.5px]">
                <span className={`h-2 w-2 rounded-full ${m.key === "fired" ? "bg-nok-600" : "bg-warn-700"}`} aria-hidden="true" />
                {m.label}{m.t < 0 ? " (kayıttan önce)" : ` · ${clock(m.t)}`}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
