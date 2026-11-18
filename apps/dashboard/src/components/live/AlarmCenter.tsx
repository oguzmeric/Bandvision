"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { desktopReady, playAlarmSound, readPref, readSound, readVolume, stopAlarmSounds } from "@/lib/attention";
import { ALARM_LABELS, api, isWatchMode, safetyHealth, toggleFalseAlarm, WATCH_WARN_AFTER_S, watchStatus, type Alarm, type LiveSession } from "@/lib/live";
import { alarmSeverity, sortAlarms } from "@/lib/alarmPopup.mjs";
import { SOUND_REPEAT_MS, soundGroup, type SoundGroup } from "@/lib/alarmSounds.mjs";
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
  /** Tarayıcı alarm sesini engelledi (sayfayla henüz etkileşim yok): çubuk "sayfaya bir kez tıklayın" der */
  soundBlocked: boolean;
  ack: (a: Alarm) => Promise<boolean>;
  markFalse: (a: Alarm) => Promise<boolean>;
  /** Alarm penceresini bu alarmda açar (çubuktaki "Alarmları göster", köşedeki "+N uyarı daha", masaüstü bildirimi) */
  open: (id: string) => void;
  /** Pencereyi, pencerenin sırasındaki (kritikler üstte, grup içinde yeniden eskiye) ilk alarmda açar */
  openFirst: () => void;
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
 * yeni alarmda (sekme arka plandaysa) masaüstü bildirimi. "Sesli uyarı" açıksa: her yeni kritik alarm çalanlar kümesine
 * girer ve ses hemen başlar; pencere açıkken kümede onaylanmamış alarm kaldıkça grubun sesi 3 sn'de bir çalar (gösterilen
 * alarm kümedeyse onun grubu, değilse kümenin en yenisininki). Gördüm / Yanlış alarm kaydedilince yalnız O alarmı kümeden
 * çıkarır (kaydedilemezse alarm açık kalır, ses sürer; uyarıyı onaylamak kritik sesi susturmaz); Küçült ya da pencerenin kapanması kümeyi boşaltır (pencere elle yeniden açılınca çalmaz).
 * Yalnız uyarı geldiyse ses bir kez çalar. Tarayıcı izin vermezse çubukta tıklama ipucu çıkar. Alarm
 * varken sekme başlığı yanıp söner; onaylanmamış kritik alarm varken ekranın kenarı kırmızı yanıp söner (hareket azaltma
 * tercihinde sabit). Üstteki çubuk (`AlarmBanner`) bu verinin görünümüdür.
 */
export default function AlarmCenter({ children }: { children: React.ReactNode }) {
  const [alarms, setAlarms] = useState<Alarm[]>([]);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [ackFailed, setAckFailed] = useState<string | null>(null);
  const [unwatched, setUnwatched] = useState<Unwatched[]>([]);
  const [sessions, setSessions] = useState<LiveSession[]>([]);
  /** Sesi çalan kritik alarmlar: bu sekmede yeni gelen, Gördüm / Yanlış alarm henüz kaydedilmemiş; Küçült ya da kapanış boşaltır */
  const [ringing, setRinging] = useState<ReadonlySet<string>>(() => new Set());
  /** Yeni kritik alarm kümeye her girişte artar: ses (aynı grup olsa da) 3 sn'yi beklemeden hemen yeniden başlar */
  const [ringStart, setRingStart] = useState(0);
  /** Kritik ses şu anda çalıyor (tekrar etkisi kurulu): yeni uyarının tek seferlik sesi ayrıca çalmaz */
  const ringActive = useRef(false);
  const [soundBlocked, setSoundBlocked] = useState(false);
  /** Açık alarm penceresi: gösterilen alarm ve listedeki yeri (alarm onaylanınca aynı yerdeki sonrakine geçilir) */
  const [viewer, setViewer] = useState<{ id: string; index: number } | null>(null);
  /** × ile gizlenen köşe kartları (bu sekmede, sayfa yenilense de; alarm çubukta ve pencerenin listesinde kalır). Sunucu
   * çiziminde depo yok: boş başlar; ilk çizimde alarm olmadığından (yoklama sonra gelir) çizim farkı doğmaz */
  const [hidden, setHidden] = useState<Set<string>>(() => (typeof window === "undefined" ? new Set() : loadIds(HIDDEN_KEY)));
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

  useEffect(() => { saveIds(HIDDEN_KEY, hidden); }, [hidden]);

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

  /** Grubun seçili sesini ayarlı düzeyde çalar; tarayıcı engellerse çubukta "sayfaya bir kez tıklayın" çıkar */
  const play = useCallback(async (group: SoundGroup) => {
    const result = await playAlarmSound(readSound(group), readVolume());
    if (result !== "failed") setSoundBlocked(result === "blocked");   // dosya hatası tıklamayla çözülmez: ipucu yok
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
    if (alarmSeverity(newest.type) === "critical") {
      setViewer({ id: newest.id, index: ordered.indexOf(newest) });
      const ids = fresh.filter((a) => alarmSeverity(a.type) === "critical").map((a) => a.id);
      setRinging((r) => new Set([...r, ...ids]));       // ses aşağıdaki tekrar etkisinde (ayar açıksa), hemen başlar
      setRingStart((n) => n + 1);
    } else if (!ringActive.current && readPref("sound")) {
      void play(soundGroup(newest.type));               // yalnız uyarı: bir kez
    }
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
  }, [alarms, ordered, open, play]);

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

  /** Yalnız bu alarmı çalanlardan çıkarır (uyarı ya da kümede olmayan alarm: değişiklik yok) */
  const unring = useCallback((id: string) => {
    setRinging((r) => {
      if (!r.has(id)) return r;
      const next = new Set(r);
      next.delete(id);
      return next;
    });
  }, []);

  const ack = useCallback(async (a: Alarm) => {
    setAckFailed(null);
    seq.current += 1;
    try {
      await api(`alarms/${a.id}/ack`, { method: "POST" });
      seq.current += 1;                                 // onaydan önce başlamış istekler geçersiz
      unring(a.id);                                     // yalnız kaydedilince: kaydedilemezse alarm açık kalır ve ses sürer
      setAlarms((x) => x.filter((y) => y.id !== a.id));
      refreshRef.current();
      return true;
    } catch {
      setAckFailed(a.id);                               // alarm listede kalır
      return false;
    }
  }, [unring]);

  const markFalse = useCallback(async (a: Alarm) => {
    seq.current += 1;
    try {
      await toggleFalseAlarm(a);
      seq.current += 1;
      unring(a.id);                                     // yalnız kaydedilince
      if (!a.falseAlarm) setAlarms((x) => x.filter((y) => y.id !== a.id));   // işaretlenen alarm onaylanır, şeritten kalkar
      refreshRef.current();
      return true;
    } catch {
      return false;
    }
  }, [unring]);

  const close = useCallback(() => { setViewer(null); setRinging(new Set()); }, []);
  const hide = useCallback((id: string) => setHidden((h) => new Set(h).add(id)), []);
  /** Pencereyi pencerenin sırasındaki ilk alarmda açar (çubuktaki "Alarmları göster"; sıranın tek kaynağı burası) */
  const openFirst = useCallback(() => {
    const first = latest.current[0];
    if (first) open(first.id);
  }, [open]);
  const refresh = useCallback(() => refreshRef.current(), []);
  const value = useMemo(() => ({ alarms, problem, unwatched, sessions, liveSessionIds, ackFailed, soundBlocked, ack, markFalse, open, openFirst, refresh }),
    [alarms, problem, unwatched, sessions, liveSessionIds, ackFailed, soundBlocked, ack, markFalse, open, openFirst, refresh]);
  const showing = viewer === null ? null
    : ordered.some((a) => a.id === viewer.id) ? viewer.id
    : ordered.length > 0 ? ordered[Math.min(viewer.index, ordered.length - 1)].id
    : null;

  // Pencere kapandı (Küçült, Esc, alarm kalmadı): susturulur; elle yeniden açılınca çalmaz
  useEffect(() => { if (showing === null) setRinging((r) => (r.size === 0 ? r : new Set())); }, [showing]);
  /** Çalan sesin grubu: gösterilen alarm çalanlardaysa onunki, değilse çalanların listede kalan en yenisininki (pencerenin
   * sırası kritikleri yeniden eskiye dizer); pencere kapalıysa ya da çalan kalmadıysa null */
  const ringGroup: SoundGroup | null = showing === null || ringing.size === 0 ? null : (() => {
    const a = ordered.find((x) => x.id === showing && ringing.has(x.id)) ?? ordered.find((x) => ringing.has(x.id));
    return a ? soundGroup(a.type) : null;
  })();
  useEffect(() => {
    if (ringGroup === null) return;
    const tick = () => { if (readPref("sound")) void play(ringGroup); };
    ringActive.current = true;
    tick();
    const t = setInterval(tick, SOUND_REPEAT_MS);
    return () => { clearInterval(t); ringActive.current = false; stopAlarmSounds(); };   // susturunca çalan ses de hemen kesilir
  }, [ringGroup, ringStart, play]);

  // Engellenen ses: sayfaya ilk tıklama / tuş tarayıcıda sesi açar, uyarı kalkar (sonraki çalma artık engellenmez)
  useEffect(() => {
    if (!soundBlocked) return;
    const clear = () => setSoundBlocked(false);
    window.addEventListener("pointerdown", clear, true);
    window.addEventListener("keydown", clear, true);
    return () => { window.removeEventListener("pointerdown", clear, true); window.removeEventListener("keydown", clear, true); };
  }, [soundBlocked]);

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
