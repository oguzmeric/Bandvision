"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { STREAM_RETRY_MS } from "@/lib/views";

/**
 * Canlı MJPEG `<img>`'inin yeniden bağlanma anahtarı (`k`). Sunucu akışı bilerek bitirebilir (şablon silindi, merkez
 * durdu, boşta kalan birleştirici temizlendi, 60 sn kare yok); Chrome çoğu zaman bitmiş çok parçalı akışta olay
 * vermediği için anahtar şu durumlarda artırılır:
 *   - `<img>` `error` olayı: `STREAM_RETRY_MS` sonra (`onError`);
 *   - sekme yeniden görünür olunca (telefon uyandı, sekmeye dönüldü): hemen;
 *   - ağ geri gelince (`online`): hemen;
 *   - çağıran `bump()` derse (durum yoklaması koptuktan sonra düzeldi: sunucu yeniden başladı): hemen.
 * Anahtar `src`'ye eklenir; değişince tarayıcı akışı baştan açar.
 */
export function useStreamKey(): { streamKey: number; onError: () => void; bump: () => void } {
  const [streamKey, setStreamKey] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const bump = useCallback(() => {
    clearTimeout(timer.current);                        // bekleyen hata yeniden denemesi ikinci kez bağlanmasın
    setStreamKey((k) => k + 1);
  }, []);

  useEffect(() => {
    const onVisible = () => { if (document.visibilityState === "visible") bump(); };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", bump);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", bump);
      clearTimeout(timer.current);
    };
  }, [bump]);

  const onError = useCallback(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setStreamKey((k) => k + 1), STREAM_RETRY_MS);
  }, []);

  return { streamKey, onError, bump };
}
