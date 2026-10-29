"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef } from "react";
import { UNSAVED_TEXT } from "@/lib/views";

/** Geri bekçisinin geçmiş kaydını işaretleyen alan (Next'in kendi geçmiş durumunun yanına eklenir) */
const SENTINEL = "bvUnsaved";
/** Onaylanan çıkış bu süre içinde gerçekleşmezse (ör. geri gidilecek sayfa yok) bekçi yeniden sormaya başlar */
const LEAVE_LATCH_MS = 10_000;
/** Bekçi kaydını geri alan `history.back()` yanıtı (popstate) en geç bu sürede gelmezse beklenmez */
const POP_TIMEOUT_MS = 1000;

const isSentinel = (state: unknown): boolean => typeof state === "object" && state !== null && SENTINEL in state;

interface UnsavedGuard {
  /** Sayfada kaydedilmemiş değişiklik var mı (sayfa bildirir; ayrılırken temizler) */
  setDirty: (dirty: boolean) => void;
  /** Ayrılmak serbest mi: değişiklik yoksa evet; varsa "Kaydedilmedi, çıkılsın mı?" sorulur */
  confirmLeave: () => boolean;
  /** Bağlantı olmayan bir çıkış için (ör. "Çıkış"): sorar; onaylanırsa geçmişteki bekçi kaydını kaldırıp değişikliği
   * bırakır (sayfa kapanırken bir daha sorulmaz). Ayrılmak serbestse true. */
  leave: () => Promise<boolean>;
}

const Ctx = createContext<UnsavedGuard>({ setDirty: () => undefined, confirmLeave: () => true, leave: async () => true });

export function useUnsavedGuard(): UnsavedGuard {
  return useContext(Ctx);
}

/**
 * Bağlantı tıklamasının etkisi: "leave" başka bir adrese gider; "same" aynı adrese (Next yeniden gezinir, geçmiş kaydını
 * yeniler); null bağlantı değil ya da yeni sekme/indirme/çapa (bu sayfayı etkilemez).
 */
function linkKind(e: MouseEvent): { kind: "leave" | "same"; anchor: HTMLAnchorElement } | null {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return null;
  const a = e.target instanceof Element ? e.target.closest("a[href]") : null;
  if (!(a instanceof HTMLAnchorElement) || a.hasAttribute("download") || (a.target && a.target !== "_self")) return null;
  const to = new URL(a.href, window.location.href);
  const here = window.location;
  if (to.origin === here.origin && to.pathname === here.pathname && to.search === here.search) {
    return to.hash ? null : { kind: "same", anchor: a };
  }
  return { kind: "leave", anchor: a };
}

/** Geri gidilecek bir sayfa var mı (Navigation API; bilinmiyorsa var sayılır) */
function canGoBack(): boolean {
  const nav = (window as { navigation?: { canGoBack?: boolean } }).navigation;
  return nav?.canGoBack !== false;
}

/**
 * Kaydedilmemiş değişiklik bekçisi (Canlı izleme şablon düzenleyicisi). Değişiklik varken:
 *   - sayfadaki her bağlantı (soldaki menü, alarm şeridi, kutu bağlantıları, Next `Link` ya da düz `<a>`) gezinmeden
 *     önce "Kaydedilmedi, çıkılsın mı?" sorar; Vazgeç denirse tıklama hiçbir dinleyiciye ulaşmaz (pencere yakalama
 *     evresi). Aynı adrese giden bağlantı (ör. menüde "Canlı izleme") gezinmez (sorulmaz, düzenleme kalır);
 *   - sekmeyi kapatma / yenileme tarayıcının kendi `beforeunload` sorusunu çıkarır;
 *   - "Çıkış" `leave` ile sorar;
 *   - tarayıcının Geri düğmesi: değişiklik olunca geçmişe aynı adresle bir bekçi kaydı eklenir (Next'in geçmiş durumu
 *     kopyalanarak; sayfa yenilendiyse kayıt zaten bekçidir, o kullanılır). Geri bu kaydı çıkarınca sorulur: Vazgeç
 *     `history.forward()` ile aynı kayda döner (yeni kayıt eklenmez), Tamam bir adım daha geri gider (geri gidilecek
 *     sayfa yoksa bekçi kaydına dönülür, sorulmaya devam edilir).
 * Geçmişte artık adım kalmaz: değişiklik kaydedilince/atılınca ve onaylanmış bir bağlantıyla çıkarken bekçi kaydı önce
 * geri alınır; sonra gezinilir. Tarayıcı ileri kayıtları silemediği için Geri → Tamam'dan sonra İleri ile bekçi kaydına
 * gelinirse (değişiklik yokken) sessizce bir önceki aynı adresli kayda dönülür.
 * Çıkış onaylandıktan sonra (`leaving`) bir daha sorulmaz; çıkış LEAVE_LATCH_MS içinde gerçekleşmezse yeniden sorulur.
 */
export function UnsavedGuardProvider({ children }: { children: React.ReactNode }) {
  const dirty = useRef(false);
  /** Kullanıcı çıkmayı onayladı: gezinme sürerken bir daha sorulmaz */
  const leaving = useRef(false);
  const leavingTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  /** Şu anki geçmiş kaydı bizim bekçi kaydımız mı ve hangi adreste */
  const onSentinel = useRef(false);
  const sentinelHref = useRef("");
  /** Bizim tetiklediğimiz (yok sayılacak) `popstate` sayısı ve bekçi kaydı geri alınınca yapılacak iş */
  const ignorePops = useRef(0);
  const afterPop = useRef<(() => void) | null>(null);

  const pushSentinel = useCallback(() => {
    window.history.pushState({ ...(window.history.state ?? {}), [SENTINEL]: true }, "", window.location.href);
    onSentinel.current = true;
    sentinelHref.current = window.location.href;
  }, []);
  /** Bekçiyi kurar: şu anki kayıt zaten bekçiyse (sayfa yenilendi, Next aynı durumu korudu) onu kullanır */
  const arm = useCallback(() => {
    if (isSentinel(window.history.state)) {
      onSentinel.current = true;
      sentinelHref.current = window.location.href;
    } else {
      pushSentinel();
    }
  }, [pushSentinel]);
  /** Bekçi kaydı şu anki kayıtsa geri alır, sonra `then`; değilse `then` hemen */
  const popSentinel = useCallback((then?: () => void) => {
    if (onSentinel.current && isSentinel(window.history.state) && window.location.href === sentinelHref.current) {
      ignorePops.current += 1;
      afterPop.current = then ?? null;
      window.history.back();
      return;
    }
    then?.();
  }, []);
  const setLeaving = useCallback((on: boolean) => {
    leaving.current = on;
    clearTimeout(leavingTimer.current);
    if (!on) return;
    leavingTimer.current = setTimeout(() => {
      leaving.current = false;
      if (dirty.current) arm();                           // çıkılmadı: bekçi yerinde olsun
    }, LEAVE_LATCH_MS);
  }, [arm]);

  const confirmLeave = useCallback((): boolean => {
    if (!dirty.current || leaving.current) return true;
    if (!window.confirm(UNSAVED_TEXT)) return false;
    setLeaving(true);
    return true;
  }, [setLeaving]);

  const setDirty = useCallback((d: boolean) => {
    if (d === dirty.current) return;
    dirty.current = d;
    if (d) {
      setLeaving(false);
      arm();
      return;
    }
    // Değişiklik kalmadı (kaydedildi, geri alındı, vazgeçildi): sayfada kalınıyorsa bekçi kaydı geri alınır; çıkılıyorsa
    // çıkış yolu onu zaten kaldırdı
    if (!leaving.current) popSentinel();
    setLeaving(false);
  }, [arm, popSentinel, setLeaving]);

  const leave = useCallback(async (): Promise<boolean> => {
    if (!confirmLeave()) return false;
    await new Promise<void>((done) => {
      const t = setTimeout(done, POP_TIMEOUT_MS);
      popSentinel(() => { clearTimeout(t); done(); });
    });
    setDirty(false);
    return true;
  }, [confirmLeave, popSentinel, setDirty]);

  useEffect(() => {
    // Sayfa bekçi kaydının üstünde açıldı (yenilendi): Geri basılınca aynı adresli adım atlanabilsin
    if (isSentinel(window.history.state)) {
      onSentinel.current = true;
      sentinelHref.current = window.location.href;
    }
    const onClick = (e: MouseEvent) => {
      if (!dirty.current) return;
      const link = linkKind(e);
      if (!link) return;
      if (link.kind === "same") { e.preventDefault(); return; }   // aynı sayfa: gezinme yok (menü yine kapanır)
      if (leaving.current) return;                                    // onaylandı (aşağıdaki yeniden tıklama)
      e.preventDefault();
      e.stopPropagation();
      if (!confirmLeave()) return;
      // Önce bekçi kaydı geri alınır (geçmişte artık adım kalmasın), sonra aynı bağlantı yeniden tıklanır. Tıklama bir
      // sonraki görevde: Next aynı geri gidişi (popstate) işlerken gelen gezinmeyi yutabiliyor
      popSentinel(() => { setTimeout(() => link.anchor.click(), 0); });
    };
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (!dirty.current || leaving.current) return;
      e.preventDefault();
      e.returnValue = "";                                 // eski tarayıcılar soruyu ancak bununla gösterir
    };
    const onPopState = (e: PopStateEvent) => {
      const wasOn = onSentinel.current;
      onSentinel.current = isSentinel(e.state);
      if (onSentinel.current) sentinelHref.current = window.location.href;
      if (ignorePops.current > 0) {
        ignorePops.current -= 1;
        const then = afterPop.current;
        afterPop.current = null;
        then?.();
        return;
      }
      if (onSentinel.current) {
        // Değişiklik yokken artık bir bekçi kaydına gelindi (Geri → Tamam sonrası İleri): aynı adresli kayda dönülür
        if (!dirty.current) { ignorePops.current += 1; window.history.back(); }
        return;
      }
      // Yalnız bekçi kaydından aynı adrese geri çıkıldıysa (kullanıcı bu sayfadan Geri ile çıkmak istiyor)
      if (!wasOn || window.location.href !== sentinelHref.current) return;
      // Değişiklik yok (ör. sayfa yenilendi, bekçi kaydı kaldı) ya da çıkış onaylı: aynı adresli adım atlanır
      if (!dirty.current || leaving.current) { window.history.back(); return; }
      if (!window.confirm(UNSAVED_TEXT) || !canGoBack()) {
        // Vazgeç (ya da gidilecek sayfa yok): hâlâ duran bekçi kaydına dönülür; yeni kayıt eklenmez
        ignorePops.current += 1;
        window.history.forward();
        return;
      }
      setLeaving(true);
      window.history.back();
    };
    window.addEventListener("click", onClick, true);
    window.addEventListener("beforeunload", onBeforeUnload);
    window.addEventListener("popstate", onPopState);
    return () => {
      window.removeEventListener("click", onClick, true);
      window.removeEventListener("beforeunload", onBeforeUnload);
      window.removeEventListener("popstate", onPopState);
      clearTimeout(leavingTimer.current);
    };
  }, [confirmLeave, popSentinel, setLeaving]);

  const value = useMemo(() => ({ setDirty, confirmLeave, leave }), [setDirty, confirmLeave, leave]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
