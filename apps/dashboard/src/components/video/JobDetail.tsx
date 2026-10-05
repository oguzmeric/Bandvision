"use client";

import { useState } from "react";
import { bytes, duration, int, num, signedPct, when } from "@/lib/format";
import { ANCHOR_LABELS, DIRECTION_LABELS, MODE_LABELS, PRESET_LABELS, type AnalysisJob } from "@/lib/types";
import CountChart from "./CountChart";
import { StatusPill } from "./JobList";

const STAGE: Record<string, string> = {
  calibrating: "Kalibrasyon: arka plan, eşik ve ürün boyu öğreniliyor",
  counting: "Sayılıyor",
  encoding: "İşaretli video hazırlanıyor",
};

function Stat({ label, value, hint, hero }: { label: string; value: string; hint?: string; hero?: boolean }) {
  return (
    <div className={`rounded-2xl p-3.5 ${hero ? "text-white" : "border border-line bg-white"}`}
         style={hero ? { background: "linear-gradient(135deg,#6d3bf0 0%,#9b3be6 55%,#e0368c 100%)" } : undefined}>
      <small className={`block text-xs ${hero ? "text-white/80" : "text-muted"}`}>{label}</small>
      <b className="text-2xl font-semibold tracking-tight">{value}</b>
      {hint && <span className={`ml-1.5 text-xs font-semibold ${hero ? "text-white/80" : "text-muted"}`}>{hint}</span>}
    </div>
  );
}

export default function JobDetail({ job, onDeleted }: { job: AnalysisJob; onDeleted: () => void }) {
  const [deleting, setDeleting] = useState(false);
  const r = job.result;
  const files = new Set(r?.files ?? []);
  const fileUrl = (name: string) => `/api/jobs/${job.id}/files/${name}`;
  const meta = [
    job.video.width && job.video.height ? `${job.video.width}×${job.video.height}` : null,
    job.video.fps ? `${num(job.video.fps, 0)} fps` : null,
    job.video.seconds ? duration(job.video.seconds) : null,
    bytes(job.video.sizeBytes),
    job.options.preset ? `${PRESET_LABELS[job.options.preset]} profili` : null,
  ].filter(Boolean).join(" · ");

  async function remove() {
    if (!confirm(`"${job.video.name}" analizi ve dosyaları silinsin mi?`)) return;
    setDeleting(true);
    const res = await fetch(`/api/jobs/${job.id}`, { method: "DELETE" });
    setDeleting(false);
    if (res.ok || res.status === 404) onDeleted();
  }

  const accuracy = r?.truth && r.errorPct !== null ? `%${num(Math.max(0, 100 - Math.abs(r.errorPct)), 1)}` : "—";
  const twoWay = r?.countOut !== undefined;

  return (
    <section className="card min-w-0 p-5" aria-labelledby="job-title" data-testid="job-detail">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <StatusPill job={job} />
          <h2 id="job-title" className="mt-1.5 truncate text-lg font-semibold">{job.video.name}</h2>
          <p className="text-[13px] text-muted">{meta}</p>
          <p className="text-xs text-faint">{when(job.createdAt)} · dosyalar {new Date(job.expiresAt).toLocaleDateString("tr-TR")} tarihinde silinir</p>
        </div>
        <div className="flex flex-nowrap gap-2">
          {files.has("counts.csv") && <a href={fileUrl("counts.csv")} className="h-9 rounded-[10px] border border-line bg-white px-3 text-[13px] font-medium leading-9 hover:border-brand-100">CSV indir</a>}
          {files.has("profile.json") && <a href={fileUrl("profile.json")} download="profil.json" className="h-9 rounded-[10px] border border-line bg-white px-3 text-[13px] font-medium leading-9 hover:border-brand-100">Profili indir</a>}
          <button type="button" onClick={remove} disabled={deleting} className="h-9 rounded-[10px] border border-line bg-white px-3 text-[13px] font-medium text-nok-600 hover:border-nok-50">{deleting ? "Siliniyor…" : "Sil"}</button>
        </div>
      </header>

      {(job.status === "queued" || job.status === "running") && (
        <div className="rounded-2xl border border-line bg-[#fbfaff] p-5" aria-live="polite">
          <p className="font-medium">{job.status === "queued" ? "Sırada bekliyor" : STAGE[job.stage ?? "counting"]}</p>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-brand-50">
            <div className="brand-gradient h-full transition-[width]" style={{ width: `${Math.round(job.progress * 100)}%` }} />
          </div>
          <p className="mt-2 text-xs text-muted">%{Math.round(job.progress * 100)} · sayfa kendiliğinden güncellenir</p>
        </div>
      )}

      {job.status === "failed" && (
        <div role="alert" className="rounded-2xl bg-nok-50 p-4 text-sm text-nok-600">
          <p className="font-medium">Analiz tamamlanamadı</p>
          <p className="mt-1">{job.error}</p>
          <p className="mt-2 text-xs">İpucu: video sabit kamerayla, bandın tepesinden çekilmiş olmalı. Bant başta doluysa &quot;boş bant aralığı&quot;nı belirterek yeniden dene.</p>
        </div>
      )}

      {r && (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            {twoWay ? (
              <>
                <Stat hero label="Giriş" value={int(r.count)} />
                <Stat label="Çıkış" value={int(r.countOut ?? 0)} />
              </>
            ) : (
              <>
                <Stat hero label="Sayım" value={int(r.count)} />
                <Stat label="Doğru adet" value={r.truth ? int(r.truth) : "—"} />
              </>
            )}
            <Stat label="Doğruluk" value={accuracy} hint={r.truth && r.errorPct !== null ? signedPct(r.errorPct) : undefined} />
            <Stat label="İşleme hızı" value={r.processingFps ? int(r.processingFps) : "—"} hint="kare/sn" />
          </div>

          <div className="grid gap-4 md:grid-cols-[minmax(200px,280px)_minmax(0,1fr)]">
            <div className="overflow-hidden rounded-2xl bg-[#111]">
              {files.has("annotated.mp4") ? (
                <video key={job.id} src={fileUrl("annotated.mp4")} controls playsInline preload="metadata"
                       className="block max-h-[520px] w-full bg-black" data-testid="annotated-video">
                  İşaretli video bu tarayıcıda oynatılamıyor.
                </video>
              ) : (
                <p className="p-6 text-center text-sm text-white/70">
                  {job.status === "expired" ? "Saklama süresi doldu; video silindi." : "İşaretli video yok."}
                </p>
              )}
            </div>
            <div className="min-w-0">
              <p className="eyebrow mb-2.5">Kalibrasyon</p>
              <dl className="mb-4 grid grid-cols-[120px_1fr] gap-x-3 gap-y-2 text-[13.5px]">
                <dt className="text-muted">Yöntem</dt><dd className="font-medium">{MODE_LABELS[r.calibration?.countMode ?? "blob"]}</dd>
                <dt className="text-muted">{twoWay ? "Giriş yönü" : "Akış yönü"}</dt><dd className="font-medium">{r.calibration?.direction ? DIRECTION_LABELS[r.calibration.direction] : "—"}</dd>
                {twoWay ? (
                  <>
                    <dt className="text-muted">Kamera</dt><dd className="font-medium">{ANCHOR_LABELS[job.options.countAnchor ?? "center"]}</dd>
                    <dt className="text-muted">Doğru giriş</dt><dd className="font-medium">{r.truth ? int(r.truth) : "—"}</dd>
                  </>
                ) : r.calibration?.countMode === "linescan" ? (
                  <>
                    <dt className="text-muted">Ürün boyu</dt>
                    <dd className="font-medium">{r.calibration.productLength ? `alanın %${num(r.calibration.productLength * 100, 0)}` : "—"}</dd>
                  </>
                ) : (
                  <>
                    <dt className="text-muted">Arka plan</dt><dd className="font-medium">{r.calibration?.background ?? "—"}</dd>
                    <dt className="text-muted">Eşik</dt><dd className="font-medium">{r.calibration?.threshold ?? "—"}</dd>
                    <dt className="text-muted">Tek ürün alanı</dt><dd className="font-medium">{r.calibration?.expectedArea ? num(r.calibration.expectedArea, 4) : "—"}</dd>
                  </>
                )}
              </dl>
              {r.calibration?.notes?.map((n) => (
                <p key={n} className="mb-3 rounded-xl bg-warn-50 px-3 py-2 text-[12.5px] text-warn-700">{n}</p>
              ))}
              {files.has("counts.csv") && (
                <>
                  <p className="eyebrow mb-2">Zamana göre sayım</p>
                  <CountChart jobId={job.id} seconds={job.video.seconds} />
                </>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
