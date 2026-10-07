"use client";

import { useEffect, useRef, useState } from "react";
import {
  isVertical, lineEndpoints, MAX_POLYGON_POINTS, setCountLine, setPolygon, clampLine, fitCountLine,
  type Geometry, type Line,
} from "@/lib/geometry";
import type { Point } from "@/lib/types";

type Handle =
  | { kind: "corner"; i: 0 | 1 | 2 | 3 }
  | { kind: "vertex"; i: number }
  | { kind: "midpoint"; i: number }
  | { kind: "line" }
  | { kind: "lineA" }
  | { kind: "lineB" }
  | { kind: "lineMid" }
  | { kind: "area" };

const YELLOW = "#facc15", ORANGE = "#f97316";

/**
 * Görüntü üstünde ilgi alanı ve sayım çizgisi düzenleyici (telefondaki OverlayView ile aynı tutamaçlar):
 * dikdörtgen köşeleri; çokgende köşeler, kenar ortasındaki "+" ile köşe ekleme, köşeye çift tıklayınca silme;
 * düz çizgi ortasından akış ekseninde; açılı çizgi uçlarından ve ortasından. Alanın içinden tutup alan taşınır.
 */
export default function RoiEditor({ src, aspect, value, onChange, twoWay = false, showLine = true, editable = true, children }: {
  src: string | null;
  /** görüntü genişliği / yüksekliği */
  aspect: number;
  value: Geometry;
  onChange: (g: Geometry) => void;
  twoWay?: boolean;
  /** false: sayım çizgisi, oku ve tutamaçları çizilmez (yalnızca alan; ör. güvenlik) */
  showLine?: boolean;
  editable?: boolean;
  children?: React.ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [widthPx, setWidthPx] = useState(600);
  const drag = useRef<{ h: Handle; start: Point; g0: Geometry } | null>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidthPx(el.clientWidth || 600));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const W = 1000, H = 1000 / aspect;
  const u = W / Math.max(1, widthPx);                 // 1 ekran pikseli = u birim
  const P = (p: Point) => ({ x: p.x * W, y: p.y * H });
  const g = value;
  const line = lineEndpoints(g);
  const la = P(line.a), lb = P(line.b);
  const mid = { x: (la.x + lb.x) / 2, y: (la.y + lb.y) / 2 };

  // akış/giriş oku: a→b'nin sağ eli (düz çizgide yöne göre uçlar sıralanır)
  const [ea, eb] = !g.countLine && (g.direction === "up" || g.direction === "right") ? [lb, la] : [la, lb];
  const len = Math.max(1e-6, Math.hypot(eb.x - ea.x, eb.y - ea.y));
  const n = { x: -(eb.y - ea.y) / len, y: (eb.x - ea.x) / len };
  const tip = { x: mid.x + n.x * 46 * u, y: mid.y + n.y * 46 * u };
  const side = { x: -n.y * 8 * u, y: n.x * 8 * u };
  const back = { x: tip.x - n.x * 13 * u, y: tip.y - n.y * 13 * u };

  const areaPath = g.roiPolygon
    ? "M" + g.roiPolygon.map((q) => `${q.x * W},${q.y * H}`).join(" L") + " Z"
    : `M${g.roi.x * W},${g.roi.y * H} h${g.roi.width * W} v${g.roi.height * H} h${-g.roi.width * W} Z`;

  function handles(): Array<[Handle, Point]> {
    const out: Array<[Handle, Point]> = [];
    if (g.roiPolygon) g.roiPolygon.forEach((q, i) => out.push([{ kind: "vertex", i }, P(q)]));
    else {
      const r = g.roi;
      out.push([{ kind: "corner", i: 0 }, P({ x: r.x, y: r.y })], [{ kind: "corner", i: 1 }, P({ x: r.x + r.width, y: r.y })],
               [{ kind: "corner", i: 2 }, P({ x: r.x + r.width, y: r.y + r.height })], [{ kind: "corner", i: 3 }, P({ x: r.x, y: r.y + r.height })]);
    }
    if (g.countLine) out.push([{ kind: "lineA" }, la], [{ kind: "lineB" }, lb], [{ kind: "lineMid" }, mid]);
    else out.push([{ kind: "line" }, mid]);
    return showLine ? out : out.filter(([h]) => !h.kind.startsWith("line"));
  }

  function midpoints(): Array<[Handle, Point]> {
    if (!g.roiPolygon || g.roiPolygon.length >= MAX_POLYGON_POINTS) return [];
    const poly = g.roiPolygon;
    return poly.map((a, i) => {
      const b = poly[(i + 1) % poly.length];
      return [{ kind: "midpoint", i }, P({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 })];
    });
  }

  function norm(e: React.PointerEvent): Point {
    const rect = box.current!.getBoundingClientRect();
    return { x: Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)),
             y: Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height)) };
  }

  function insideArea(p: Point): boolean {
    if (!g.roiPolygon) return p.x >= g.roi.x && p.x <= g.roi.x + g.roi.width && p.y >= g.roi.y && p.y <= g.roi.y + g.roi.height;
    let inside = false;
    const poly = g.roiPolygon;
    for (let k = 0, j = poly.length - 1; k < poly.length; j = k++) {
      const a = poly[k], b = poly[j];
      if ((a.y > p.y) !== (b.y > p.y) && p.x < ((b.x - a.x) * (p.y - a.y)) / (b.y - a.y) + a.x) inside = !inside;
    }
    return inside;
  }

  function pick(p: Point): Handle | null {
    const pt = P(p);
    const cand = [...handles(), ...midpoints()];
    let best: [Handle, number] | null = null;
    for (const [h, q] of cand) {
      const d = Math.hypot(q.x - pt.x, q.y - pt.y) / u;
      if (d < 26 && (!best || d < best[1])) best = [h, d];
    }
    if (best) return best[0];
    // çizginin herhangi bir yerinden
    const ab = { x: lb.x - la.x, y: lb.y - la.y };
    const l2 = ab.x * ab.x + ab.y * ab.y || 1;
    const t = Math.max(0, Math.min(1, ((pt.x - la.x) * ab.x + (pt.y - la.y) * ab.y) / l2));
    const dl = Math.hypot(pt.x - (la.x + ab.x * t), pt.y - (la.y + ab.y * t)) / u;
    if (showLine && dl < 16) return g.countLine ? { kind: "lineMid" } : { kind: "line" };
    return insideArea(p) ? { kind: "area" } : null;
  }

  function apply(h: Handle, p: Point, start: Point, g0: Geometry) {
    const dx = p.x - start.x, dy = p.y - start.y;
    switch (h.kind) {
      case "corner": {
        const r = g0.roi;
        let x0 = r.x, y0 = r.y, x1 = r.x + r.width, y1 = r.y + r.height;
        if (h.i === 0 || h.i === 3) x0 = Math.min(p.x, x1 - 0.05); else x1 = Math.max(p.x, x0 + 0.05);
        if (h.i === 0 || h.i === 1) y0 = Math.min(p.y, y1 - 0.05); else y1 = Math.max(p.y, y0 + 0.05);
        onChange(fitCountLine(clampLine({ ...g0, roi: { x: x0, y: y0, width: x1 - x0, height: y1 - y0 } })));
        return;
      }
      case "vertex": {
        const poly = g0.roiPolygon!.map((q, i) => (i === h.i ? p : q));
        onChange(setPolygon(g0, poly));
        return;
      }
      case "midpoint": {
        const poly = [...g0.roiPolygon!];
        poly.splice(h.i + 1, 0, p);
        const next = setPolygon(g0, poly);
        drag.current = { h: { kind: "vertex", i: h.i + 1 }, start, g0: next };   // sürükleme yeni köşeyle sürer
        onChange(next);
        return;
      }
      case "line": {
        const pos = isVertical(g0.direction) ? p.y : p.x;
        onChange(clampLine({ ...g0, linePosition: pos }));
        return;
      }
      case "lineA":
      case "lineB": {
        const cl = { ...g0.countLine! } as Line;
        if (h.kind === "lineA") cl.a = p; else cl.b = p;
        if (Math.hypot((cl.b.x - cl.a.x) * aspect, cl.b.y - cl.a.y) <= 0.05) return;   // uçlar üst üste binmesin
        onChange(setCountLine(g0, cl, aspect));
        return;
      }
      case "lineMid": {
        const s = g0.countLine!;
        const ddx = Math.min(Math.max(dx, -Math.min(s.a.x, s.b.x)), 1 - Math.max(s.a.x, s.b.x));
        const ddy = Math.min(Math.max(dy, -Math.min(s.a.y, s.b.y)), 1 - Math.max(s.a.y, s.b.y));
        onChange(setCountLine(g0, { a: { x: s.a.x + ddx, y: s.a.y + ddy }, b: { x: s.b.x + ddx, y: s.b.y + ddy } }, aspect));
        return;
      }
      case "area": {
        if (g0.roiPolygon) {
          const xs = g0.roiPolygon.map((q) => q.x), ys = g0.roiPolygon.map((q) => q.y);
          const mx = Math.min(Math.max(dx, -Math.min(...xs)), 1 - Math.max(...xs));
          const my = Math.min(Math.max(dy, -Math.min(...ys)), 1 - Math.max(...ys));
          let next = setPolygon(g0, g0.roiPolygon.map((q) => ({ x: q.x + mx, y: q.y + my })));
          next = { ...next, linePosition: g0.linePosition + (isVertical(g0.direction) ? my : mx) };
          if (g0.countLine) next = setCountLine(next, { a: { x: g0.countLine.a.x + mx, y: g0.countLine.a.y + my }, b: { x: g0.countLine.b.x + mx, y: g0.countLine.b.y + my } }, aspect);
          onChange(fitCountLine(clampLine(next)));
        } else {
          const r = g0.roi;
          const mx = Math.min(Math.max(dx, -r.x), 1 - r.x - r.width);
          const my = Math.min(Math.max(dy, -r.y), 1 - r.y - r.height);
          let next: Geometry = { ...g0, roi: { ...r, x: r.x + mx, y: r.y + my },
                                 linePosition: g0.linePosition + (isVertical(g0.direction) ? my : mx) };
          if (g0.countLine) next = setCountLine(next, { a: { x: g0.countLine.a.x + mx, y: g0.countLine.a.y + my }, b: { x: g0.countLine.b.x + mx, y: g0.countLine.b.y + my } }, aspect);
          onChange(fitCountLine(clampLine(next)));
        }
        return;
      }
    }
  }

  function onPointerDown(e: React.PointerEvent) {
    if (!editable) return;
    const p = norm(e);
    const h = pick(p);
    if (!h) return;
    e.preventDefault();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    drag.current = { h, start: p, g0: g };
    if (h.kind === "midpoint") apply(h, p, p, g);
  }

  function onPointerMove(e: React.PointerEvent) {
    const d = drag.current;
    if (!d) return;
    apply(d.h, norm(e), d.start, d.g0);
  }

  /** Çizgi sürüklemesi bitince açılı çizgi alanın kenarından kenarına (sürüklerken uç parmağın altından kaçmasın) */
  function endDrag() {
    const d = drag.current;
    drag.current = null;
    if (d && (d.h.kind === "lineA" || d.h.kind === "lineB" || d.h.kind === "lineMid")) onChange(fitCountLine(value));
  }

  function onDoubleClick(e: React.MouseEvent) {
    if (!editable || !g.roiPolygon || g.roiPolygon.length <= 3) return;
    const rect = box.current!.getBoundingClientRect();
    const pt = P({ x: (e.clientX - rect.left) / rect.width, y: (e.clientY - rect.top) / rect.height });
    const i = g.roiPolygon.findIndex((q) => Math.hypot(q.x * W - pt.x, q.y * H - pt.y) / u < 22);
    if (i >= 0) onChange(setPolygon(g, g.roiPolygon.filter((_, k) => k !== i)));
  }

  return (
    <div ref={box} className="relative w-full select-none overflow-hidden rounded-2xl bg-[#111]"
         style={{ aspectRatio: String(aspect) }} data-testid="roi-editor">
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element -- canlı akış/kare, Next görüntü iyileştirmesi uygun değil
        <img src={src} alt="" className="absolute inset-0 h-full w-full" draggable={false} />
      ) : (
        <div className="absolute inset-0 grid place-items-center text-sm text-white/60">Görüntü bekleniyor…</div>
      )}
      <svg viewBox={`0 0 ${W} ${H}`} className={`absolute inset-0 h-full w-full ${editable ? "cursor-crosshair touch-none" : "pointer-events-none"}`}
           onPointerDown={onPointerDown} onPointerMove={onPointerMove}
           onPointerUp={endDrag} onPointerCancel={endDrag}
           onDoubleClick={onDoubleClick}
           role="img" aria-label={`İlgi alanı: ${g.roiPolygon ? `${g.roiPolygon.length} köşeli çokgen` : "dikdörtgen"}${showLine ? `; sayım çizgisi ${g.countLine ? "açılı" : "düz"}` : ""}`}>
        <path d={`M0,0 H${W} V${H} H0 Z ${areaPath}`} fill="black" fillOpacity={0.38} fillRule="evenodd" />
        <path d={areaPath} fill="none" stroke={YELLOW} strokeWidth={2.5} vectorEffect="non-scaling-stroke" />
        {showLine && (
          <>
            <line x1={la.x} y1={la.y} x2={lb.x} y2={lb.y} stroke={ORANGE} strokeWidth={4} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
            <path d={`M${mid.x + n.x * 12 * u},${mid.y + n.y * 12 * u} L${tip.x},${tip.y} M${back.x + side.x},${back.y + side.y} L${tip.x},${tip.y} L${back.x - side.x},${back.y - side.y}`}
                  fill="none" stroke={ORANGE} strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
            {twoWay && (
              <g transform={`translate(${tip.x + n.x * 22 * u},${tip.y + n.y * 22 * u}) scale(${u})`}>
                <rect x={-26} y={-10} width={52} height={20} rx={10} fill={ORANGE} />
                <text x={0} y={4.5} textAnchor="middle" fontSize={11.5} fontWeight={800} fill="#111">GİRİŞ</text>
              </g>
            )}
          </>
        )}
        {editable && (
          <>
            {midpoints().map(([h, q]) => (
              <g key={`m${(h as { i: number }).i}`} transform={`translate(${q.x},${q.y}) scale(${u})`}>
                <circle r={8} fill={YELLOW} fillOpacity={0.8} />
                <text y={4} textAnchor="middle" fontSize={12} fontWeight={800} fill="#111">+</text>
              </g>
            ))}
            {handles().map(([h, q], k) => (
              <circle key={`h${k}`} cx={q.x} cy={q.y} r={10 * u} fill="white" stroke="#111" strokeWidth={2} vectorEffect="non-scaling-stroke"
                      data-handle={h.kind} />
            ))}
          </>
        )}
      </svg>
      {children}
    </div>
  );
}
