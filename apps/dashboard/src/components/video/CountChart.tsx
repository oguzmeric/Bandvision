"use client";

import { useEffect, useState } from "react";
import { int } from "@/lib/format";

/** counts.csv (zaman_sn;iz;delta;toplam) → zamana göre kümülatif sayım çizgisi. */
export default function CountChart({ jobId, seconds }: { jobId: string; seconds?: number }) {
  const [points, setPoints] = useState<Array<[number, number]> | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setPoints(null);
    setFailed(false);
    fetch(`/api/jobs/${jobId}/files/counts.csv`, { cache: "no-store" })
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then((text) => {
        if (cancelled) return;
        const rows = text.trim().split(/\r?\n/).slice(1)
          .map((l) => l.split(";").map(Number))
          .filter((c) => c.length >= 4 && c.every(Number.isFinite))
          .map((c) => [c[0], c[3]] as [number, number]);
        setPoints(rows);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => { cancelled = true; };
  }, [jobId]);

  if (failed) return null;
  if (!points) return <div className="h-[120px] animate-pulse rounded-xl bg-canvas" />;
  if (points.length === 0) return <p className="text-sm text-muted">Bu videoda sayım olmadı.</p>;

  const W = 420, H = 120, P = 6;
  const tMax = Math.max(seconds ?? 0, points[points.length - 1][0], 1);
  const nMax = Math.max(points[points.length - 1][1], 1);
  const x = (t: number) => P + (t / tMax) * (W - 2 * P);
  const y = (n: number) => H - P - (n / nMax) * (H - 2 * P);
  // basamak çizgi: sayım anında artar
  let d = `M${x(0)},${y(0)}`;
  let prev = 0;
  for (const [t, n] of points) {
    d += ` L${x(t)},${y(prev)} L${x(t)},${y(n)}`;
    prev = n;
  }
  d += ` L${x(tMax)},${y(prev)}`;

  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-[120px] w-full" role="img"
           aria-label={`Zamana göre sayım: ${int(prev)} ürün, ${Math.round(tMax)} saniye`}>
        <defs>
          <linearGradient id="cc" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#6d3bf0" stopOpacity="0.22" />
            <stop offset="1" stopColor="#6d3bf0" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={`${d} L${x(tMax)},${H - P} L${x(0)},${H - P} Z`} fill="url(#cc)" />
        <path d={d} fill="none" stroke="#6d3bf0" strokeWidth={2.2} strokeLinejoin="round" />
      </svg>
      <figcaption className="mt-1 flex justify-between text-[11px] text-faint">
        <span>0 sn</span><span>{Math.round(tMax)} sn · {int(prev)} adet</span>
      </figcaption>
    </figure>
  );
}
