"use client";

import { useCallback, useEffect, useState } from "react";

/** Telefon yan çevrilmiş: yatay ve kısa ekran */
const QUERY = "(orientation: landscape) and (max-height: 500px)";

/**
 * Telefonu yan çevirince izleme tam ekrana yakın görünür (`active`): ızgara/tek kamera ekranı kaplar, araç çubuğu
 * gizlenir. Gerçek tam ekran (`requestFullscreen`) kullanıcı dokunuşu ister, yalnız yön değişimiyle açılamaz; bu yüzden
 * CSS ile kaplama. `exit` bu yönlendirmede kaplamadan çıkar; telefon dikeye dönünce kendiliğinden sıfırlanır.
 */
export function usePhoneLandscape(): { active: boolean; exit: () => void } {
  const [match, setMatch] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(QUERY);
    const sync = () => {
      setMatch(mq.matches);
      if (!mq.matches) setDismissed(false);
    };
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);
  const exit = useCallback(() => setDismissed(true), []);
  return { active: match && !dismissed, exit };
}
