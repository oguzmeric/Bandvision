"use client";

import { useState } from "react";
import {
  addArea, AREA_NAME_MAX, AREA_RULE_LABELS, AREA_RULES, AREAS_HELP, areaWatches, enabledRules, MAX_AREAS, removeArea, renameArea,
  safetyAreas, toggleAreaRule, withAreas,
} from "@/lib/safetyAreas.mjs";
import type { SafetyArea, SafetyConfig } from "@/lib/live";
import { SAFETY_DEFAULTS } from "./SafetyPanel";

/**
 * Alan adı kutusu: yazılan metin burada tutulur, profile kırpılmış ve boş değilse gider (boş ad kaydedilmez); kutudan
 * çıkınca kayıtlı ad görünür. Ad dışarıdan değişirse (alan silindi, satır kaydı) kutu onu gösterir.
 */
function AreaName({ name, onRename }: { name: string; onRename: (raw: string) => void }) {
  const [text, setText] = useState(name);
  const [shown, setShown] = useState(name);
  if (shown !== name) {
    setShown(name);
    if (text.trim() !== name) setText(name);
  }
  return (
    <input type="text" aria-label="Alan adı" maxLength={AREA_NAME_MAX} value={text} className="pl-input h-7 min-w-0 flex-1"
           onChange={(e) => { setText(e.target.value); onRename(e.target.value); }}
           onBlur={() => setText(name)} />
  );
}

/**
 * Ayarla panelinde güvenlik (poz) ve telefon kameralarının "Analiz alanları": ad, bu alanda bakılan kurallar (yalnız
 * kamerada açık kurallar seçilebilir; en az biri kalır), Sil; "Alan ekle" (en çok 16; yeni alan "Alan N" ve kamerada açık
 * kurallarla). Çokgenler görüntü üstünde ZonesEditor'da çizilir. Liste boşsa `areas` profile hiç yazılmaz.
 */
export function SafetyAreas({ value, onChange }: { value: SafetyConfig | undefined; onChange: (v: SafetyConfig) => void }) {
  const base = value ?? SAFETY_DEFAULTS;
  const areas = safetyAreas(base);
  const on = enabledRules(base);
  const set = (next: SafetyArea[]) => { if (next !== areas) onChange(withAreas(base, next)); };
  return (
    <div role="group" aria-label="Analiz alanları" className="grid gap-1.5">
      <p className="text-xs font-medium text-pl-muted">Analiz alanları</p>
      {areas.length > 0 && (
        <ul className="grid border border-pl-line-soft text-[13px]">
          {areas.map((a, i) => (
            <li key={i} data-testid="safety-area" className="grid gap-1 border-b border-pl-line-soft px-2 py-1.5 last:border-b-0">
              <div className="flex items-center gap-2">
                <AreaName name={a.name} onRename={(raw) => set(renameArea(areas, i, raw))} />
                <button type="button" aria-label={`${a.name} alanını sil`} onClick={() => set(removeArea(areas, i))}
                        className="text-[12.5px] font-medium text-nok-ink hover:underline">Sil</button>
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-1">
                {AREA_RULES.map((k) => {
                  const checked = a.rules.includes(k);
                  const off = !on.includes(k);
                  const last = checked && a.rules.length === 1;
                  return (
                    <label key={k} className={`flex items-center gap-1.5 text-[12.5px] ${off ? "text-pl-faint" : ""}`}
                           title={off ? "Kamerada kapalı: önce yukarıdaki kuralı açın" : last ? "Alanın en az bir kuralı olmalı" : undefined}>
                      <input type="checkbox" className="h-3.5 w-3.5 accent-pl-accent" checked={checked} disabled={off || last}
                             onChange={(e) => set(toggleAreaRule(areas, i, k, e.target.checked))} />
                      {AREA_RULE_LABELS[k]}
                    </label>
                  );
                })}
              </div>
              {!areaWatches(a, base) && <p className="text-[11.5px] text-warn-ink">Bu alanda kamerada açık kural yok.</p>}
            </li>
          ))}
        </ul>
      )}
      <button type="button" onClick={() => set(addArea(areas, on))} disabled={areas.length >= MAX_AREAS || on.length === 0}
              className="pl-btn h-8 w-full justify-center">+ Alan ekle</button>
      <p className="text-[11.5px] text-pl-faint">{AREAS_HELP}</p>
      <p className="text-[11.5px] text-pl-faint">
        En çok {MAX_AREAS} alan. Kişinin kutusunun ortası alanın içindeyse o alanda işaretli kurallara bakılır; hiçbir alanda
        olmayan kişi izlenmez. Köşeleri sürükle; kenardaki + ile köşe ekle, köşeye çift tıklayınca silinir.
      </p>
    </div>
  );
}
