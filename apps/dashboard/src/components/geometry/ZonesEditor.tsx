"use client";

import { useEffect, useRef, useState } from "react";
import {
  deleteVertex, insertVertex, insideZone, MAX_ZONE_POINTS, moveVertex, translateZone, type Zone,
} from "@/lib/fireAlarms.mjs";

type Handle = { kind: "vertex"; z: number; i: number } | { kind: "midpoint"; z: number; i: number } | { kind: "zone"; z: number };
type Pt = [number, number];

const RED = "#ef4444";

/**
 * Görüntü üstünde çoklu çokgen düzenleyici (yangın/duman "Hariç bölgeler"): RoiEditor'ın çokgen tutamaçlarıyla aynı —
 * köşeyi sürükle, kenar ortasındaki "+" ile köşe ekle, köşeye çift tıklayınca sil (en az 3), bölgenin içinden tutup taşı.
 * Bölge ekleme/silme yan paneldedir (FireSettings). Köşeler normalize `[x, y]`; sınırlar src/lib/fireAlarms.mjs'de.
 */
export default function ZonesEditor({ src, aspect, zones, onChange, editable = true }: {
  src: string | null;
  /** görüntü genişliği / yüksekliği */
  aspect: number;
  zones: Zone[];
  onChange: (zones: Zone[]) => void;
  editable?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [widthPx, setWidthPx] = useState(600);
  const drag = useRef<{ h: Handle; start: Pt; z0: Zone[] } | null>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidthPx(el.clientWidth || 600));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const W = 1000, H = 1000 / aspect;
  const u = W / Math.max(1, widthPx);                 // 1 ekran pikseli = u birim
  const P = (p: Pt) => ({ x: p[0] * W, y: p[1] * H });
  const path = (z: Zone) => "M" + z.map((q) => `${q[0] * W},${q[1] * H}`).join(" L") + " Z";

  function handles(): Array<[Handle, { x: number; y: number }]> {
    const out: Array<[Handle, { x: number; y: number }]> = [];
    zones.forEach((z, zi) => z.forEach((q, i) => out.push([{ kind: "vertex", z: zi, i }, P(q)])));
    return out;
  }

  function midpoints(): Array<[Handle, { x: number; y: number }]> {
    const out: Array<[Handle, { x: number; y: number }]> = [];
    zones.forEach((z, zi) => {
      if (z.length >= MAX_ZONE_POINTS) return;
      z.forEach((a, i) => {
        const b = z[(i + 1) % z.length];
        out.push([{ kind: "midpoint", z: zi, i }, P([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2])]);
      });
    });
    return out;
  }

  function norm(e: { clientX: number; clientY: number }): Pt {
    const rect = box.current!.getBoundingClientRect();
    return [Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)), Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height))];
  }

  function pick(p: Pt): Handle | null {
    const pt = P(p);
    let best: [Handle, number] | null = null;
    for (const [h, q] of [...handles(), ...midpoints()]) {
      const d = Math.hypot(q.x - pt.x, q.y - pt.y) / u;
      if (d < 22 && (!best || d < best[1])) best = [h, d];
    }
    if (best) return best[0];
    for (let z = zones.length - 1; z >= 0; z--) if (insideZone(zones[z], p)) return { kind: "zone", z };   // üstteki önce
    return null;
  }

  function apply(h: Handle, p: Pt, start: Pt, z0: Zone[]) {
    if (h.kind === "vertex") onChange(moveVertex(z0, h.z, h.i, p));
    else if (h.kind === "midpoint") {
      const next = insertVertex(z0, h.z, h.i, p);
      drag.current = { h: { kind: "vertex", z: h.z, i: h.i + 1 }, start, z0: next };   // sürükleme yeni köşeyle sürer
      onChange(next);
    } else onChange(translateZone(z0, h.z, p[0] - start[0], p[1] - start[1]));
  }

  function onPointerDown(e: React.PointerEvent) {
    if (!editable) return;
    const p = norm(e);
    const h = pick(p);
    if (!h) return;
    e.preventDefault();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    drag.current = { h, start: p, z0: zones };
    if (h.kind === "midpoint") apply(h, p, p, zones);
  }

  function onPointerMove(e: React.PointerEvent) {
    const d = drag.current;
    if (d) apply(d.h, norm(e), d.start, d.z0);
  }

  function onDoubleClick(e: React.MouseEvent) {
    if (!editable) return;
    const pt = P(norm(e));
    for (let z = 0; z < zones.length; z++) {
      const i = zones[z].findIndex((q) => Math.hypot(q[0] * W - pt.x, q[1] * H - pt.y) / u < 22);
      if (i >= 0) { onChange(deleteVertex(zones, z, i)); return; }
    }
  }

  return (
    <div ref={box} className="relative w-full select-none overflow-hidden rounded-[2px] bg-[#111]"
         style={{ aspectRatio: String(aspect) }} data-testid="zones-editor">
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element -- canlı kare, Next görüntü iyileştirmesi uygun değil
        <img src={src} alt="" className="absolute inset-0 h-full w-full" draggable={false} />
      ) : (
        <div className="absolute inset-0 grid place-items-center text-sm text-white/60">Görüntü bekleniyor…</div>
      )}
      <svg viewBox={`0 0 ${W} ${H}`} className={`absolute inset-0 h-full w-full ${editable ? "cursor-crosshair touch-none" : "pointer-events-none"}`}
           onPointerDown={onPointerDown} onPointerMove={onPointerMove}
           onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}
           onDoubleClick={onDoubleClick}
           role="img" aria-label={zones.length ? `Hariç bölgeler: ${zones.length}` : "Hariç bölge yok"}>
        {zones.map((z, zi) => {
          const c = P(z.reduce<Pt>((s, q) => [s[0] + q[0] / z.length, s[1] + q[1] / z.length], [0, 0]));
          return (
            <g key={zi} data-zone={zi}>
              <path d={path(z)} fill={RED} fillOpacity={0.22} stroke={RED} strokeWidth={2.5} strokeDasharray="8 5" vectorEffect="non-scaling-stroke" />
              <g transform={`translate(${c.x},${c.y}) scale(${u})`}>
                <rect x={-34} y={-10} width={68} height={20} rx={3} fill={RED} />
                <text x={0} y={4.5} textAnchor="middle" fontSize={11.5} fontWeight={800} fill="white">HARİÇ {zi + 1}</text>
              </g>
            </g>
          );
        })}
        {editable && (
          <>
            {midpoints().map(([h, q]) => (
              <g key={`m${(h as { z: number }).z}-${(h as { i: number }).i}`} transform={`translate(${q.x},${q.y}) scale(${u})`}>
                <circle r={7} fill={RED} fillOpacity={0.85} />
                <text y={4} textAnchor="middle" fontSize={12} fontWeight={800} fill="white">+</text>
              </g>
            ))}
            {handles().map(([h, q]) => (
              <circle key={`h${(h as { z: number }).z}-${(h as { i: number }).i}`} cx={q.x} cy={q.y} r={9 * u} fill="white" stroke="#111"
                      strokeWidth={2} vectorEffect="non-scaling-stroke" data-handle="vertex" />
            ))}
          </>
        )}
      </svg>
    </div>
  );
}
