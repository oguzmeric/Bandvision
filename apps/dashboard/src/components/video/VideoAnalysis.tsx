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
    <div className="grid items-start gap-5 lg:grid-cols-[380px_minmax(0,1fr)]">
      <div className="min-w-0">
        <UploadCard onCreated={(j) => { setSelected(j.id); wake(); }} />
        <div className="mt-5">
          <p className="eyebrow">Son analizler</p>
          {error && (
            <p role="alert" className="mt-2 rounded-xl bg-nok-50 px-3 py-2 text-sm text-nok-600">{error}</p>
          )}
          {jobs === null && !error ? (
            <div className="mt-2 h-16 animate-pulse rounded-xl bg-white/70" />
          ) : (
            <JobList jobs={jobs ?? []} selected={selected} onSelect={setSelected} />
          )}
        </div>
      </div>
      {job ? (
        <JobDetail key={job.id} job={job} onDeleted={() => { setSelected(null); wake(); }} />
      ) : (
        <section className="card grid min-h-[320px] place-items-center p-8 text-center text-muted">
          <div>
            <p className="font-medium text-ink">Sonuçlar burada görünecek</p>
            <p className="mt-1 text-sm">Soldan bir video yükle ya da listeden bir analiz seç.</p>
          </div>
        </section>
      )}
    </div>
  );
}
