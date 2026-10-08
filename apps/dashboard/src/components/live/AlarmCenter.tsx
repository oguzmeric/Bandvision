"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { desktopReady, playBeep, readPref } from "@/lib/attention";
import { ALARM_LABELS, ApiError, api, safetyHealth, WATCH_WARN_AFTER_S, type Alarm, type LiveSession } from "@/lib/live";
import AlarmViewer from "./AlarmViewer";

const POLL_MS = 2000;
/** Güvenlik kameralarının izlenme durumu daha seyrek yoklanır */
const SESSIONS_POLL_MS = 5000;
/** Üst üste bu kadar istek başarısız olunca (≈6 sn) şeritte uyarı satırı çıkar */
const FAILS_BEFORE_WARNING = 3;
/** Bu sekmede gösterilmiş alarmlar (pencere aynı alarm için yeniden açılmasın; sayfa yenilense de) */
const SHOWN_KEY = "bv.alarm.shown";
const SHOWN_MAX = 200;
/** Onaylanmamış alarm varken sekme başlığı bu aralıkla "🚨 ALARM — <kamera>" ile sayfa başlığı arasında gidip gelir */
export const TITLE_FLASH_MS = 1000;
/** Arka plandaki sekmede aynı anda en çok bu kadar masaüstü bildirimi */
const MAX_NOTIFICATIONS = 3;

export interface Unwatched { id: string; name: string; reason: string }

interface AlarmCenterValue {
  /** Onaylanmamış alarmlar, yeniden eskiye */
  alarms: Alarm[];
  /** Alarm akışı koptu: oturum süresi doldu (401) ya da analiz sunucusu yok */
  problem: "auth" | "down" | null;
  /** 60 sn'den uzun süredir izlenmeyen güvenlik kameraları */
  unwatched: Unwatched[];
  /** "Gördüm"ü kaydedilemeyen alarm */
  ackFailed: string | null;
  ack: (a: Alarm) => Promise<boolean>;
  markFalse: (a: Alarm) => Promise<boolean>;
  /** Alarm penceresini bu alarmda açar (şeritteki "Kaydı izle", masaüstü bildirimi) */
  open: (id: string) => void;
  /** Alarm listesini hemen yeniden ister (başka yerde onaylandı) */
  refresh: () => void;
}

const Ctx = createContext<AlarmCenterValue | null>(null);

/** Panel düzenindeki alarm merkezi (yoksa null: ör. giriş sayfası) */
export function useAlarmCenter(): AlarmCenterValue | null {
  return useContext(Ctx);
}

function loadShown(): Set<string> {
  try {
    const v: unknown = JSON.parse(window.sessionStorage.getItem(SHOWN_KEY) ?? "[]");
    return new Set(Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

function saveShown(shown: Set<string>): void {
  try {
    window.sessionStorage.setItem(SHOWN_KEY, JSON.stringify([...shown].slice(-SHOWN_MAX)));
  } catch {
    // depolama yok: yalnızca bu sayfa açıkken hatırlanır
  }
}

/**
 * Her panel sayfasında alarmların tek kaynağı (tek yoklama): onaylanmamış alarmlar (2 sn'de bir), izlenmeyen güvenlik
 * kameraları (5 sn'de bir), alarm penceresi ve dikkat çekme. Bu sekmede henüz gösterilmemiş onaylanmamış alarm gelince
 * alarm penceresi açılır (en yenisinde); ayar açıksa sesli uyarı ve (sekme arka plandaysa) masaüstü bildirimi. Alarm
 * varken sekme başlığı yanıp söner. Şerit (`AlarmBanner`) bu verinin görünümüdür.
 */
export default function AlarmCenter({ children }: { children: React.ReactNode }) {
  const [alarms, setAlarms] = useState<Alarm[]>([]);
  const [problem, setProblem] = useState<"auth" | "down" | null>(null);
  const [ackFailed, setAckFailed] = useState<string | null>(null);
  const [unwatched, setUnwatched] = useState<Unwatched[]>([]);
  /** Açık alarm penceresi: gösterilen alarm ve listedeki yeri (alarm onaylanınca aynı yerdeki sonrakine geçilir) */
  const [viewer, setViewer] = useState<{ id: string; index: number } | null>(null);
  /** Cevap yalnızca istek ile cevap arasında sıra değişmediyse uygulanır (onaydan önce başlayan istek geri getirmesin) */
  const seq = useRef(0);
  const refreshRef = useRef<() => void>(() => undefined);
  const shown = useRef<Set<string> | null>(null);
  const latest = useRef<Alarm[]>([]);
  useEffect(() => { latest.current = alarms; }, [alarms]);

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
    refreshRef.current = poll;
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
      const i = alarms.findIndex((a) => a.id === v.id);
      if (i >= 0) return i === v.index ? v : { id: v.id, index: i };
      if (alarms.length === 0) return null;
      const j = Math.min(v.index, alarms.length - 1);
      return { id: alarms[j].id, index: j };
    });
  }, [alarms]);

  // Bu sekmede ilk kez görülen onaylanmamış alarm: pencere en yenisinde açılır, ses ve masaüstü bildirimi
  useEffect(() => {
    shown.current ??= loadShown();
    const seen = shown.current;
    const fresh = alarms.filter((a) => !seen.has(a.id));
    if (fresh.length === 0) return;
    for (const a of fresh) seen.add(a.id);
    saveShown(seen);
    const newest = fresh[0];
    setViewer({ id: newest.id, index: alarms.indexOf(newest) });
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
  }, [alarms, open]);

  // Sekme başlığı: onaylanmamış alarm varken her saniye "🚨 ALARM — <kamera>" ↔ sayfa başlığı; alarm bitince geri
  const flashCamera = alarms[0]?.camera ?? null;
  useEffect(() => {
    if (flashCamera === null) return;
    const text = `🚨 ALARM — ${flashCamera}`;
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
      await api(`alarms/${a.id}/false-alarm`, { method: "POST" });
      seq.current += 1;
      setAlarms((x) => x.filter((y) => y.id !== a.id));
      refreshRef.current();
      return true;
    } catch {
      return false;
    }
  }, []);

  const close = useCallback(() => setViewer(null), []);
  const refresh = useCallback(() => refreshRef.current(), []);
  const value = useMemo(() => ({ alarms, problem, unwatched, ackFailed, ack, markFalse, open, refresh }),
    [alarms, problem, unwatched, ackFailed, ack, markFalse, open, refresh]);
  const showing = viewer === null ? null
    : alarms.some((a) => a.id === viewer.id) ? viewer.id
    : alarms.length > 0 ? alarms[Math.min(viewer.index, alarms.length - 1)].id
    : null;

  return (
    <Ctx.Provider value={value}>
      {children}
      {showing && (
        <AlarmViewer alarms={alarms} id={showing} mode="active" onSelect={open} onClose={close} onAck={ack} onFalseAlarm={markFalse} />
      )}
    </Ctx.Provider>
  );
}
