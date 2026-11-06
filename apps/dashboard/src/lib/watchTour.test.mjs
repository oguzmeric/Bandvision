import assert from "node:assert/strict";
import test from "node:test";
import {
  DEFAULT_TOUR_S, TOUR_COOKIE, TOUR_INTERVALS, filledIndexes, parseTourInterval, readCookie, stepFilled, tourCookie, tourPosition,
} from "./watchTour.mjs";

const cam = (s) => ({ sourceId: s, channelId: null });
// 0 dolu, 1 boş, 2 dolu, 3 boş, 4 dolu
const TILES = [cam("a"), null, cam("b"), null, cam("c")];

test("aralıklar: 5, 10, 20, 30, 60 sn; varsayılan 10", () => {
  assert.deepEqual(TOUR_INTERVALS, [5, 10, 20, 30, 60]);
  assert.equal(DEFAULT_TOUR_S, 10);
});

test("filledIndexes: kutu sırasıyla dolu kutular", () => {
  assert.deepEqual(filledIndexes(TILES), [0, 2, 4]);
  assert.deepEqual(filledIndexes([null, null]), []);
});

test("stepFilled: sonraki dolu kutu, boşlar atlanır, başa sarar", () => {
  assert.equal(stepFilled(TILES, 0, 1), 2);
  assert.equal(stepFilled(TILES, 2, 1), 4);
  assert.equal(stepFilled(TILES, 4, 1), 0);                 // sondan başa
});

test("stepFilled: önceki dolu kutu, boşlar atlanır, sona sarar", () => {
  assert.equal(stepFilled(TILES, 4, -1), 2);
  assert.equal(stepFilled(TILES, 2, -1), 0);
  assert.equal(stepFilled(TILES, 0, -1), 4);                // baştan sona
});

test("stepFilled: boş kutudan da yürür; tek dolu kutuda kendisi; hiç yoksa null", () => {
  assert.equal(stepFilled(TILES, 1, 1), 2);
  assert.equal(stepFilled(TILES, 3, -1), 2);
  assert.equal(stepFilled([null, cam("a"), null], 1, 1), 1);
  assert.equal(stepFilled([null, cam("a"), null], 1, -1), 1);
  assert.equal(stepFilled([null, null], 0, 1), null);
  assert.equal(stepFilled([], 0, 1), null);
});

test("tourPosition: dolu kutular arasında 1'den başlayan sıra ve toplam", () => {
  assert.deepEqual(tourPosition(TILES, 0), { n: 1, total: 3 });
  assert.deepEqual(tourPosition(TILES, 4), { n: 3, total: 3 });
  assert.deepEqual(tourPosition(TILES, 1), { n: 0, total: 3 });     // boş kutu sırada değil
});

test("çerez: aralık yazılır ve okunur; geçersiz değer varsayılana döner", () => {
  assert.equal(tourCookie(20), `${TOUR_COOKIE}=20; Path=/; Max-Age=31536000; SameSite=Lax`);
  assert.equal(readCookie(`x=1; ${TOUR_COOKIE}=30; y=2`, TOUR_COOKIE), "30");
  assert.equal(readCookie("x=1", TOUR_COOKIE), null);
  assert.equal(readCookie("", TOUR_COOKIE), null);
  assert.equal(parseTourInterval("30"), 30);
  assert.equal(parseTourInterval("5"), 5);
  for (const bad of [null, undefined, "", "7", "abc", "10.5", "-5", "600"]) assert.equal(parseTourInterval(bad), DEFAULT_TOUR_S, String(bad));
});
