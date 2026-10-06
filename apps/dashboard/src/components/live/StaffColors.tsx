"use client";

import type { LabColor } from "@/lib/live";
import { isAchromatic, labToCss, MAX_STAFF_COLORS } from "@/lib/staff";

/** Kişi sayımı ayarı: personel üniforma renkleri (§4.10 eki). Öğretmede görüntüde personelin üstüne tıklanır. */
export default function StaffColors({ colors, teaching, onTeach, onRemove }: {
  colors: LabColor[]; teaching: boolean; onTeach: (on: boolean) => void; onRemove: (i: number) => void;
}) {
  const full = colors.length >= MAX_STAFF_COLORS;
  return (
    <div role="group" aria-label="Personel rengi">
      <div className="mb-1.5 flex items-center justify-between">
        <p className="text-xs font-medium text-muted">Personel rengi</p>
        <button type="button" onClick={() => onTeach(!teaching)} disabled={!teaching && full}
                className="h-8 rounded-[9px] border border-line px-2.5 text-[12.5px] font-medium hover:border-brand-100 disabled:opacity-50">
          {teaching ? "Vazgeç" : "Personel rengini öğret"}
        </button>
      </div>
      {teaching && <p className="mb-1.5 rounded-lg bg-warn-50 px-2.5 py-1.5 text-[12px] text-warn-700">Görüntüde bir personelin gövdesine tıklayın.</p>}
      {colors.length === 0 ? (
        <p className="text-[11.5px] text-faint">Kapalı — tüm geçişler sayılır.</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {colors.map((c, i) => (
            <span key={i} data-testid="staff-swatch" className="inline-flex items-center gap-1 rounded-full border border-line py-0.5 pl-0.5 pr-1.5">
              <span aria-hidden="true" className="h-6 w-6 rounded-full border border-black/10" style={{ background: labToCss(c) }} />
              <button type="button" aria-label={`${i + 1}. personel rengini sil`} onClick={() => onRemove(i)}
                      className="grid h-5 w-5 place-items-center rounded-full text-muted hover:bg-nok-50 hover:text-nok-600">×</button>
            </span>
          ))}
        </div>
      )}
      {colors.some(isAchromatic) && (
        <p className="mt-1.5 text-[11.5px] text-warn-700">Bu renk müşterilerde de sık görülür; müşteri yanlışlıkla düşülebilir.</p>
      )}
      {full && !teaching && <p className="mt-1 text-[11.5px] text-faint">En fazla {MAX_STAFF_COLORS} renk.</p>}
      <p className="mt-1 text-[11.5px] text-faint">Bu renkte giyinenlerin geçişi giriş/çıkışa eklenmez, ayrı sayılır.</p>
    </div>
  );
}
