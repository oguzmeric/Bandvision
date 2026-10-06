"use client";

import { useEffect, useState } from "react";
import { int } from "@/lib/format";

type Series = { label: string; color: string; points: Array<[number, number]> };

/**
 * counts.csv → zamana göre kümülatif sayım çizgisi.
 * Tek yönlü: `zaman_sn;iz;delta;toplam`. İki yönlü (kişi): `zaman_sn;iz;yon;giris_toplam;cikis_toplam` → Giriş ve Çıkış.
 */
export function parseCounts(text: string): Series[] {
  const lines = text.trim().split(/\r?\n/);
  const header = (lines[0] ?? "").split(";");
  const rows = lines.slice(1).map((l) => l.split(";"));
  if (header.includes("yon")) {
    const inP: Array<[number, number]> = [], outP: Array<[number, number]> = [];
    for (const c of rows) {
      const t = Number(c[0]), nIn = Number(c[3]), nOut = Number(c[4]);
      if (![t, nIn, nOut].every(Number.isFinite)) continue;
      if (c[2] === "giris") inP.push([t, nIn]);
      else if (c[2] === "cikis") outP.push([t, nOut]);
    }
    return [
      { label: "giriş", color: "#16a34a", points: inP },
      { label: "çıkış", color: "#ea7a0c", points: outP },
    ];
  }
  const pts = rows.map((c) => c.map(Number))
    .filter((c) => c.length >= 4 && c.every(Number.isFinite))
    .map((c) => [c[0], c[3]] as [number, number]);
  return [{ label: "adet", color: "#6d3bf0", points: pts }];
}

export default function CountChart({ jobId, seconds }: { jobId: string; seconds?: number }) {
  const [series, setSeries] = useState<Series[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setSeries(null);
    setFailed(false);
    fetch(`/api/jobs/${jobId}/files/counts.csv`, { cache: "no-store" })
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then((text) => !cancelled && setSeries(parseCounts(text)))
      .catch(() => !cancelled && setFailed(true));
    return () => { cancelled = true; };
  }, [jobId]);

  if (failed) return null;
  if (!series) return <div className="h-[120px] animate-pulse rounded-xl bg-canvas" />;
  if (series.every((s) => s.points.length === 0)) return <p className="text-sm text-muted">Bu videoda sayım olmadı.</p>;

  const W = 420, H = 120, P = 6;
  const lastT = Math.max(...series.map((s) => s.points.at(-1)?.[0] ?? 0));
  const tMax = Math.max(seconds ?? 0, lastT, 1);
  const nMax = Math.max(...series.map((s) => s.points.at(-1)?.[1] ?? 0), 1);
  const x = (t: number) => P + (t / tMax) * (W - 2 * P);
  const y = (n: number) => H - P - (n / nMax) * (H - 2 * P);
  // basamak çizgi: sayım anında artar
  const step = (points: Array<[number, number]>) => {
    let d = `M${x(0)},${y(0)}`;
    let prev = 0;
    for (const [t, n] of points) {
      d += ` L${x(t)},${y(prev)} L${x(t)},${y(n)}`;
      prev = n;
    }
    return { d: `${d} L${x(tMax)},${y(prev)}`, total: prev };
  };
  const drawn = series.map((s) => ({ ...s, ...step(s.points) }));
  const single = drawn.length === 1;
  const summary = single ? `${int(drawn[0].total)} ürün` : drawn.map((s) => `${int(s.total)} ${s.label}`).join(" · ");

  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-[120px] w-full" role="img"
           aria-label={`Zamana göre sayım: ${summary}, ${Math.round(tMax)} saniye`}>
        {single && (
          <>
            <defs>
              <linearGradient id="cc" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0" stopColor="#6d3bf0" stopOpacity="0.22" />
                <stop offset="1" stopColor="#6d3bf0" stopOpacity="0" />
              </linearGradient>
            </defs>
            <path d={`${drawn[0].d} L${x(tMax)},${H - P} L${x(0)},${H - P} Z`} fill="url(#cc)" />
          </>
        )}
        {drawn.map((s) => (
          <path key={s.label} d={s.d} fill="none" stroke={s.color} strokeWidth={2.2} strokeLinejoin="round" />
        ))}
      </svg>
      <figcaption className="mt-1 flex justify-between text-[11px] text-faint">
        <span>0 sn</span>
        <span className="flex items-center gap-2">
          {!single && drawn.map((s) => (
            <span key={s.label} className="inline-flex items-center gap-1">
              <i className="inline-block h-0.5 w-3 rounded" style={{ background: s.color }} aria-hidden="true" />
              {int(s.total)} {s.label}
            </span>
          ))}
          <span>{Math.round(tMax)} sn{single ? ` · ${int(drawn[0].total)} adet` : ""}</span>
        </span>
      </figcaption>
    </figure>
  );
}
