"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, type Source } from "@/lib/live";
import { FAILS_BEFORE_WARNING, useAlarmCenter } from "@/components/live/AlarmCenter";
import PageHeader from "@/components/PageHeader";
import { useUnsavedGuard } from "@/components/UnsavedGuard";
import { layoutFor } from "@/lib/layoutGrid.mjs";
import {
  applyLayout, assign, canRedo, canUndo, initHistory, isDirty, neighbor, newDraft, newName, push, redo, refKey, sameContent, swap, undo,
  type Draft, type History,
} from "@/lib/templateEdit.mjs";
import {
  copyName, LAST_VIEW_KEY, liveHref, problemOf, RELOAD_RETRY_MS, RESIZE_DEBOUNCE_MS, STATUS_POLL_MS, streamSize, UNSAVED_TEXT,
  type Problem, type TileRef, type TileStatus, type ViewLayout, type ViewStatus, type ViewTemplate,
} from "@/lib/views";
import CameraList, { type CamState } from "./CameraList";
import ConnectionProblem from "./ConnectionProblem";
import ContextMenu, { type MenuAction } from "./ContextMenu";
import EditorMenu from "./EditorMenu";
import NameDialog from "./NameDialog";
import SingleCamera, { type SingleMode } from "./SingleCamera";
import TemplateTabs, { PANEL_ID, tabDomId, type TabItem } from "./TemplateTabs";
import TileOverlay, { type TileDrop, type TileMove } from "./TileOverlay";
import { useDraft } from "./useDraft";
import { usePhoneLandscape } from "./usePhoneLandscape";
import { useStreamKey } from "./useStreamKey";

/** Kaydedilmemiş yeni şablonun sekmesi (sunucuda henüz yok) */
const NEW_ID = "yeni";
const isDraftId = (id: string) => id.startsWith("draft-");
const droppedNote = (n: number) => `${n} kamera düzene sığmadı ve şablondan çıkarıldı. Geri al ile geri getirilebilir.`;
const FULL_HINT = "Bütün kutular dolu: değiştirmek istediğiniz kutuyu seçin ya da önce bir kutuyu boşaltın.";
const DELETED_ELSEWHERE = "Bu şablon başka yerde silindi; değişiklikler kaydedilmemiş yeni sekmede.";

/** Durum, şablonun bu hâline mi ait: aynı düzen ve her kutuda aynı kamera (boş kutu boş) */
function sameTiles(status: ViewStatus, view: ViewTemplate): boolean {
  return sameContent({ layout: status.layout, tiles: status.tiles }, view);
}

function remembered(): string | null {
  try { return window.localStorage.getItem(LAST_VIEW_KEY); } catch { return null; }
}
function remember(id: string): void {
  try { window.localStorage.setItem(LAST_VIEW_KEY, id); } catch { /* depolama yok */ }
}
const firstEmpty = (tiles: Array<TileRef | null>): number | null => {
  const i = tiles.findIndex((t) => !t);
  return i < 0 ? null : i;
};
/** `from`'dan sonraki ilk boş kutu (başa sararak); boş kalmadıysa null */
const nextEmpty = (tiles: Array<TileRef | null>, from: number): number | null => {
  for (let k = 1; k <= tiles.length; k++) {
    const j = (from + k) % tiles.length;
    if (!tiles[j]) return j;
  }
  return null;
};
/** Klavye kısayolu yazı kutusunda mı (Ctrl+Z oradaki metni geri alsın) */
const typing = (t: EventTarget | null) => t instanceof HTMLElement && (t.isContentEditable || !!t.closest("input, textarea, select"));

type Single = { sourceId: string; channelId: string | null; name: string; liveHref: string };
type Menu = { kind: "tab"; id: string; x: number; y: number } | { kind: "tile"; index: number; x: number; y: number };
type Naming = { title: string; initial: string; submit: (name: string) => Promise<void> };

/**
 * Canlı izleme (TRASSIR gibi; taslak duzen.html, sayfalar.html): üstte şablon sekmeleri, "Şablon editörü" menüsü,
 * birleşik canlı görüntü + kutu katmanları, sağda kamera listesi; tek kamera, video duvarı (tam ekran), telefon yatay.
 *
 * Düzenleme her zaman açıktır: düzen düğmesi, sürükle-bırak, dokun-seç ya da Boşalt şablonun düzenlenen hâlini değiştirir
 * (geri al / yinele geçmişi, sekme başına, sayfa yenilenince silinir). Düzenlenen hâl kayıtlı şablondan farklıysa
 * analiz sunucusunda bir taslak açılır ve ızgara taslağın akışını gösterir; "Kaydet" tıklanana dek şablon değişmez.
 * Kaydedilmemiş değişiklikle sekme değiştirmek, menüden başka sayfaya gitmek ya da sayfayı kapatmak sorulur.
 */
export default function WatchView() {
  const [layouts, setLayouts] = useState<ViewLayout[]>([]);
  const [views, setViews] = useState<ViewTemplate[]>([]);
  /** Şablon listesi en az bir kez alındı ("Henüz şablon yok" ancak o zaman söylenir) */
  const [loaded, setLoaded] = useState(false);
  const [currentId, setCurrentId] = useState<string | null>(null);
  /** Kaydedilmemiş yeni şablonun adı (sekmesi açıkken); yeni şablon yalnız seçiliyken vardır */
  const [fresh, setFresh] = useState<string | null>(null);
  /** Düzenleme geçmişi; yalnız `tabId` sekmesi seçiliyken geçerli (yoksa kayıtlı şablonun kendisi gösterilir) */
  const [edit, setEdit] = useState<{ tabId: string; hist: History } | null>(null);
  /** Seçili kutu: listeden tıklanan kamera buraya yerleşir */
  const [selected, setSelected] = useState<number | null>(null);
  /** Izgaranın klavye sekme durağı (gezici sekme sırası: ok tuşları kutudan kutuya); seçimden bağımsız */
  const [focusIdx, setFocusIdx] = useState(0);
  const [status, setStatus] = useState<ViewStatus | null>(null);
  const [single, setSingle] = useState<Single | null>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  /** Analiz sunucusuyla konuşulamıyor (liste ya da durum yoklaması başarısız): sunucu yok ya da oturum doldu; düzelince kalkar */
  const [problem, setProblem] = useState<Problem | null>(null);
  /** Kayıt cihazları ("NVR'dan şablon" için) */
  const [recorders, setRecorders] = useState<Source[]>([]);
  /** Kamera → kutu etiketi (kamera listesinden): durum gelmeden kutuda ad görünsün */
  const [labels, setLabels] = useState<Record<string, string>>({});
  /** Kaydet / kopyala / sil / NVR'dan şablon sürerken tekrar tıklanamaz */
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** Düzen küçülünce düşen kameralar ya da "bütün kutular dolu" */
  const [note, setNote] = useState<string | null>(null);
  /** Sunucu bu şablon için 404 verdi (silindi): akış istenmez, liste yeniden alınıp seçim düzeltilir */
  const [goneId, setGoneId] = useState<string | null>(null);
  const [menu, setMenu] = useState<Menu | null>(null);
  const [naming, setNaming] = useState<Naming | null>(null);
  /** Video duvarı (tam ekran) açık mı; tarayıcı tam ekranı desteklemiyorsa (ör. iPhone) düğme gizlenir */
  const [wallOn, setWallOn] = useState(false);
  const [canWall, setCanWall] = useState(false);
  const { streamKey, onError, bump, visible } = useStreamKey();
  const phone = usePhoneLandscape();
  const gridRef = useRef<HTMLDivElement>(null);
  const wallRef = useRef<HTMLDivElement>(null);
  const center = useAlarmCenter();
  const guard = useUnsavedGuard();
  /** Bu sayfada silinen şablon: listeden kalkınca "başka yerde silindi" sayılmasın */
  const discarded = useRef<string | null>(null);
  /** Güncel değerler (işleyiciler ve `reload` sabit kalsın diye ref üzerinden okunur); her çizimde aşağıda doldurulur */
  const live = useRef({
    hist: null as History | null, currentId: null as string | null, present: null as Draft | null, selected: null as number | null,
    single: null as Single | null, byKey: new Map<string, TileStatus>(), labels: {} as Record<string, string>, dirty: false,
    layout: null as ViewLayout | null, tabName: null as string | null,
  });
  const keepAsNew = useRef<(notice: string) => void>(() => undefined);

  /**
   * Şablon ve düzen listesini alır; başarıyı döndürür. Seçili şablon silinmişse kalanlardan birine geçilir; ama
   * kaydedilmemiş düzenlemesi varsa (başka yerde silindi) düzenleme atılmaz: kaydedilmemiş yeni sekme olarak kalır.
   */
  const reload = useCallback(async (): Promise<boolean> => {
    try {
      const [l, v] = await Promise.all([api<ViewLayout[]>("view-layouts"), api<ViewTemplate[]>("views")]);
      setLayouts(l);
      setViews(v);
      setLoaded(true);
      setProblem(null);
      const { currentId: id, dirty: d } = live.current;
      if (d && id && id !== NEW_ID && id !== discarded.current && !v.some((x) => x.id === id)) {
        keepAsNew.current(DELETED_ELSEWHERE);
        return true;
      }
      setCurrentId((cur) => {
        if (cur === NEW_ID) return cur;                     // kaydedilmemiş yeni şablon açık kalır
        const want = remembered();
        return want && v.some((x) => x.id === want) ? want : cur && v.some((x) => x.id === cur) ? cur : v[0]?.id ?? null;
      });
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

  const isNew = currentId === NEW_ID && fresh !== null;
  const view = isNew ? null : views.find((v) => v.id === currentId) ?? null;
  const saved = useMemo<Draft | null>(() => (view ? { layout: view.layout, tiles: view.tiles, name: view.name } : null), [view]);
  const hist = useMemo<History | null>(
    () => (edit && edit.tabId === currentId ? edit.hist : saved ? initHistory(saved) : null), [edit, currentId, saved]);
  const present = hist?.present ?? null;
  const dirty = hist !== null && isDirty(hist, isNew ? null : saved);
  const tabName = isNew ? fresh : view?.name ?? "";
  const presentLayout = present?.layout ?? null;
  const layout = useMemo(() => (presentLayout ? layoutFor(presentLayout, layouts) : null), [presentLayout, layouts]);

  // Sekme değişince: başka sekmenin geçmişi, yeni şablon, seçim, menü ve iletiler bırakılır; seçim hatırlanır
  useEffect(() => {
    setEdit((e) => (e && e.tabId !== currentId ? null : e));
    if (currentId !== NEW_ID) setFresh(null);
    setSelected(null);
    setFocusIdx(0);
    setMenu(null);
    setNote(null);
    if (currentId && currentId !== NEW_ID) remember(currentId);
  }, [currentId]);
  // Kayıtlı şablon değişti (başka cihazda düzenlendi): düzenleme yoksa (kayıtlı hâl gösteriliyordu) yenisi izlenir;
  // kaydedilmemiş düzenleme varsa korunur. Kaydet sonrası (düzenlenen = kayıtlı) geçmiş de korunur.
  const prevSaved = useRef<Draft | null>(null);
  useEffect(() => {
    const prev = prevSaved.current;
    prevSaved.current = saved;
    if (!saved) return;
    setEdit((e) => {
      if (!e || e.tabId !== currentId || sameContent(e.hist.present, saved)) return e;
      return prev && sameContent(e.hist.present, prev) ? null : e;
    });
  }, [saved, currentId]);

  // Kaydedilmemiş değişiklik bekçisi (menü bağlantıları, sayfayı kapatma)
  useEffect(() => { guard.setDirty(dirty); }, [dirty, guard]);
  useEffect(() => () => guard.setDirty(false), [guard]);

  // Kaydedilmemiş düzenleme analiz sunucusunda taslak olarak canlı akar
  const draftBody = useMemo(() => (dirty && present && layout ? { layout: present.layout, tiles: present.tiles } : null),
    [dirty, present, layout]);
  const { draftId, error: draftError, lost } = useDraft(currentId, draftBody);
  const streamId = dirty && draftId ? draftId : view?.id ?? null;

  // Şablon başka bir cihazda düzenlendi: aynı şablonun durumu farklı düzen ya da kutularda farklı kamera bildirir
  // (önbellekteki şablon eski). Uyuşmazlık başına BİR kez liste yeniden alınır; yükleme sürerken tekrarlanmaz,
  // eşleşme görülünce (ya da yükleme başarısız olursa) yeniden izin verilir. Taslak gösterilirken bakılmaz.
  const resyncing = useRef(false);
  useEffect(() => {
    if (!status || !view || status.id !== view.id) return;
    if (sameTiles(status, view)) { resyncing.current = false; return; }
    if (resyncing.current) return;
    resyncing.current = true;
    void reload().then((ok) => { if (!ok) resyncing.current = false; });
  }, [status, view, reload]);
  const hasPresent = present !== null;
  useEffect(() => { if (!hasPresent) setSingle(null); }, [hasPresent]);   // şablon kalmadıysa tek kamera da kapanır
  // Kayıt cihazları: şablon listesi alınabildikten sonra (sunucu ayakta), "NVR'dan şablon" seçici için
  useEffect(() => {
    if (!loaded) return;
    api<Source[]>("sources").then((s) => setRecorders(s.filter((x) => x.kind === "recorder"))).catch(() => undefined);
  }, [loaded]);
  // Seçili kutu düzen küçülünce kalmadıysa seçim kalkar
  const tileCount = layout?.cells.length ?? 0;
  useEffect(() => { setSelected((s) => (s !== null && s >= tileCount ? null : s)); }, [tileCount]);

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

  // Kutu durumları (şablonun ya da taslağın); aynı zamanda akışın bekçisi: Chrome, ilk karesi geldikten sonra kopan çok
  // parçalı görüntüde çoğu zaman `error` vermez. Yoklama koptuktan sonra düzelirse (sunucu yeniden başladı) akış baştan
  // açılır; 404'te şablon silinmişse liste yeniden alınır, taslak silinmişse (10 dk boşta, sunucu yeniden başladı)
  // sessizce yenisi açılır. 128 kutuda da tek yoklama.
  useEffect(() => {
    if (!streamId || single) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failed = false;
    let notFound = false;
    let fails = 0;                                      // üst üste başarısız yoklama (404 sunucunun ayakta olduğunu gösterir, sayılmaz)
    const poll = async () => {
      try {
        const s = await api<ViewStatus>(`views/${streamId}/status`);
        if (!alive) return;
        setStatus(s);
        fails = 0;
        setProblem(null);
        setGoneId((g) => (g === streamId ? null : g));
        notFound = false;
        if (failed) { failed = false; bump(); }
      } catch (e) {
        if (!alive) return;
        failed = true;
        if (e instanceof ApiError && e.status === 404) {
          fails = 0;
          if (isDraftId(streamId)) lost(streamId);
          else {
            setGoneId(streamId);
            if (!notFound) void reload();
          }
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
  }, [streamId, single, bump, reload, lost]);

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
  const closeMenu = useCallback(() => setMenu(null), []);

  /** Kameranın canlı durumu (son yoklamadan; kamera başına, kutu sırasından bağımsız: taslak güncellenirken de geçerli) */
  const byKey = useMemo(() => new Map((status?.tiles ?? []).filter((t): t is TileStatus => !!t)
    .map((t) => [refKey(t), t] as const)), [status]);
  const tileStatus = (i: number): TileStatus | null => {
    const ref = present?.tiles[i];
    return ref ? byKey.get(refKey(ref)) ?? null : null;
  };
  const used = useMemo(() => new Set((present?.tiles ?? []).filter((t): t is TileRef => !!t).map(refKey)), [present]);
  const stateOf = useCallback((key: string): CamState | undefined => {
    const st = byKey.get(key)?.state;
    return st === "live" ? "live" : st === "error" ? "problem" : undefined;
  }, [byKey]);

  // ---- düzenleme (geçmişe yazılır)

  live.current = { hist, currentId, present, selected, single, byKey, labels, dirty, layout, tabName };
  const commit = useCallback((next: Draft) => {
    const { hist: h, currentId: id } = live.current;
    if (!h || !id) return;
    setEdit({ tabId: id, hist: push(h, next) });
  }, []);
  const place = useCallback((i: number, ref: TileRef, label?: string) => {
    const p = live.current.present;
    if (!p) return;
    commit(assign(p, i, ref));
    if (label) setLabels((m) => (m[refKey(ref)] === label ? m : { ...m, [refKey(ref)]: label }));
    setNote(null);
  }, [commit]);
  const emptyTile = useCallback((i: number) => {
    const p = live.current.present;
    if (!p) return;
    commit(assign(p, i, null));
    setSelected(i);
    setNote(null);
  }, [commit]);
  const onDropped = useCallback((i: number, d: TileDrop) => {
    const p = live.current.present;
    if (!p) return;
    if (d.kind === "tile") { commit(swap(p, d.from, i)); setSelected(i); return; }
    try {
      const { ref, name } = JSON.parse(d.payload) as { ref: TileRef; name: string };
      place(i, ref, name);
      setSelected(i);
    } catch { /* bozuk sürükleme verisi yok sayılır */ }
  }, [commit, place]);
  /** Listeden tıklanan kamera: seçili kutuya, yoksa ilk boş kutuya; sonra sıradaki boş kutu seçilir */
  const pick = useCallback((ref: TileRef, label: string) => {
    const { present: p, selected: sel } = live.current;
    if (!p) return;
    const target = sel ?? firstEmpty(p.tiles);
    if (target === null) { setNote(FULL_HINT); return; }
    place(target, ref, label);
    setSelected(nextEmpty(assign(p, target, ref).tiles, target));
  }, [place]);
  const chooseLayout = (id: string) => {
    if (!present) return;
    const r = applyLayout(present, id, layouts);
    commit(r.draft);
    setSelected(null);
    setNote(r.dropped ? droppedNote(r.dropped) : null);
  };
  const doUndo = useCallback(() => {
    const { hist: h, currentId: id } = live.current;
    if (h && id && canUndo(h)) { setEdit({ tabId: id, hist: undo(h) }); setNote(null); }
  }, []);
  const doRedo = useCallback(() => {
    const { hist: h, currentId: id } = live.current;
    if (h && id && canRedo(h)) { setEdit({ tabId: id, hist: redo(h) }); setNote(null); }
  }, []);
  // Ctrl+Z / Ctrl+Y (Ctrl+Shift+Z): yazı kutusu, açık pencere ya da tek kamera dışında
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.altKey || typing(e.target) || document.querySelector("dialog[open]") || live.current.single) return;
      const k = e.key.toLowerCase();
      if (k === "z" && !e.shiftKey) { e.preventDefault(); doUndo(); }
      else if (k === "y" || (k === "z" && e.shiftKey)) { e.preventDefault(); doRedo(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [doUndo, doRedo]);

  const openTile = useCallback((i: number) => {
    const { present: p, byKey: m, labels: names } = live.current;
    const t = p?.tiles[i];
    if (!t) return;
    const st = m.get(refKey(t)) ?? null;
    setSingle({ sourceId: t.sourceId, channelId: t.channelId, name: st?.name ?? names[refKey(t)] ?? "Kamera", liveHref: liveHref(st?.analysis) });
  }, []);
  const addLabels = useCallback((l: Record<string, string>) => setLabels((m) => ({ ...m, ...l })), []);
  const onAlarm = useCallback((id: string) => center?.open(id), [center]);
  const onTileMenu = useCallback((index: number, x: number, y: number) => setMenu({ kind: "tile", index, x, y }), []);
  /** Klavye: ok tuşları / Home / End ile sekme durağı ve odak komşu kutuya geçer (seçim değişmez) */
  const onMove = useCallback((i: number, to: TileMove) => {
    const l = live.current.layout;
    if (!l) return;
    const n = to === "home" ? 0 : to === "end" ? l.cells.length - 1 : neighbor(l, i, to);
    setFocusIdx(n);
    gridRef.current?.querySelectorAll<HTMLElement>("[data-testid=watch-tile]")[n]?.focus();
  }, []);
  /**
   * Şablon sunucuda yok (başka yerde silindi) ama kaydedilmemiş düzenleme var: düzenleme atılmaz, aynı adla kaydedilmemiş
   * yeni sekmeye taşınır ("Kaydet" yeni şablon olarak yazar) ve neden söylenir.
   */
  keepAsNew.current = (notice: string) => {
    const { hist: h, tabName: name } = live.current;
    if (!h) return;
    setFresh(name || newName([]));
    setEdit({ tabId: NEW_ID, hist: h });
    setCurrentId(NEW_ID);
    setInfo(notice);
  };

  // ---- sekmeler ve şablon işlemleri

  /** Kaydedilmemiş değişiklik varsa sorar; ayrılmak serbestse true */
  const leaveOk = () => !dirty || window.confirm(UNSAVED_TEXT);
  const clearMessages = () => { setInfo(null); setError(null); };
  const selectTab = (id: string) => {
    if (id === currentId || !leaveOk()) return;
    clearMessages();
    setCurrentId(id);
  };
  const newTemplate = () => {
    if (!layouts.length || !leaveOk()) return;
    clearMessages();
    const name = newName(views.map((v) => v.name));
    setFresh(name);
    setCurrentId(NEW_ID);
    setEdit({ tabId: NEW_ID, hist: initHistory({ ...newDraft(layouts), name }) });
    setSelected(null);
    setNote(null);
  };
  /**
   * Sunucudan dönen yeni şablonu listeye ekler ve (uygunsa) ona geçer; geçildiyse true. `origin`: işlemin başladığı
   * sekme; `carry`: o sekmenin düzenleme geçmişi yeni şablona taşınır (Kaydet, Farklı kaydet). İstek sürerken başka
   * sekmeye geçildiyse, ya da (taşımadan) bu sekmede yeni düzenleme yapıldıysa geçilmez: düzenleme sorusuz atılmaz.
   */
  const adopt = (v: ViewTemplate, origin: string | null, carry: boolean): boolean => {
    const { currentId: cur, dirty: d } = live.current;
    setViews((vs) => [...vs.filter((x) => x.id !== v.id), v]);
    const go = cur === origin && (carry || !d);
    if (go) {
      setEdit((e) => (carry && e && e.tabId === origin ? { tabId: v.id, hist: e.hist } : null));
      setCurrentId(v.id);
    }
    void reload();
    return go;
  };
  const added = (v: ViewTemplate) => `"${v.name}" şablonu eklendi.`;
  const run = async (fn: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    clearMessages();
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const save = () => run(async () => {
    if (!present || !tabName) return;
    const origin = currentId;
    const body = { name: tabName, layout: present.layout, tiles: present.tiles };
    if (isNew) {
      const v = await api<ViewTemplate>("views", { method: "POST", json: body });
      if (!adopt(v, origin, true)) setInfo(added(v));
    } else if (view) {
      try {
        const v = await api<ViewTemplate>(`views/${view.id}`, { method: "PUT", json: body });
        setViews((vs) => vs.map((x) => (x.id === v.id ? v : x)));
      } catch (e) {
        // Şablon başka yerde silinmiş: düzenleme kaydedilmemiş yeni sekmede kalır (yeniden "Kaydet" yeni şablon yazar)
        if (!(e instanceof ApiError && e.status === 404) || live.current.currentId !== origin) throw e;
        setViews((vs) => vs.filter((x) => x.id !== view.id));
        keepAsNew.current(DELETED_ELSEWHERE);
      }
    }
  });
  const saveAs = () => {
    if (!present) return;
    const content = { layout: present.layout, tiles: present.tiles };
    const origin = currentId;
    setNaming({
      title: "Farklı kaydet", initial: copyName(tabName ?? "", views.map((v) => v.name)),
      submit: async (name) => {
        const v = await api<ViewTemplate>("views", { method: "POST", json: { name, ...content } });
        setNaming(null);
        clearMessages();
        if (!adopt(v, origin, true)) setInfo(added(v));
      },
    });
  };
  const renameTab = (id: string) => {
    if (id === NEW_ID) {
      setNaming({ title: "Yeniden adlandır", initial: fresh ?? "", submit: async (name) => { setFresh(name); setNaming(null); } });
      return;
    }
    const v = views.find((x) => x.id === id);
    if (!v) return;
    setNaming({
      title: "Yeniden adlandır", initial: v.name,
      // Yalnız ad değişir: sunucudaki GÜNCEL düzen ve kutular gider (başka yerdeki düzenleme geri alınmaz); bu sekmedeki
      // kaydedilmemiş düzenleme olduğu gibi kalır
      submit: async (name) => {
        const list = await api<ViewTemplate[]>("views");
        const cur = list.find((x) => x.id === v.id);
        if (!cur) throw new Error("Şablon bulunamadı; başka yerde silinmiş olabilir.");
        const n = await api<ViewTemplate>(`views/${v.id}`, { method: "PUT", json: { name, layout: cur.layout, tiles: cur.tiles } });
        setViews(list.map((x) => (x.id === n.id ? n : x)));
        setNaming(null);
      },
    });
  };
  const copyTab = (id: string) => {
    const v = views.find((x) => x.id === id);
    if (!v || !leaveOk()) return;
    const origin = currentId;
    void run(async () => {
      const c = await api<ViewTemplate>("views", { method: "POST", json: { name: copyName(v.name, views.map((x) => x.name)), layout: v.layout, tiles: v.tiles } });
      if (!adopt(c, origin, false)) setInfo(added(c));
    });
  };
  const deleteTab = (id: string) => {
    const name = id === NEW_ID ? fresh : views.find((x) => x.id === id)?.name;
    if (name == null || !window.confirm(`"${name}" şablonu silinsin mi?`)) return;
    if (id === NEW_ID) {
      clearMessages();
      setCurrentId(views.find((x) => x.id === remembered())?.id ?? views[0]?.id ?? null);
      return;
    }
    void run(async () => {
      discarded.current = id;
      await api(`views/${id}`, { method: "DELETE" });
      setViews((vs) => vs.filter((x) => x.id !== id));
      setEdit((e) => (e && e.tabId === id ? null : e));
      await reload();
    });
  };
  /** Kayıt cihazının tüm kanallarından (en çok 16) şablon kurar ve ona geçer */
  const fromRecorder = (sourceId: string) => {
    if (!leaveOk()) return;
    const origin = currentId;
    void run(async () => {
      const v = await api<ViewTemplate & { truncated: boolean; channelCount: number }>("views/from-recorder", { method: "POST", json: { sourceId } });
      const note = v.truncated ? `İlk 16 kanal alındı (toplam ${v.channelCount}).` : null;
      setInfo(adopt(v, origin, false) ? note : [added(v), note].filter(Boolean).join(" "));
    });
  };

  const tabs: TabItem[] = [
    ...views.map((v) => ({ id: v.id, name: v.name, unsaved: v.id === currentId && dirty })),
    ...(isNew && fresh ? [{ id: NEW_ID, name: fresh, unsaved: true }] : []),
  ];
  const menuActions = (m: Menu): MenuAction[] => {
    if (m.kind === "tab") {
      return [
        { label: "Yeniden adlandır", onSelect: () => renameTab(m.id) },
        { label: "Kopyala", onSelect: () => copyTab(m.id), disabled: m.id === NEW_ID || busy },
        { label: "Sil", onSelect: () => deleteTab(m.id), disabled: busy },
      ];
    }
    return [
      { label: "Tek kamera", onSelect: () => openTile(m.index) },
      { label: "Boşalt", onSelect: () => emptyTile(m.index) },
    ];
  };

  const aspect = layout ? `${layout.cols * 16} / ${layout.rows * 9}` : "16 / 9";
  const ratio = layout ? (layout.cols * 16) / (layout.rows * 9) : 16 / 9;
  // Gizli sekmede akış istenmez (`<img>` çizilmez): sunucuda birleştirici ve okuyucular boşuna açık kalmaz
  const src = visible && streamId && size && streamId !== goneId ? `/api/live/views/${streamId}/stream?w=${size.w}&h=${size.h}&k=${streamKey}` : null;
  const singleMode: SingleMode = wallOn ? "wall" : phone.active ? "phone" : "page";
  // Video duvarında ızgara ekranı oranını koruyarak doldurur (ultra geniş ekranda taşmaz); telefon yatayken ekranı kaplar
  const gridClass = wallOn ? "relative overflow-hidden bg-black"
    : immersive ? "fixed inset-0 z-50 overflow-hidden bg-black"
    : "relative w-full overflow-hidden bg-black";
  const gridStyle = immersive ? undefined
    : wallOn ? { aspectRatio: aspect, width: `min(100vw, calc(100vh * ${ratio}))` }
    // sayfada: geniş ekranda ızgara pencere yüksekliğine sığar (sekmeler ve araç çubuğu görünür kalır)
    : { aspectRatio: aspect, width: `min(100%, max(320px, calc((100svh - 230px) * ${ratio})))` };
  const chrome = !single && !immersive;
  const message = "border px-3 py-1.5 text-[13px]";

  return (
    <div className="grid min-w-0 gap-2">
      {chrome && (
        <>
          <PageHeader title="Canlı izleme" />
          <TemplateTabs tabs={tabs} current={currentId} onSelect={selectTab} onAdd={newTemplate}
                        onMenu={(id, x, y) => setMenu({ kind: "tab", id, x, y })} addDisabled={layouts.length === 0} />
          <div className="flex flex-wrap items-center gap-1.5">
            <EditorMenu layoutId={present?.layout ?? null} canUndo={!!hist && canUndo(hist)} canRedo={!!hist && canRedo(hist)}
                        canSave={dirty && !!layout} canSaveAs={!!present && !!layout} busy={busy} disabled={layouts.length === 0}
                        recorders={recorders} onNew={newTemplate} onUndo={doUndo} onRedo={doRedo} onSave={save} onSaveAs={saveAs}
                        onLayout={chooseLayout} onFromRecorder={fromRecorder}
                        canClearSelected={selected !== null && !!present?.tiles[selected]}
                        onClearSelected={() => { if (selected !== null) emptyTile(selected); }} />
            <button type="button" onClick={save} disabled={!dirty || !layout || busy} className="pl-btn">Kaydet</button>
            <button type="button" onClick={doUndo} disabled={!hist || !canUndo(hist)} className="pl-btn">Geri al</button>
            {canWall && <button type="button" onClick={wall} disabled={!present || !layout} className="pl-btn">Tüm ekran</button>}
            {dirty && <span className="text-[12px] text-warn-700">Kaydedilmemiş değişiklik var</span>}
          </div>
        </>
      )}
      {problem && !single && (
        <p role="status" className={`${message} border-warn-line bg-warn-50 text-warn-700`}><ConnectionProblem problem={problem} /></p>
      )}
      {(error || draftError) && chrome && (
        <p role="alert" className={`${message} border-nok-line bg-nok-50 text-nok-600`}>{error ?? draftError}</p>
      )}
      {info && chrome && <p role="status" className={`${message} border-warn-line bg-warn-50 text-warn-700`}>{info}</p>}
      {note && chrome && <p role="status" className={`${message} border-warn-line bg-warn-50 text-warn-700`}>{note}</p>}
      <div className="flex min-w-0 flex-col gap-2 lg:flex-row lg:items-start">
        <div className="grid min-w-0 flex-1 gap-2"
             {...(present && currentId ? { role: "tabpanel", id: PANEL_ID, "aria-labelledby": tabDomId(currentId) } : {})}>
          {present && layout ? (
            // Video duvarı (tam ekran) bu kapsayıcıdır: tek kameraya geçilince de içinde kalır, tam ekran bozulmaz
            <div ref={wallRef} data-wall={wallOn ? "true" : undefined} className={wallOn ? "grid h-screen w-screen place-items-center bg-black" : undefined}>
              {single ? (
                <SingleCamera {...single} mode={singleMode} onClose={closeSingle} />
              ) : (
                <div ref={gridRef} data-testid="watch-grid" data-stream={streamId ?? undefined} className={gridClass} style={gridStyle}>
                  {src && (
                    // eslint-disable-next-line @next/next/no-img-element -- canlı MJPEG akışı
                    <img alt={`${tabName} canlı görüntü`} src={src} className="absolute inset-0 h-full w-full" onError={onError} />
                  )}
                  {layout.cells.map((_, i) => {
                    const ref = present.tiles[i] ?? null;
                    return (
                      <TileOverlay key={i} layout={layout} index={i} filled={ref !== null} tile={tileStatus(i)}
                                   label={ref ? labels[refKey(ref)] ?? null : null} selected={selected === i}
                                   onOpen={openTile} onAlarm={onAlarm} onSelect={setSelected} onDropped={onDropped}
                                   onEmpty={emptyTile} onMenu={onTileMenu}
                                   active={i === Math.min(focusIdx, layout.cells.length - 1)} onFocusTile={setFocusIdx} onMove={onMove} />
                    );
                  })}
                  {immersive && (
                    <button type="button" aria-label="Tam ekran görünümünden çık" onClick={phone.exit}
                            className="absolute bottom-2 left-2 z-10 grid h-8 w-8 place-items-center rounded-full bg-black/60 text-lg leading-none text-white">×</button>
                  )}
                </div>
              )}
            </div>
          ) : present ? (
            <p className="border border-pl-line px-3 py-4 text-[13px] text-pl-muted">Bu şablonun düzeni tanınmıyor. Şablon editöründen bir düzen seçin.</p>
          ) : loaded ? (
            <p className="border border-pl-line px-3 py-4 text-[13px] text-pl-muted">Henüz şablon yok. &quot;+&quot; ile yeni şablon ekleyin ya da Şablon editöründen NVR&apos;dan şablon kurun.</p>
          ) : null}
        </div>
        {chrome && <CameraList used={used} stateOf={stateOf} onPick={pick} onLabels={addLabels} />}
      </div>
      {menu && (
        <ContextMenu label={menu.kind === "tab" ? "Şablon işlemleri" : "Kutu işlemleri"} x={menu.x} y={menu.y}
                     actions={menuActions(menu)} onClose={closeMenu} />
      )}
      {naming && <NameDialog title={naming.title} initial={naming.initial} onSubmit={naming.submit} onCancel={() => setNaming(null)} />}
    </div>
  );
}
