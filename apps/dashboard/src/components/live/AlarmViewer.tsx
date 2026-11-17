"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ALARM_LABELS, ALARM_TITLES, ARCHIVE_LEAD_S, NOTIFY_LABELS, alarmImageUrl, api, type Alarm, type AlarmType, type Source,
} from "@/lib/live";
import { agoText, alarmSeverity, liveStreamUrl } from "@/lib/alarmPopup.mjs";
import AlarmIcon from "./AlarmIcon";
import AlarmMedia from "./AlarmMedia";
import { runAlarmAction, type AlarmAction } from "./alarmAction";

/** "active": onaylanmamış alarmlar (alarm penceresi, Küçült); "browse": geçmiş alarmlar (Alarmlar sayfası, Son alarmlar) */
export type ViewerMode = "active" | "browse";

interface Props {
  /** Gezinilen alarmlar (etkin kipte kritikler üstte, grup içinde yeniden eskiye; göz atmada yeniden eskiye) */
  alarms: Alarm[];
  /** Gösterilen alarm (listede yoksa ilk alarm) */
  id: string;
  mode: ViewerMode;
  /** Hâlâ açık canlı oturumların kimlikleri (canlı görüntü oturumun işaretli akışından; yoksa kameranın ham akışından) */
  liveSessionIds: ReadonlySet<string>;
  onSelect: (id: string) => void;
  /** Küçült (etkin) / Kapat (göz atma); Esc de bunu yapar — asla "Gördüm" değil */
  onClose: () => void;
  onAck: (a: Alarm) => Promise<boolean>;
  /** "Yanlış alarm" düğmesi: işaretli değilse işaretler, işaretliyse geri alır (çağıran `toggleFalseAlarm` kullanır) */
  onFalseAlarm: (a: Alarm) => Promise<boolean>;
}

/** Kaynak listesi alınamazsa ikinci (son) denemeye kadar beklenen süre */
const SOURCES_RETRY_MS = 5000;

const FOCUSABLE = 'a[href], button:not([disabled]), video[controls], [tabindex]:not([tabindex="-1"])';

/** Tür rengi: başlık şeridi (`head`), başlıktaki beyaz rozetin simge rengi (`icon`) ve liste satırının sol kenarı (`edge`).
 * Yangın/duman turuncu, kişi alarmları kırmızı, telefon sarı (koyu yazı), deneme gri-mavi */
export const ALARM_TONES: Record<AlarmType, { head: string; icon: string; edge: string }> = {
  fire: { head: "bg-fire-600 text-white", icon: "text-fire-600", edge: "border-l-fire-600" },
  smoke: { head: "bg-fire-600 text-white", icon: "text-fire-600", edge: "border-l-fire-600" },
  hands_up: { head: "bg-nok-600 text-white", icon: "text-nok-ink", edge: "border-l-nok-600" },
  lying: { head: "bg-nok-600 text-white", icon: "text-nok-ink", edge: "border-l-nok-600" },
  phone: { head: "bg-alert-warn text-alert-warn-ink", icon: "text-alert-warn-ink", edge: "border-l-alert-warn" },
  test: { head: "bg-alert-test text-white", icon: "text-alert-test", edge: "border-l-alert-test" },
};

/**
 * Ortadaki alarm penceresi: tür renginde başlık (beyaz rozette türün çizgi simgesi — emoji yok —, tür, altında "<kamera> ·
 * <tarih-saat>", sağda "devam ediyor" ya da "Süre: N sn"), bilgi satırı (Geçen süre — saniyede bir —, Bildirim), görüntü alanı (`AlarmMedia`: etkin kipte canlı kaynak varsa Canlı ve alarm anı
 * köşe penceresi; yoksa ve göz atmada Alarm kaydı), Gördüm / Kamerayı aç / Kayıt cihazında izle (kayıt cihazı kanalında;
 * alarm anından 10 sn önceden) / Yanlış alarm / Küçült. Etkin kipte birden çok alarmda sağda açık alarmlar listesi (olay
 * resmi küçüğü — canlı değil —, tür, kamera, geçen süre); dar ekranda (< 768 px) liste gizlenir, "1 / 3" ve ‹ › gelir. Göz
 * atmada liste yok, ‹ › her genişlikte.
 * Yerel `<dialog>` + `showModal()`: tarayıcının üst katmanında açılır — açık başka bir modal pencerenin (ör. "Canlı sayımı
 * başlat", geometri) de üstünde; sayfanın geri kalanı etkisizdir. Erişilebilirlik: `role="alertdialog"`, açılınca odak
 * pencereye (Gördüm) gelir ve içinde kalır (Tab döner); Esc (`cancel`) küçültür, asla onaylamaz.
 */
export default function AlarmViewer({ alarms, id, mode, liveSessionIds, onSelect, onClose, onAck, onFalseAlarm }: Props) {
  const index = Math.max(0, alarms.findIndex((x) => x.id === id));
  const a = alarms[index];
  const dialog = useRef<HTMLDialogElement>(null);
  const primary = useRef<HTMLButtonElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ id: string; text: string } | null>(null);
  const [, setTick] = useState(0);
  /** Kayıt cihazı kaynaklarının kimlikleri ("Kayıt cihazında izle" yalnız onlarda); kaynaklı alarm görülünce bir kez istenir */
  const [recorders, setRecorders] = useState<Set<string> | null>(null);
  const needSources = alarms.some((x) => x.sourceId);
  useEffect(() => {
    if (!needSources || recorders) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    // kaynaklar alınamazsa pencere açıkken 5 sn sonra bir kez daha denenir; yine olmazsa düğme görünmez
    const load = (retry: boolean) => {
      api<Source[]>("sources")
        .then((list) => { if (live) setRecorders(new Set(list.filter((s) => s.kind === "recorder").map((s) => s.id))); })
        .catch(() => { if (live && retry) timer = setTimeout(() => load(false), SOURCES_RETRY_MS); });
    };
    load(true);
    return () => { live = false; clearTimeout(timer); };
  }, [needSources, recorders]);

  // açılınca üst katmanda modal; odak pencereye (Gördüm varsa ona); kapanınca önceki öğeye geri
  const alive = useRef(true);
  useEffect(() => {
    const d = dialog.current;
    if (!d) return;
    alive.current = true;
    const before = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (!d.open) d.showModal();
    (primary.current ?? d).focus();
    return () => {
      alive.current = false;
      if (d.open) d.close();
      if (before && document.contains(before)) before.focus();
    };
  }, []);

  // işlemden sonra (Gördüm / Yanlış alarm pencereyi sıradaki alarma geçirince) odak kaybolduysa yine Gördüm'e
  const shownId = a?.id;
  useEffect(() => {
    const d = dialog.current;
    if (!d?.open || busy) return;
    const el = document.activeElement;
    if (!el || el === document.body || !d.contains(el) || (el instanceof HTMLButtonElement && el.disabled)) {
      (primary.current ?? d).focus();
    }
  }, [shownId, busy]);

  // geçen süre (bilgi satırı ve liste) saniyede bir
  useEffect(() => {
    const t = setInterval(() => setTick((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, []);

  if (!a) return null;

  function trap(e: React.KeyboardEvent) {
    if (e.key !== "Tab" || !dialog.current) return;
    // görünmeyenler (dar ekranda liste, geniş ekranda ‹ ›) sayılmaz: odak alamazlar
    const items = [...dialog.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.getClientRects().length > 0);
    if (items.length === 0) { e.preventDefault(); return; }
    const first = items[0], last = items[items.length - 1];
    const cur = document.activeElement;
    if (e.shiftKey && (cur === first || cur === dialog.current)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && cur === last) { e.preventDefault(); first.focus(); }
  }

  async function act(kind: AlarmAction) {
    const text = await runAlarmAction(a, kind, {
      onAck, onFalseAlarm, onStart: () => { setBusy(true); setError(null); }, onEnd: () => setBusy(false),
    });
    if (text) setError({ id: a.id, text });
  }

  const now = Date.now() / 1000;
  const severity = alarmSeverity(a.type);
  const onWarn = severity === "warning";                    // sarı başlık: koyu yazı, koyu kenarlı düğmeler
  const ongoing = a.type !== "test" && a.endedAt === null;
  const liveUrl = liveStreamUrl(a, liveSessionIds);
  const queue = mode === "active" && alarms.length > 1;
  // alarm anından 10 sn önceden kayıt cihazında izle (yalnız kayıt cihazı kanalındaki alarm)
  const archiveHref = a.sourceId && a.channelId && recorders?.has(a.sourceId)
    ? `/archive?source=${encodeURIComponent(a.sourceId)}&channel=${encodeURIComponent(a.channelId)}&t=${Math.max(0, Math.floor(a.firedAt - ARCHIVE_LEAD_S))}`
    : null;
  // Başlıktaki küçük yazılar (ikinci satır, süre çipi, sayaç) koyu yarı saydam zemin üstünde: beyaz yazı yangın turuncusunda
  // (#e2531f, 3,8:1) tek başına 4,5:1'i tutmaz; %25 siyah zeminle ≥6:1 (kırmızıda ≥6,4:1, gri-mavide ≥8:1). Sarıda koyu
  // yazı zaten ≥6:1; %10 siyah yalnız görünüm birliği için (≥5,6:1)
  const shade = onWarn ? "bg-black/10" : "bg-black/25";
  const navBtn = `grid h-7 w-7 place-items-center rounded-[2px] border text-base disabled:opacity-40 ${onWarn
    ? "border-black/25 bg-black/10 hover:bg-black/15" : "border-white/40 bg-black/25 hover:bg-black/35"}`;
  const term = "text-[11.5px] text-pl-faint";
  const desc = "truncate font-semibold tabular-nums";

  return (
    <dialog ref={dialog} role="alertdialog" aria-modal="true" aria-label="Alarm" onKeyDown={trap}
            onCancel={(e) => { e.preventDefault(); onClose(); }}         // Esc: Küçült / Kapat (onay değil)
            // tarayıcı kendisi kapattıysa durum eşlensin; geliştirmede (StrictMode) ilk kapanışın geç gelen olayı, yeniden
            // açılmış pencereyi kapatmasın
            onClose={() => { if (alive.current && !dialog.current?.open) onClose(); }}
            data-testid="alarm-modal" data-severity={severity} data-kind={a.type}
            // yükseklik sınırı pencerenin kendisinde (tarayıcının modal varsayılanı içeriği kırpardı); iç kutular onu doldurur,
            // kısa ekranda orta bölüm kayar, başlık ve düğmeler hep görünür (iç kutu 2 px kısa: pencerenin 1 px kenarlığı)
            className={`m-auto max-h-[calc(100dvh-1.5rem)] ${queue ? "w-[min(68rem,calc(100vw-1.5rem))]" : "w-[min(52rem,calc(100vw-1.5rem))]"} max-w-none overflow-hidden rounded-[3px] border border-pl-line bg-white p-0 text-pl-ink outline-none backdrop:bg-black/60`}>
      <div className="flex max-h-[calc(100dvh-1.5rem-2px)]">
        <div className="grid max-h-[calc(100dvh-1.5rem-2px)] min-w-0 flex-1 grid-rows-[auto_minmax(0,1fr)_auto]">
          <header data-testid="alarm-header" className={`flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 ${ALARM_TONES[a.type].head}`}>
            <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-[6px] bg-white ${ALARM_TONES[a.type].icon}`} aria-hidden="true">
              <AlarmIcon type={a.type} className="h-7 w-7" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-[22px] font-bold uppercase leading-tight tracking-wide md:text-[26px]" data-testid="alarm-title">{ALARM_TITLES[a.type]}</p>
              <p className="mt-0.5 flex min-w-0">
                <span className={`truncate rounded-[2px] px-1.5 py-px text-[13.5px] font-medium ${shade}`} data-testid="alarm-subtitle">
                  <span title={a.camera}>{a.camera}</span> · <span className="tabular-nums" data-testid="alarm-time">{new Date(a.firedAt * 1000).toLocaleString("tr-TR")}</span>
                </span>
              </p>
            </div>
            {ongoing ? (
              <span className="inline-flex items-center gap-1.5 rounded-[2px] bg-white px-2 py-0.5 text-[12px] font-bold uppercase text-nok-ink" data-testid="alarm-status">
                <span className="h-2 w-2 animate-pulse rounded-full bg-nok-600 motion-reduce:animate-none" aria-hidden="true" />devam ediyor
              </span>
            ) : a.endedAt !== null && (
              <span className={`rounded-[2px] px-2 py-0.5 text-[12px] font-semibold ${shade}`} data-testid="alarm-status">
                Süre: {Math.max(0, Math.round(a.endedAt - a.startedAt))} sn
              </span>
            )}
            {alarms.length > 1 && (
              // etkin kipte yalnız dar ekranda (genişte sağdaki liste var); göz atmada her genişlikte
              <div className={`flex items-center gap-1 text-[13px] font-semibold ${queue ? "md:hidden" : ""}`}>
                <button type="button" aria-label="Önceki alarm" disabled={index === 0} onClick={() => onSelect(alarms[index - 1].id)}
                        className={navBtn}>‹</button>
                <span data-testid="alarm-counter" className={`min-w-12 rounded-[2px] px-1 py-0.5 text-center tabular-nums ${shade}`}>{index + 1} / {alarms.length}</span>
                <button type="button" aria-label="Sonraki alarm" disabled={index === alarms.length - 1} onClick={() => onSelect(alarms[index + 1].id)}
                        className={navBtn}>›</button>
              </div>
            )}
          </header>

          <div className="overflow-auto">
            {/* kamera ve tarih-saat başlığın ikinci satırında; burada yinelenmez */}
            <dl className="flex flex-wrap gap-x-8 gap-y-1.5 border-b border-pl-line-soft bg-pl-side px-4 py-2 text-[13px]">
              <div className="min-w-0"><dt className={term}>Geçen süre</dt><dd className={desc} data-testid="alarm-ago">{agoText(now - a.firedAt)}</dd></div>
              <div className="min-w-0"><dt className={term}>Bildirim</dt><dd className={desc}>{NOTIFY_LABELS[a.notify]}</dd></div>
            </dl>

            <AlarmMedia alarm={a} liveUrl={liveUrl} initial={mode === "browse" || !liveUrl ? "clip" : "live"} size="large" />

            {mode === "browse" && (
              <p className="flex flex-wrap gap-2 px-4 pt-3 text-[12px]" data-testid="alarm-state">
                <span className={`rounded-[2px] px-2 py-0.5 font-medium ${a.acked ? "bg-ok-50 text-ok-ink" : "bg-warn-50 text-warn-ink"}`}>{a.acked ? "Onaylandı" : "Onay bekliyor"}</span>
                {a.falseAlarm && <span className="rounded-[2px] bg-pl-head px-2 py-0.5 font-medium text-pl-muted">Yanlış alarm</span>}
              </p>
            )}
          </div>

          <footer className="mt-3 grid gap-2 border-t border-pl-line-soft bg-pl-side px-4 py-3">
            {error?.id === a.id && <p role="status" className="text-[13px] font-medium text-nok-ink">{error.text}</p>}
            <div className="flex flex-wrap gap-2">
              {!a.acked && (
                <button ref={primary} type="button" disabled={busy} onClick={() => act("ack")}
                        className="h-10 min-w-32 rounded-[2px] border border-nok-600 bg-nok-600 px-5 text-[15px] font-bold text-white hover:bg-[#c42f3f] disabled:opacity-60">
                  Gördüm
                </button>
              )}
              {a.sessionId && (
                <Link href={`/live?s=${a.sessionId}`} onClick={() => { if (mode === "active") onClose(); }}
                      className="pl-btn h-10 px-4 font-semibold">
                  Kamerayı aç
                </Link>
              )}
              {archiveHref && (
                <Link href={archiveHref} onClick={() => { if (mode === "active") onClose(); }}
                      className="pl-btn h-10 px-4 font-semibold">
                  Kayıt cihazında izle
                </Link>
              )}
              <button type="button" disabled={busy} onClick={() => act("false")} className="pl-btn h-10 px-4">
                {a.falseAlarm ? "Yanlış alarm işaretini kaldır" : "Yanlış alarm"}
              </button>
              <button type="button" onClick={onClose}
                      className="pl-btn ml-auto h-10 px-4">
                {mode === "active" ? "Küçült" : "Kapat"}
              </button>
            </div>
            {mode === "active" && <p className="text-[11.5px] text-pl-faint">Küçültünce alarm sayfanın üstündeki alarm çubuğunda kalır; Gördüm deyince kapanır.</p>}
          </footer>
        </div>

        {queue && (
          // liste pencereyi uzatmasın: mutlak konumlu kutuda kayar (pencerenin yüksekliğini orta sütun belirler)
          <aside aria-label="Açık alarmlar" className="relative hidden w-64 shrink-0 border-l border-pl-line-soft bg-pl-side md:block">
            <div className="absolute inset-0 flex flex-col">
              <p className="border-b border-pl-line-soft px-3 py-2 text-[12px] font-semibold text-pl-muted">Açık alarmlar ({alarms.length})</p>
              <ul data-testid="alarm-queue" className="min-h-0 flex-1 overflow-auto">
                {alarms.map((x) => {
                  const current = x.id === a.id;
                  return (
                    <li key={x.id}>
                      <button type="button" data-testid="queue-item" aria-current={current ? "true" : undefined}
                              onClick={() => onSelect(x.id)}
                              className={`flex w-full items-center gap-2.5 border-b border-l-4 border-b-pl-line-soft px-2.5 py-2 text-left text-[12.5px] ${ALARM_TONES[x.type].edge} ${current ? "bg-pl-sel" : "hover:bg-pl-head"}`}>
                        <span className="grid h-11 w-[4.25rem] shrink-0 place-items-center overflow-hidden rounded-[2px] bg-[#111]">
                          {x.image
                            // eslint-disable-next-line @next/next/no-img-element -- yerel olay resmi küçüğü (canlı değil: bağlantı sınırı)
                            ? <img src={alarmImageUrl(x.id)} alt="" className="h-full w-full object-cover" />
                            : <AlarmIcon type={x.type} className="h-6 w-6 text-white/75" />}
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate font-semibold">{ALARM_LABELS[x.type]}</span>
                          <span className="block truncate text-pl-muted">{x.camera}</span>
                          <span className="block text-[11.5px] tabular-nums text-pl-faint">{agoText(now - x.firedAt)}</span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          </aside>
        )}
      </div>
    </dialog>
  );
}
