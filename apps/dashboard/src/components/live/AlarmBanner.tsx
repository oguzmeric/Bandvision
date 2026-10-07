"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ALARM_LABELS, ApiError, api, type Alarm } from "@/lib/live";

const POLL_MS = 2000;
/** Üst üste bu kadar istek başarısız olunca (≈6 sn) şeritte uyarı satırı çıkar */
const FAILS_BEFORE_WARNING = 3;
const SHOWN = 3;

/** Bugünün alarmında yalnızca saat, eskisinde tarih de */
function stamp(sec: number): string {
  const d = new Date(sec * 1000);
  return d.toDateString() === new Date().toDateString() ? d.toLocaleTimeString("tr-TR") : d.toLocaleString("tr-TR");
}

/**
 * Her panel sayfasında: onaylanmamış güvenlik alarmları (2 sn'de bir). Ses yok (sessiz alarm).
 * Şerit çoğu zaman tek alarm kanalıdır (Telegram varsayılan kapalı): alarm akışı koparsa (oturum süresi doldu,
 * analiz sunucusu yok) eski liste sessizce kalmaz, sarı uyarı satırı çıkar.
 */
export default function AlarmBanner() {
  const [alarms, setAlarms] = useState<Alarm[]>([]);
  const [problem, setProblem] = useState<"auth" | "down" | null>(null);
  const [ackError, setAckError] = useState(false);
  /** Cevap yalnızca istek ile cevap arasında sıra değişmediyse uygulanır (onaydan önce başlayan istek geri getirmesin) */
  const seq = useRef(0);
  const refresh = useRef<() => void>(() => undefined);

  useEffect(() => {
    let alive = true;
    let busy = false;                                   // aynı anda tek istek: yavaş cevaplar üst üste binmez
    let again = false;
    let fails = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      clearTimeout(timer);
      if (busy) { again = true; return; }
      busy = true;
      const mine = seq.current;
      try {
        const list = await api<Alarm[]>("alarms?active=1");
        if (!alive) return;
        fails = 0;
        setProblem(null);
        if (mine === seq.current) setAlarms(list);
        else again = true;                              // bayat cevap: hemen yenisi
      } catch (e) {
        if (!alive) return;
        fails += 1;
        if (fails >= FAILS_BEFORE_WARNING) setProblem(e instanceof ApiError && e.status === 401 ? "auth" : "down");
      } finally {
        busy = false;
        if (alive) {
          timer = setTimeout(poll, again ? 0 : POLL_MS);
          again = false;
        }
      }
    };
    refresh.current = poll;
    poll();
    return () => { alive = false; clearTimeout(timer); };
  }, []);

  async function ack(a: Alarm) {
    setAckError(false);
    seq.current += 1;
    try {
      await api(`alarms/${a.id}/ack`, { method: "POST" });
      seq.current += 1;                                 // onaydan önce başlamış istekler geçersiz
      setAlarms((x) => x.filter((y) => y.id !== a.id));
      refresh.current();
    } catch {
      setAckError(true);                                // alarm listede kalır
    }
  }

  const warning = problem && (
    <p role="status" data-testid="alarm-feed-warning" className="mb-3 rounded-xl bg-warn-50 px-3 py-2 text-[13px] text-warn-700">
      {problem === "auth" ? (
        <>
          Oturum süresi doldu — alarmları görmek için yeniden giriş yapın.{" "}
          <a href={`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`} className="font-semibold underline">Giriş yap</a>
        </>
      ) : "Alarmlar alınamıyor — analiz sunucusuna ulaşılamıyor."}
    </p>
  );

  if (alarms.length === 0) return warning || null;
  return (
    <>
      {warning}
      <div role="alert" aria-label="Güvenlik alarmı" className="mb-4 grid gap-2">
        {alarms.slice(0, SHOWN).map((a) => {
          const label = ALARM_LABELS[a.type];
          return (
            <div key={a.id} className="flex flex-wrap items-center gap-3 rounded-2xl bg-nok-600 px-4 py-3 text-white shadow-lg">
              <span className="text-lg" aria-hidden="true">🚨</span>
              <p className="min-w-0 flex-1 text-sm font-semibold">
                {label} — {a.camera} · {stamp(a.firedAt)}
                {a.endedAt === null && a.type !== "test" && <span className="ml-2 rounded-full bg-white/20 px-2 py-0.5 text-[11px]">devam ediyor</span>}
              </p>
              {a.sessionId && <Link href={`/live?s=${a.sessionId}`} className="text-[13px] font-medium underline">Kamerayı aç</Link>}
              <button type="button" onClick={() => ack(a)} aria-label={`Gördüm: ${label} — ${a.camera}`}
                      className="h-8 rounded-[9px] bg-white px-3 text-[13px] font-semibold text-nok-600">Gördüm</button>
            </div>
          );
        })}
        {alarms.length > SHOWN && <p className="px-1 text-[13px] font-semibold text-nok-600">+{alarms.length - SHOWN} alarm daha</p>}
        {ackError && <p className="px-1 text-[13px] font-medium text-nok-600">Gördüm kaydedilemedi; alarm açık kalıyor. Tekrar deneyin.</p>}
      </div>
    </>
  );
}
