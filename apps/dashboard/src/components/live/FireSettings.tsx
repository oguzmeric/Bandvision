"use client";

import {
  addZone, FIRE_RULES, FIRE_WARNING, fireConfig, fireModelLine, MAX_ZONES, removeZone, SENSITIVITIES, SENSITIVITY_LABELS,
} from "@/lib/fireAlarms.mjs";
import type { FireConfig, LiveSession } from "@/lib/live";

/** Yangın/duman uyarısı: ayar panelinde ve izleme panelinde hep görünür */
export function FireWarning() {
  return (
    <p className="rounded-[2px] border border-warn-line bg-warn-50 px-2.5 py-1.5 text-[12px] text-warn-ink" data-testid="fire-warning">
      {FIRE_WARNING}
    </p>
  );
}

/** Model satırı: "Yangın/duman modeli: hazır / yükleniyor / kurulu değil" (oturumun `fire` bloğundan) */
export function FireModelLine({ status }: { status: LiveSession["fire"] }) {
  const line = fireModelLine(status);
  if (!line) return null;
  const tone = line.tone === "ok" ? "text-ok-ink" : line.tone === "warn" ? "text-nok-ink" : "text-pl-muted";
  return <p className={`text-[12.5px] font-medium ${tone}`} data-testid="fire-model">{line.text}</p>;
}

/**
 * Ayarla panelinde yangın/duman ayarları: iki kural (aç/kapa + süre), hassasiyet, alarm resmi, hariç bölgelerin listesi
 * (çizimi görüntü üstünde ZonesEditor yapar), model satırı ve sabit uyarı.
 */
export function FireSettings({ value, status, onChange }: {
  value: Partial<FireConfig> | undefined; status: LiveSession["fire"]; onChange: (v: FireConfig) => void;
}) {
  const v = fireConfig(value);
  const rule = (k: "fire" | "smoke") => {
    const { title, min, max } = FIRE_RULES[k];
    return (
      <div className="grid gap-1">
        <label className="flex items-center gap-2 text-[13px] font-medium">
          <input type="checkbox" className="h-4 w-4 accent-pl-accent" checked={v[k].enabled}
                 onChange={(e) => onChange({ ...v, [k]: { ...v[k], enabled: e.target.checked } })} />
          {title}
        </label>
        <label className="text-[13px]">{title} süresi: <b>{v[k].seconds} sn</b>
          <input type="range" aria-label={`${title} süresi`} min={min} max={max} step={1} value={v[k].seconds} disabled={!v[k].enabled}
                 className="mt-1 w-full accent-pl-accent" onChange={(e) => onChange({ ...v, [k]: { ...v[k], seconds: Number(e.target.value) } })} />
        </label>
      </div>
    );
  };
  const zones = v.ignoreZones;
  return (
    <div role="group" aria-label="Yangın/duman kuralları" className="grid gap-3">
      <FireModelLine status={status} />
      {rule("fire")}
      {rule("smoke")}
      {!v.fire.enabled && !v.smoke.enabled && (
        <p role="status" className="text-[12.5px] text-nok-ink">En az bir kural açık olmalı.</p>
      )}
      <div>
        <p className="mb-1 text-xs font-medium text-pl-muted">Hassasiyet</p>
        <div role="radiogroup" aria-label="Hassasiyet" className="grid auto-cols-fr grid-flow-col overflow-hidden rounded-[2px] border border-pl-ctl text-[13px]">
          {SENSITIVITIES.map((s) => (
            <button key={s} type="button" role="radio" aria-checked={v.sensitivity === s} onClick={() => onChange({ ...v, sensitivity: s })}
                    className={`h-7 border-r border-pl-ctl px-2 last:border-r-0 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-pl-accent ${v.sensitivity === s ? "bg-pl-sel font-semibold text-pl-ink" : "bg-[#f7f8fa] text-pl-muted hover:bg-pl-head hover:text-pl-ink"}`}>
              {SENSITIVITY_LABELS[s]}
            </button>
          ))}
        </div>
        <p className="mt-1 text-[11.5px] text-pl-faint">Yüksek: daha küçük ve soluk alev/duman da yakalanır, yanlış alarm artabilir.</p>
      </div>
      <label className="flex items-start gap-2 text-[13px]">
        <input type="checkbox" className="mt-0.5 h-4 w-4 accent-pl-accent" checked={v.sendImage} onChange={(e) => onChange({ ...v, sendImage: e.target.checked })} />
        <span>Alarm resmini gönder
          <span className="block text-[11.5px] text-pl-faint">Telegram&apos;a olay resmi de gider. Kapalıyken yalnızca kamera adı ve saat gider.</span>
        </span>
      </label>
      <div>
        <p className="mb-1 text-xs font-medium text-pl-muted">Hariç bölgeler</p>
        {zones.length === 0 ? (
          <p className="text-[12.5px] text-pl-faint">Hariç bölge yok: görüntünün tamamı izlenir.</p>
        ) : (
          <ul className="grid border border-pl-line-soft text-[13px]" data-testid="fire-zones">
            {zones.map((z, i) => (
              <li key={i} className="flex items-center justify-between gap-2 border-b border-pl-line-soft px-2 py-1 last:border-b-0">
                <span>Bölge {i + 1} <span className="text-[11.5px] text-pl-faint">· {z.length} köşe</span></span>
                <button type="button" aria-label={`Bölge ${i + 1} sil`} onClick={() => onChange({ ...v, ignoreZones: removeZone(zones, i) })}
                        className="text-[12.5px] font-medium text-nok-ink hover:underline">Sil</button>
              </li>
            ))}
          </ul>
        )}
        <button type="button" onClick={() => onChange({ ...v, ignoreZones: addZone(zones) })} disabled={zones.length >= MAX_ZONES}
                className="pl-btn mt-1.5 h-8 w-full justify-center">+ Bölge ekle</button>
        <p className="mt-1 text-[11.5px] text-pl-faint">
          Ocak, kaynak, mum gibi bilinen alev ya da buhar kaynaklarını kırmızı alanın içine al (en çok {MAX_ZONES} bölge). Köşeleri
          sürükle; kenardaki + ile köşe ekle, köşeye çift tıklayınca silinir.
        </p>
      </div>
      <FireWarning />
    </div>
  );
}
