// Kayıttan izleme: zaman, takvim, çizelge ve dışa aktarma hesapları (saf mantık; DOM'a dokunmaz, birim testli).
// API zamanları epoch saniyedir (UTC); gösterim ve gün sınırı bu tarayıcının yerel saatindedir.

/** Dışa aktarmanın en uzun süresi (sunucu `MAX_EXPORT_S` ile aynı) */
export const MAX_EXPORT_S = 1800;
/** Oynatıcı yoklama aralığı (ms) */
export const POLL_MS = 1000;

export const MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"];
/** Haftanın günleri, pazartesiden başlayarak */
export const WEEKDAYS = ["Pt", "Sa", "Ça", "Pe", "Cu", "Ct", "Pz"];

const pad = (n, w = 2) => String(n).padStart(w, "0");
const sec = (date) => date.getTime() / 1000;

/** `at` anının yerel gün başı (00:00:00) */
export function dayStart(at) {
  const d = new Date(at * 1000);
  return sec(new Date(d.getFullYear(), d.getMonth(), d.getDate()));
}

/** Yerel takvim günü (`month` 1–12) → gün başı */
export function dayOf(year, month, day) {
  return sec(new Date(year, month - 1, day));
}

/** Gün başından sonraki gün başı (yaz saati geçişinde gün 23 ya da 25 saattir) */
export function dayEnd(day) {
  const d = new Date(day * 1000);
  return sec(new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1));
}

/** `at` anının yerel yılı, ayı (1–12) ve günü */
export function partsOf(at) {
  const d = new Date(at * 1000);
  return { year: d.getFullYear(), month: d.getMonth() + 1, day: d.getDate() };
}

/** Ay gezgini: `delta` ay ileri/geri */
export function shiftMonth(year, month, delta) {
  const i = year * 12 + (month - 1) + delta;
  return { year: Math.floor(i / 12), month: (i % 12 + 12) % 12 + 1 };
}

/** Ayın gün sayısı */
export function daysInMonth(year, month) {
  return new Date(year, month, 0).getDate();
}

/** Ay tablosu: pazartesiden başlayan haftalar; ay dışındaki hücreler null */
export function monthGrid(year, month) {
  const lead = (new Date(year, month - 1, 1).getDay() + 6) % 7;
  const cells = Array.from({ length: lead }, () => null);
  for (let d = 1; d <= daysInMonth(year, month); d++) cells.push(d);
  while (cells.length % 7) cells.push(null);
  const weeks = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

/** Yerel saat `HH:MM:SS` */
export function clock(at) {
  const d = new Date(Math.floor(at) * 1000);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/** Yerel tarih `GG.AA.YYYY` */
export function dateLabel(at) {
  const d = new Date(at * 1000);
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}`;
}

/** Uzun tarih: "7 Kasım 2026" */
export function longDate(year, month, day) {
  return `${day} ${MONTHS[month - 1]} ${year}`;
}

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

/** Çizelgede `at`'in yeri (yüzde, 0–100'e kırpılır) */
export function toPercent(at, day, end) {
  return clamp(((at - day) / (end - day)) * 100, 0, 100);
}

/** Çizelgedeki yüzde → epoch */
export function fromPercent(percent, day, end) {
  return day + (clamp(percent, 0, 100) / 100) * (end - day);
}

/** Konumu günün içine kırpar: `[gün, sonraki gün − 1]` */
export function clampToDay(at, day, end) {
  return clamp(at, day, end - 1);
}

/** Kayıtlı aralıklar → başa göre sıralı çizelge dilimleri (günün dışına taşanlar kırpılır, gün dışındakiler atılır) */
export function segments(ranges, day, end) {
  const out = [];
  for (const [a, b] of [...ranges].sort((x, y) => x[0] - y[0])) {
    const s = Math.max(a, day);
    const e = Math.min(b, end);
    if (e <= s) continue;
    out.push({ start: s, end: e, left: toPercent(s, day, end), width: toPercent(e, day, end) - toPercent(s, day, end) });
  }
  return out;
}

/** `at`'ten sonra başlayan ilk kayıt aralığının başı; yoksa null */
export function nextRangeStart(ranges, at) {
  let best = null;
  for (const [a] of ranges) if (a > at && (best === null || a < best)) best = a;
  return best;
}

/** Günün varsayılan konumu: günün ilk kaydının başı (önceki günden süren kayıtta gün başı); kayıt yoksa gün başı */
export function defaultCursor(ranges, day, end) {
  const first = segments(ranges, day, end)[0];
  return first ? first.start : day;
}

/** `datetime-local` değeri (saniyeli, yerel) */
export function toLocalInput(at) {
  const d = new Date(Math.floor(at) * 1000);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/** `datetime-local` değeri → epoch; geçersizse null */
export function fromLocalInput(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?$/.exec(value ?? "");
  if (!m) return null;
  const [y, mo, d, h, mi, s] = m.slice(1).map((x) => Number(x ?? 0));
  const date = new Date(y, mo - 1, d, h, mi, s);
  if (date.getFullYear() !== y || date.getMonth() !== mo - 1 || date.getDate() !== d) return null;
  if (h > 23 || mi > 59 || s > 59) return null;
  return sec(date);
}

/** Dışa aktarma aralığının denetimi: uygunsa null, değilse Türkçe ileti */
export function exportProblem(start, end) {
  if (start === null || end === null) return "Geçerli bir tarih ve saat girin.";
  if (end <= start) return "Bitiş, başlangıçtan sonra olmalı.";
  if (end - start > MAX_EXPORT_S) return "En çok 30 dakika.";
  return null;
}

/** Dosya adı damgası `YYYYMMDD-HHMM` (yerel) */
export function fileStamp(at) {
  const d = new Date(at * 1000);
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`;
}

/** Sunucu ad vermezse indirilen dosyanın adı */
export function fallbackFilename(start) {
  return `kayit-${fileStamp(start)}.mp4`;
}

/** Dosya adından yol ayırıcıları ve denetim karakterlerini atar */
function safeName(name) {
  return name.replace(/[\\/\u0000-\u001f\u007f]/g, "").trim();
}

/** `Content-Disposition` → dosya adı: önce `filename*` (RFC 5987, UTF-8), yoksa `filename`; ikisi de yoksa `fallback` */
export function dispositionFilename(header, fallback) {
  if (!header) return fallback;
  const star = /(?:^|;)\s*filename\*\s*=\s*"?([^;"]*)"?/i.exec(header);
  if (star) {
    const m = /^[\w!#$%&+.^`|~-]*'[^']*'(.*)$/.exec(star[1].trim());
    if (m) {
      try {
        const name = safeName(decodeURIComponent(m[1]));
        if (name) return name;
      } catch {
        // bozuk kodlama: düz `filename`'e düşülür
      }
    }
  }
  const plain = /(?:^|;)\s*filename\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^;]*))/i.exec(header);
  if (plain) {
    const name = safeName((plain[1] ?? plain[2] ?? "").replace(/\\(.)/g, "$1"));
    if (name) return name;
  }
  return fallback;
}
