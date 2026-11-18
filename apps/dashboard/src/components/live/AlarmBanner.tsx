"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { KEEP_UNSAVED_ATTR } from "@/components/UnsavedGuard";
import { refusalText } from "@/lib/analyzerRefusal.mjs";
import { ALARM_LABELS } from "@/lib/live";
import { alarmSeverity } from "@/lib/alarmPopup.mjs";
import { useAlarmCenter } from "./AlarmCenter";

/**
 * Her panel sayfasında, sayfa kaydırılsa da üstte (yapışkan): onaylanmamış alarmların ince sayaç çubuğu ("● N kritik alarm"
 * kırmızı, "N uyarı" sarı, "Son: <tür> — <kamera>", "Alarmları göster") ve 60 sn'den uzun süredir izlenmeyen güvenlik ve
 * yangın/duman kameraları. Veri `AlarmCenter`'ın tek yoklamasından gelir (ikinci yoklama yok). Alarm penceresi küçültülse ya da
 * köşe kartı gizlense de alarm burada sayılır; "Alarmları göster" pencereyi pencerenin sırasındaki ilk alarmda açar.
 * Şerit çoğu zaman tek alarm kanalıdır (Telegram varsayılan kapalı): alarm akışı koparsa (oturum süresi doldu, analiz
 * sunucusu yok, analiz sunucusu panelin anahtarını ya da adresini reddetti) eski liste sessizce kalmaz, sarı uyarı satırı çıkar.
 * Tarayıcı alarm sesini engellediyse (sayfayla henüz etkileşim yok) "Alarm sesi için sayfaya bir kez tıklayın" yazar; ilk
 * tıklama ya da tuşla kalkar.
 */
export default function AlarmBanner() {
  const center = useAlarmCenter();
  const pathname = usePathname();
  const search = useSearchParams().toString();
  if (!center) return null;
  const { alarms, problem, unwatched, ackFailed, soundBlocked, openFirst } = center;

  const next = pathname + (search ? `?${search}` : "");
  const refused = problem && refusalText(problem);
  const warning = problem && (
    <p role="status" data-testid="alarm-feed-warning" className="rounded-[2px] border border-warn-line bg-warn-50 px-3 py-1.5 text-[13px] text-warn-ink">
      {problem === "auth" ? (
        <>
          Oturum süresi doldu — alarmları görmek için yeniden giriş yapın.{" "}
          {/* Oturum düştü: kaydedilmemiş düzenleme (Canlı izleme) sorulmadan saklı kalır, girişten sonra geri yüklenir */}
          <a href={`/login?next=${encodeURIComponent(next)}`} {...{ [KEEP_UNSAVED_ATTR]: "" }} className="font-semibold underline">Giriş yap</a>
        </>
      ) : refused ? `Alarmlar alınamıyor — ${refused}` : "Alarmlar alınamıyor — analiz sunucusuna ulaşılamıyor."}
    </p>
  );
  const ackError = ackFailed !== null && alarms.some((a) => a.id === ackFailed);
  const criticalCount = alarms.filter((a) => alarmSeverity(a.type) === "critical").length;
  const warningCount = alarms.length - criticalCount;
  // en son gelen alarm (sunucu sırasından bağımsız: en büyük alarm anı)
  const last = alarms.reduce<(typeof alarms)[number] | undefined>((x, a) => (!x || a.firedAt > x.firedAt ? a : x), undefined);

  if (alarms.length === 0 && !warning && unwatched.length === 0 && !soundBlocked) return null;
  return (
    // Yapışkan: canlı sayfada aşağı kaydırıp görüntüyü izlerken de alarm görünür; zemin düz (içerik arkadan görünmez)
    <div data-testid="alarm-banner" className="sticky top-0 z-40 -mx-5 mb-2 grid gap-1.5 bg-white px-5 py-2 md:-mx-9 md:px-9">
      {warning}
      {soundBlocked && (
        <p role="status" data-testid="sound-blocked" className="rounded-[2px] border border-warn-line bg-warn-50 px-3 py-1.5 text-[13px] font-medium text-warn-ink">
          Alarm sesi için sayfaya bir kez tıklayın
        </p>
      )}
      {unwatched.map((u) => (
        <p key={u.id} role="status" data-testid="watch-warning"
           className="flex flex-wrap items-center gap-x-3 rounded-[2px] border border-warn-line bg-warn-50 px-3 py-1.5 text-[13px] text-warn-ink">
          <span className="min-w-0 flex-1"><b>{u.fire ? "Yangın/duman kamerası" : "Güvenlik kamerası"} izlenmiyor: {u.name}</b> — {u.reason}</span>
          <Link href={`/live?s=${u.id}`} className="font-medium underline">Kamerayı aç</Link>
        </p>
      ))}
      {last && (
        <div role="alert" aria-label="Alarm" className="grid gap-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[2px] border border-pl-line bg-pl-side px-3 py-1 text-[13px]">
            {criticalCount > 0 && (
              <span data-testid="alarm-count-critical" className="inline-flex items-center gap-1.5 font-bold text-nok-ink">
                <span className="h-2.5 w-2.5 rounded-full bg-nok-600" aria-hidden="true" />{criticalCount} kritik alarm
              </span>
            )}
            {warningCount > 0 && (
              <span data-testid="alarm-count-warning" className="rounded-[2px] bg-alert-warn px-1.5 py-px font-semibold text-alert-warn-ink">
                {warningCount} uyarı
              </span>
            )}
            <span className="min-w-0 flex-1 truncate text-pl-muted">
              Son: <b className="font-semibold text-pl-ink">{ALARM_LABELS[last.type]} — {last.camera}</b>
            </span>
            <button type="button" onClick={openFirst} className="pl-btn h-7 text-[12.5px] font-semibold">
              Alarmları göster
            </button>
          </div>
          {ackError && <p className="px-1 text-[13px] font-medium text-nok-ink">Gördüm kaydedilemedi; alarm açık kalıyor. Tekrar deneyin.</p>}
        </div>
      )}
    </div>
  );
}
