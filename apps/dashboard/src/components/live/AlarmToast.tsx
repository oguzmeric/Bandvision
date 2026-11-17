"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ALARM_LABELS, alarmImageUrl, type Alarm } from "@/lib/live";
import { agoText, alarmSeverity, liveStreamUrl } from "@/lib/alarmPopup.mjs";
import AlarmIcon from "./AlarmIcon";
import AlarmMedia from "./AlarmMedia";
import { ALARM_TONES } from "./AlarmViewer";

/** Köşede en çok bu kadar uyarı (ilki tam, ikincisi küçük); fazlası "+N uyarı daha" */
const SHOWN = 2;

interface Props {
  /** Gösterilecek uyarılar (gizlenmemiş; yeniden eskiye). Boşsa bölge boş kalır (ekran okuyucu bölgesi yerinde durur) */
  warnings: Alarm[];
  /** Hâlâ açık canlı oturumların kimlikleri (tam kartın canlı görüntüsü için) */
  liveSessionIds: ReadonlySet<string>;
  onAck: (a: Alarm) => Promise<boolean>;
  onFalseAlarm: (a: Alarm) => Promise<boolean>;
  /** × : kartı gizler (onay değil; alarm üstteki çubukta kalır) */
  onHide: (id: string) => void;
  /** "+N uyarı daha": ortadaki pencereyi bu alarmda (gösterilmeyen ilk uyarı) açar */
  onOpenAll: (id: string) => void;
}

function HideIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden="true">
      <path d="M4 4l8 8M12 4l-8 8" />
    </svg>
  );
}

/**
 * Sağ altta uyarı (telefon kullanımı) kartları: modal değildir, sayfayı kilitlemez ve odak çalmaz. En yeni uyarı tam kart
 * (tür renginde başlık, görüntü alanı — `AlarmMedia` "compact": canlı varsa Canlı ve alarm anı köşe penceresi —, kamera ·
 * saat · geçen süre, Gördüm / Kamerayı aç / Yanlış alarm / ×); ikincisi küçük kart (olay resmi küçüğü — canlı değil: yalnız
 * gösterilen alarm canlı akar —, kamera · saat, aynı düğmeler); fazlası "+N uyarı daha". Bölge `aria-live="assertive"`:
 * yeni uyarı ekran okuyucuda okunur. Ortadaki pencere açıkken çağıran boş liste verir (uyarılar pencerenin listesinde).
 */
export default function AlarmToast({ warnings, liveSessionIds, onAck, onFalseAlarm, onHide, onOpenAll }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<{ id: string; text: string } | null>(null);
  const [, setTick] = useState(0);
  const any = warnings.length > 0;

  // geçen süre saniyede bir (yalnız kart varken)
  useEffect(() => {
    if (!any) return;
    const t = setInterval(() => setTick((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, [any]);

  async function act(a: Alarm, kind: "ack" | "false") {
    if (kind === "false" && !confirm("Bu alarm yanlış alarm olarak işaretlensin mi? Alarm kapanır ve listede «Yanlış alarm» olarak görünür.")) return;
    setBusy(a.id);
    setError(null);
    const ok = await (kind === "ack" ? onAck(a) : onFalseAlarm(a));
    setBusy(null);
    if (!ok) {
      setError({ id: a.id, text: kind === "ack" ? "Gördüm kaydedilemedi; alarm açık kalıyor. Tekrar deneyin."
        : "Yanlış alarm kaydedilemedi. Tekrar deneyin." });
    }
  }

  const now = Date.now() / 1000;
  const shown = warnings.slice(0, SHOWN);
  const rest = warnings.slice(SHOWN);

  const buttons = (a: Alarm, small: boolean) => {
    const h = small ? "h-7 px-2.5 text-[12.5px]" : "h-8 px-3 text-[13px]";
    return (
      <div className="flex flex-wrap gap-1.5">
        <button type="button" disabled={busy === a.id} onClick={() => act(a, "ack")}
                className={`rounded-[2px] border border-nok-600 bg-nok-600 font-bold text-white hover:bg-[#c42f3f] disabled:opacity-60 ${h}`}>
          Gördüm
        </button>
        {a.sessionId && <Link href={`/live?s=${a.sessionId}`} className={`pl-btn font-semibold ${h}`}>Kamerayı aç</Link>}
        <button type="button" disabled={busy === a.id} onClick={() => act(a, "false")} className={`pl-btn ${h}`}>Yanlış alarm</button>
      </div>
    );
  };
  const errorLine = (a: Alarm) => error?.id === a.id && (
    <p role="status" data-testid="toast-error" className="text-[12.5px] font-medium text-nok-ink">{error.text}</p>
  );
  const hide = (a: Alarm, className: string) => (
    <button type="button" onClick={() => onHide(a.id)} aria-label={`Gizle: ${ALARM_LABELS[a.type]} — ${a.camera}`}
            title="Gizle (alarm üstteki çubukta kalır)" className={`grid h-7 w-7 shrink-0 place-items-center rounded-[2px] ${className}`}>
      <HideIcon />
    </button>
  );
  const clock = (a: Alarm) => new Date(a.firedAt * 1000).toLocaleTimeString("tr-TR");

  return (
    <section data-testid="alarm-toasts" aria-live="assertive" aria-label="Uyarılar"
             className="pointer-events-none fixed bottom-4 right-4 z-50 grid w-[min(23rem,calc(100vw-2rem))] gap-2">
      {shown.map((a, i) => {
        const tone = ALARM_TONES[a.type];
        // sarı başlıkta koyu yazı zaten ≥6:1; başka tür renginde (beyaz yazı) küçük başlık koyu yarı saydam zemin üstünde
        const shade = alarmSeverity(a.type) === "warning" ? "" : "rounded-[2px] bg-black/25 px-1.5";
        const label = ALARM_LABELS[a.type];
        if (i === 0) {
          const liveUrl = liveStreamUrl(a, liveSessionIds);
          return (
            <article key={a.id} data-testid="alarm-toast" data-kind={a.type} aria-label={`${label} — ${a.camera}`}
                     className="pointer-events-auto overflow-hidden rounded-[3px] border border-pl-line bg-white text-pl-ink outline outline-1 outline-black/10">
              <header className={`flex items-center gap-2 px-2.5 py-1.5 ${tone.head}`}>
                <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-[4px] bg-white ${tone.icon}`} aria-hidden="true">
                  <AlarmIcon type={a.type} className="h-[18px] w-[18px]" />
                </span>
                <p className="min-w-0 flex-1 truncate text-[14px] font-bold">
                  <span className={shade} data-testid="toast-title">{label}</span>
                </p>
                {hide(a, alarmSeverity(a.type) === "warning" ? "hover:bg-black/10" : "hover:bg-white/15")}
              </header>
              <AlarmMedia alarm={a} liveUrl={liveUrl} initial={liveUrl ? "live" : "clip"} size="compact" />
              <div className="grid gap-2 px-2.5 py-2">
                <p data-testid="toast-meta" className="truncate text-[12.5px] tabular-nums text-pl-muted">
                  <b className="font-semibold text-pl-ink" title={a.camera}>{a.camera}</b> · {clock(a)} · {agoText(now - a.firedAt)}
                </p>
                {errorLine(a)}
                {buttons(a, false)}
              </div>
            </article>
          );
        }
        return (
          <article key={a.id} data-testid="alarm-toast" data-kind={a.type} data-compact="true" aria-label={`${label} — ${a.camera}`}
                   className={`pointer-events-auto flex gap-2.5 overflow-hidden rounded-[3px] border border-l-4 border-pl-line bg-white p-2 text-pl-ink outline outline-1 outline-black/10 ${tone.edge}`}>
            <span className="grid h-14 w-20 shrink-0 place-items-center overflow-hidden rounded-[2px] bg-[#111]">
              {a.image
                // eslint-disable-next-line @next/next/no-img-element -- yerel olay resmi küçüğü (canlı değil: bağlantı sınırı)
                ? <img src={alarmImageUrl(a.id)} alt="" className="h-full w-full object-cover" />
                : <AlarmIcon type={a.type} className="h-6 w-6 text-white/75" />}
            </span>
            <div className="grid min-w-0 flex-1 gap-1.5">
              <div className="flex min-w-0 items-start gap-1">
                <p className="min-w-0 flex-1 text-[12.5px]">
                  <span className="flex items-center gap-1 truncate font-semibold">
                    <AlarmIcon type={a.type} className={`h-3.5 w-3.5 shrink-0 ${tone.icon}`} />{label}
                  </span>
                  <span className="block truncate tabular-nums text-pl-muted">
                    <span title={a.camera}>{a.camera}</span> · {clock(a)} · {agoText(now - a.firedAt)}
                  </span>
                </p>
                {hide(a, "-mr-1 -mt-1 text-pl-muted hover:bg-pl-head")}
              </div>
              {errorLine(a)}
              {buttons(a, true)}
            </div>
          </article>
        );
      })}
      {rest.length > 0 && (
        <button type="button" data-testid="toast-more" onClick={() => onOpenAll(rest[0].id)}
                className="pointer-events-auto justify-self-end rounded-[2px] border border-pl-line bg-white px-3 py-1.5 text-[13px] font-semibold text-pl-ink hover:bg-pl-head">
          +{rest.length} uyarı daha
        </button>
      )}
    </section>
  );
}
