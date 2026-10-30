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
        <p className="text-xs font-medium text-pl-muted">Personel rengi</p>
        <button type="button" onClick={() => onTeach(!teaching)} disabled={!teaching && full} className="pl-btn h-7 text-[12.5px]">
          {teaching ? "Vazgeç" : "Personel rengini öğret"}
        </button>
      </div>
      {teaching && <p className="mb-1.5 rounded-[2px] border border-warn-line bg-warn-50 px-2.5 py-1.5 text-[12px] text-warn-ink">Görüntü donduruldu: bir personelin gövdesine tıklayın.</p>}
      {colors.length === 0 ? (
        <p className="text-[11.5px] text-pl-faint">Kapalı — tüm geçişler sayılır.</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {colors.map((c, i) => (
            <span key={i} data-testid="staff-swatch" className="inline-flex items-center gap-1 rounded-[2px] border border-pl-line py-0.5 pl-0.5 pr-1">
              <span aria-hidden="true" className="h-6 w-6 rounded-[2px] border border-black/10" style={{ background: labToCss(c) }} />
              <button type="button" aria-label={`${i + 1}. personel rengini sil`} onClick={() => onRemove(i)}
                      className="grid h-5 w-5 place-items-center rounded-[2px] text-pl-muted hover:bg-nok-50 hover:text-nok-ink">×</button>
            </span>
          ))}
        </div>
      )}
      {colors.some(isAchromatic) && (
        <p className="mt-1.5 text-[11.5px] text-warn-ink">Bu renk müşterilerde de sık görülür; müşteri yanlışlıkla düşülebilir.</p>
      )}
      {full && !teaching && <p className="mt-1 text-[11.5px] text-pl-faint">En fazla {MAX_STAFF_COLORS} renk.</p>}
      <p className="mt-1 text-[11.5px] text-pl-faint">Bu renkte giyinenlerin geçişi giriş/çıkışa eklenmez, ayrı sayılır.</p>
    </div>
  );
}
