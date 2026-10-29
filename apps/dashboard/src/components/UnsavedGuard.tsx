"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef } from "react";
import { UNSAVED_TEXT } from "@/lib/views";

/** Geri bekçisinin geçmiş kaydını işaretleyen alan (Next'in kendi geçmiş durumunun yanına eklenir) */
const SENTINEL = "bvUnsaved";

const isSentinel = (state: unknown): boolean => typeof state === "object" && state !== null && SENTINEL in state;

interface UnsavedGuard {
  /** Sayfada kaydedilmemiş değişiklik var mı (sayfa bildirir; ayrılırken temizler) */
  setDirty: (dirty: boolean) => void;
  /** Ayrılmak serbest mi: değişiklik yoksa evet; varsa "Kaydedilmedi, çıkılsın mı?" sorulur */
  confirmLeave: () => boolean;
}

const Ctx = createContext<UnsavedGuard>({ setDirty: () => undefined, confirmLeave: () => true });

export function useUnsavedGuard(): UnsavedGuard {
  return useContext(Ctx);
}

/** Bağlantı tıklaması bu sayfadan başka bir adrese mi götürür (yeni sekme, indirme, aynı adres ya da yalnız #çapa değil) */
function leavesPage(e: MouseEvent): boolean {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return false;
  const a = e.target instanceof Element ? e.target.closest("a[href]") : null;
  if (!(a instanceof HTMLAnchorElement) || a.hasAttribute("download") || (a.target && a.target !== "_self")) return false;
  const to = new URL(a.href, window.location.href);
  const here = window.location;
  return to.origin !== here.origin || to.pathname !== here.pathname || to.search !== here.search;
}

/**
 * Kaydedilmemiş değişiklik bekçisi (Canlı izleme şablon düzenleyicisi). Değişiklik varken:
 *   - sayfadaki her bağlantı (soldaki menü, alarm şeridi, kutu bağlantıları, Next `Link` ya da düz `<a>`) gezinmeden
 *     önce "Kaydedilmedi, çıkılsın mı?" sorar; Vazgeç denirse tıklama hiçbir dinleyiciye ulaşmaz (pencere yakalama evresi);
 *   - sekmeyi kapatma / yenileme tarayıcının kendi `beforeunload` sorusunu çıkarır;
 *   - menüdeki "Çıkış" `confirmLeave` ile sorar;
 *   - tarayıcının Geri düğmesi: değişiklik olunca geçmişe aynı adresle bir bekçi kaydı eklenir (Next'in geçmiş durumu
 *     kopyalanarak). Geri bu kaydı çıkarınca sorulur: Vazgeç kaydı geri koyar (sayfada kalınır), Tamam bir adım daha
 *     geri gider. Değişiklik kaydedilince/atılınca bekçi kaydı sessizce geri alınır (geçmişte fazladan adım kalmaz).
 * Çıkış onaylandıktan sonra (`leaving`) ne `beforeunload` ne Geri bir daha sorar ("Çıkış" iki kez sormaz).
 */
export function UnsavedGuardProvider({ children }: { children: React.ReactNode }) {
  const dirty = useRef(false);
  /** Kullanıcı çıkmayı onayladı: sayfa değişene dek bir daha sorulmaz, bekçi kaydına dokunulmaz */
  const leaving = useRef(false);
  /** Şu anki geçmiş kaydı bizim bekçi kaydımız mı; hangi adreste; bizim tetiklediğimiz kaç `popstate` yok sayılacak */
  const onSentinel = useRef(false);
  const sentinelHref = useRef("");
  const ignorePops = useRef(0);

  const pushSentinel = useCallback(() => {
    window.history.pushState({ ...(window.history.state ?? {}), [SENTINEL]: true }, "", window.location.href);
    onSentinel.current = true;
    sentinelHref.current = window.location.href;
  }, []);

  const confirmLeave = useCallback((): boolean => {
    if (!dirty.current || leaving.current) return true;
    if (!window.confirm(UNSAVED_TEXT)) return false;
    leaving.current = true;
    return true;
  }, []);

  const setDirty = useCallback((d: boolean) => {
    if (d === dirty.current) return;
    dirty.current = d;
    if (d) {
      leaving.current = false;
      if (!isSentinel(window.history.state)) pushSentinel();
      return;
    }
    // Değişiklik kalmadı (kaydedildi, geri alındı, vazgeçildi): sayfadan çıkılmıyorsa bekçi kaydı geri alınır
    if (!leaving.current && onSentinel.current && isSentinel(window.history.state) && window.location.href === sentinelHref.current) {
      ignorePops.current += 1;
      window.history.back();
    }
    leaving.current = false;
  }, [pushSentinel]);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (!dirty.current || !leavesPage(e)) return;
      if (confirmLeave()) return;
      e.preventDefault();
      e.stopPropagation();
    };
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (!dirty.current || leaving.current) return;
      e.preventDefault();
      e.returnValue = "";                                 // eski tarayıcılar soruyu ancak bununla gösterir
    };
    const onPopState = (e: PopStateEvent) => {
      const wasOn = onSentinel.current;
      onSentinel.current = isSentinel(e.state);
      if (ignorePops.current > 0) { ignorePops.current -= 1; return; }
      // Yalnız bekçi kaydından aynı adrese geri çıkıldıysa (kullanıcı bu sayfadan Geri ile çıkmak istiyor)
      if (onSentinel.current || !wasOn || window.location.href !== sentinelHref.current || !dirty.current) return;
      if (leaving.current || window.confirm(UNSAVED_TEXT)) {
        leaving.current = true;
        window.history.back();
        return;
      }
      pushSentinel();                                      // Vazgeç: sayfada kalınır, bekçi yeniden kurulur
    };
    window.addEventListener("click", onClick, true);
    window.addEventListener("beforeunload", onBeforeUnload);
    window.addEventListener("popstate", onPopState);
    return () => {
      window.removeEventListener("click", onClick, true);
      window.removeEventListener("beforeunload", onBeforeUnload);
      window.removeEventListener("popstate", onPopState);
    };
  }, [confirmLeave, pushSentinel]);

  const value = useMemo(() => ({ setDirty, confirmLeave }), [setDirty, confirmLeave]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
