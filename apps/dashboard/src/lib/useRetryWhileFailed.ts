"use client";

import { useEffect, useRef } from "react";
import { RELOAD_RETRY_MS } from "./views";

/**
 * İlk yüklemesi başarısız olan sayfa, hata durduğu sürece 5 sn'de bir kendiliğinden yeniden dener: sunucu dönünce ya da anahtar
 * düzeltilince eski hata satırı kalmaz, tıklamak ve sayfayı yenilemek gerekmez. `retry` hatayı kendisi temizler ve başarısızsa
 * yeniden yazar (hatayı önce silmemeli: satır her denemede yanıp sönerdi). Süren deneme bitmeden yenisi başlamaz.
 */
export function useRetryWhileFailed(failed: boolean, retry: () => unknown): void {
  const latest = useRef(retry);
  latest.current = retry;
  useEffect(() => {
    if (!failed) return;
    let busy = false;
    const timer = setInterval(() => {
      if (busy) return;
      busy = true;
      void Promise.resolve().then(() => latest.current()).catch(() => undefined).finally(() => { busy = false; });
    }, RELOAD_RETRY_MS);
    return () => clearInterval(timer);
  }, [failed]);
}
