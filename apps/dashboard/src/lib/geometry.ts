/**
 * İlgi alanı ve sayım çizgisi geometrisi — telefondaki `ProductProfile` (setPolygon, setCountLine,
 * straightCountLine) ve Python `Profile.set_polygon`, `lineframe.nearest_direction` ile aynı kurallar.
 * Tüm koordinatlar normalize (0–1), görüntü sol üst köşesi başlangıç.
 */
import type { Direction, Point } from "./types";

export type Rect = { x: number; y: number; width: number; height: number };
export type Line = { a: Point; b: Point };

export interface Geometry {
  roi: Rect;
  roiPolygon: Point[] | null;
  countLine: Line | null;
  linePosition: number;
  direction: Direction;
}

export const MAX_POLYGON_POINTS = 12;

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), Math.max(lo, hi));
const clampPoint = (p: Point): Point => ({ x: clamp(p.x, 0, 1), y: clamp(p.y, 0, 1) });

export const isVertical = (d: Direction) => d === "down" || d === "up";

export const DEFAULT_GEOMETRY: Geometry = {
  roi: { x: 0.05, y: 0.1, width: 0.9, height: 0.8 },
  roiPolygon: null,
  countLine: null,
  linePosition: 0.5,
  direction: "down",
};

/** Çizgi akış ekseninde alanın içinde kalsın (kenarlardan 0,02 içeride) */
export function clampLine(g: Geometry): Geometry {
  const lo = isVertical(g.direction) ? g.roi.y : g.roi.x;
  const hi = lo + (isVertical(g.direction) ? g.roi.height : g.roi.width);
  return { ...g, linePosition: clamp(g.linePosition, lo + 0.02, hi - 0.02) };
}

/** Çokgeni ayarlar: köşeler kırpılır, alan çokgenin sınır kutusu olur, çizgi kutunun içine çekilir. null → dikdörtgen. */
export function setPolygon(g: Geometry, points: Point[] | null): Geometry {
  if (!points || points.length < 3) return { ...g, roiPolygon: null };
  const pts = points.slice(0, MAX_POLYGON_POINTS).map(clampPoint);
  const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
  const minX = Math.min(...xs), minY = Math.min(...ys);
  const roi = { x: minX, y: minY, width: Math.max(Math.max(...xs) - minX, 0.01), height: Math.max(Math.max(...ys) - minY, 0.01) };
  return clampLine({ ...g, roiPolygon: pts, roi });
}

export function roiCorners(r: Rect): Point[] {
  return [{ x: r.x, y: r.y }, { x: r.x + r.width, y: r.y }, { x: r.x + r.width, y: r.y + r.height }, { x: r.x, y: r.y + r.height }];
}

/** Açılı çizginin akışına (a→b'nin sağ eli) en yakın eksen yönü; `aspect` = genişlik / yükseklik */
export function nearestDirection(a: Point, b: Point, aspect: number): Direction {
  const dx = (b.x - a.x) * aspect, dy = b.y - a.y;
  const fx = -dy, fy = dx;
  if (Math.abs(fy) >= Math.abs(fx)) return fy > 0 ? "down" : "up";
  return fx > 0 ? "right" : "left";
}

/** Açılı çizgiyi ayarlar; yön akışa en yakın eksene güncellenir. null → düz çizgiye dön (ortası linePosition olur). */
export function setCountLine(g: Geometry, line: Line | null, aspect: number): Geometry {
  if (!line) {
    if (!g.countLine) return g;
    const old = g.countLine;
    const mid = isVertical(g.direction) ? (old.a.y + old.b.y) / 2 : (old.a.x + old.b.x) / 2;
    return clampLine({ ...g, countLine: null, linePosition: mid });
  }
  const cl = { a: clampPoint(line.a), b: clampPoint(line.b) };
  return { ...g, countLine: cl, direction: nearestDirection(cl.a, cl.b, aspect) };
}

/** Düz çizgiden açılıya geçerken başlangıç: aynı çizgi, aynı akış (sağ el kuralı) */
export function straightCountLine(g: Geometry): Line {
  const p = g.linePosition, r = g.roi;
  switch (g.direction) {
    case "down": return { a: { x: r.x, y: p }, b: { x: r.x + r.width, y: p } };
    case "up": return { a: { x: r.x + r.width, y: p }, b: { x: r.x, y: p } };
    case "right": return { a: { x: p, y: r.y + r.height }, b: { x: p, y: r.y } };
    case "left": return { a: { x: p, y: r.y }, b: { x: p, y: r.y + r.height } };
  }
}

export const OPPOSITE: Record<Direction, Direction> = { down: "up", up: "down", right: "left", left: "right" };

/** Akış/giriş yönünü tersine çevirir (açılı çizgide uçlar yer değiştirir) */
export function flip(g: Geometry, aspect: number): Geometry {
  if (g.countLine) return setCountLine(g, { a: g.countLine.b, b: g.countLine.a }, aspect);
  return clampLine({ ...g, direction: OPPOSITE[g.direction] });
}

/** Ekranda çizilecek çizgi uçları (düz çizgide alan genişliğince; çokgende çokgenin içindeki parça) */
export function lineEndpoints(g: Geometry): Line {
  if (g.countLine) return g.countLine;
  const pos = g.linePosition, vertical = isVertical(g.direction);
  if (g.roiPolygon && g.roiPolygon.length >= 3) {
    const hits: number[] = [];
    const poly = g.roiPolygon;
    for (let k = 0; k < poly.length; k++) {
      const a = poly[k], b = poly[(k + 1) % poly.length];
      const [ua, ub] = vertical ? [a.y, b.y] : [a.x, b.x];
      const [va, vb] = vertical ? [a.x, b.x] : [a.y, b.y];
      if (ua === ub || !((ua <= pos && pos <= ub) || (ub <= pos && pos <= ua))) continue;
      hits.push(va + ((vb - va) * (pos - ua)) / (ub - ua));
    }
    if (hits.length >= 2) {
      const lo = Math.min(...hits), hi = Math.max(...hits);
      if (hi - lo > 1e-6) return vertical ? { a: { x: lo, y: pos }, b: { x: hi, y: pos } } : { a: { x: pos, y: lo }, b: { x: pos, y: hi } };
    }
  }
  const r = g.roi;
  return vertical
    ? { a: { x: r.x, y: pos }, b: { x: r.x + r.width, y: pos } }
    : { a: { x: pos, y: r.y }, b: { x: pos, y: r.y + r.height } };
}

/** Profil sözlüğünden geometri (sözleşme alanları) */
export function geometryOf(p: { roi: Rect; roiPolygon?: Point[] | null; countLine?: Line | null; linePosition: number; direction: Direction }): Geometry {
  return {
    roi: { ...p.roi },
    roiPolygon: p.roiPolygon && p.roiPolygon.length >= 3 ? p.roiPolygon.map((q) => ({ ...q })) : null,
    countLine: p.countLine ? { a: { ...p.countLine.a }, b: { ...p.countLine.b } } : null,
    linePosition: p.linePosition,
    direction: p.direction,
  };
}

/** Geometriyi profil sözlüğüne yazar (çokgen/çizgi yoksa alan silinir) */
export function withGeometry<T extends Record<string, unknown>>(p: T, g: Geometry): T {
  const out: Record<string, unknown> = { ...p, roi: g.roi, linePosition: g.linePosition, direction: g.direction };
  if (g.roiPolygon) out.roiPolygon = g.roiPolygon; else delete out.roiPolygon;
  if (g.countLine) out.countLine = g.countLine; else delete out.countLine;
  return out as T;
}
