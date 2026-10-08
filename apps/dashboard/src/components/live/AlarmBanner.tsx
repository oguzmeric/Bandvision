"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { ALARM_LABELS, stamp } from "@/lib/live";
import { useAlarmCenter } from "./AlarmCenter";

const SHOWN = 3;

/**
 * Her panel sayfasında, sayfa kaydırılsa da üstte (yapışkan): onaylanmamış güvenlik alarmları ve 60 sn'den uzun süredir
 * izlenmeyen güvenlik kameraları. Veri `AlarmCenter`'ın tek yoklamasından gelir (ikinci yoklama yok). Alarm penceresi
 * küçültülse de alarm burada kalır; "Kaydı izle" pencereyi o alarmda yeniden açar.
 * Şerit çoğu zaman tek alarm kanalıdır (Telegram varsayılan kapalı): alarm akışı koparsa (oturum süresi doldu,
 * analiz sunucusu yok) eski liste sessizce kalmaz, sarı uyarı satırı çıkar.
 */
export default function AlarmBanner() {
  const center = useAlarmCenter();
  const pathname = usePathname();
  const search = useSearchParams().toString();
  if (!center) return null;
  const { alarms, problem, unwatched, ackFailed, ack, open } = center;

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
                <button type="button" onClick={() => open(a.id)} aria-label={`Kaydı izle: ${label} — ${a.camera}`}
                        className="text-[13px] font-semibold underline">Kaydı izle</button>
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
