"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ApiError, api, type Source } from "@/lib/live";
import { FAILS_BEFORE_WARNING, useAlarmCenter } from "@/components/live/AlarmCenter";
import {
  copyName, LAST_VIEW_KEY, liveHref, problemOf, RELOAD_RETRY_MS, RESIZE_DEBOUNCE_MS, STATUS_POLL_MS, streamSize,
  type Problem, type TileStatus, type ViewLayout, type ViewStatus, type ViewTemplate,
} from "@/lib/views";
import { refKey } from "./CameraList";
import ConnectionProblem from "./ConnectionProblem";
import TileOverlay from "./TileOverlay";
import SingleCamera, { type SingleMode } from "./SingleCamera";
import ViewEditor from "./ViewEditor";
import { usePhoneLandscape } from "./usePhoneLandscape";
import { useStreamKey } from "./useStreamKey";

/** Durum, şablonun bu hâline mi ait: aynı düzen ve her kutuda aynı kamera (boş kutu boş) */
function sameTiles(status: ViewStatus, view: ViewTemplate): boolean {
  if (status.layout !== view.layout || status.tiles.length !== view.tiles.length) return false;
  return status.tiles.every((st, i) => {
    const ref = view.tiles[i] ?? null;
    if (!st || !ref) return !st && !ref;
    return st.sourceId === ref.sourceId && (st.channelId ?? null) === (ref.channelId ?? null);
  });
}

function remembered(): string | null {
  try { return window.localStorage.getItem(LAST_VIEW_KEY); } catch { return null; }
}
function remember(id: string): void {
  try { window.localStorage.setItem(LAST_VIEW_KEY, id); } catch { /* depolama yok */ }
}

const TOOL_BTN = "h-10 rounded-[10px] border border-line px-3 text-sm disabled:opacity-50";

/** İzleme sayfası: şablon seçici ve düzenleyici, birleşik canlı görüntü + kutu katmanları, tek kamera, tüm ekran (video duvarı) */
export default function WatchView() {
  const [layouts, setLayouts] = useState<ViewLayout[]>([]);
  const [views, setViews] = useState<ViewTemplate[]>([]);
  /** Şablon listesi en az bir kez alındı ("Henüz şablon yok" ancak o zaman söylenir) */
  const [loaded, setLoaded] = useState(false);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [status, setStatus] = useState<ViewStatus | null>(null);
  const [single, setSingle] = useState<{ sourceId: string; channelId: string | null; name: string; liveHref: string } | null>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  /** Analiz sunucusuyla konuşulamıyor (liste ya da durum yoklaması başarısız): sunucu yok ya da oturum doldu; düzelince kalkar */
  const [problem, setProblem] = useState<Problem | null>(null);
  /** Şablon düzenleyici açık: düzenlenen şablon ("new": yeni) */
  const [editing, setEditing] = useState<ViewTemplate | "new" | null>(null);
  /** Kayıt cihazları ("Tüm kanallardan şablon" için) */
  const [recorders, setRecorders] = useState<Source[]>([]);
  /** Kopyala / tüm kanallardan şablon sürerken tekrar tıklanamaz (çift kopya olmasın) */
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** Sunucu bu şablon için 404 verdi (silindi): akış istenmez, liste yeniden alınıp seçim düzeltilir */
  const [goneId, setGoneId] = useState<string | null>(null);
  /** Video duvarı (tam ekran) açık mı; tarayıcı tam ekranı desteklemiyorsa (ör. iPhone) düğme gizlenir */
  const [wallOn, setWallOn] = useState(false);
  const [canWall, setCanWall] = useState(false);
  const { streamKey, onError, bump, visible } = useStreamKey();
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
      setProblem(null);
      const want = select ?? remembered();
      setCurrentId((cur) => (want && v.some((x) => x.id === want) ? want : cur && v.some((x) => x.id === cur) ? cur : v[0]?.id ?? null));
      return true;
    } catch (e) {
      setProblem(problemOf(e));
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

  // Şablon başka bir cihazda düzenlendi: aynı şablonun durumu farklı düzen ya da kutularda farklı kamera bildirir
  // (önbellekteki şablon eski). Uyuşmazlık başına BİR kez liste yeniden alınır; yükleme sürerken tekrarlanmaz,
  // eşleşme görülünce (ya da yükleme başarısız olursa) yeniden izin verilir.
  const resyncing = useRef(false);
  useEffect(() => {
    if (!status || !view || status.id !== view.id) return;
    if (sameTiles(status, view)) { resyncing.current = false; return; }
    if (resyncing.current) return;
    resyncing.current = true;
    void reload(view.id).then((ok) => { if (!ok) resyncing.current = false; });
  }, [status, view, reload]);
  useEffect(() => { if (currentId) remember(currentId); }, [currentId]);
  const hasView = view !== null;
  useEffect(() => { if (!hasView) setSingle(null); }, [hasView]);   // şablon kalmadıysa tek kamera da kapanır
  // Kayıt cihazları: şablon listesi alınabildikten sonra (sunucu ayakta), "Tüm kanallardan şablon" seçici için
  useEffect(() => {
    if (!loaded) return;
    api<Source[]>("sources").then((s) => setRecorders(s.filter((x) => x.kind === "recorder"))).catch(() => undefined);
  }, [loaded]);

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
  }, [layout, single, wallOn, immersive, editing]);

  // Kutu durumları; aynı zamanda akışın bekçisi: Chrome, ilk karesi geldikten sonra kopan çok parçalı görüntüde çoğu
  // zaman `error` vermez (sekme görünür ve çevrimiçi kalır, görüntü son karede donar, rozetler taze görünür). Yoklama
  // koptuktan sonra düzelirse (sunucu yeniden başladı) akış baştan açılır; 404'te (şablon silindi) liste yeniden alınır.
  useEffect(() => {
    if (!currentId || single) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failed = false;
    let notFound = false;
    let fails = 0;                                      // üst üste başarısız yoklama (404 sunucunun ayakta olduğunu gösterir, sayılmaz)
    const poll = async () => {
      try {
        const s = await api<ViewStatus>(`views/${currentId}/status`);
        if (!alive) return;
        setStatus(s);
        fails = 0;
        setProblem(null);
        setGoneId((g) => (g === currentId ? null : g));
        notFound = false;
        if (failed) { failed = false; bump(); }
      } catch (e) {
        if (!alive) return;
        failed = true;
        if (e instanceof ApiError && e.status === 404) {
          fails = 0;
          setGoneId(currentId);
          if (!notFound) void reload();
          notFound = true;
        } else {
          notFound = false;
          fails += 1;
          if (fails >= FAILS_BEFORE_WARNING) setProblem(problemOf(e));   // tek aksama uyarı çıkarmaz (alarm şeridiyle aynı eşik)
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
  /** Düzenleyicinin kutu adları: şablonun son durumundaki kamera adları (kamera → ad) */
  const names = Object.fromEntries((status?.tiles ?? []).filter((t): t is TileStatus => !!t)
    .map((t) => [refKey({ sourceId: t.sourceId, channelId: t.channelId }), t.name]));
  const startEdit = (v: ViewTemplate | "new") => { setInfo(null); setError(null); setEditing(v); };
  /** Şablonu kopyalar ("… (kopya)", ad doluysa "… (kopya) 2") ve yeni şablona geçer */
  const copy = async () => {
    if (!view || busy) return;
    setBusy(true); setInfo(null); setError(null);
    try {
      const v = await api<ViewTemplate>("views", { method: "POST", json: { name: copyName(view.name, views.map((x) => x.name)), layout: view.layout, tiles: view.tiles } });
      await reload(v.id);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  /** Kayıt cihazının tüm kanallarından (en çok 16) şablon kurar ve ona geçer */
  const fromRecorder = async (sourceId: string) => {
    if (!sourceId || busy) return;
    setBusy(true); setInfo(null); setError(null);
    try {
      const v = await api<ViewTemplate & { truncated: boolean; channelCount: number }>("views/from-recorder", { method: "POST", json: { sourceId } });
      setInfo(v.truncated ? `İlk 16 kanal alındı (toplam ${v.channelCount}).` : null);
      await reload(v.id);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const openTile = (i: number) => {
    const t = view?.tiles[i];
    if (!t) return;
    const st = tileStatus(i);
    setSingle({ sourceId: t.sourceId, channelId: t.channelId, name: st?.name ?? "Kamera", liveHref: liveHref(st?.analysis) });
  };

  const aspect = layout ? `${layout.cols * 16} / ${layout.rows * 9}` : "16 / 9";
  const ratio = layout ? (layout.cols * 16) / (layout.rows * 9) : 16 / 9;
  // Gizli sekmede akış istenmez (`<img>` çizilmez): sunucuda birleştirici ve okuyucular boşuna açık kalmaz
  const src = visible && view && size && view.id !== goneId ? `/api/live/views/${view.id}/stream?w=${size.w}&h=${size.h}&k=${streamKey}` : null;
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
          {!editing && (
            <>
              <select aria-label="Şablon" value={currentId ?? ""}
                      onChange={(e) => { setInfo(null); setError(null); setCurrentId(e.target.value || null); }}
                      className="h-10 min-w-0 flex-1 rounded-[10px] border border-line bg-white px-3 text-sm sm:max-w-[320px]">
                {views.length === 0 && <option value="">{loaded ? "Henüz şablon yok" : "Yükleniyor…"}</option>}
                {views.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
              </select>
              {canWall && <button type="button" onClick={wall} disabled={!view} className={TOOL_BTN}>Tüm ekran</button>}
              <button type="button" onClick={() => startEdit("new")} disabled={layouts.length === 0} className={TOOL_BTN}>Yeni şablon</button>
              <button type="button" onClick={() => view && startEdit(view)} disabled={!view || layouts.length === 0} className={TOOL_BTN}>Düzenle</button>
              <button type="button" onClick={copy} disabled={!view || busy} className={TOOL_BTN}>Kopyala</button>
              {recorders.length > 0 && (
                <select aria-label="Tüm kanallardan şablon" value="" disabled={busy} onChange={(e) => fromRecorder(e.target.value)}
                        className="h-10 rounded-[10px] border border-line bg-white px-2 text-sm disabled:opacity-50">
                  <option value="">Tüm kanallardan şablon…</option>
                  {recorders.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                </select>
              )}
            </>
          )}
        </div>
      )}
      {problem && !single && (
        <p role="status" className="rounded-xl bg-warn-50 px-3 py-2 text-sm text-warn-700"><ConnectionProblem problem={problem} /></p>
      )}
      {error && <p role="alert" className="rounded-xl bg-nok-50 px-3 py-2 text-sm text-nok-600">{error}</p>}
      {info && <p role="status" className="rounded-xl bg-warn-50 px-3 py-2 text-sm text-warn-700">{info}</p>}
      {editing ? (
        <ViewEditor initial={editing === "new" ? null : editing} layouts={layouts} names={names}
                    onSaved={(v) => { setEditing(null); void reload(v.id); }} onCancel={() => setEditing(null)}
                    onDeleted={() => { setEditing(null); void reload(); }} />
      ) : view && layout ? (
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
