"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import PageHeader from "@/components/PageHeader";
import ShortcutHelp from "@/components/watch/ShortcutHelp";
import { calendarDays, timelineRanges, type ArchiveCamera } from "@/lib/archive";
import { archiveKeysBlocked, archiveShortcut } from "@/lib/archiveKeys.mjs";
import {
  clampToDay, dayEnd, dayStart, defaultCursor, nextRangeStart, partsOf, shiftMonth, type Range,
} from "@/lib/archiveTime.mjs";
import CameraPicker from "./CameraPicker";
import Calendar from "./Calendar";
import ExportDialog from "./ExportDialog";
import Player from "./Player";
import Timeline from "./Timeline";
import { useArchivePlayer } from "./useArchivePlayer";

/** Kayıttan izleme kısayolları (archiveKeys.mjs `archiveShortcut` ile aynı) */
const KEYS: ReadonlyArray<readonly [string, string]> = [
  ["← / →", "10 saniye geri ya da ileri sarar"],
  ["Shift + ← / →", "1 dakika geri ya da ileri sarar"],
  ["Boşluk", "Duraklatır ya da sürdürür"],
  ["?", "Bu listeyi açar ya da kapatır"],
];
const KEYS_NOTE = "Sarma ve duraklatma, oynatıcı ya da çizelge odaktayken çalışır (çizelgeye bir kez tıklamak yeter).";

/** Derin bağlantı `/archive?source=&channel=&t=<epoch sn>`; eksik ya da geçersizse null */
function deepLink(params: URLSearchParams): { cam: ArchiveCamera; t: number } | null {
  const sourceId = params.get("source");
  const channelId = params.get("channel");
  const t = Number(params.get("t"));
  if (!sourceId || !channelId || !params.get("t") || !Number.isFinite(t) || t < 0) return null;
  return { cam: { sourceId, channelId }, t };
}

const now = () => Date.now() / 1000;

/**
 * Kayıttan izleme sayfası (R12): başlık ve kısayol listesi. Gövde ("bugün", yerel saat) yalnız tarayıcıda çizilir:
 * sunucunun saati/saat dilimiyle çizilen içerik hidrasyonda uyuşmazdı.
 */
export default function ArchiveView() {
  const [mounted, setMounted] = useState(false);
  const [help, setHelp] = useState(false);
  useEffect(() => { setMounted(true); }, []);

  // "?" sayfanın her yerinde (yazı kutusu ve açık pencere dışında) kısayol listesini açar
  const openHelp = useCallback((e: KeyboardEvent) => {
    if (e.defaultPrevented) return;
    const target = e.target instanceof Element ? e.target : null;
    const sc = archiveShortcut(e, { blocked: archiveKeysBlocked(target, document), control: false });
    if (sc?.type !== "help") return;
    e.preventDefault();
    setHelp(true);
  }, []);
  useEffect(() => {
    window.addEventListener("keydown", openHelp);
    return () => window.removeEventListener("keydown", openHelp);
  }, [openHelp]);

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="Kayıttan izleme"
                  text="Kayıt cihazındaki (NVR) eski görüntüyü izleyin: kamerayı ve günü seçin, çizelgede bir ana tıklayın.">
        <button type="button" aria-haspopup="dialog" onClick={() => setHelp(true)} className="pl-btn">Kısayollar</button>
      </PageHeader>
      {mounted && <ArchiveBody />}
      {help && <ShortcutHelp keys={KEYS} note={KEYS_NOTE} onClose={() => setHelp(false)} />}
    </div>
  );
}

/**
 * Üstte kamera seçici, oynatıcı ve sağında ay takvimi, oynatıcının altında 24 saatlik çizelge. Kamera ya da gün
 * değişince oynatıcı kapanır (`DELETE`); ilk oynatma yeni oynatıcı açar.
 */
function ArchiveBody() {
  const params = useSearchParams();
  const [deep] = useState(() => deepLink(params));
  const [cam, setCam] = useState<ArchiveCamera | null>(deep?.cam ?? null);
  const [camLabel, setCamLabel] = useState("");
  const [day, setDay] = useState(() => dayStart(deep?.t ?? now()));
  const [month, setMonth] = useState(() => { const p = partsOf(deep?.t ?? now()); return { year: p.year, month: p.month }; });
  const [today] = useState(() => dayStart(now()));
  const [cursor, setCursor] = useState(() => deep?.t ?? dayStart(now()));
  const [ranges, setRanges] = useState<Range[] | null>(null);
  const [timelineError, setTimelineError] = useState<string | null>(null);
  const [days, setDays] = useState<Set<number> | null>(null);
  const [calendarError, setCalendarError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const player = useArchivePlayer();
  /** Derin bağlantının konumu ilk çizelge yüklemesinde varsayılan imleçle ezilmez */
  const keepCursor = useRef(deep !== null);
  const end = dayEnd(day);
  const at = player.view?.at ?? cursor;

  // Oynatıcının konumu imleçtir (oynatıcı kapanınca imleç son konumda kalır)
  const viewAt = player.view?.at;
  useEffect(() => { if (viewAt !== undefined) setCursor(viewAt); }, [viewAt]);

  // Takvim: seçili kameranın o aydaki kayıtlı günleri
  useEffect(() => {
    setDays(null);
    setCalendarError(null);
    if (!cam) return;
    const ctl = new AbortController();
    calendarDays(cam, month.year, month.month, ctl.signal)
      .then((d) => setDays(new Set(d)))
      .catch((e: Error) => { if (!ctl.signal.aborted) setCalendarError(e.message); });
    return () => ctl.abort();
  }, [cam, month.year, month.month]);

  // Çizelge: seçili günün kayıtlı aralıkları; oynatıcı yoksa imleç günün ilk kaydına gelir
  const hasPlayer = useRef(false);
  hasPlayer.current = player.view !== null;
  useEffect(() => {
    setRanges(null);
    setTimelineError(null);
    if (!cam) return;
    const ctl = new AbortController();
    timelineRanges(cam, day, ctl.signal)
      .then((r) => {
        setRanges(r);
        if (!keepCursor.current && !hasPlayer.current) setCursor(defaultCursor(r, day, dayEnd(day)));
        keepCursor.current = false;
      })
      .catch((e: Error) => { if (!ctl.signal.aborted) setTimelineError(e.message); });
    return () => ctl.abort();
  }, [cam, day]);

  // Derin bağlantı: kamera ve gün seçili, `t`'den oynatılır (bir kez)
  const started = useRef(false);
  const { seek } = player;
  useEffect(() => {
    if (!deep || started.current) return;
    started.current = true;
    seek(deep.cam, deep.t);
  }, [deep, seek]);

  const selectCamera = (c: ArchiveCamera, label: string) => {
    setCamLabel(label);
    if (cam?.sourceId === c.sourceId && cam.channelId === c.channelId) return;
    player.close();
    keepCursor.current = false;
    setCam(c);
    setCursor(day);
  };

  const selectDay = (d: number) => {
    if (d !== day) {
      player.close();
      keepCursor.current = false;
      setDay(d);
      setCursor(d);
    }
    const p = partsOf(d);
    if (p.year !== month.year || p.month !== month.month) setMonth({ year: p.year, month: p.month });
  };

  /** Konuma git: oynatıcı varsa sarar, yoksa yalnız imleç taşınır (gün içine kırpılır) */
  const moveTo = (t: number) => {
    const target = clampToDay(t, day, end);
    if (cam && player.view) player.seek(cam, target);
    else setCursor(target);
  };
  /** Çizelge tıklaması: oynatıcı yoksa o andan oynatmaya başlar */
  const pickTime = (t: number) => {
    if (!cam) return;
    const target = clampToDay(t, day, end);
    setCursor(target);
    player.seek(cam, target);
  };
  const toggle = () => { if (cam) player.toggle(cam, at); };
  const nextAt = ranges ? nextRangeStart(ranges, at) : null;

  // Oynatıcı/çizelge bölgesinin kısayolları (←/→, Shift+←/→, Boşluk); "?"yi sayfa işler
  const onRegionKey = (e: React.KeyboardEvent) => {
    const target = e.target instanceof Element ? e.target : null;
    const sc = archiveShortcut(e, { blocked: archiveKeysBlocked(target, document), control: !!target?.closest("button, a[href]") });
    if (!sc || sc.type === "help" || !cam) return;
    e.preventDefault();
    if (sc.type === "step") moveTo(at + sc.seconds);
    else if (sc.type === "toggle") toggle();
  };
  const name = player.view?.name || camLabel;

  return (
    <>
      <div className="grid gap-3">
        <CameraPicker selected={cam} onSelect={selectCamera} />
        <div className="grid items-start gap-3 lg:grid-cols-[minmax(0,1fr)_300px]">
          <div className="grid min-w-0 gap-2" onKeyDown={onRegionKey} data-testid="archive-region">
            <Player name={name} hasCamera={cam !== null} view={player.view} opening={player.opening} seeking={player.seeking}
                    error={player.error} notice={player.notice} streamKey={player.streamKey} at={at} speed={player.speed}
                    nextAt={nextAt} onToggle={toggle} onStep={(s) => moveTo(at + s)}
                    onSpeed={(s) => { if (cam) player.setSpeed(cam, s, at); }}
                    onNext={() => { if (nextAt !== null) moveTo(nextAt); }}
                    onExport={() => setExporting(true)} />
            <section className="pl-section mb-0 min-w-0" aria-labelledby="archive-timeline-title">
              <h2 id="archive-timeline-title">Çizelge</h2>
              <Timeline day={day} end={end} ranges={ranges} error={timelineError} at={at} disabled={!cam} onSeek={pickTime} />
            </section>
          </div>
          <Calendar year={month.year} month={month.month} days={days} error={calendarError} selected={day} today={today}
                    onMonth={(d) => setMonth((m) => shiftMonth(m.year, m.month, d))} onSelect={selectDay} />
        </div>
      </div>
      {exporting && cam && (
        <ExportDialog cam={cam} name={name} at={at} onClose={() => setExporting(false)} />
      )}
    </>
  );
}
