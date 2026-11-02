"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ANALYZER_STATE_TEXT, fetchSystem, type SystemInfo } from "@/lib/system";
import { useRetryWhileFailed } from "@/lib/useRetryWhileFailed";

/** Analiz sunucusunun sürümü ve git özeti; sunucu çalışmıyorsa "—" ve nedeni (çalışana dek kendiliğinden yeniden sorulur). */
export default function AnalyzerVersion() {
  const [info, setInfo] = useState<SystemInfo | null | undefined>(undefined);

  const ctrl = useRef<AbortController | null>(null);
  const load = useCallback(() => {
    const c = ctrl.current;
    return c && fetchSystem(c.signal).then((v) => { if (!c.signal.aborted) setInfo(v); });
  }, []);
  useEffect(() => {
    ctrl.current = new AbortController();
    void load();
    return () => ctrl.current?.abort();
  }, [load]);
  useRetryWhileFailed(info === null || (info !== undefined && info.analyzer !== "up"), load);

  let text: string;
  if (info === undefined) text = "Yükleniyor…";
  else if (info === null) text = "—";
  else if (info.analyzer === "up") text = `${info.analyzerVersion} (${info.analyzerCommit})`;
  else text = `— (analiz sunucusu ${ANALYZER_STATE_TEXT[info.analyzer]})`;
  return <span data-testid="about-analyzer">{text}</span>;
}
