"use client";

import { MONTHS, WEEKDAYS, dayOf, longDate, monthGrid } from "@/lib/archiveTime.mjs";

/**
 * Ay takvimi: ◀ ▶ ile ay değişir; kayıtlı günler koyu ve kalın, bugün çerçeveli, seçili gün dolu. Gün seçmek o günün
 * çizelgesini açar. `days` null: kayıtlı günler henüz bilinmiyor (kamera seçilmedi ya da yükleniyor).
 */
export default function Calendar({ year, month, days, error, selected, today, onMonth, onSelect }: {
  year: number; month: number; days: ReadonlySet<number> | null; error: string | null;
  /** Seçili gün ve bugün: yerel gün başı (epoch sn) */
  selected: number; today: number;
  onMonth: (delta: number) => void; onSelect: (day: number) => void;
}) {
  return (
    <section className="pl-section mb-0 min-w-0" aria-labelledby="archive-calendar-title">
      <h2 id="archive-calendar-title">Takvim</h2>
      <div className="mb-1.5 flex items-center gap-1">
        <button type="button" onClick={() => onMonth(-1)} aria-label="Önceki ay" className="pl-btn h-7 px-2">◀</button>
        <p className="flex-1 text-center font-semibold" aria-live="polite" data-testid="calendar-month">{MONTHS[month - 1]} {year}</p>
        <button type="button" onClick={() => onMonth(1)} aria-label="Sonraki ay" className="pl-btn h-7 px-2">▶</button>
      </div>
      <table className="w-full table-fixed border-collapse text-center">
        <thead>
          <tr>{WEEKDAYS.map((w) => <th key={w} scope="col" className="py-0.5 text-[11.5px] font-medium text-pl-faint">{w}</th>)}</tr>
        </thead>
        <tbody>
          {monthGrid(year, month).map((week, i) => (
            <tr key={i}>
              {week.map((d, j) => {
                if (d === null) return <td key={j} />;
                const at = dayOf(year, month, d);
                const recorded = days?.has(d) ?? false;
                const sel = at === selected;
                const isToday = at === today;
                return (
                  <td key={j} className="p-px">
                    <button type="button" onClick={() => onSelect(at)} aria-pressed={sel}
                            aria-current={isToday ? "date" : undefined}
                            aria-label={`${longDate(year, month, d)}${recorded ? ", kayıt var" : ""}`}
                            data-recorded={recorded || undefined}
                            className={`h-8 w-full rounded-[2px] border text-[13px] ${
                              sel ? "border-pl-accent bg-pl-accent font-bold text-white"
                                : `${isToday ? "border-pl-accent" : "border-transparent"} ${recorded ? "bg-pl-sel font-bold text-pl-ink" : "text-pl-faint"} hover:bg-pl-head`}`}>
                      {d}
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {error && <p role="alert" className="mt-1.5 text-nok-ink">{error}</p>}
    </section>
  );
}
