"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ALARM_TITLES, CLIP_PENDING_S, NOTIFY_LABELS, alarmClipUrl, alarmImageUrl, type Alarm } from "@/lib/live";

/** "active": onaylanmamış alarmlar (alarm penceresi, Küçült); "browse": geçmiş alarmlar (Alarmlar sayfası, Son alarmlar) */
export type ViewerMode = "active" | "browse";

interface Props {
  /** Gezinilen alarmlar, yeniden eskiye */
  alarms: Alarm[];
  /** Gösterilen alarm (listede yoksa ilk alarm) */
  id: string;
  mode: ViewerMode;
  onSelect: (id: string) => void;
  /** Küçült (etkin) / Kapat (göz atma); Esc de bunu yapar — asla "Gördüm" değil */
  onClose: () => void;
  onAck: (a: Alarm) => Promise<boolean>;
  onFalseAlarm: (a: Alarm) => Promise<boolean>;
}

const FOCUSABLE = 'a[href], button:not([disabled]), video[controls], [tabindex]:not([tabindex="-1"])';

/** 0:05 biçimi (kayıt içi saniye) */
function clock(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * Alarm penceresi: büyük kırmızı başlık (tür, kamera, tarih-saat, sürüyor/süre), ihlal anının kaydı (video; hazır
 * değilse olay resmi), kayıt içinde durumun başladığı ve alarmın verildiği an (tıklayınca oraya atlar), Gördüm /
 * Kamerayı aç / Yanlış alarm / Küçült. Birden çok alarmda "1 / 3" ve ‹ › ile gezinilir.
 * Erişilebilirlik: `role="alertdialog"`, açılınca odak pencereye gelir ve içinde kalır (Tab döner); Esc küçültür.
 */
export default function AlarmViewer({ alarms, id, mode, onSelect, onClose, onAck, onFalseAlarm }: Props) {
  const index = Math.max(0, alarms.findIndex((x) => x.id === id));
  const a = alarms[index];
  const dialog = useRef<HTMLDivElement>(null);
  const primary = useRef<HTMLButtonElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ id: string; text: string } | null>(null);
  const [clipFailed, setClipFailed] = useState<string | null>(null);
  const [duration, setDuration] = useState<{ id: string; sec: number } | null>(null);
  const [, setTick] = useState(0);

  // açılınca odak pencereye (Gördüm varsa ona); kapanınca önceki öğeye geri
  useEffect(() => {
    const before = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    (primary.current ?? dialog.current)?.focus();
    return () => { if (before && document.contains(before)) before.focus(); };
  }, []);

  // Esc: odak pencerede ya da hiçbir yerde değilse (arka plana tıklandı) küçültür
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      const el = document.activeElement;
      if (dialog.current && (dialog.current.contains(el) || el === document.body || el === null)) {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const now = Date.now() / 1000;
  const pending = a ? !a.clip && now - a.firedAt < CLIP_PENDING_S : false;
  // kayıt hazırlanırken ekran kendiliğinden yenilensin (20 sn sonra resim/simgeye geçilir)
  useEffect(() => {
    if (!pending) return;
    const t = setTimeout(() => setTick((x) => x + 1), 1000);
    return () => clearTimeout(t);
  });

  if (!a) return null;

  function trap(e: React.KeyboardEvent) {
    if (e.key !== "Tab" || !dialog.current) return;
    const items = [...dialog.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    if (items.length === 0) { e.preventDefault(); return; }
    const first = items[0], last = items[items.length - 1];
    const cur = document.activeElement;
    if (e.shiftKey && (cur === first || cur === dialog.current)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && cur === last) { e.preventDefault(); first.focus(); }
  }

  async function act(kind: "ack" | "false") {
    if (kind === "false" && !confirm("Bu alarm yanlış alarm olarak işaretlensin mi? Alarm kapanır ve listede «Yanlış alarm» olarak görünür.")) return;
    setBusy(true);
    setError(null);
    const ok = await (kind === "ack" ? onAck(a) : onFalseAlarm(a));
    setBusy(false);
    if (!ok) setError({ id: a.id, text: kind === "ack" ? "Gördüm kaydedilemedi; alarm açık kalıyor. Tekrar deneyin." : "Yanlış alarm kaydedilemedi. Tekrar deneyin." });
  }

  const showVideo = Boolean(a.clip) && clipFailed !== a.id;
  const ongoing = a.type !== "test" && a.endedAt === null;
  const base = a.clipStartedAt ?? null;
  const len = duration?.id === a.id ? duration.sec : null;
  const marks = showVideo && base !== null ? [
    ...(a.type !== "test" && a.startedAt < a.firedAt ? [{ key: "start", label: "Durum başladı", t: a.startedAt - base }] : []),
    { key: "fired", label: "Alarm anı", t: a.firedAt - base },
  ] : [];
  const seek = (t: number) => {
    const v = video.current;
    if (!v) return;
    v.currentTime = Math.max(0, t);
    void v.play().catch(() => undefined);
  };
  const caption = pending ? "Kayıt hazırlanıyor…" : clipFailed === a.id ? "Kayıt oynatılamadı; olay resmi gösteriliyor." : "Bu alarmın kaydı yok.";

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-[#1d1a2e]/70 p-3 backdrop-blur-[2px] md:p-6">
      <div ref={dialog} role="alertdialog" aria-modal="true" aria-label="Güvenlik alarmı" tabIndex={-1} onKeyDown={trap}
           data-testid="alarm-modal"
           className="grid max-h-[calc(100vh-1.5rem)] w-full max-w-3xl grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden rounded-3xl bg-white shadow-2xl outline-none">
        <header className="flex flex-wrap items-start gap-x-4 gap-y-2 bg-nok-600 px-5 py-4 text-white">
          <span className="mt-0.5 text-3xl" aria-hidden="true">🚨</span>
          <div className="min-w-0 flex-1">
            <p className="text-2xl font-bold tracking-wide md:text-[28px]" data-testid="alarm-title">{ALARM_TITLES[a.type]}</p>
            <p className="mt-0.5 truncate text-[15px] font-semibold">{a.camera}</p>
            <p className="text-[13px] text-white/85" data-testid="alarm-time">{new Date(a.firedAt * 1000).toLocaleString("tr-TR")}</p>
          </div>
          <div className="flex flex-col items-end gap-2">
            {ongoing ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-2.5 py-1 text-[12px] font-bold text-nok-600" data-testid="alarm-status">
                <span className="h-2 w-2 animate-pulse rounded-full bg-nok-600" aria-hidden="true" />devam ediyor
              </span>
            ) : a.endedAt !== null && (
              <span className="rounded-full bg-white/20 px-2.5 py-1 text-[12px] font-semibold" data-testid="alarm-status">
                Süre: {Math.max(0, Math.round(a.endedAt - a.startedAt))} sn
              </span>
            )}
            {alarms.length > 1 && (
              <div className="flex items-center gap-1 text-[13px] font-semibold">
                <button type="button" aria-label="Önceki alarm" disabled={index === 0} onClick={() => onSelect(alarms[index - 1].id)}
                        className="grid h-7 w-7 place-items-center rounded-lg bg-white/15 text-base hover:bg-white/25 disabled:opacity-40">‹</button>
                <span data-testid="alarm-counter" className="min-w-12 text-center tabular-nums">{index + 1} / {alarms.length}</span>
                <button type="button" aria-label="Sonraki alarm" disabled={index === alarms.length - 1} onClick={() => onSelect(alarms[index + 1].id)}
                        className="grid h-7 w-7 place-items-center rounded-lg bg-white/15 text-base hover:bg-white/25 disabled:opacity-40">›</button>
              </div>
            )}
          </div>
        </header>

        <div className="overflow-auto">
          <div className="relative grid aspect-video place-items-center bg-[#0e0c17]">
            {showVideo ? (
              <video key={a.id} ref={video} src={alarmClipUrl(a.id)} autoPlay muted loop playsInline controls data-testid="alarm-video"
                     aria-label="İhlal anının kaydı" className="h-full w-full object-contain"
                     onError={() => setClipFailed(a.id)}
                     onLoadedMetadata={(e) => { const d = e.currentTarget.duration; if (Number.isFinite(d) && d > 0) setDuration({ id: a.id, sec: d }); }} />
            ) : a.image ? (
              // eslint-disable-next-line @next/next/no-img-element -- yerel olay resmi (analiz sunucusundan, vekil üzerinden)
              <img src={alarmImageUrl(a.id)} alt="Olay resmi" className="h-full w-full object-contain" />
            ) : (
              <span className="text-6xl" aria-hidden="true">🚨</span>
            )}
            {!showVideo && (
              <p role="status" data-testid="clip-caption"
                 className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-black/70 px-3 py-1 text-[12.5px] font-medium text-white">
                {caption}
              </p>
            )}
          </div>

          {marks.length > 0 && (
            <div className="px-5 pt-3" data-testid="alarm-timeline">
              {len !== null && (
                // kaydın süresi üstünde iki an (süre video yüklenince bilinir)
                <div className="relative h-1.5 rounded-full bg-line" aria-hidden="true">
                  {marks.map((m) => (
                    <span key={m.key} className={`absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white ${m.key === "fired" ? "bg-nok-600" : "bg-warn-700"}`}
                          style={{ left: `${Math.min(100, Math.max(0, (m.t / len) * 100))}%` }} />
                  ))}
                </div>
              )}
              <div className="mt-2 flex flex-wrap gap-2">
                {marks.map((m) => (
                  <button key={m.key} type="button" onClick={() => seek(m.t)}
                          className="inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-1 text-[12.5px] font-medium hover:border-brand-100">
                    <span className={`h-2 w-2 rounded-full ${m.key === "fired" ? "bg-nok-600" : "bg-warn-700"}`} aria-hidden="true" />
                    {m.label}{m.t < 0 ? " (kayıttan önce)" : ` · ${clock(m.t)}`}
                  </button>
                ))}
              </div>
            </div>
          )}

          {mode === "browse" && (
            <p className="flex flex-wrap gap-2 px-5 pt-3 text-[12px]" data-testid="alarm-state">
              <span className={`rounded-full px-2.5 py-0.5 font-medium ${a.acked ? "bg-ok-50 text-ok-600" : "bg-warn-50 text-warn-700"}`}>{a.acked ? "Onaylandı" : "Onay bekliyor"}</span>
              {a.falseAlarm && <span className="rounded-full bg-canvas-2 px-2.5 py-0.5 font-medium text-muted">Yanlış alarm</span>}
              <span className="rounded-full bg-canvas px-2.5 py-0.5 text-muted">{NOTIFY_LABELS[a.notify]}</span>
            </p>
          )}
        </div>

        <footer className="grid gap-2 px-5 pb-5 pt-4">
          {error?.id === a.id && <p role="status" className="text-[13px] font-medium text-nok-600">{error.text}</p>}
          <div className="flex flex-wrap gap-2">
            {!a.acked && (
              <button ref={primary} type="button" disabled={busy} onClick={() => act("ack")}
                      className="h-11 min-w-32 rounded-xl bg-nok-600 px-5 text-[15px] font-bold text-white shadow-sm hover:bg-[#c42f3f] disabled:opacity-60">
                Gördüm
              </button>
            )}
            {a.sessionId && (
              <Link href={`/live?s=${a.sessionId}`} onClick={() => { if (mode === "active") onClose(); }}
                    className="inline-grid h-11 place-items-center rounded-xl border border-line px-4 text-sm font-semibold hover:border-brand-100">
                Kamerayı aç
              </Link>
            )}
            {!a.falseAlarm && (
              <button type="button" disabled={busy} onClick={() => act("false")}
                      className="h-11 rounded-xl border border-line px-4 text-sm font-medium text-muted hover:border-brand-100 hover:text-ink disabled:opacity-60">
                Yanlış alarm
              </button>
            )}
            <button type="button" onClick={onClose}
                    className="ml-auto h-11 rounded-xl px-4 text-sm font-medium text-muted hover:bg-canvas hover:text-ink">
              {mode === "active" ? "Küçült" : "Kapat"}
            </button>
          </div>
          {mode === "active" && <p className="text-[11.5px] text-faint">Küçültünce alarm sayfanın üstündeki şeritte kalır; Gördüm deyince kapanır.</p>}
        </footer>
      </div>
    </div>
  );
}
