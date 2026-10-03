const nf = new Intl.NumberFormat("tr-TR");

export const num = (n: number, digits = 0) =>
  new Intl.NumberFormat("tr-TR", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(n);

export const int = (n: number) => nf.format(Math.round(n));

export function duration(seconds?: number): string {
  if (seconds === undefined) return "—";
  const s = Math.round(seconds);
  return s < 60 ? `${s} sn` : `${Math.floor(s / 60)} dk ${s % 60} sn`;
}

export function bytes(n: number): string {
  if (n < 1024 * 1024) return `${num(n / 1024)} KB`;
  if (n < 1024 * 1024 * 1024) return `${num(n / 1024 / 1024, 1)} MB`;
  return `${num(n / 1024 / 1024 / 1024, 2)} GB`;
}

export function when(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const time = d.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return `Bugün ${time}`;
  const y = new Date(today);
  y.setDate(today.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return `Dün ${time}`;
  return `${d.toLocaleDateString("tr-TR", { day: "numeric", month: "short" })} ${time}`;
}

/** Hata yüzdesi: +2,1% / −0,5% / ±0 */
export function signedPct(p: number): string {
  if (Math.abs(p) < 0.005) return "±0";
  return `${p > 0 ? "+" : "−"}${num(Math.abs(p), 1)}%`;
}
