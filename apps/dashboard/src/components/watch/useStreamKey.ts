"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { STREAM_REKEY_MS, STREAM_RETRY_MS } from "@/lib/views";

/**
 * Canlı MJPEG `<img>`'inin yeniden bağlanma anahtarı (`k`). Sunucu akışı bilerek bitirebilir (şablon silindi, merkez
 * durdu, boşta kalan birleştirici temizlendi, 60 sn kare yok); Chrome çoğu zaman bitmiş çok parçalı akışta olay
 * vermediği için anahtar şu durumlarda artırılır:
 *   - `<img>` `error` olayı: `STREAM_RETRY_MS` sonra (`onError`);
 *   - sekme yeniden görünür olunca (telefon uyandı, sekmeye dönüldü): hemen;
 *   - ağ geri gelince (`online`): hemen;
 *   - çağıran `bump()` derse (durum yoklaması koptuktan sonra düzeldi: sunucu yeniden başladı): hemen;
 *   - sigorta: sekme görünürken `STREAM_REKEY_MS`'de bir (ağ sessizce takılıp görüntü donarsa ne olay ne hata gelir).
 * Anahtar `src`'ye eklenir; değişince tarayıcı akışı baştan açar.
 * `visible`: sekme görünür mü. Gizliyken çağıran `<img>`'i hiç çizmez: arka plandaki masaüstü sekmesi akışı (sunucuda
 * birleştirici ve okuyucular) boşuna açık tutmaz; görünür olunca yeni anahtarla yeniden açılır.
 */
export function useStreamKey(): { streamKey: number; onError: () => void; bump: () => void; visible: boolean } {
  const [streamKey, setStreamKey] = useState(0);
  // İlk çizim (sunucu tarafı dahil) görünür kabul edilir; gerçek durum ilk etkide okunur (hidrasyon uyuşmazlığı olmasın)
  const [visible, setVisible] = useState(true);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const bump = useCallback(() => {
    clearTimeout(timer.current);                        // bekleyen hata yeniden denemesi ikinci kez bağlanmasın
    setStreamKey((k) => k + 1);
  }, []);

  useEffect(() => {
    setVisible(document.visibilityState !== "hidden");
    const onVisibility = () => {
      const shown = document.visibilityState !== "hidden";
      setVisible(shown);
      if (shown) bump();
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("online", bump);
    const rekey = setInterval(() => { if (document.visibilityState === "visible") bump(); }, STREAM_REKEY_MS);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("online", bump);
      clearInterval(rekey);
      clearTimeout(timer.current);
    };
  }, [bump]);

  const onError = useCallback(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setStreamKey((k) => k + 1), STREAM_RETRY_MS);
  }, []);

  return { streamKey, onError, bump, visible };
}
