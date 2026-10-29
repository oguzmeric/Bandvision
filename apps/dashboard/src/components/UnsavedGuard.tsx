"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef } from "react";
import { UNSAVED_TEXT } from "@/lib/views";

/** Onaylanmış çıkıştan sonra bu süre içinde gelen `beforeunload` ikinci kez sormaz (tam sayfa bağlantı: "Giriş yap") */
const CONFIRMED_LEAVE_MS = 2000;

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
 *   - menüdeki "Çıkış" `confirmLeave` ile sorar.
 * Not: tarayıcının Geri düğmesi (uygulama içi geçmiş) yakalanmaz.
 */
export function UnsavedGuardProvider({ children }: { children: React.ReactNode }) {
  const dirty = useRef(false);
  const confirmedAt = useRef(0);

  const confirmLeave = useCallback((): boolean => {
    if (!dirty.current) return true;
    if (!window.confirm(UNSAVED_TEXT)) return false;
    confirmedAt.current = Date.now();
    return true;
  }, []);
  const setDirty = useCallback((d: boolean) => { dirty.current = d; }, []);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (!dirty.current || !leavesPage(e)) return;
      if (confirmLeave()) return;
      e.preventDefault();
      e.stopPropagation();
    };
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (!dirty.current || Date.now() - confirmedAt.current < CONFIRMED_LEAVE_MS) return;
      e.preventDefault();
      e.returnValue = "";                                 // eski tarayıcılar soruyu ancak bununla gösterir
    };
    window.addEventListener("click", onClick, true);
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      window.removeEventListener("click", onClick, true);
      window.removeEventListener("beforeunload", onBeforeUnload);
    };
  }, [confirmLeave]);

  const value = useMemo(() => ({ setDirty, confirmLeave }), [setDirty, confirmLeave]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
