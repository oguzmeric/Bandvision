"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { ALARM_LABELS, ApiError, api, safetyHealth, stamp, WATCH_WARN_AFTER_S, type Alarm, type LiveSession } from "@/lib/live";

const POLL_MS = 2000;
/** Güvenlik kameralarının izlenme durumu daha seyrek yoklanır */
const SESSIONS_POLL_MS = 5000;
/** Üst üste bu kadar istek başarısız olunca (≈6 sn) şeritte uyarı satırı çıkar */
const FAILS_BEFORE_WARNING = 3;
const SHOWN = 3;

interface Unwatched { id: string; name: string; reason: string }

/**
 * Her panel sayfasında, sayfa kaydırılsa da üstte (yapışkan): onaylanmamış güvenlik alarmları (2 sn'de bir) ve
 * 60 sn'den uzun süredir izlenmeyen güvenlik kameraları (5 sn'de bir). Ses yok (sessiz alarm).
 * Şerit çoğu zaman tek alarm kanalıdır (Telegram varsayılan kapalı): alarm akışı koparsa (oturum süresi doldu,
 * analiz sunucusu yok) eski liste sessizce kalmaz, sarı uyarı satırı çıkar.
 */
export default function AlarmBanner() {
  const [alarms, setAlarms] = useState<Alarm[]>([]);
  const [problem, setProblem] = useState<"auth" | "down" | null>(null);
  /** "Gördüm"ü kaydedilemeyen alarm; o alarm listeden çıkınca hata da görünmez */
  const [ackFailed, setAckFailed] = useState<string | null>(null);
  const [unwatched, setUnwatched] = useState<Unwatched[]>([]);
  /** Cevap yalnızca istek ile cevap arasında sıra değişmediyse uygulanır (onaydan önce başlayan istek geri getirmesin) */
  const seq = useRef(0);
  const refresh = useRef<() => void>(() => undefined);
  const pathname = usePathname();
  const search = useSearchParams().toString();

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

  // İzlenmeyen güvenlik kameraları: sağlıksızlık sunucunun bildirdiği süreyle (unhealthyFor) başlatılır, tarayıcı
  // saatiyle sürdürülür (iki makinenin saati farklı olabilir); 60 sn'yi aşan her kamera için bir uyarı satırı.
  useEffect(() => {
    let alive = true;
    let busy = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const since = new Map<string, number>();            // oturum → sağlıksız olduğu an (ms)
    const poll = async () => {
      if (busy) return;
      busy = true;
      try {
        const list = await api<LiveSession[]>("sessions");
        if (!alive) return;
        const now = Date.now();
        const seen = new Set<string>();
        const out: Unwatched[] = [];
        for (const s of list) {
          if (s.profile.countMode !== "safety") continue;
          const h = safetyHealth(s);
          if (h.healthy) continue;
          seen.add(s.id);
          if (!since.has(s.id)) since.set(s.id, now - (s.safety?.unhealthyFor ?? 0) * 1000);
          if (now - since.get(s.id)! > WATCH_WARN_AFTER_S * 1000) out.push({ id: s.id, name: s.name, reason: h.reason ?? "neden bilinmiyor" });
        }
        for (const id of [...since.keys()]) if (!seen.has(id)) since.delete(id);
        setUnwatched(out);
      } catch {
        // bağlantı sorunu alarm akışının uyarı satırında görünür; eski liste kalır
      } finally {
        busy = false;
        if (alive) timer = setTimeout(poll, SESSIONS_POLL_MS);
      }
    };
    poll();
    return () => { alive = false; clearTimeout(timer); };
  }, []);

  async function ack(a: Alarm) {
    setAckFailed(null);
    seq.current += 1;
    try {
      await api(`alarms/${a.id}/ack`, { method: "POST" });
      seq.current += 1;                                 // onaydan önce başlamış istekler geçersiz
      setAlarms((x) => x.filter((y) => y.id !== a.id));
      refresh.current();
    } catch {
      setAckFailed(a.id);                               // alarm listede kalır
    }
  }

  const next = pathname + (search ? `?${search}` : "");
  const warning = problem && (
    <p role="status" data-testid="alarm-feed-warning" className="rounded-xl bg-warn-50 px-3 py-2 text-[13px] text-warn-700">
      {problem === "auth" ? (
        <>
          Oturum süresi doldu — alarmları görmek için yeniden giriş yapın.{" "}
          <a href={`/login?next=${encodeURIComponent(next)}`} className="font-semibold underline">Giriş yap</a>
        </>
      ) : "Alarmlar alınamıyor — analiz sunucusuna ulaşılamıyor."}
    </p>
  );
  const ackError = ackFailed !== null && alarms.some((a) => a.id === ackFailed);

  if (alarms.length === 0 && !warning && unwatched.length === 0) return null;
  return (
    // Yapışkan: canlı sayfada aşağı kaydırıp görüntüyü izlerken de alarm görünür; zemin düz (içerik arkadan görünmez)
    <div data-testid="alarm-banner" className="sticky top-0 z-40 -mx-5 mb-2 grid gap-2 bg-canvas px-5 py-2 md:-mx-9 md:px-9">
      {warning}
      {unwatched.map((u) => (
        <p key={u.id} role="status" data-testid="watch-warning"
           className="flex flex-wrap items-center gap-x-3 rounded-xl border border-[#f7d9b5] bg-warn-50 px-3 py-2 text-[13px] text-warn-700">
          <span className="min-w-0 flex-1"><b>Güvenlik kamerası izlenmiyor: {u.name}</b> — {u.reason}</span>
          <Link href={`/live?s=${u.id}`} className="font-medium underline">Kamerayı aç</Link>
        </p>
      ))}
      {alarms.length > 0 && (
        <div role="alert" aria-label="Güvenlik alarmı" className="grid gap-2">
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
      )}
    </div>
  );
}
