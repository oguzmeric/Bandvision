"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/live";
import { useAlarmCenter } from "@/components/live/AlarmCenter";
import {
  LAST_VIEW_KEY, liveHref, RELOAD_RETRY_MS, RESIZE_DEBOUNCE_MS, STATUS_POLL_MS, streamSize,
  type TileStatus, type ViewLayout, type ViewStatus, type ViewTemplate,
} from "@/lib/views";
import TileOverlay from "./TileOverlay";
import SingleCamera, { type SingleMode } from "./SingleCamera";
import { usePhoneLandscape } from "./usePhoneLandscape";
import { useStreamKey } from "./useStreamKey";

function remembered(): string | null {
  try { return window.localStorage.getItem(LAST_VIEW_KEY); } catch { return null; }
}
function remember(id: string): void {
  try { window.localStorage.setItem(LAST_VIEW_KEY, id); } catch { /* depolama yok */ }
}

/** İzleme sayfası: şablon seçici, birleşik canlı görüntü + kutu katmanları, tek kamera, tüm ekran (video duvarı) */
export default function WatchView() {
  const [layouts, setLayouts] = useState<ViewLayout[]>([]);
  const [views, setViews] = useState<ViewTemplate[]>([]);
  /** Şablon listesi en az bir kez alındı ("Henüz şablon yok" ancak o zaman söylenir) */
  const [loaded, setLoaded] = useState(false);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [status, setStatus] = useState<ViewStatus | null>(null);
  const [single, setSingle] = useState<{ sourceId: string; channelId: string | null; name: string; liveHref: string } | null>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  /** Analiz sunucusuna ulaşılamıyor (liste ya da durum yoklaması başarısız); düzelince kalkar */
  const [down, setDown] = useState(false);
  /** Sunucu bu şablon için 404 verdi (silindi): akış istenmez, liste yeniden alınıp seçim düzeltilir */
  const [goneId, setGoneId] = useState<string | null>(null);
  /** Video duvarı (tam ekran) açık mı; tarayıcı tam ekranı desteklemiyorsa (ör. iPhone) düğme gizlenir */
  const [wallOn, setWallOn] = useState(false);
  const [canWall, setCanWall] = useState(false);
  const { streamKey, onError, bump } = useStreamKey();
  const phone = usePhoneLandscape();
  const gridRef = useRef<HTMLDivElement>(null);
  const wallRef = useRef<HTMLDivElement>(null);
  const center = useAlarmCenter();

  /** Şablon ve düzen listesini alır; başarıyı döndürür (seçili şablon silinmişse kalanlardan birine geçilir) */
  const reload = useCallback(async (select?: string): Promise<boolean> => {
    try {
      const [l, v] = await Promise.all([api<ViewLayout[]>("view-layouts"), api<ViewTemplate[]>("views")]);
      setLayouts(l);
      setViews(v);
      setLoaded(true);
      setDown(false);
      const want = select ?? remembered();
      setCurrentId((cur) => (want && v.some((x) => x.id === want) ? want : cur && v.some((x) => x.id === cur) ? cur : v[0]?.id ?? null));
      return true;
    } catch {
      setDown(true);
      return false;
    }
  }, []);
  // İlk yükleme: sunucu yoksa başarana dek RELOAD_RETRY_MS'de bir yeniden denenir
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const attempt = async () => {
      const ok = await reload();
      if (alive && !ok) timer = setTimeout(attempt, RELOAD_RETRY_MS);
    };
    attempt();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [reload]);

  const view = views.find((v) => v.id === currentId) ?? null;
  const layout = view ? layouts.find((l) => l.id === view.layout) ?? null : null;
  useEffect(() => { if (currentId) remember(currentId); }, [currentId]);
  const hasView = view !== null;
  useEffect(() => { if (!hasView) setSingle(null); }, [hasView]);   // şablon kalmadıysa tek kamera da kapanır

  const immersive = phone.active && !wallOn;

  // Kapsayıcı boyutu: birleşik görüntü tam bu boyutta istenir (telefonda küçük, masaüstünde büyük). İlk ölçüm hemen
  // (şablon değişince eski boyut hiç istenmesin), sonraki boyut değişimleri durulunca; boyut aynıysa durum değişmez.
  useLayoutEffect(() => {
    const el = gridRef.current;
    if (!el || !layout) return;
    const measure = () => {
      const n = streamSize(el);
      setSize((p) => (p && p.w === n.w && p.h === n.h ? p : n));
    };
    measure();
    let t: ReturnType<typeof setTimeout> | undefined;
    const ro = new ResizeObserver(() => { clearTimeout(t); t = setTimeout(measure, RESIZE_DEBOUNCE_MS); });
    ro.observe(el);
    return () => { ro.disconnect(); clearTimeout(t); };
  }, [layout, single, wallOn, immersive]);

  // Kutu durumları; aynı zamanda akışın bekçisi: Chrome, ilk karesi geldikten sonra kopan çok parçalı görüntüde çoğu
  // zaman `error` vermez (sekme görünür ve çevrimiçi kalır, görüntü son karede donar, rozetler taze görünür). Yoklama
  // koptuktan sonra düzelirse (sunucu yeniden başladı) akış baştan açılır; 404'te (şablon silindi) liste yeniden alınır.
  useEffect(() => {
    if (!currentId || single) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failed = false;
    let notFound = false;
    const poll = async () => {
      try {
        const s = await api<ViewStatus>(`views/${currentId}/status`);
        if (!alive) return;
        setStatus(s);
        setDown(false);
        setGoneId((g) => (g === currentId ? null : g));
        notFound = false;
        if (failed) { failed = false; bump(); }
      } catch (e) {
        if (!alive) return;
        failed = true;
        if (e instanceof ApiError && e.status === 404) {
          setGoneId(currentId);
          if (!notFound) void reload();
          notFound = true;
        } else {
          notFound = false;
          setDown(true);
        }
      }
      if (alive) timer = setTimeout(poll, STATUS_POLL_MS);
    };
    poll();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [currentId, single, bump, reload]);

  // Video duvarı: tam ekranın açık/kapalı durumu (Esc ile kapanınca da buradan öğrenilir)
  useEffect(() => {
    setCanWall(document.fullscreenEnabled === true);
    const onChange = () => setWallOn(document.fullscreenElement !== null && document.fullscreenElement === wallRef.current);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  const wall = async () => {
    try { await wallRef.current?.requestFullscreen(); } catch { /* tarayıcı izin vermedi */ }
  };
  const closeSingle = useCallback(() => setSingle(null), []);

  /** Kutunun canlı durumu: yalnız bu şablonun, bu düzenin ve bu kutudaki kamerayla eşleşen durumu sayılır */
  const tileStatus = (i: number): TileStatus | null => {
    if (!view || !status || status.id !== view.id || status.layout !== view.layout) return null;
    const st = status.tiles[i] ?? null;
    const ref = view.tiles[i] ?? null;
    if (!st || !ref || st.sourceId !== ref.sourceId || (st.channelId ?? null) !== (ref.channelId ?? null)) return null;
    return st;
  };
  const openTile = (i: number) => {
    const t = view?.tiles[i];
    if (!t) return;
    const st = tileStatus(i);
    setSingle({ sourceId: t.sourceId, channelId: t.channelId, name: st?.name ?? "Kamera", liveHref: liveHref(st?.analysis) });
  };

  const aspect = layout ? `${layout.cols * 16} / ${layout.rows * 9}` : "16 / 9";
  const ratio = layout ? (layout.cols * 16) / (layout.rows * 9) : 16 / 9;
  const src = view && size && view.id !== goneId ? `/api/live/views/${view.id}/stream?w=${size.w}&h=${size.h}&k=${streamKey}` : null;
  const singleMode: SingleMode = wallOn ? "wall" : phone.active ? "phone" : "page";
  // Video duvarında ızgara ekranı oranını koruyarak doldurur (ultra geniş ekranda taşmaz); telefon yatayken ekranı kaplar
  const gridClass = wallOn ? "relative overflow-hidden bg-black"
    : immersive ? "fixed inset-0 z-50 overflow-hidden bg-black"
    : "relative w-full overflow-hidden rounded-2xl bg-black";
  const gridStyle = immersive ? undefined
    : wallOn ? { aspectRatio: aspect, width: `min(100vw, calc(100vh * ${ratio}))` } : { aspectRatio: aspect };

  return (
    <div className="grid gap-4">
      {!single && !immersive && (
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="mr-2 text-2xl font-semibold">İzleme</h1>
          <select aria-label="Şablon" value={currentId ?? ""} onChange={(e) => setCurrentId(e.target.value || null)}
                  className="h-10 min-w-0 flex-1 rounded-[10px] border border-line bg-white px-3 text-sm sm:max-w-[320px]">
            {views.length === 0 && <option value="">{loaded ? "Henüz şablon yok" : "Yükleniyor…"}</option>}
            {views.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
          {canWall && (
            <button type="button" onClick={wall} disabled={!view} className="h-10 rounded-[10px] border border-line px-3 text-sm">Tüm ekran</button>
          )}
          {/* Görev 6: "Yeni şablon", "Düzenle", "Tüm kanallardan şablon" düğmeleri buraya */}
        </div>
      )}
      {down && !single && (
        <p role="status" className="rounded-xl bg-warn-50 px-3 py-2 text-sm text-warn-700">Analiz sunucusuna ulaşılamıyor; yeniden deneniyor…</p>
      )}
      {view && layout ? (
        // Video duvarı (tam ekran) bu kapsayıcıdır: tek kameraya geçilince de içinde kalır, tam ekran bozulmaz
        <div ref={wallRef} data-wall={wallOn ? "true" : undefined} className={wallOn ? "grid h-screen w-screen place-items-center bg-black" : undefined}>
          {single ? (
            <SingleCamera {...single} mode={singleMode} onClose={closeSingle} />
          ) : (
            <div ref={gridRef} data-testid="watch-grid" className={gridClass} style={gridStyle}>
              {src && (
                // eslint-disable-next-line @next/next/no-img-element -- canlı MJPEG akışı
                <img alt={`${view.name} canlı görüntü`} src={src} className="absolute inset-0 h-full w-full" onError={onError} />
              )}
              {layout.cells.map((_, i) => (
                <TileOverlay key={i} layout={layout} index={i} filled={view.tiles[i] != null} tile={tileStatus(i)}
                             onOpen={() => openTile(i)} onAlarm={(id) => center?.open(id)} />
              ))}
              {immersive && (
                <button type="button" aria-label="Tam ekran görünümünden çık" onClick={phone.exit}
                        className="absolute bottom-2 left-2 z-10 grid h-8 w-8 place-items-center rounded-full bg-black/60 text-lg leading-none text-white">×</button>
              )}
            </div>
          )}
        </div>
      ) : view ? (
        <p className="card p-6 text-sm text-muted">Bu şablonun düzeni tanınmıyor.</p>
      ) : loaded ? (
        <p className="card p-6 text-sm text-muted">Henüz şablon yok. &quot;Yeni şablon&quot; ile kameraları bir düzene yerleştirin.</p>
      ) : null}
    </div>
  );
}
