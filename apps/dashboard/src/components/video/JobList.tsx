"use client";

import { duration, signedPct, when } from "@/lib/format";
import type { AnalysisJob } from "@/lib/types";

const STAGE: Record<string, string> = { calibrating: "Kalibrasyon", counting: "Sayılıyor", encoding: "Video hazırlanıyor" };

export function StatusPill({ job }: { job: AnalysisJob }) {
  const base = "whitespace-nowrap rounded-[2px] px-2 py-0.5 text-[11px] font-semibold";
  switch (job.status) {
    case "done": {
      const r = job.result;
      if (r?.truth) {
        const ok = (r.errorPct ?? 0) === 0;
        return <span className={`${base} ${ok ? "bg-ok-50 text-ok-ink" : "bg-nok-50 text-nok-ink"}`}>
          {ok ? `${r.count} / ${r.truth}` : signedPct(r.errorPct ?? 0)}</span>;
      }
      return <span className={`${base} bg-ok-50 text-ok-ink`}>
        {r?.countOut !== undefined ? `${r.count} giriş · ${r.countOut} çıkış` : `${r?.count ?? 0} adet`}</span>;
    }
    case "running":
    case "queued":
      return <span className={`${base} bg-pl-sel text-pl-accent`}>{job.status === "queued" ? "Sırada" : "Sürüyor"}</span>;
    case "failed":
      return <span className={`${base} bg-nok-50 text-nok-ink`}>Başarısız</span>;
    default:
      return <span className={`${base} bg-pl-head text-pl-muted`}>Süresi doldu</span>;
  }
}

export default function JobList({ jobs, selected, onSelect }: {
  jobs: AnalysisJob[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  if (jobs.length === 0) {
    return <p className="py-1 text-pl-muted">Henüz analiz yok. İlk videonu yükle.</p>;
  }
  return (
    <ul className="flex flex-col border border-pl-line-soft" aria-label="Son analizler">
      {jobs.map((job) => {
        const active = job.status === "running" || job.status === "queued";
        const sub = active
          ? `${STAGE[job.stage ?? ""] ?? "Sırada"} · %${Math.round(job.progress * 100)}`
          : `${when(job.createdAt)} · ${duration(job.video.seconds)}`;
        return (
          <li key={job.id} className="border-b border-pl-line-soft last:border-b-0">
            <button type="button" onClick={() => onSelect(job.id)} aria-current={selected === job.id ? "true" : undefined}
                    data-testid="job-row"
                    className={`flex w-full items-center gap-2.5 px-2 py-1.5 text-left ${
                      selected === job.id ? "bg-pl-sel" : "hover:bg-pl-side"}`}>
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-[2px] bg-[#3a3f47] text-white/80" aria-hidden="true">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium">{job.video.name}</span>
                <span className="block text-xs text-pl-muted">{sub}</span>
                {active && (
                  <span className="mt-1 block h-1.5 overflow-hidden rounded-[1px] bg-pl-head">
                    <span className="block h-full bg-pl-accent transition-[width]" style={{ width: `${Math.round(job.progress * 100)}%` }} />
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
