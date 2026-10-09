"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/live";
import { useAlarmCenter } from "@/components/live/AlarmCenter";
import { LAST_VIEW_KEY, STATUS_POLL_MS, streamSize, type ViewLayout, type ViewStatus, type ViewTemplate } from "@/lib/views";
import TileOverlay from "./TileOverlay";
import SingleCamera from "./SingleCamera";
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
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [status, setStatus] = useState<ViewStatus | null>(null);
  const [single, setSingle] = useState<{ sourceId: string; channelId: string | null; name: string } | null>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** Video duvarı (tam ekran) açık mı; tarayıcı tam ekranı desteklemiyorsa (ör. iPhone) düğme gizlenir */
  const [wallOn, setWallOn] = useState(false);
  const [canWall, setCanWall] = useState(false);
  const { streamKey, onError } = useStreamKey();
  const gridRef = useRef<HTMLDivElement>(null);
  const wallRef = useRef<HTMLDivElement>(null);
  const center = useAlarmCenter();

  const reload = useCallback(async (select?: string) => {
    const [l, v] = await Promise.all([api<ViewLayout[]>("view-layouts"), api<ViewTemplate[]>("views")]);
    setLayouts(l);
    setViews(v);
    const want = select ?? remembered();
    setCurrentId((cur) => (want && v.some((x) => x.id === want) ? want : cur && v.some((x) => x.id === cur) ? cur : v[0]?.id ?? null));
  }, []);
  useEffect(() => { reload().catch((e: Error) => setError(e.message)); }, [reload]);

  const view = views.find((v) => v.id === currentId) ?? null;
  const layout = view ? layouts.find((l) => l.id === view.layout) ?? null : null;
  useEffect(() => { if (currentId) remember(currentId); }, [currentId]);

  // Kapsayıcı boyutu: birleşik görüntü tam bu boyutta istenir (telefonda küçük, masaüstünde büyük)
  useEffect(() => {
    const el = gridRef.current;
    if (!el || !layout) return;
    const update = () => setSize(streamSize(el));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [layout, single]);

  // Kutu durumları
  useEffect(() => {
    if (!currentId || single) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const s = await api<ViewStatus>(`views/${currentId}/status`);
        if (alive) setStatus(s);
      } catch { /* sunucu yoksa şerit zaten uyarır */ }
      if (alive) timer = setTimeout(poll, STATUS_POLL_MS);
    };
    poll();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [currentId, single]);

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

  if (single) return <SingleCamera {...single} onClose={closeSingle} />;
  const aspect = layout ? `${layout.cols * 16} / ${layout.rows * 9}` : "16 / 9";
  const ratio = layout ? (layout.cols * 16) / (layout.rows * 9) : 16 / 9;
  const src = view && size ? `/api/live/views/${view.id}/stream?w=${size.w}&h=${size.h}&k=${streamKey}` : null;

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-2 text-2xl font-semibold">İzleme</h1>
        <select aria-label="Şablon" value={currentId ?? ""} onChange={(e) => setCurrentId(e.target.value || null)}
                className="h-10 min-w-0 flex-1 rounded-[10px] border border-line bg-white px-3 text-sm sm:max-w-[320px]">
          {views.length === 0 && <option value="">Henüz şablon yok</option>}
          {views.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
        </select>
        {canWall && (
          <button type="button" onClick={wall} disabled={!view} className="h-10 rounded-[10px] border border-line px-3 text-sm">Tüm ekran</button>
        )}
        {/* Görev 6: "Yeni şablon", "Düzenle", "Tüm kanallardan şablon" düğmeleri buraya */}
      </div>
      {error && <p role="alert" className="rounded-xl bg-nok-50 px-3 py-2 text-sm text-nok-600">{error}</p>}
      {view && layout ? (
        // Video duvarında kapsayıcı ekranı doldurur, ızgara oranını koruyarak ortalanır (ultra geniş ekranda taşmaz)
        <div ref={wallRef} data-wall={wallOn ? "true" : undefined} className={wallOn ? "grid h-screen w-screen place-items-center bg-black" : "bg-black"}>
          <div ref={gridRef} data-testid="watch-grid" className={`relative w-full overflow-hidden bg-black ${wallOn ? "" : "rounded-2xl"}`}
               style={wallOn ? { aspectRatio: aspect, width: `min(100vw, calc(100vh * ${ratio}))` } : { aspectRatio: aspect }}>
            {src && (
              // eslint-disable-next-line @next/next/no-img-element -- canlı MJPEG akışı
              <img alt={`${view.name} canlı görüntü`} src={src} className="absolute inset-0 h-full w-full" onError={onError} />
            )}
            {layout.cells.map((_, i) => (
              <TileOverlay key={i} layout={layout} index={i} tile={status?.id === view.id ? status.tiles[i] ?? null : null}
                           onOpen={() => {
                             const t = view.tiles[i];
                             const st = status?.tiles[i];
                             if (t) setSingle({ sourceId: t.sourceId, channelId: t.channelId, name: st?.name ?? "Kamera" });
                           }}
                           onAlarm={(id) => center?.open(id)} />
            ))}
          </div>
        </div>
      ) : (
        <p className="card p-6 text-sm text-muted">Henüz şablon yok. &quot;Yeni şablon&quot; ile kameraları bir düzene yerleştirin.</p>
      )}
    </div>
  );
}
