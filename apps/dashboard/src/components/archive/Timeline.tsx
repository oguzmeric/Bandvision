"use client";

import { clock, fromPercent, segments, toPercent, type Range } from "@/lib/archiveTime.mjs";

const HOURS = [0, 6, 12, 18, 24];

/**
 * 24 saatlik çizelge: kayıtlı aralıklar dolu, imleç çizgisi `at`'te, saat etiketleri 0/6/12/18/24. Tıklama o ana sarar.
 * Odaklanabilir kaydırıcı (`role="slider"`); ←/→ ve Boşluk kısayollarını üstteki oynatıcı bölgesi işler.
 */
export default function Timeline({ day, end, ranges, error, at, disabled, onSeek }: {
  /** Gün başı ve sonraki gün başı (yerel, epoch sn) */
  day: number; end: number;
  ranges: readonly Range[] | null; error: string | null; at: number; disabled: boolean;
  onSeek: (at: number) => void;
}) {
  const segs = segments(ranges ?? [], day, end);
  const pick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (disabled) return;
    const r = e.currentTarget.getBoundingClientRect();
    if (r.width <= 0) return;
    onSeek(Math.round(fromPercent(((e.clientX - r.left) / r.width) * 100, day, end)));
  };
  const inDay = at >= day && at < end;

  return (
    <div className="min-w-0">
      <div role="slider" tabIndex={disabled ? -1 : 0} aria-label="Zaman çizelgesi" aria-disabled={disabled || undefined}
           aria-valuemin={0} aria-valuemax={Math.round(end - day)} aria-valuenow={Math.round(Math.min(Math.max(at - day, 0), end - day))}
           aria-valuetext={inDay ? clock(at) : "Gün dışında"} data-testid="timeline" onClick={pick}
           className={`relative h-9 border border-pl-line bg-pl-side outline-none focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-pl-accent ${disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}>
        {HOURS.slice(1, -1).map((h) => (
          <span key={h} aria-hidden="true" className="absolute inset-y-0 w-px bg-pl-line-soft" style={{ left: `${toPercent(day + h * 3600, day, end)}%` }} />
        ))}
        {segs.map((s) => (
          <span key={s.start} data-testid="timeline-range" title={`${clock(s.start)} – ${clock(s.end)}`}
                className="absolute inset-y-1 bg-pl-accent/60" style={{ left: `${s.left}%`, width: `max(${s.width}%, 2px)` }} />
        ))}
        {inDay && (
          <span aria-hidden="true" data-testid="timeline-cursor" className="absolute -inset-y-1 w-0.5 -translate-x-1/2 bg-nok-600"
                style={{ left: `${toPercent(at, day, end)}%` }} />
        )}
      </div>
      <div aria-hidden="true" className="relative h-4 text-[11.5px] text-pl-faint">
        {HOURS.map((h, i) => (
          <span key={h} className={`absolute top-0.5 ${i === 0 ? "" : i === HOURS.length - 1 ? "-translate-x-full" : "-translate-x-1/2"}`}
                style={{ left: `${h === 24 ? 100 : toPercent(day + h * 3600, day, end)}%` }}>
            {h}
          </span>
        ))}
      </div>
      {ranges === null && !error && !disabled && <p className="text-pl-muted">Kayıtlar yükleniyor…</p>}
      {ranges !== null && segs.length === 0 && <p className="text-pl-muted">Bu günde kayıt yok.</p>}
      {error && <p role="alert" className="text-nok-ink">{error}</p>}
    </div>
  );
}
