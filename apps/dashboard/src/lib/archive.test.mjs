import assert from "node:assert/strict";
import test from "node:test";
import {
  MAX_EXPORT_S, clampToDay, clock, dateLabel, dayEnd, dayOf, dayStart, daysInMonth, defaultCursor, dispositionFilename,
  exportProblem, fallbackFilename, fileStamp, fromLocalInput, fromPercent, longDate, monthGrid, nextRangeStart, partsOf,
  segments, shiftMonth, toLocalInput, toPercent,
} from "./archiveTime.mjs";

/** Yerel saatle bir an (testler hangi saat diliminde koşarsa koşsun aynı sonucu verir) */
const local = (y, mo, d, h = 0, mi = 0, s = 0) => new Date(y, mo - 1, d, h, mi, s).getTime() / 1000;

/** Saat dilimini geçici olarak değiştirir (Node `process.env.TZ` atamasını hemen uygular) */
function inZone(tz, fn) {
  const old = process.env.TZ;
  process.env.TZ = tz;
  try { fn(); } finally { if (old === undefined) delete process.env.TZ; else process.env.TZ = old; }
}

test("gün başı yereldir: günün her anı aynı gün başını verir; dayOf aynı değeri üretir", () => {
  const day = local(2026, 11, 7);
  assert.equal(dayStart(local(2026, 11, 7, 0, 0, 0)), day);
  assert.equal(dayStart(local(2026, 11, 7, 13, 45, 12) + 0.5), day);
  assert.equal(dayStart(local(2026, 11, 7, 23, 59, 59)), day);
  assert.equal(dayOf(2026, 11, 7), day);
  assert.deepEqual(partsOf(local(2026, 11, 7, 23, 59)), { year: 2026, month: 11, day: 7 });
});

test("gün sonu bir sonraki yerel gün başıdır; yaz saati geçişinde gün 23 ya da 25 saattir", () => {
  assert.equal(dayEnd(local(2026, 11, 7)), local(2026, 11, 8));
  assert.equal(dayEnd(local(2026, 12, 31)), local(2027, 1, 1));
  inZone("Europe/Berlin", () => {
    assert.equal(dayEnd(dayOf(2026, 3, 29)) - dayOf(2026, 3, 29), 23 * 3600);
    assert.equal(dayEnd(dayOf(2026, 10, 25)) - dayOf(2026, 10, 25), 25 * 3600);
  });
  inZone("Europe/Istanbul", () => {
    const day = dayOf(2026, 11, 7);
    assert.equal(day, Date.UTC(2026, 10, 6, 21) / 1000);         // İstanbul UTC+3: yerel 00:00 = önceki gün 21:00Z
    assert.equal(dayEnd(day) - day, 86400);
    assert.equal(dayStart(day + 86399), day);
  });
});

test("ay gezgini yıl sınırını geçer; ayın gün sayısı (artık yıl)", () => {
  assert.deepEqual(shiftMonth(2026, 1, -1), { year: 2025, month: 12 });
  assert.deepEqual(shiftMonth(2026, 12, 1), { year: 2027, month: 1 });
  assert.deepEqual(shiftMonth(2026, 11, 0), { year: 2026, month: 11 });
  assert.deepEqual(shiftMonth(2026, 3, -15), { year: 2024, month: 12 });
  assert.equal(daysInMonth(2028, 2), 29);
  assert.equal(daysInMonth(2026, 2), 28);
  assert.equal(daysInMonth(2026, 11), 30);
});

test("ay tablosu pazartesiden başlar, ay dışı hücreler boş, haftalar 7 gün", () => {
  const weeks = monthGrid(2026, 11);                 // 1 Kasım 2026 pazar
  assert.ok(weeks.every((w) => w.length === 7));
  assert.deepEqual(weeks[0], [null, null, null, null, null, null, 1]);
  assert.deepEqual(weeks.at(-1), [30, null, null, null, null, null, null]);
  assert.deepEqual(weeks.flat().filter((d) => d !== null), Array.from({ length: 30 }, (_, i) => i + 1));
  assert.equal(monthGrid(2026, 6)[0][0], 1);         // 1 Haziran 2026 pazartesi
});

test("saat HH:MM:SS ve tarih yerel; kesirli saniye aşağı yuvarlanır", () => {
  assert.equal(clock(local(2026, 11, 7, 9, 5, 3)), "09:05:03");
  assert.equal(clock(local(2026, 11, 7, 23, 59, 59) + 0.9), "23:59:59");
  assert.equal(clock(local(2026, 11, 7)), "00:00:00");
  assert.equal(dateLabel(local(2026, 1, 2, 12)), "02.01.2026");
  assert.equal(longDate(2026, 11, 7), "7 Kasım 2026");
});

test("çizelge: yüzde ↔ epoch ikisi de kırpılır; gün içine kırpma", () => {
  const day = local(2026, 11, 7);
  const end = dayEnd(day);
  const len = end - day;
  assert.equal(toPercent(day, day, end), 0);
  assert.equal(toPercent(day + len / 2, day, end), 50);
  assert.equal(toPercent(day - 10, day, end), 0);
  assert.equal(toPercent(end + 10, day, end), 100);
  assert.equal(fromPercent(25, day, end), day + len / 4);
  assert.equal(fromPercent(-5, day, end), day);
  assert.equal(fromPercent(150, day, end), end);
  assert.ok(Math.abs(fromPercent(toPercent(day + 12345, day, end), day, end) - (day + 12345)) < 1e-6);
  assert.equal(clampToDay(day - 5, day, end), day);
  assert.equal(clampToDay(end + 30, day, end), end - 1);
  assert.equal(clampToDay(day + 60, day, end), day + 60);
});

test("çizelge dilimleri sıralanır, gün dışına taşan kırpılır, gün dışındaki atılır", () => {
  const day = local(2026, 11, 7);
  const end = dayEnd(day);
  const len = end - day;
  const segs = segments([[day + len / 2, day + len / 2 + 7200], [day - 3600, day + 3600], [end + 10, end + 20], [day - 50, day - 10]], day, end);
  assert.equal(segs.length, 2);
  assert.deepEqual(segs.map((s) => [s.start, s.end]), [[day, day + 3600], [day + len / 2, day + len / 2 + 7200]]);
  assert.equal(segs[0].left, 0);
  assert.ok(Math.abs(segs[1].left - 50) < 1e-9 && Math.abs(segs[1].width - (7200 / len) * 100) < 1e-9);
});

test("sonraki kayıt ve varsayılan imleç", () => {
  const day = local(2026, 11, 7);
  const end = dayEnd(day);
  const ranges = [[day + 10000, day + 20000], [day + 3600, day + 7200]];
  assert.equal(nextRangeStart(ranges, day + 7200), day + 10000);
  assert.equal(nextRangeStart(ranges, day), day + 3600);
  assert.equal(nextRangeStart(ranges, day + 10000), null);         // son kaydın içinde: sonraki yok
  assert.equal(nextRangeStart([], day), null);
  assert.equal(defaultCursor(ranges, day, end), day + 3600);
  assert.equal(defaultCursor([[day - 600, day + 600]], day, end), day);   // gece yarısını geçen kayıt
  assert.equal(defaultCursor([], day, end), day);
});

test("datetime-local gidiş-dönüş; geçersiz değer null", () => {
  const at = local(2026, 11, 7, 14, 3, 9);
  assert.equal(toLocalInput(at), "2026-11-07T14:03:09");
  assert.equal(toLocalInput(at + 0.7), "2026-11-07T14:03:09");
  assert.equal(fromLocalInput("2026-11-07T14:03:09"), at);
  assert.equal(fromLocalInput("2026-11-07T14:03"), at - 9);
  assert.equal(fromLocalInput(toLocalInput(at)), at);
  for (const bad of ["", null, undefined, "2026-02-30T10:00", "2026-11-07T24:00", "2026-11-07 14:03", "dün"]) {
    assert.equal(fromLocalInput(bad), null, String(bad));
  }
});

test("dışa aktarma sınırı: 30 dk dahil, üstü 'En çok 30 dakika.'; ters ya da boş aralık", () => {
  const s = local(2026, 11, 7, 10);
  assert.equal(MAX_EXPORT_S, 1800);
  assert.equal(exportProblem(s, s + 120), null);
  assert.equal(exportProblem(s, s + 1800), null);
  assert.equal(exportProblem(s, s + 1801), "En çok 30 dakika.");
  assert.equal(exportProblem(s, s), "Bitiş, başlangıçtan sonra olmalı.");
  assert.equal(exportProblem(s + 10, s), "Bitiş, başlangıçtan sonra olmalı.");
  assert.equal(exportProblem(null, s), "Geçerli bir tarih ve saat girin.");
  assert.equal(exportProblem(s, null), "Geçerli bir tarih ve saat girin.");
});

test("dosya adı: önce filename* (UTF-8), yoksa filename; yol ayırıcıları atılır; hiçbiri yoksa yedek ad", () => {
  const at = local(2026, 11, 7, 9, 5);
  assert.equal(fileStamp(at), "20261107-0905");
  assert.equal(fallbackFilename(at), "kayit-20261107-0905.mp4");
  assert.equal(dispositionFilename("attachment; filename=\"Kasa-20261107-0905.mp4\"; filename*=UTF-8''Kasa%20%C3%B6n%C3%BC-20261107-0905.mp4", "x.mp4"),
    "Kasa önü-20261107-0905.mp4");
  assert.equal(dispositionFilename("attachment; filename*=UTF-8''%C4%B0%C3%A7%20kap%C4%B1.mp4; filename=\"Ic kapi.mp4\"", "x.mp4"), "İç kapı.mp4");
  assert.equal(dispositionFilename("attachment; filename=\"Giris.mp4\"", "x.mp4"), "Giris.mp4");
  assert.equal(dispositionFilename("attachment; filename=Giris.mp4", "x.mp4"), "Giris.mp4");
  assert.equal(dispositionFilename("attachment; filename*=UTF-8''%E0%A4; filename=\"Yedek.mp4\"", "x.mp4"), "Yedek.mp4");  // bozuk kodlama
  assert.equal(dispositionFilename("attachment; filename*=UTF-8''..%2F..%2Fetc.mp4", "x.mp4"), "....etc.mp4");
  assert.equal(dispositionFilename("attachment; filename=\"a\\\\b/c.mp4\"", "x.mp4"), "abc.mp4");
  assert.equal(dispositionFilename("attachment", "x.mp4"), "x.mp4");
  assert.equal(dispositionFilename(null, "x.mp4"), "x.mp4");
  assert.equal(dispositionFilename("attachment; filename=\"\"", "x.mp4"), "x.mp4");
});
