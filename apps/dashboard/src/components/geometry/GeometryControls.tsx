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
         className="grid auto-cols-fr grid-flow-col rounded-[10px] border border-line bg-canvas p-0.5 text-[13px]">
      {options.map(([v, text]) => (
        <button key={String(v)} type="button" role="radio" aria-checked={v === value} onClick={() => onChange(v)}
                className={`h-8 rounded-[8px] px-2 font-medium transition ${v === value ? "bg-white text-ink shadow-sm" : "text-muted hover:text-ink"}`}>
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
    <div className={`grid gap-3 ${compact ? "" : "text-sm"}`}>
      <div>
        <p className="mb-1.5 text-xs font-medium text-muted">Alan</p>
        <div className="flex items-center gap-2">
          <div className="flex-1">
            <Segmented label="Alan biçimi" testId="roi-shape" value={g.roiPolygon !== null}
                       options={[[false, "Dikdörtgen"], [true, "Çokgen"]]}
                       onChange={(poly) => onChange(setPolygon(g, poly ? roiCorners(g.roi) : null))} />
          </div>
          {g.roiPolygon && (
            <button type="button" className="text-xs font-medium text-brand-500 hover:underline"
                    onClick={() => onChange(setPolygon(g, roiCorners(g.roi)))}>Köşeleri sıfırla</button>
          )}
        </div>
        <p className="mt-1 text-[11.5px] text-faint">
          {g.roiPolygon
            ? "Köşeleri sürükle · sarı + ile köşe ekle (en çok 12) · köşeye çift tıkla: sil · içinden tutup taşı"
            : "Köşelerden sürükleyerek boyutlandır · içinden tutup taşı"}
        </p>
      </div>
      <div>
        <p className="mb-1.5 text-xs font-medium text-muted">Sayım çizgisi</p>
        {allowAngled ? (
          <Segmented label="Sayım çizgisi" testId="line-mode" value={g.countLine !== null}
                     options={[[false, "Düz çizgi"], [true, "Açılı çizgi"]]}
                     onChange={(angled) => onChange(fitCountLine(setCountLine(g, angled ? straightCountLine(g) : null, aspect)))} />
        ) : (
          <p className="text-[12px] text-faint">Bu yöntemde düz çizgi kullanılır.</p>
        )}
        <p className="mt-1 text-[11.5px] text-faint">
          {g.countLine ? "Uçlarını sürükle · ortasından tutup taşı · ok yönü gösterir" : "Turuncu çizgiyi ortasındaki tutamaçla kaydır"}
        </p>
      </div>
      <div>
        <p className="mb-1.5 text-xs font-medium text-muted">{twoWay ? "Giriş yönü" : "Akış yönü"}</p>
        <div className="flex items-center gap-2">
          {!g.countLine ? (
            <select aria-label={twoWay ? "Giriş yönü" : "Akış yönü"} value={g.direction}
                    onChange={(e) => onChange(clampLine({ ...g, direction: e.target.value as Direction }))}
                    className="h-9 flex-1 rounded-[10px] border border-line bg-white px-2.5 text-[13px] outline-none focus:border-brand-500">
              {(Object.keys(DIRECTION_LABELS) as Direction[]).map((d) => (
                <option key={d} value={d}>{ARROW[d]} {DIRECTION_LABELS[d]}</option>
              ))}
            </select>
          ) : (
            <span className="flex-1 text-[13px] text-muted">Çizgideki ok yönünde</span>
          )}
          <button type="button" onClick={() => onChange(flip(g, aspect))} data-testid="flip-direction"
                  className="h-9 rounded-[10px] border border-line bg-white px-3 text-[13px] font-medium hover:border-brand-100">
            ⇅ {twoWay ? "Girişi çevir" : "Yönü çevir"}
          </button>
        </div>
      </div>
    </div>
  );
}
