"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef } from "react";
import { UNSAVED_TEXT } from "@/lib/views";

interface UnsavedGuard {
  /**
   * Sayfada kaydedilmemiş değişiklik var mı (sayfa bildirir; ayrılırken temizler). `discard`: kullanıcı çıkmayı
   * onaylayınca çağrılır (sayfa sakladığı düzenlemeyi siler).
   */
  setDirty: (dirty: boolean, discard?: () => void) => void;
  /** Ayrılmak serbest mi: değişiklik yoksa evet; varsa "Kaydedilmedi, çıkılsın mı?" sorulur, onaylanırsa değişiklik bırakılır */
  confirmLeave: () => boolean;
}

const Ctx = createContext<UnsavedGuard>({ setDirty: () => undefined, confirmLeave: () => true });

export function useUnsavedGuard(): UnsavedGuard {
  return useContext(Ctx);
}

/**
 * Bağlantı tıklamasının etkisi: "leave" başka bir adrese gider; "same" aynı adrese (gezinmeye gerek yok); null bağlantı
 * değil ya da yeni sekme/indirme/çapa (bu sayfayı etkilemez).
 */
function linkKind(e: MouseEvent): "leave" | "same" | null {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return null;
  const a = e.target instanceof Element ? e.target.closest("a[href]") : null;
  if (!(a instanceof HTMLAnchorElement) || a.hasAttribute("download") || (a.target && a.target !== "_self")) return null;
  const to = new URL(a.href, window.location.href);
  const here = window.location;
  if (to.origin === here.origin && to.pathname === here.pathname && to.search === here.search) return to.hash ? null : "same";
  return "leave";
}

/**
 * Kaydedilmemiş değişiklik bekçisi (Canlı izleme şablon düzenleyicisi). Değişiklik varken:
 *   - sayfadaki her bağlantı (soldaki menü, alarm şeridi, kutu bağlantıları, Next `Link` ya da düz `<a>`) gezinmeden
 *     önce "Kaydedilmedi, çıkılsın mı?" sorar; Vazgeç denirse tıklama hiçbir dinleyiciye ulaşmaz (pencere yakalama
 *     evresi), Tamam denirse değişiklik bırakılır ve normal gezinilir. Aynı adrese giden bağlantı (menüde "Canlı
 *     izleme") gezinmez: düzenleme kalır, sorulmaz (menü yine kapanır);
 *   - sekmeyi kapatma / yenileme tarayıcının kendi `beforeunload` sorusunu çıkarır;
 *   - "Çıkış" `confirmLeave` ile bir kez sorar.
 * Tarayıcının Geri/İleri düğmesi sorulmaz ve geçmişe hiçbir kayıt eklenmez/değiştirilmez (tarayıcılar geri dönüşü
 * kilitlemeye direnir); bunun yerine sayfa düzenlemeyi tarayıcı sekmesinde saklar ve dönünce geri yükler.
 */
export function UnsavedGuardProvider({ children }: { children: React.ReactNode }) {
  const dirty = useRef(false);
  const discard = useRef<(() => void) | undefined>(undefined);

  const setDirty = useCallback((d: boolean, onDiscard?: () => void) => {
    dirty.current = d;
    discard.current = d ? onDiscard : undefined;
  }, []);

  const confirmLeave = useCallback((): boolean => {
    if (!dirty.current) return true;
    if (!window.confirm(UNSAVED_TEXT)) return false;
    // Onaylandı: değişiklik bırakılır (sayfa kapanırken ya da gezinirken bir daha sorulmaz)
    const drop = discard.current;
    dirty.current = false;
    discard.current = undefined;
    drop?.();
    return true;
  }, []);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (!dirty.current) return;
      const kind = linkKind(e);
      if (kind === "same") { e.preventDefault(); return; }    // aynı sayfa: gezinme yok, Link'in onClick'i (menü kapanır) çalışır
      if (kind !== "leave" || confirmLeave()) return;
      e.preventDefault();
      e.stopPropagation();
    };
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (!dirty.current) return;
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
