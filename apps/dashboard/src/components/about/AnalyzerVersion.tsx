"use client";

import { useEffect, useState } from "react";
import { ANALYZER_STATE_TEXT, fetchSystem, type SystemInfo } from "@/lib/system";

/** Analiz sunucusunun sürümü ve git özeti; sunucu çalışmıyorsa "—" ve nedeni. */
export default function AnalyzerVersion() {
  const [info, setInfo] = useState<SystemInfo | null | undefined>(undefined);

  useEffect(() => {
    const ctrl = new AbortController();
    void fetchSystem(ctrl.signal).then((v) => { if (!ctrl.signal.aborted) setInfo(v); });
    return () => ctrl.abort();
  }, []);

  let text: string;
  if (info === undefined) text = "Yükleniyor…";
  else if (info === null) text = "—";
  else if (info.analyzer === "up") text = `${info.analyzerVersion} (${info.analyzerCommit})`;
  else text = `— (analiz sunucusu ${ANALYZER_STATE_TEXT[info.analyzer]})`;
  return <span data-testid="about-analyzer">{text}</span>;
}
