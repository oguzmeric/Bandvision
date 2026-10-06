import type { LabColor } from "./live";

export const MAX_STAFF_COLORS = 3;

/** Lab (D65) → ekranda gösterilecek sRGB (#rrggbb); Python/Swift çevirisinin tersi */
export function labToCss(c: LabColor): string {
  const fy = (c.L + 16) / 116, fx = fy + c.a / 500, fz = fy - c.b / 200;
  const inv = (t: number) => (t ** 3 > 0.008856 ? t ** 3 : (t - 16 / 116) / 7.787);
  const X = 0.95047 * inv(fx), Y = inv(fy), Z = 1.08883 * inv(fz);
  const lin = [
    3.2404542 * X - 1.5371385 * Y - 0.4985314 * Z,
    -0.969266 * X + 1.8760108 * Y + 0.041556 * Z,
    0.0556434 * X - 0.2040259 * Y + 1.0572252 * Z,
  ];
  const hex = lin.map((v) => {
    const s = v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055;
    return Math.round(Math.min(1, Math.max(0, s)) * 255).toString(16).padStart(2, "0");
  });
  return `#${hex.join("")}`;
}

/** Siyah, beyaz, gri (akromatik) ya da lacivert gibi koyu renkler müşterilerde de sık görülür (Python is_achromatic ile aynı) */
export const isAchromatic = (c: LabColor) => Math.hypot(c.a, c.b) < 15 || c.L < 30;
