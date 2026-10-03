"use client";

import { duration, signedPct, when } from "@/lib/format";
import type { AnalysisJob } from "@/lib/types";

const STAGE: Record<string, string> = { calibrating: "Kalibrasyon", counting: "Sayılıyor", encoding: "Video hazırlanıyor" };

export function StatusPill({ job }: { job: AnalysisJob }) {
  const base = "whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-semibold";
  switch (job.status) {
    case "done": {
      const r = job.result;
      if (r?.truth) {
        const ok = (r.errorPct ?? 0) === 0;
        return <span className={`${base} ${ok ? "bg-ok-50 text-ok-600" : "bg-nok-50 text-nok-600"}`}>
          {ok ? `${r.count} / ${r.truth}` : signedPct(r.errorPct ?? 0)}</span>;
      }
      return <span className={`${base} bg-ok-50 text-ok-600`}>{r?.count ?? 0} adet</span>;
    }
    case "running":
    case "queued":
      return <span className={`${base} bg-brand-50 text-brand-500`}>{job.status === "queued" ? "Sırada" : "Sürüyor"}</span>;
    case "failed":
      return <span className={`${base} bg-nok-50 text-nok-600`}>Başarısız</span>;
    default:
      return <span className={`${base} bg-canvas-2 text-muted`}>Süresi doldu</span>;
  }
}

export default function JobList({ jobs, selected, onSelect }: {
  jobs: AnalysisJob[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  if (jobs.length === 0) {
    return <p className="mt-2 text-sm text-muted">Henüz analiz yok. İlk videonu yükle.</p>;
  }
  return (
    <ul className="mt-2 flex flex-col gap-2" aria-label="Son analizler">
      {jobs.map((job) => {
        const active = job.status === "running" || job.status === "queued";
        const sub = active
          ? `${STAGE[job.stage ?? ""] ?? "Sırada"} · %${Math.round(job.progress * 100)}`
          : `${when(job.createdAt)} · ${duration(job.video.seconds)}`;
        return (
          <li key={job.id}>
            <button type="button" onClick={() => onSelect(job.id)} aria-current={selected === job.id ? "true" : undefined}
                    data-testid="job-row"
                    className={`flex w-full items-center gap-3 rounded-xl border bg-white p-3 text-left transition ${
                      selected === job.id ? "border-brand-500 ring-3 ring-brand-50" : "border-line hover:border-brand-100"}`}>
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-[#2b2740] text-white/80" aria-hidden="true">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13.5px] font-medium">{job.video.name}</span>
                <span className="block text-xs text-muted">{sub}</span>
                {active && (
                  <span className="mt-1.5 block h-1.5 overflow-hidden rounded-full bg-[#eeeafb]">
                    <span className="brand-gradient block h-full transition-[width]" style={{ width: `${Math.round(job.progress * 100)}%` }} />
                  </span>
                )}
              </span>
              <StatusPill job={job} />
            </button>
          </li>
        );
      })}
    </ul>
  );
}
