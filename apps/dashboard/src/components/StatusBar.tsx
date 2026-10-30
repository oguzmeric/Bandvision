"use client";

import { useEffect, useState } from "react";
import { ANALYZER_STATE_TEXT, fetchSystem, type SystemInfo } from "@/lib/system";

const POLL_MS = 5000;

/**
 * Ekranın altındaki durum şeridi: analiz sunucusu çalışıyor mu, işlemci yükü, ekran kartı yükü (proje 2 gelene dek "—").
 * Lisans durumu proje 3 gelene dek gösterilmez. `/api/system` 5 sn'de bir yoklanır; istekler üst üste binmez.
 * Panele ulaşılamıyor ya da oturum düşmüşse (giriş yönlendirmesi alarm şeridinde) her alan "—".
 */
export default function StatusBar() {
  const [info, setInfo] = useState<SystemInfo | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      const next = await fetchSystem(ctrl.signal);
      if (ctrl.signal.aborted) return;
      setInfo(next);
      timer = setTimeout(tick, POLL_MS);
    };
    void tick();
    return () => {
      ctrl.abort();
      clearTimeout(timer);
    };
  }, []);

  const server = info ? ANALYZER_STATE_TEXT[info.analyzer] : "—";
  // İşlemci yükü bilinmiyorsa (psutil'siz eski kurulum, durum ucu olmayan eski analiz sunucusu) da "—"
  const cpu = info?.analyzer === "up" && info.cpuPercent !== null ? `%${Math.round(info.cpuPercent)}` : "—";
  return (
    <footer data-testid="status-bar" aria-label="Durum şeridi"
            className="sticky bottom-0 z-30 flex flex-wrap gap-x-2 border-t border-pl-line bg-pl-side px-3 py-1 text-xs text-pl-muted">
      <span>Analiz sunucusu: <span className={info?.analyzer === "up" ? "text-pl-ink" : info ? "font-semibold text-nok-600" : ""}>{server}</span></span>
      <span aria-hidden="true">·</span>
      <span>İşlemci {cpu}</span>
      <span aria-hidden="true">·</span>
      <span>Ekran kartı: —</span>
    </footer>
  );
}
