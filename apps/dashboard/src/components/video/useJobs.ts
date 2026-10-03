"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { AnalysisJob } from "@/lib/types";

const ACTIVE = new Set(["queued", "running"]);

/**
 * İş listesi yoklaması: sürmekte olan iş varken 1,5 sn'de bir, yoksa 15 sn'de bir.
 * Tek döngü; `wake()` beklemeyi keser, istek sürüyorsa bittiğinde hemen bir tur daha atılır.
 */
export function useJobs() {
  const [jobs, setJobs] = useState<AnalysisJob[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wakeRef = useRef<() => void>(() => {});

  const load = useCallback(async (): Promise<AnalysisJob[] | null> => {
    try {
      const res = await fetch("/api/jobs", { cache: "no-store" });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.detail ?? `HTTP ${res.status}`);
      setJobs(body as AnalysisJob[]);
      setError(null);
      return body as AnalysisJob[];
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    }
  }, []);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let inFlight = false;
    let again = false;

    const tick = async () => {
      timer = null;
      inFlight = true;
      const list = await load();
      inFlight = false;
      if (stopped) return;
      if (again) {
        again = false;
        void tick();
        return;
      }
      const busy = list?.some((j) => ACTIVE.has(j.status)) ?? false;
      timer = setTimeout(tick, busy ? 1500 : 15000);
    };

    wakeRef.current = () => {
      if (inFlight) {
        again = true;
      } else {
        if (timer) clearTimeout(timer);
        void tick();
      }
    };
    void tick();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [load]);

  const wake = useCallback(() => wakeRef.current(), []);
  return { jobs, error, wake };
}
