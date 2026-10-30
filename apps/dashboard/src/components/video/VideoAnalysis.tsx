"use client";

import { useEffect, useState } from "react";
import JobDetail from "./JobDetail";
import JobList from "./JobList";
import UploadCard from "./UploadCard";
import { useJobs } from "./useJobs";

export default function VideoAnalysis() {
  const { jobs, error, wake } = useJobs();
  const [selected, setSelected] = useState<string | null>(null);

  // İlk yüklemede en son işi seç; seçili iş silinince listedeki ilkine geç
  useEffect(() => {
    if (!jobs) return;
    if (!selected || !jobs.some((j) => j.id === selected)) setSelected(jobs[0]?.id ?? null);
  }, [jobs, selected]);

  const job = jobs?.find((j) => j.id === selected) ?? null;

  return (
    <div className="grid items-start gap-3 lg:grid-cols-[380px_minmax(0,1fr)]">
      <div className="min-w-0">
        <UploadCard onCreated={(j) => { setSelected(j.id); wake(); }} />
        <section className="pl-section mb-0">
          <h2>Son analizler</h2>
          {error && (
            <p role="alert" className="mb-2 rounded-[2px] border border-nok-line bg-nok-50 px-3 py-2 text-[13px] text-nok-ink">{error}</p>
          )}
          {jobs === null && !error ? (
            <div className="h-16 animate-pulse rounded-[2px] bg-pl-side" />
          ) : (
            <JobList jobs={jobs ?? []} selected={selected} onSelect={setSelected} />
          )}
        </section>
      </div>
      {job ? (
        <JobDetail key={job.id} job={job} onDeleted={() => { setSelected(null); wake(); }} />
      ) : (
        <section className="pl-section mb-0 grid min-h-[240px] place-items-center p-8 text-center text-pl-muted">
          <div>
            <p className="font-medium text-pl-ink">Sonuçlar burada görünecek</p>
            <p className="mt-1 text-[13px]">Soldan bir video yükle ya da listeden bir analiz seç.</p>
          </div>
        </section>
      )}
    </div>
  );
}
