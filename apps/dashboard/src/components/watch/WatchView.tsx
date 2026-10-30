"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, type Source } from "@/lib/live";
import { FAILS_BEFORE_WARNING, useAlarmCenter } from "@/components/live/AlarmCenter";
import PageHeader from "@/components/PageHeader";
import { useUnsavedGuard } from "@/components/UnsavedGuard";
import { layoutFor, MAX_TILES, ROOT_PX } from "@/lib/layoutGrid.mjs";
import {
  applyLayout, assign, canRedo, canUndo, initHistory, isDirty, neighbor, newDraft, newName, parseUnsaved, push, redo, refKey, retile,
  sameContent, swap, undo, type Draft, type History, type UnsavedEntry,
} from "@/lib/templateEdit.mjs";
import {
  copyName, LAST_VIEW_KEY, UNSAVED_KEY, liveHref, problemOf, RELOAD_RETRY_MS, RESIZE_DEBOUNCE_MS, STATUS_POLL_MS, streamSize,
  TEMPLATE_TIMEOUT_MS, TIMEOUT_NOT_RELOADED, TIMEOUT_RELOADED, UNSAVED_TEXT,
  type Problem, type TileRef, type TileStatus, type ViewLayout, type ViewStatus, type ViewTemplate,
} from "@/lib/views";
import CameraList, { type CamState } from "./CameraList";
import ConnectionProblem from "./ConnectionProblem";
import ContextMenu, { type MenuAction } from "./ContextMenu";
import EditorMenu, { EDITOR_ID } from "./EditorMenu";
import NameDialog from "./NameDialog";
import SingleCamera, { type SingleMode } from "./SingleCamera";
import TemplateTabs, { ADD_ID, PANEL_ID, TABLIST_ID, tabDomId, type TabItem } from "./TemplateTabs";
import TileOverlay, { type TileDrop, type TileMove } from "./TileOverlay";
import { useDraft } from "./useDraft";
import { usePhoneLandscape } from "./usePhoneLandscape";
import { useStreamKey } from "./useStreamKey";

/** Kaydedilmemiş yeni şablonun sekme kimliği (sunucuda henüz yok): her yeni sekmede ayrı ("yeni-1", "yeni-2"…), böylece
 * süren bir kayıt yanıtı sonradan açılan başka bir yeni sekmeyle karışmaz */
const LOCAL_PREFIX = "yeni-";
const isLocal = (id: string | null) => !!id && id.startsWith(LOCAL_PREFIX);
const isDraftId = (id: string) => id.startsWith("draft-");
const droppedNote = (n: number) => `${n} kamera düzene sığmadı ve şablondan çıkarıldı. Geri al ile geri getirilebilir.`;
const FULL_HINT = "Bütün kutular dolu: değiştirmek istediğiniz kutuyu seçin ya da önce bir kutuyu boşaltın.";
const DELETED_ELSEWHERE = "Bu şablon başka yerde silindi; değişiklikler kaydedilmemiş yeni sekmede.";
const RESTORED = "Kaydedilmemiş değişiklikler geri yüklendi.";
const RESTORED_CHANGED = "Şablon bu arada başka yerde değiştirildi; kaydederseniz bu değişiklikler onun yerine geçer.";
const RESTORED_DELETED = "Şablon bu arada başka yerde silindi; değişiklikler kaydedilmemiş yeni sekmede.";
const CHANGED_ELSEWHERE = "Bu şablon başka yerde değiştirildi. Üzerine yazılsın mı?";
const NOT_FOUND = "Şablon bulunamadı; başka yerde silinmiş olabilir.";
const BUSY_TEXT = "Başka bir şablon işlemi sürüyor; bitince yeniden deneyin.";

/**
 * Sekmenin düzenleme geçmişi ve temeli: düzenleme başladığında şablonun sunucudaki `updatedAt` değeri (kaydedilmemiş yeni
 * sekmede null). Temel sonraki liste yenilemelerini izlemez; Kaydet sunucudaki güncel değer farklıysa üzerine yazmadan sorar.
 */
type Edit = { tabId: string; hist: History; base: number | null };
/** Düzenlemenin temeli: süren (kaydedilmemiş) düzenlemede aynı kalır; kayıtlı hâlden başlayan düzenlemede şablonun şimdiki değeri */
function baseOf(cur: { edit: Edit | null; dirty: boolean; viewAt: number | null }, tabId: string): number | null {
  return cur.edit && cur.edit.tabId === tabId && cur.dirty ? cur.edit.base : cur.viewAt;
}

/**
 * Kaydedilmemiş düzenlemenin bu tarayıcı sekmesindeki kaydı (sessionStorage; sekmeler arası taşmaz). Geri/İleri, yenileme
 * ya da çökmeden sonra Canlı izlemeye dönünce geri yüklenir. Depo yoksa ya da kayıt bozuksa sessizce yok sayılır (ve silinir).
 */
function readUnsaved(): UnsavedEntry | null {
  try {
    const raw = window.sessionStorage.getItem(UNSAVED_KEY);
    const entry = parseUnsaved(raw);
    if (raw !== null && !entry) window.sessionStorage.removeItem(UNSAVED_KEY);
    return entry;
  } catch { return null; }
}
function writeUnsaved(entry: UnsavedEntry): void {
  try { window.sessionStorage.setItem(UNSAVED_KEY, JSON.stringify(entry)); } catch { /* depolama yok ya da dolu */ }
}
function clearUnsaved(): void {
  try { window.sessionStorage.removeItem(UNSAVED_KEY); } catch { /* depolama yok */ }
}

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
/** Şablon isteği TEMPLATE_TIMEOUT_MS içinde bitmedi (kesildi) */
class TemplateTimeout extends Error {}
/**
 * Şablon isteği (liste, Kaydet'in denetimi, şablonu yazan işlemler): TEMPLATE_TIMEOUT_MS içinde bitmezse kesilir
 * (`TemplateTimeout`); `page` kesilince (sayfa söküldü) de kesilir.
 */
function timedApi<T>(page: AbortSignal, path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const ctrl = new AbortController();
  const onPage = () => ctrl.abort();
  page.addEventListener("abort", onPage);
  if (page.aborted) ctrl.abort();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; ctrl.abort(); }, TEMPLATE_TIMEOUT_MS);
  return api<T>(path, { ...init, signal: ctrl.signal })
    .catch((e: unknown) => { throw timedOut ? new TemplateTimeout() : e; })
    .finally(() => { clearTimeout(timer); page.removeEventListener("abort", onPage); });
}
/** focusLater: o an seçili sekme (sekme kalmadıysa "+") */
const CURRENT_TAB = "#seçili-sekme";

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
 * Kaydedilmemiş değişiklikle sekme değiştirmek, menüden başka sayfaya gitmek ya da sayfayı kapatmak sorulur; tarayıcının
 * Geri/İleri düğmesi sorulmaz: düzenleme bu tarayıcı sekmesinde saklanır ve Canlı izlemeye dönünce geri yüklenir.
 * Kaydet, şablon bu düzenleme başladıktan sonra başka yerde değiştirildiyse üzerine yazmadan önce sorar.
 */
export default function WatchView() {
  const [layouts, setLayouts] = useState<ViewLayout[]>([]);
  const [views, setViews] = useState<ViewTemplate[]>([]);
  /** Şablon listesi en az bir kez alındı ("Henüz şablon yok" ancak o zaman söylenir) */
  const [loaded, setLoaded] = useState(false);
  const [currentId, setCurrentId] = useState<string | null>(null);
  /** Kaydedilmemiş yeni şablonun sekmesi (kimlik, ad); yeni şablon yalnız seçiliyken vardır */
  const [fresh, setFresh] = useState<{ id: string; name: string } | null>(null);
  const localSeq = useRef(0);
  /** Düzenleme geçmişi ve temeli; yalnız `tabId` sekmesi seçiliyken geçerli (yoksa kayıtlı şablonun kendisi gösterilir) */
  const [edit, setEdit] = useState<Edit | null>(null);
  /** Seçili kutu: listeden tıklanan kamera buraya yerleşir */
  const [selected, setSelected] = useState<number | null>(null);
  /** Izgaranın klavye sekme durağı (gezici sekme sırası: ok tuşları kutudan kutuya); seçimden bağımsız */
  const [focusIdx, setFocusIdx] = useState(0);
  const [status, setStatus] = useState<ViewStatus | null>(null);
  const [single, setSingle] = useState<Single | null>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  /** Izgaranın CSS boyutu: kutu katmanının yoğunluğu buna göre (akış boyutunun aksine beklemeden güncellenir) */
  const [gridBox, setGridBox] = useState<{ w: number; h: number } | null>(null);
  /**
   * Kök yazı boyutu (px; tarayıcının yazı boyutu ayarı): kutu katmanı rem cinsindendir, yoğunluk eşikleri de. 1 rem
   * genişliğindeki gizli ölçü öğesinden okunur; ayar sayfa açıkken değişirse ResizeObserver ile hemen güncellenir.
   */
  const [rem, setRem] = useState(ROOT_PX);
  const remRef = useRef<HTMLSpanElement>(null);
  /** Analiz sunucusuyla konuşulamıyor (liste ya da durum yoklaması başarısız): sunucu yok ya da oturum doldu; düzelince kalkar */
  const [problem, setProblem] = useState<Problem | null>(null);
  /** Kayıt cihazları ("NVR'dan şablon" için) */
  const [recorders, setRecorders] = useState<Source[]>([]);
  /** Kamera → kutu etiketi (kamera listesinden): durum gelmeden kutuda ad görünsün */
  const [labels, setLabels] = useState<Record<string, string>>({});
  /**
   * Şablonu yazan bir işlem sürüyor (Kaydet, Farklı kaydet, Yeniden adlandır, Kopyala, Sil, NVR'dan şablon): bunlar tek tek
   * çalışır, biri sürerken ötekiler pasiftir (ör. Kaydet'in isteği sürerken ad değişip Kaydet'in eski adı geri yazmasın)
   */
  const [busy, setBusy] = useState(false);
  /** `busy`'nin hemen güncellenen kopyası: aynı çizimdeki ikinci tık da başlamasın */
  const busyRef = useRef(false);
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
    edit: null as Edit | null,
    hist: null as History | null, currentId: null as string | null, present: null as Draft | null, selected: null as number | null,
    single: null as Single | null, byKey: new Map<string, TileStatus>(), labels: {} as Record<string, string>, dirty: false,
    layout: null as ViewLayout | null, tabName: null as string | null, viewAt: null as number | null,
  });
  const keepAsNew = useRef<(notice: string) => void>(() => undefined);
  /**
   * Saklanan düzenlemenin geri yüklenmesi: "pending" (depo henüz okunmadı), okunan kayıt (liste gelince uygulanacak),
   * "applying" (uygulandı, düzenleme çizilince saklama yeniden başlar), "done". Bitene dek saklanan kayıt silinmez.
   */
  const restore = useRef<"pending" | "applying" | "done" | UnsavedEntry>("pending");
  /** Geri yükleme bildirimi ("Değişiklikleri at" ile) */
  const [restored, setRestored] = useState<string | null>(null);
  /**
   * Bir sonraki çizimden sonra odaklanacak öğenin DOM kimliği ya da CURRENT_TAB (o an seçili sekme; sekme kalmadıysa "+"):
   * "Değişiklikleri at" düğmesi kalkınca, sekme silinince odak sayfaya düşmesin. Hedef pasifse ya da yoksa Şablon editörü
   * düğmesi, o da pasifse sekme listesi.
   */
  const focusTab = useRef<string | null>(null);
  const [focusNonce, setFocusNonce] = useState(0);
  const focusLater = useCallback((id: string) => { focusTab.current = id; setFocusNonce((n) => n + 1); }, []);
  /** Kullanıcı çıkmayı onayladı (bağlantı, Çıkış): saklanan düzenleme silindi, sayfa kapanana dek yeniden yazılmaz */
  const dropped = useRef(false);
  /**
   * Düzenlemeden ayrılma sayacı: sekme değişince, "Değişiklikleri at" ile ve onaylı çıkışta (bağlantı, Çıkış) artar.
   * Kaydet'in denetim isteği sürerken artarsa ne sorulur ne yazılır. Düzenlemenin nesne kimliğine bakılmaz: istek
   * sürerken düzenleme sürdüyse Kaydet'e basıldığı andaki hâl yazılır, sonraki düzenlemeler kaydedilmemiş kalır.
   */
  const leaves = useRef(0);
  /**
   * Sayfanın ömrü: sökülünce (başka sayfaya geçildi, uygulama içi Geri) süren şablon istekleri kesilir ve ayrılma sayacı
   * artar: Kaydet'in denetim isteği sürüyorsa ne "Üzerine yazılsın mı?" sorulur ne yazılır (düzenleme depoda kalır, dönünce
   * geri yüklenir)
   */
  const pageLife = useRef(new AbortController());
  useEffect(() => {
    const c = new AbortController();
    pageLife.current = c;
    return () => { leaves.current += 1; c.abort(); };
  }, []);

  /**
   * Şablon ve düzen listesini alır; başarıyı döndürür. Seçili şablon silinmişse kalanlardan birine geçilir; ama
   * kaydedilmemiş düzenlemesi varsa (başka yerde silindi) düzenleme atılmaz: kaydedilmemiş yeni sekme olarak kalır.
   */
  const reload = useCallback(async (): Promise<boolean> => {
    // Sayfa bu sırada söküldüyse (ör. geliştirme kipinde React'ın çift bağlaması) yanıt ya da iptal hatası işlenmez
    const page = pageLife.current.signal;
    try {
      const [l, v] = await Promise.all([timedApi<ViewLayout[]>(page, "view-layouts"), timedApi<ViewTemplate[]>(page, "views")]);
      if (page.aborted) return false;
      setLayouts(l);
      setViews(v);
      setLoaded(true);
      setProblem(null);
      const { currentId: id, dirty: d } = live.current;
      if (d && id && !isLocal(id) && id !== discarded.current && !v.some((x) => x.id === id)) {
        keepAsNew.current(DELETED_ELSEWHERE);
        return true;
      }
      // Açık sekme (kaydedilmemiş yeni şablon da) listede kaldıkça değişmez. Hatırlanan sekme yalnız sayfa açılırken
      // seçilir: tarayıcının bütün sekmelerinde ortaktır, başka sekmedeki seçim buradaki düzenlemeyi kapatmasın
      setCurrentId((cur) => {
        if (isLocal(cur) || (cur && v.some((x) => x.id === cur))) return cur;
        const want = remembered();
        return want && v.some((x) => x.id === want) ? want : v[0]?.id ?? null;
      });
      return true;
    } catch (e) {
      if (!page.aborted) setProblem(problemOf(e));
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

  const isNew = fresh !== null && currentId === fresh.id;
  const view = isNew ? null : views.find((v) => v.id === currentId) ?? null;
  const saved = useMemo<Draft | null>(() => (view ? { layout: view.layout, tiles: view.tiles, name: view.name } : null), [view]);
  const hist = useMemo<History | null>(
    () => (edit && edit.tabId === currentId ? edit.hist : saved ? initHistory(saved) : null), [edit, currentId, saved]);
  const present = hist?.present ?? null;
  const dirty = hist !== null && isDirty(hist, isNew ? null : saved);
  const tabName = isNew ? fresh.name : view?.name ?? "";
  const presentLayout = present?.layout ?? null;
  const layout = useMemo(() => (presentLayout ? layoutFor(presentLayout, layouts) : null), [presentLayout, layouts]);

  // Sekme değişince: başka sekmenin geçmişi, yeni şablon, seçim, menü ve iletiler bırakılır; seçim hatırlanır
  useEffect(() => {
    setEdit((e) => (e && e.tabId !== currentId ? null : e));
    setFresh((f) => (f && f.id === currentId ? f : null));
    setSelected(null);
    setFocusIdx(0);
    setMenu(null);
    setNote(null);
    if (currentId && !isLocal(currentId)) remember(currentId);
  }, [currentId]);
  // Sekme değişimi düzenlemeden ayrılmaktır; işleme anında (çizimle birlikte) sayılır: süren Kaydet'in yanıtı bundan
  // önce işlenemez
  useLayoutEffect(() => { leaves.current += 1; }, [currentId]);
  // Kayıtlı şablon değişti (başka cihazda düzenlendi): düzenleme yoksa (kayıtlı hâl gösteriliyordu) yenisi izlenir;
  // kaydedilmemiş düzenleme varsa korunur. Kaydet sonrası (düzenlenen = kayıtlı) geçmiş de korunur. Yalnız AYNI sekmenin
  // önceki kayıtlı hâline bakılır: sekme değişince (ör. geri yüklenen düzenleme, hatırlanan başka sekmenin kayıtlı hâline
  // eşit) düzenleme atılmaz.
  const prevSaved = useRef<{ id: string | null; draft: Draft } | null>(null);
  useEffect(() => {
    const prev = prevSaved.current;
    prevSaved.current = saved ? { id: currentId, draft: saved } : null;
    if (!saved || !prev || prev.id !== currentId) return;
    setEdit((e) => {
      if (!e || e.tabId !== currentId || sameContent(e.hist.present, saved)) return e;
      return sameContent(e.hist.present, prev.draft) ? null : e;
    });
  }, [saved, currentId]);

  // Kaydedilmemiş değişiklik bekçisi (menü bağlantıları, Çıkış, sayfayı kapatma); çıkış onaylanınca saklanan düzenleme ve
  // sunucudaki taslak (oturum hâlâ geçerliyken) silinir
  /**
   * Araç çubuğunda en son odaklanan düğme (Kaydet, Geri al): basılınca pasifleşirse (kaydedildi, son adım geri alındı) odak
   * sayfaya düşmesin, "Şablon editörü" düğmesine geçsin. Yalnız o düğme pasifleştiği anda hâlâ odaktaysa (`activeElement`):
   * odak sonradan başka yere ya da sayfaya gittiyse (boş yere tıklandı) Ctrl+Z gibi bir işlem odağı geri çalmaz, sayfayı
   * da kaydırmaz. Düğme pasifleşince, odakta olsun olmasın, iz bırakılır (her pasifleşme tek karar).
   */
  const toolbarFocus = useRef<HTMLButtonElement | null>(null);
  useLayoutEffect(() => {
    const el = toolbarFocus.current;
    if (!el || !el.disabled) return;
    toolbarFocus.current = null;
    if (document.activeElement === el) document.getElementById(EDITOR_ID)?.focus();
  });
  /** Sunucudaki taslağı hemen silen işlev (useDraft'tan, aşağıda) */
  const releaseRef = useRef<() => void>(() => undefined);
  useEffect(() => {
    guard.setDirty(dirty, () => { dropped.current = true; leaves.current += 1; clearUnsaved(); releaseRef.current(); });
  }, [dirty, guard]);
  useEffect(() => () => guard.setDirty(false), [guard]);

  // Saklanan düzenleme: sayfa açılınca okunur (yalnız tarayıcıda), liste gelince uygulanır
  useEffect(() => {
    if (restore.current === "pending") restore.current = readUnsaved() ?? "done";
  }, []);
  useEffect(() => {
    const entry = restore.current;
    if (!loaded || typeof entry !== "object") return;
    // Liste beklenirken kayıt silindiyse (Çıkış) geri yüklenmez: silinen düzenleme yeniden yazılmasın
    if (readUnsaved() === null) { restore.current = "done"; return; }
    const lay = layoutFor(entry.layout, layouts);
    if (!lay) { restore.current = "done"; clearUnsaved(); return; }
    const content = { layout: entry.layout, tiles: retile(entry.tiles, lay.cells.length).tiles };
    const v = isLocal(entry.origin) ? null : views.find((x) => x.id === entry.origin) ?? null;
    if (v) {
      const sv = { layout: v.layout, tiles: v.tiles, name: v.name };
      if (sameContent(content, sv)) { restore.current = "done"; clearUnsaved(); return; }
      restore.current = "applying";
      setCurrentId(v.id);
      setEdit({ tabId: v.id, hist: push(initHistory(sv), { ...content, name: v.name }), base: entry.updatedAt });
      setRestored(entry.updatedAt !== null && v.updatedAt !== entry.updatedAt ? `${RESTORED} ${RESTORED_CHANGED}` : RESTORED);
      return;
    }
    // Kaydedilmemiş yeni şablon ya da bu arada başka yerde silinen şablon: kaydedilmemiş yeni sekmede açılır
    restore.current = "applying";
    const id = `${LOCAL_PREFIX}${++localSeq.current}`;
    const name = entry.name.trim() || newName(views.map((x) => x.name));
    setFresh({ id, name });
    setCurrentId(id);
    setEdit({ tabId: id, hist: initHistory({ ...content, name }), base: null });
    setRestored(isLocal(entry.origin) ? RESTORED : `${RESTORED} ${RESTORED_DELETED}`);
  }, [loaded, views, layouts]);
  // Düzenleme her değişince saklanır (temeliyle; liste yenilense de temel değişmez); kaydedilmemiş değişiklik kalmayınca
  // (kaydet, geri al, vazgeç, at) silinir
  const base = edit && edit.tabId === currentId ? edit.base : null;
  useEffect(() => {
    const r = restore.current;
    if (r === "pending" || typeof r === "object") return;    // saklanan kayıt henüz uygulanmadı: silinmesin
    if (r === "applying") {
      if (!dirty) return;
      restore.current = "done";
    }
    if (dropped.current) return;
    if (dirty && present && currentId) {
      writeUnsaved({ v: 1, origin: currentId, name: tabName, layout: present.layout, tiles: present.tiles, updatedAt: base });
    } else {
      clearUnsaved();
    }
  }, [dirty, present, currentId, tabName, base]);
  useEffect(() => { if (!dirty) setRestored(null); }, [dirty]);
  useEffect(() => {
    const want = focusTab.current;
    if (!want) return;
    focusTab.current = null;
    const id = want === CURRENT_TAB ? (currentId ? tabDomId(currentId) : ADD_ID) : want;
    // Hedef pasifse (ör. "+" kayıt sürerken) ya da yoksa: Şablon editörü düğmesi, o da pasifse sekme listesi
    for (const el of [id, EDITOR_ID, TABLIST_ID].map((x) => document.getElementById(x))) {
      el?.focus();
      if (el && document.activeElement === el) return;
    }
  }, [restored, currentId, focusNonce, views]);

  // Kaydedilmemiş düzenleme analiz sunucusunda taslak olarak canlı akar
  const draftBody = useMemo(() => (dirty && present && layout ? { layout: present.layout, tiles: present.tiles } : null),
    [dirty, present, layout]);
  const { draftId, error: draftError, lost, release } = useDraft(currentId, draftBody, problem === "auth");
  releaseRef.current = release;
  const streamId = dirty && draftId ? draftId : view?.id ?? null;

  // Şablon başka bir cihazda düzenlendi: aynı şablonun durumu farklı düzen ya da kutularda farklı kamera bildirir
  // (önbellekteki şablon eski). Uyuşmazlık başına BİR kez liste yeniden alınır; yükleme sürerken tekrarlanmaz,
  // eşleşme görülünce (ya da yükleme başarısız olursa) yeniden izin verilir. Taslak gösterilirken bakılmaz.
  const resyncing = useRef(false);
  useEffect(() => {
    // kaydedilmemiş düzenleme varken ızgara taslağı gösterir; şablonun son durumu eskidir, ona bakılmaz
    if (!status || !view || status.id !== view.id || dirty) return;
    if (sameTiles(status, view)) { resyncing.current = false; return; }
    if (resyncing.current) return;
    resyncing.current = true;
    void reload().then((ok) => { if (!ok) resyncing.current = false; });
  }, [status, view, reload, dirty]);
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
  // Kutu katmanının yoğunluğu için CSS boyutu her değişimde hemen ölçülür (katmanlar boyut değişirken de üst üste binmesin).
  useLayoutEffect(() => {
    const el = remRef.current;
    if (!el) return;
    const read = () => {
      const w = el.getBoundingClientRect().width;
      if (w > 0) setRem((p) => (p === w ? p : w));
    };
    read();
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  useLayoutEffect(() => {
    const el = gridRef.current;
    if (!el || !layout) return;
    const measure = () => {
      const n = streamSize(el);
      setSize((p) => (p && p.w === n.w && p.h === n.h ? p : n));
    };
    const box = () => {
      const r = el.getBoundingClientRect();
      setGridBox((p) => (p && p.w === r.width && p.h === r.height ? p : { w: r.width, h: r.height }));
    };
    measure();
    box();
    let t: ReturnType<typeof setTimeout> | undefined;
    const ro = new ResizeObserver(() => { box(); clearTimeout(t); t = setTimeout(measure, RESIZE_DEBOUNCE_MS); });
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

  live.current = { edit, hist, currentId, present, selected, single, byKey, labels, dirty, layout, tabName, viewAt: view?.updatedAt ?? null };
  const commit = useCallback((next: Draft) => {
    const { hist: h, currentId: id } = live.current;
    if (!h || !id) return;
    dropped.current = false;
    setEdit({ tabId: id, hist: push(h, next), base: baseOf(live.current, id) });
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
    if (h && id && canUndo(h)) { setEdit({ tabId: id, hist: undo(h), base: baseOf(live.current, id) }); setNote(null); }
  }, []);
  const doRedo = useCallback(() => {
    const { hist: h, currentId: id } = live.current;
    if (h && id && canRedo(h)) { setEdit({ tabId: id, hist: redo(h), base: baseOf(live.current, id) }); setNote(null); }
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
    const id = `${LOCAL_PREFIX}${++localSeq.current}`;
    setFresh({ id, name: name || newName([]) });
    setEdit({ tabId: id, hist: h, base: null });
    setCurrentId(id);
    setInfo(notice);
  };

  // ---- sekmeler ve şablon işlemleri

  /** Kaydedilmemiş değişiklik varsa sorar; ayrılmak serbestse true */
  const leaveOk = () => !dirty || window.confirm(UNSAVED_TEXT);
  const clearMessages = () => { setInfo(null); setError(null); };
  /**
   * Geri yüklenen değişiklikleri atar: şablon kayıtlı hâline döner; kaydedilmemiş yeni sekme kapanır. Bildirim düğmesiyle
   * birlikte kalktığından odak açık sekmeye, hiç sekme kalmadıysa "+" düğmesine geçer ("+" pasifse Şablon editörü, o da
   * pasifse sekme listesi; sayfaya düşmez). Atmak düzenlemeden ayrılmaktır: süren Kaydet yazmaz.
   */
  const discardRestored = () => {
    leaves.current += 1;
    setRestored(null);
    const to = isNew ? views.find((x) => x.id === remembered())?.id ?? views[0]?.id ?? null : currentId;
    if (isNew) setCurrentId(to);
    else setEdit(null);
    focusLater(to ? tabDomId(to) : ADD_ID);
  };
  const selectTab = (id: string) => {
    if (id === currentId || !leaveOk()) return;
    clearMessages();
    setCurrentId(id);
  };
  const newTemplate = () => {
    if (!layouts.length || busyRef.current || !leaveOk()) return;
    clearMessages();
    const name = newName(views.map((v) => v.name));
    const id = `${LOCAL_PREFIX}${++localSeq.current}`;
    setFresh({ id, name });
    setCurrentId(id);
    setEdit({ tabId: id, hist: initHistory({ ...newDraft(layouts), name }), base: null });
    setSelected(null);
    setNote(null);
  };
  /**
   * İşlemin başladığı an: sekme, düzenleme durumu ve ayrılma sayacı (`adopt` ve Kaydet istek sürerken bir şey değişti mi
   * diye bakar)
   */
  const startOf = () => ({ origin: live.current.currentId, edit: live.current.edit, leaves: leaves.current });
  /**
   * Sunucudan dönen yeni şablonu listeye ekler ve (uygunsa) ona geçer; geçildiyse true. `start`: işlemin başladığı
   * sekme ve düzenleme durumu; `carry`: o sekmenin düzenleme geçmişi yeni şablona taşınır (Kaydet, Farklı kaydet).
   * İstek sürerken başka sekmeye geçildiyse, ya da (taşımadan) bu sekmede yeni bir düzenleme yapıldıysa geçilmez:
   * istek SÜRERKEN yapılan düzenleme sorusuz atılmaz. Başlamadan önceki düzenlemenin atılması zaten sorulmuştu.
   */
  const adopt = (v: ViewTemplate, start: { origin: string | null; edit: unknown }, carry: boolean): boolean => {
    const { currentId: cur, edit: now } = live.current;
    const origin = start.origin;
    setViews((vs) => [...vs.filter((x) => x.id !== v.id), v]);
    const go = cur === origin && (carry || now === start.edit);
    if (go) {
      setEdit((e) => (carry && e && e.tabId === origin ? { tabId: v.id, hist: e.hist, base: v.updatedAt } : null));
      setCurrentId(v.id);
    }
    void reload();
    return go;
  };
  const added = (v: ViewTemplate) => `"${v.name}" şablonu eklendi.`;
  /**
   * Şablonu yazan işlemi tek başına çalıştırır (biri sürerken başlamaz); hata çağırana gider (ad penceresi kendinde
   * gösterir). İstek zaman aşımına uğrarsa (TEMPLATE_TIMEOUT_MS) işlem sunucuda tamamlanmış olabilir: liste yeniden alınır
   * (kaydedilmemiş düzenleme korunur), sonra işlem serbest kalır ve Türkçe ileti çağırana gider.
   */
  const exclusive = async (fn: () => Promise<void>): Promise<void> => {
    if (busyRef.current) throw new Error(BUSY_TEXT);
    busyRef.current = true;
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      if (!(e instanceof TemplateTimeout)) throw e;
      throw new Error((await reload()) ? TIMEOUT_RELOADED : TIMEOUT_NOT_RELOADED);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };
  /** Sayfadaki işlem (Kaydet, Kopyala, Sil, NVR'dan şablon): tek başına; hata sayfada yazar */
  const run = async (fn: () => Promise<void>) => {
    if (busyRef.current) return;
    clearMessages();
    try { await exclusive(fn); } catch (e) { setError((e as Error).message); }
  };
  const save = () => run(async () => {
    if (!present) return;
    if (!tabName.trim()) throw new Error("Şablonun adı yok: önce sekmeye sağ tıklayıp Yeniden adlandır ile ad verin.");
    const start = startOf();
    const origin = start.origin;
    const body = { name: tabName, layout: present.layout, tiles: present.tiles };
    if (isNew) {
      const v = await timedApi<ViewTemplate>(pageLife.current.signal, "views", { method: "POST", json: body });
      if (!adopt(v, start, true)) setInfo(added(v));
    } else if (view) {
      /** Şablon başka yerde silinmiş: düzenleme kaydedilmemiş yeni sekmede kalır (yeniden "Kaydet" yeni şablon yazar) */
      const gone = (e: Error) => {
        if (live.current.currentId !== origin) throw e;
        setViews((vs) => vs.filter((x) => x.id !== view.id));
        keepAsNew.current(DELETED_ELSEWHERE);
      };
      // Sunucudaki güncel hâl hemen önce alınır: bu düzenleme başladıktan sonra başka yerde değiştirildiyse üzerine yazmadan
      // sorulur (Vazgeç: yazılmaz, düzenleme kalır). Sunucuda sürüm koşulu yok: okuma ile yazma arasında kısa bir pencere kalır.
      const base = edit && edit.tabId === view.id ? edit.base : null;
      const cur = (await timedApi<ViewTemplate[]>(pageLife.current.signal, "views")).find((x) => x.id === view.id);
      // İstek sürerken düzenlemeden ayrıldıysa (sekme değişti, değişiklikler atıldı, onaylı çıkış) ne sorulur ne yazılır.
      // Yalnız düzenleme sürdüyse Kaydet'e basıldığı andaki hâl (`body`) yazılır. Soru (confirm) sayfayı bekletir: soru ile
      // PUT arasında ayrılınamaz
      if (leaves.current !== start.leaves) return;
      if (!cur) { gone(new Error(NOT_FOUND)); return; }
      if (base !== null && cur.updatedAt !== base && !window.confirm(CHANGED_ELSEWHERE)) return;
      try {
        const v = await timedApi<ViewTemplate>(pageLife.current.signal, `views/${view.id}`, { method: "PUT", json: body });
        // Kendi kaydımız: kayıtlı hâlin değişmesi "başka yerde değişti, düzenleme yoksa izle" sayılmaz; istek sürerken yapılan
        // düzenleme (kayıtlı hâle geri alma da) yeni kayıtlı hâlin üstünde kaydedilmemiş olarak kalır
        if (live.current.currentId === v.id) prevSaved.current = { id: v.id, draft: { layout: v.layout, tiles: v.tiles, name: v.name } };
        setViews((vs) => vs.map((x) => (x.id === v.id ? v : x)));
        setEdit((e) => (e && e.tabId === v.id ? { ...e, base: v.updatedAt } : e));     // kaydedilen hâl yeni temel
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 404)) throw e;
        gone(e);
      }
    }
  });
  /**
   * Ad penceresini açar ("Farklı kaydet…", "Yeniden adlandır"). İsteğin hatası pencerede yazar; istek sürerken pencere
   * Esc ya da Vazgeç ile kapandıysa hata sayfanın ileti alanında (role="alert") yazar (kaybolmaz).
   */
  const namingRef = useRef<Naming | null>(null);
  namingRef.current = naming;
  const openNaming = (title: string, initial: string, submit: (name: string) => Promise<void>) => {
    const n: Naming = {
      title, initial,
      submit: async (name) => {
        try {
          await submit(name);
        } catch (e) {
          if (namingRef.current !== n) setError((e as Error).message);
          throw e;
        }
      },
    };
    setNaming(n);
  };
  const saveAs = () => {
    if (!present || busyRef.current) return;
    const content = { layout: present.layout, tiles: present.tiles };
    const start = startOf();
    openNaming("Farklı kaydet", copyName(tabName ?? "", views.map((v) => v.name)), (name) => exclusive(async () => {
      const v = await timedApi<ViewTemplate>(pageLife.current.signal, "views", { method: "POST", json: { name, ...content } });
      setNaming(null);
      clearMessages();
      if (!adopt(v, start, true)) setInfo(added(v));
    }));
  };
  const renameTab = (id: string) => {
    if (busyRef.current) return;
    if (isLocal(id)) {
      // Kaydedilmemiş yeni sekmenin adı (sunucuya ilk Kaydet'te yazılır; o sürerken değişmez)
      openNaming("Yeniden adlandır", fresh?.name ?? "", (name) => exclusive(async () => {
        setFresh((f) => (f && f.id === id ? { ...f, name } : f));
        setNaming(null);
      }));
      return;
    }
    const v = views.find((x) => x.id === id);
    if (!v) return;
    // Yalnız ad değişir: sunucudaki GÜNCEL düzen ve kutular gider (başka yerdeki düzenleme geri alınmaz); bu sekmedeki
    // kaydedilmemiş düzenleme olduğu gibi kalır. Şablon düzenlemenin temelinden beri değişmediyse ad değişikliği kendi
    // değişikliğimizdir: temel yeni hâle geçer (Kaydet sormaz); değiştiyse temel kalır (Kaydet yine sorar)
    openNaming("Yeniden adlandır", v.name, (name) => exclusive(async () => {
      const list = await timedApi<ViewTemplate[]>(pageLife.current.signal, "views");
      const cur = list.find((x) => x.id === v.id);
      if (!cur) throw new Error(NOT_FOUND);
      const n = await timedApi<ViewTemplate>(pageLife.current.signal, `views/${v.id}`,
        { method: "PUT", json: { name, layout: cur.layout, tiles: cur.tiles } });
      setViews((vs) => vs.map((x) => (x.id === n.id ? n : x)));
      setEdit((e) => (e && e.tabId === n.id && e.base === cur.updatedAt ? { ...e, base: n.updatedAt } : e));
      setNaming(null);
    }));
  };
  const copyTab = (id: string) => {
    const v = views.find((x) => x.id === id);
    if (!v || busyRef.current || !leaveOk()) return;
    const start = startOf();
    void run(async () => {
      const c = await timedApi<ViewTemplate>(pageLife.current.signal, "views",
        { method: "POST", json: { name: copyName(v.name, views.map((x) => x.name)), layout: v.layout, tiles: v.tiles } });
      if (!adopt(c, start, false)) setInfo(added(c));
    });
  };
  const deleteTab = (id: string) => {
    const name = isLocal(id) ? fresh?.name : views.find((x) => x.id === id)?.name;
    if (name == null || busyRef.current || !window.confirm(`"${name}" şablonu silinsin mi?`)) return;
    if (isLocal(id)) {
      clearMessages();
      setCurrentId(views.find((x) => x.id === remembered())?.id ?? views[0]?.id ?? null);
      focusLater(CURRENT_TAB);
      return;
    }
    void run(async () => {
      discarded.current = id;
      await timedApi(pageLife.current.signal, `views/${id}`, { method: "DELETE" });
      setViews((vs) => vs.filter((x) => x.id !== id));
      setEdit((e) => (e && e.tabId === id ? null : e));
      await reload();
      focusLater(CURRENT_TAB);                             // silinen sekmenin yerine o an seçili sekme (yoksa "+")
    });
  };
  /** Kayıt cihazının tüm kanallarından (en çok MAX_TILES = 128) şablon kurar ve ona geçer */
  const fromRecorder = (sourceId: string) => {
    if (busyRef.current || !leaveOk()) return;
    const start = startOf();
    void run(async () => {
      const v = await timedApi<ViewTemplate & { truncated: boolean; channelCount: number }>(pageLife.current.signal,
        "views/from-recorder", { method: "POST", json: { sourceId } });
      const note = v.truncated ? `İlk ${MAX_TILES} kanal alındı (toplam ${v.channelCount}).` : null;
      setInfo(adopt(v, start, false) ? note : [added(v), note].filter(Boolean).join(" "));
    });
  };

  const tabs: TabItem[] = [
    ...views.map((v) => ({ id: v.id, name: v.name, unsaved: v.id === currentId && dirty })),
    ...(isNew ? [{ id: fresh.id, name: fresh.name, unsaved: true }] : []),
  ];
  const menuActions = (m: Menu): MenuAction[] => {
    if (m.kind === "tab") {
      return [
        { label: "Yeniden adlandır", onSelect: () => renameTab(m.id), disabled: busy },
        { label: "Kopyala", onSelect: () => copyTab(m.id), disabled: isLocal(m.id) || busy },
        { label: "Sil", onSelect: () => deleteTab(m.id), disabled: busy },
      ];
    }
    // Alarmlı kutuya dokunmak/tıklamak alarmı açtığından kutu buradan seçilir (sonra listeden kamera, ya da Boşalt)
    const alarmed = !!tileStatus(m.index)?.analysis?.alarm;
    return [
      ...(alarmed && selected !== m.index ? [{ label: "Seç", onSelect: () => setSelected(m.index) }] : []),
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
      {/* Kök yazı boyutunun ölçüsü (1 rem): görünmez, yer kaplamaz */}
      <span ref={remRef} aria-hidden="true" className="pointer-events-none invisible absolute h-0 w-[1rem]" />
      {chrome && (
        <>
          <PageHeader title="Canlı izleme" />
          <TemplateTabs tabs={tabs} current={currentId} onSelect={selectTab} onAdd={newTemplate}
                        onMenu={(id, x, y) => setMenu({ kind: "tab", id, x, y })} addDisabled={layouts.length === 0 || busy} />
          <div className="flex flex-wrap items-center gap-1.5"
               onFocus={(e) => { toolbarFocus.current = e.target instanceof HTMLButtonElement && e.target.hasAttribute("data-toolbar") ? e.target : null; }}>
            <EditorMenu layoutId={present?.layout ?? null} canUndo={!!hist && canUndo(hist)} canRedo={!!hist && canRedo(hist)}
                        canSave={dirty && !!layout && !!tabName.trim()} canSaveAs={!!present && !!layout} busy={busy} disabled={layouts.length === 0}
                        recorders={recorders} onNew={newTemplate} onUndo={doUndo} onRedo={doRedo} onSave={save} onSaveAs={saveAs}
                        onLayout={chooseLayout} onFromRecorder={fromRecorder}
                        canClearSelected={selected !== null && !!present?.tiles[selected]}
                        onClearSelected={() => { if (selected !== null) emptyTile(selected); }} />
            <button type="button" data-toolbar="" onClick={save} disabled={!dirty || !layout || busy || !tabName.trim()} className="pl-btn">Kaydet</button>
            <button type="button" data-toolbar="" onClick={doUndo} disabled={!hist || !canUndo(hist)} className="pl-btn">Geri al</button>
            {canWall && <button type="button" onClick={wall} disabled={!present || !layout} className="pl-btn">Tüm ekran</button>}
            {dirty && <span className="text-[12px] text-warn-ink">Kaydedilmemiş değişiklik var</span>}
          </div>
        </>
      )}
      {problem && !single && (
        <p role="status" className={`${message} border-warn-line bg-warn-50 text-warn-ink`}><ConnectionProblem problem={problem} /></p>
      )}
      {restored && dirty && chrome && (
        <div role="status" className={`${message} flex flex-wrap items-center gap-2 border-pl-sel-line bg-pl-sel text-pl-ink`}>
          <span className="min-w-0 flex-1">{restored}</span>
          <button type="button" onClick={discardRestored} className="pl-btn">Değişiklikleri at</button>
        </div>
      )}
      {(error || draftError) && chrome && (
        <p role="alert" className={`${message} border-nok-line bg-nok-50 text-nok-ink`}>{error ?? draftError}</p>
      )}
      {info && chrome && <p role="status" className={`${message} border-warn-line bg-warn-50 text-warn-ink`}>{info}</p>}
      {note && chrome && <p role="status" className={`${message} border-warn-line bg-warn-50 text-warn-ink`}>{note}</p>}
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
                      <TileOverlay key={i} layout={layout} index={i} grid={gridBox} rem={rem} filled={ref !== null} tile={tileStatus(i)}
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
