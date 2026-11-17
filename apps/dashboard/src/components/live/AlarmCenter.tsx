"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { desktopReady, playBeep, readPref } from "@/lib/attention";
import { ALARM_LABELS, api, isWatchMode, safetyHealth, toggleFalseAlarm, WATCH_WARN_AFTER_S, watchStatus, type Alarm, type LiveSession } from "@/lib/live";
import { alarmSeverity, sortAlarms } from "@/lib/alarmPopup.mjs";
import { problemOf, type Problem } from "@/lib/views";
import AlarmToast from "./AlarmToast";
import AlarmViewer from "./AlarmViewer";

const POLL_MS = 2000;
/** Güvenlik kameralarının izlenme durumu daha seyrek yoklanır */
const SESSIONS_POLL_MS = 5000;
/** Üst üste bu kadar istek başarısız olunca (≈6 sn) şeritte uyarı satırı çıkar */
export const FAILS_BEFORE_WARNING = 3;
/** Bu sekmede gösterilmiş alarmlar (pencere aynı alarm için yeniden açılmasın; sayfa yenilense de) */
const SHOWN_KEY = "bv.alarm.shown";
/** Bu sekmede köşe kartı × ile gizlenmiş uyarılar (sayfa yenilense de gizli kalır; alarm üstteki çubukta durur) */
const HIDDEN_KEY = "bv.alarm.hidden";
const SHOWN_MAX = 200;
/** Onaylanmamış alarm varken sekme başlığı bu aralıkla "ALARM — <kamera>" ile sayfa başlığı arasında gidip gelir */
export const TITLE_FLASH_MS = 1000;
/** Arka plandaki sekmede aynı anda en çok bu kadar masaüstü bildirimi */
const MAX_NOTIFICATIONS = 3;

/** Canlı oturumu olmayan çağıranlar için (alarm merkezi yoksa) boş küme */
export const NO_LIVE_SESSIONS: ReadonlySet<string> = new Set();

/** İzlenmeyen kamera; `fire`: yangın/duman kamerası (şerit "Yangın/duman kamerası izlenmiyor" der) */
export interface Unwatched { id: string; name: string; reason: string; fire: boolean }

interface AlarmCenterValue {
  /** Onaylanmamış alarmlar, yeniden eskiye */
  alarms: Alarm[];
  /** Alarm akışı koptu: oturum süresi doldu (401), analiz sunucusu reddetti (anahtar, adres) ya da analiz sunucusu yok */
  problem: Problem | null;
  /** 60 sn'den uzun süredir izlenmeyen güvenlik ve yangın/duman kameraları */
  unwatched: Unwatched[];
  /** Son alınan canlı oturum listesi (panel genelinde tek yoklama; ör. Canlı izleme kamera listesinin durum noktaları) */
  sessions: LiveSession[];
  /** `sessions`'ın kimlikleri: alarm penceresi alarmın oturumu hâlâ açıksa onun işaretli canlı akışını gösterir */
  liveSessionIds: ReadonlySet<string>;
  /** "Gördüm"ü kaydedilemeyen alarm */
  ackFailed: string | null;
  ack: (a: Alarm) => Promise<boolean>;
  markFalse: (a: Alarm) => Promise<boolean>;
  /** Alarm penceresini bu alarmda açar (çubuktaki "Alarmları göster", köşedeki "+N uyarı daha", masaüstü bildirimi) */
  open: (id: string) => void;
  /** Alarm listesini hemen yeniden ister (başka yerde onaylandı) */
  refresh: () => void;
}

const Ctx = createContext<AlarmCenterValue | null>(null);

/** Panel düzenindeki alarm merkezi (yoksa null: ör. giriş sayfası) */
export function useAlarmCenter(): AlarmCenterValue | null {
  return useContext(Ctx);
}

/** Pencere açıkken köşe kartlarına verilen boş liste (sabit: her çizimde yeni dizi olmasın) */
const NO_ALARMS: Alarm[] = [];

function loadIds(key: string): Set<string> {
  try {
    const v: unknown = JSON.parse(window.sessionStorage.getItem(key) ?? "[]");
    return new Set(Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

function saveIds(key: string, ids: Set<string>): void {
  try {
    window.sessionStorage.setItem(key, JSON.stringify([...ids].slice(-SHOWN_MAX)));
  } catch {
    // depolama yok: yalnızca bu sayfa açıkken hatırlanır
  }
}

/**
 * Her panel sayfasında alarmların tek kaynağı (tek yoklama): onaylanmamış alarmlar (2 sn'de bir), izlenmeyen güvenlik
 * kameraları (5 sn'de bir), alarm penceresi, köşe kartları ve dikkat çekme. Bu sekmede henüz gösterilmemiş onaylanmamış
 * alarmlar arasında kritik varsa ortadaki pencere en yeni kritikte açılır; yalnız uyarı (telefon) geldiyse pencere açılmaz,
 * uyarı sağ altta köşe kartında görünür (kartlar yalnız pencere kapalıyken çizilir; × ile gizlenen kart gizli kalır). Her
 * yeni alarmda ayar açıksa sesli uyarı ve (sekme arka plandaysa) masaüstü bildirimi. Alarm varken sekme başlığı yanıp söner;
 * onaylanmamış kritik alarm varken ekranın kenarı kırmızı yanıp söner (hareket azaltma tercihinde sabit). Üstteki çubuk
 * (`AlarmBanner`) bu verinin görünümüdür.
 */
export default function AlarmCenter({ children }: { children: React.ReactNode }) {
  const [alarms, setAlarms] = useState<Alarm[]>([]);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [ackFailed, setAckFailed] = useState<string | null>(null);
  const [unwatched, setUnwatched] = useState<Unwatched[]>([]);
  const [sessions, setSessions] = useState<LiveSession[]>([]);
  /** Açık alarm penceresi: gösterilen alarm ve listedeki yeri (alarm onaylanınca aynı yerdeki sonrakine geçilir) */
  const [viewer, setViewer] = useState<{ id: string; index: number } | null>(null);
  /** × ile gizlenen köşe kartları (bu sekmede; alarm çubukta ve pencerenin listesinde kalır) */
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());
  /** Cevap yalnızca istek ile cevap arasında sıra değişmediyse uygulanır (onaydan önce başlayan istek geri getirmesin) */
  const seq = useRef(0);
  const refreshRef = useRef<() => void>(() => undefined);
  const shown = useRef<Set<string> | null>(null);
  /** Pencerenin sırası: kritikler üstte, grup içinde yeniden eskiye (şerit ve sekme başlığı sunucunun sırasını kullanır) */
  const ordered = useMemo(() => sortAlarms(alarms), [alarms]);
  const latest = useRef<Alarm[]>([]);
  useEffect(() => { latest.current = ordered; }, [ordered]);
  const liveSessionIds = useMemo<ReadonlySet<string>>(() => new Set(sessions.map((s) => s.id)), [sessions]);
  /** Köşe kartlarındaki uyarılar: gizlenmemiş, yeniden eskiye */
  const warnings = useMemo(() => ordered.filter((a) => alarmSeverity(a.type) === "warning" && !hidden.has(a.id)), [ordered, hidden]);
  const critical = ordered.some((a) => alarmSeverity(a.type) === "critical");

  // gizlenen kartlar sayfa yenilense de gizli kalır (oturum belleği; sunucu çiziminde pencere nesnesi yok)
  useEffect(() => { setHidden(loadIds(HIDDEN_KEY)); }, []);

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
        if (fails >= FAILS_BEFORE_WARNING) setProblem(problemOf(e));
      } finally {
        busy = false;
        if (alive) {
          timer = setTimeout(poll, again ? 0 : POLL_MS);
          again = false;
        }
      }
    };
    refreshRef.current = poll;
    poll();
    return () => { alive = false; clearTimeout(timer); };
  }, []);

  // İzlenmeyen güvenlik ve yangın/duman kameraları: sağlıksızlık sunucunun bildirdiği süreyle (unhealthyFor) başlatılır,
  // tarayıcı saatiyle sürdürülür (iki makinenin saati farklı olabilir); 60 sn'yi aşan her kamera için bir uyarı satırı.
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
        setSessions(Array.isArray(list) ? list : []);
        const now = Date.now();
        const seen = new Set<string>();
        const out: Unwatched[] = [];
        for (const s of list) {
          if (!isWatchMode(s.profile.countMode)) continue;
          const h = safetyHealth(s);
          if (h.healthy) continue;
          seen.add(s.id);
          if (!since.has(s.id)) since.set(s.id, now - (watchStatus(s)?.unhealthyFor ?? 0) * 1000);
          if (now - since.get(s.id)! > WATCH_WARN_AFTER_S * 1000) {
            out.push({ id: s.id, name: s.name, reason: h.reason ?? "neden bilinmiyor", fire: s.profile.countMode === "fire" });
          }
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

  /** Pencereyi bu alarmda açar; listedeki yeri, onaylanınca aynı yerdeki sonrakine geçmek için tutulur */
  const open = useCallback((id: string) => {
    setViewer({ id, index: Math.max(0, latest.current.findIndex((a) => a.id === id)) });
  }, []);

  // Liste değişince durum eşlenir: penceredeki alarm onaylandıysa aynı yerdeki sonrakine geçilir, hiç kalmadıysa
  // pencere kapanır. Gösterilen alarm aşağıda çizim sırasında aynı kuralla seçilir (`showing`): pencere onaylar arasında
  // hiç kapanıp açılmaz (perde yanıp sönmez, odak sayfaya kaçmaz, ekran okuyucu yeniden duyurmaz).
  useEffect(() => {
    setViewer((v) => {
      if (!v) return v;
      const i = ordered.findIndex((a) => a.id === v.id);
      if (i >= 0) return i === v.index ? v : { id: v.id, index: i };
      if (ordered.length === 0) return null;
      const j = Math.min(v.index, ordered.length - 1);
      return { id: ordered[j].id, index: j };
    });
  }, [ordered]);

  // Bu sekmede ilk kez görülen onaylanmamış alarmlar: aralarında kritik varsa pencere en yeni kritikte açılır (yalnız uyarı:
  // pencere açılmaz, köşe kartı çıkar; küçültülmüş pencere de kapalı kalır); her durumda ses ve masaüstü bildirimi
  useEffect(() => {
    shown.current ??= loadIds(SHOWN_KEY);
    const seen = shown.current;
    const fresh = alarms.filter((a) => !seen.has(a.id));
    if (fresh.length === 0) return;
    for (const a of fresh) seen.add(a.id);
    saveIds(SHOWN_KEY, seen);
    const newest = sortAlarms(fresh)[0];                // kritikler önde, grup içinde en yeni
    if (alarmSeverity(newest.type) === "critical") setViewer({ id: newest.id, index: ordered.indexOf(newest) });
    if (readPref("sound")) playBeep();
    if (document.hidden && desktopReady()) {
      for (const a of fresh.slice(0, MAX_NOTIFICATIONS)) {
        try {
          const n = new Notification(ALARM_LABELS[a.type], {
            body: `${a.camera} · ${new Date(a.firedAt * 1000).toLocaleTimeString("tr-TR")}`,
            tag: a.id, requireInteraction: true,
          });
          n.onclick = () => { window.focus(); open(a.id); n.close(); };
        } catch {
          // bildirim gösterilemedi (izin geri alındı vb.): pencere ve şerit yine var
        }
      }
    }
  }, [alarms, ordered, open]);

  // Sekme başlığı: onaylanmamış alarm varken her saniye "ALARM — <kamera>" ↔ sayfa başlığı (emoji yok); alarm bitince geri
  const flashCamera = alarms[0]?.camera ?? null;
  useEffect(() => {
    if (flashCamera === null) return;
    const text = `ALARM — ${flashCamera}`;
    let base = document.title;
    let alarmNext = true;
    const tick = () => {
      if (document.title !== text) base = document.title;     // sayfa (ya da gezinme) başlığı değiştirdi
      document.title = alarmNext ? text : base;
      alarmNext = !alarmNext;
    };
    tick();
    const t = setInterval(tick, TITLE_FLASH_MS);
    return () => {
      clearInterval(t);
      if (document.title === text) document.title = base;
    };
  }, [flashCamera]);

  const ack = useCallback(async (a: Alarm) => {
    setAckFailed(null);
    seq.current += 1;
    try {
      await api(`alarms/${a.id}/ack`, { method: "POST" });
      seq.current += 1;                                 // onaydan önce başlamış istekler geçersiz
      setAlarms((x) => x.filter((y) => y.id !== a.id));
      refreshRef.current();
      return true;
    } catch {
      setAckFailed(a.id);                               // alarm listede kalır
      return false;
    }
  }, []);

  const markFalse = useCallback(async (a: Alarm) => {
    seq.current += 1;
    try {
      await toggleFalseAlarm(a);
      seq.current += 1;
      if (!a.falseAlarm) setAlarms((x) => x.filter((y) => y.id !== a.id));   // işaretlenen alarm onaylanır, şeritten kalkar
      refreshRef.current();
      return true;
    } catch {
      return false;
    }
  }, []);

  const close = useCallback(() => setViewer(null), []);
  const hide = useCallback((id: string) => {
    setHidden((h) => {
      const next = new Set(h).add(id);
      saveIds(HIDDEN_KEY, next);
      return next;
    });
  }, []);
  const refresh = useCallback(() => refreshRef.current(), []);
  const value = useMemo(() => ({ alarms, problem, unwatched, sessions, liveSessionIds, ackFailed, ack, markFalse, open, refresh }),
    [alarms, problem, unwatched, sessions, liveSessionIds, ackFailed, ack, markFalse, open, refresh]);
  const showing = viewer === null ? null
    : ordered.some((a) => a.id === viewer.id) ? viewer.id
    : ordered.length > 0 ? ordered[Math.min(viewer.index, ordered.length - 1)].id
    : null;

  return (
    <Ctx.Provider value={value}>
      {children}
      {critical && (
        // onaylanmamış kritik alarm: ekranın kenarı kırmızı yanıp söner (hareket azaltma tercihinde sabit); tıklanamaz, sayfa
        // kullanılmaya devam eder; ekran okuyucudan gizli (alarm çubukta ve pencerede yazılı)
        <div data-testid="alarm-edge" aria-hidden="true"
             className="pointer-events-none fixed inset-0 z-[60] border-[5px] border-nok-600 motion-safe:animate-alarm-edge" />
      )}
      <AlarmToast warnings={showing ? NO_ALARMS : warnings} liveSessionIds={liveSessionIds} onAck={ack} onFalseAlarm={markFalse}
                  onHide={hide} onOpenAll={open} />
      {showing && (
        <AlarmViewer alarms={ordered} id={showing} mode="active" liveSessionIds={liveSessionIds} onSelect={open} onClose={close}
                     onAck={ack} onFalseAlarm={markFalse} />
      )}
    </Ctx.Provider>
  );
}
