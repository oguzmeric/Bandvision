"use client";

import { DIRECTION_LABELS, type Direction } from "@/lib/types";
import {
  flip, fitCountLine, roiCorners, setCountLine, setPolygon, straightCountLine, clampLine, type Geometry,
} from "@/lib/geometry";

const ARROW: Record<Direction, string> = { down: "↓", up: "↑", right: "→", left: "←" };

function Segmented<T extends string | boolean>({ label, value, options, onChange, testId }: {
  label: string; value: T; options: Array<[T, string]>; onChange: (v: T) => void; testId?: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} data-testid={testId}
         className="grid auto-cols-fr grid-flow-col overflow-hidden rounded-[2px] border border-pl-ctl text-[13px]">
      {options.map(([v, text]) => (
        <button key={String(v)} type="button" role="radio" aria-checked={v === value} onClick={() => onChange(v)}
                className={`h-7 border-r border-pl-ctl px-2 last:border-r-0 ${v === value ? "bg-pl-sel font-semibold text-pl-ink" : "bg-[#f7f8fa] text-pl-muted hover:bg-pl-head hover:text-pl-ink"}`}>
          {text}
        </button>
      ))}
    </div>
  );
}

/** Alan biçimi, çizgi türü, yön / giriş yönü — telefondaki kalibrasyon panelinin karşılığı */
export default function GeometryControls({ value, onChange, aspect, twoWay = false, allowAngled = true, compact = false }: {
  value: Geometry; onChange: (g: Geometry) => void; aspect: number;
  twoWay?: boolean; allowAngled?: boolean; compact?: boolean;
}) {
  const g = value;
  return (
    <div className={`grid gap-3 ${compact ? "" : "text-[13px]"}`}>
      <div>
        <p className="mb-1 text-xs font-medium text-pl-muted">Alan</p>
        <div className="flex items-center gap-2">
          <div className="flex-1">
            <Segmented label="Alan biçimi" testId="roi-shape" value={g.roiPolygon !== null}
                       options={[[false, "Dikdörtgen"], [true, "Çokgen"]]}
                       onChange={(poly) => onChange(setPolygon(g, poly ? roiCorners(g.roi) : null))} />
          </div>
          {g.roiPolygon && (
            <button type="button" className="text-xs font-medium text-pl-accent hover:underline"
                    onClick={() => onChange(setPolygon(g, roiCorners(g.roi)))}>Köşeleri sıfırla</button>
          )}
        </div>
        <p className="mt-1 text-[11.5px] text-pl-faint">
          {g.roiPolygon
            ? "Köşeleri sürükle · sarı + ile köşe ekle (en çok 12) · köşeye çift tıkla: sil · içinden tutup taşı"
            : "Köşelerden sürükleyerek boyutlandır · içinden tutup taşı"}
        </p>
      </div>
      <div>
        <p className="mb-1 text-xs font-medium text-pl-muted">Sayım çizgisi</p>
        {allowAngled ? (
          <Segmented label="Sayım çizgisi" testId="line-mode" value={g.countLine !== null}
                     options={[[false, "Düz çizgi"], [true, "Açılı çizgi"]]}
                     onChange={(angled) => onChange(fitCountLine(setCountLine(g, angled ? straightCountLine(g) : null, aspect)))} />
        ) : (
          <p className="text-[12px] text-pl-faint">Bu yöntemde düz çizgi kullanılır.</p>
        )}
        <p className="mt-1 text-[11.5px] text-pl-faint">
          {g.countLine ? "Uçlarını sürükle · ortasından tutup taşı · ok yönü gösterir" : "Turuncu çizgiyi ortasındaki tutamaçla kaydır"}
        </p>
      </div>
      <div>
        <p className="mb-1 text-xs font-medium text-pl-muted">{twoWay ? "Giriş yönü" : "Akış yönü"}</p>
        <div className="flex items-center gap-2">
          {!g.countLine ? (
            <select aria-label={twoWay ? "Giriş yönü" : "Akış yönü"} value={g.direction}
                    onChange={(e) => onChange(clampLine({ ...g, direction: e.target.value as Direction }))}
                    className="pl-input h-8 flex-1">
              {(Object.keys(DIRECTION_LABELS) as Direction[]).map((d) => (
                <option key={d} value={d}>{ARROW[d]} {DIRECTION_LABELS[d]}</option>
              ))}
            </select>
          ) : (
            <span className="flex-1 text-[13px] text-pl-muted">Çizgideki ok yönünde</span>
          )}
          <button type="button" onClick={() => onChange(flip(g, aspect))} data-testid="flip-direction"
                  className="pl-btn h-8">
            ⇅ {twoWay ? "Girişi çevir" : "Yönü çevir"}
          </button>
        </div>
      </div>
    </div>
  );
}
