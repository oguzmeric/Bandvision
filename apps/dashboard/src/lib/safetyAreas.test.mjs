import assert from "node:assert/strict";
import test from "node:test";
import {
  addArea, AREA_NAME_MAX, areaSlot, areaWatches, enabledRules, MAX_AREAS, nextAreaName, removeArea, renameArea, safetyAreas,
  toggleAreaRule, withAreaPoints, withAreas,
} from "./safetyAreas.mjs";

const SAFETY = { handsUp: { enabled: true, seconds: 3 }, lying: { enabled: true, seconds: 10 }, phone: { enabled: false, seconds: 15 }, sendImage: false };

test("enabledRules: kamerada açık kurallar; eski profilde phone yoksa kapalı, enabled yoksa varsayılan", () => {
  assert.deepEqual(enabledRules(SAFETY), ["handsUp", "lying"]);
  assert.deepEqual(enabledRules({ ...SAFETY, handsUp: { enabled: false, seconds: 3 }, phone: { enabled: true, seconds: 15 } }), ["lying", "phone"]);
  assert.deepEqual(enabledRules({ handsUp: { enabled: true, seconds: 3 }, lying: { enabled: false, seconds: 10 }, sendImage: false }), ["handsUp"]);
  assert.deepEqual(enabledRules(undefined), ["handsUp", "lying"]);
});

test("safetyAreas: yoksa boş; bozuk öğe, köşe ve kural düşer; kopya döner", () => {
  assert.deepEqual(safetyAreas(SAFETY), []);
  assert.deepEqual(safetyAreas({ ...SAFETY, areas: "x" }), []);
  const src = { ...SAFETY, areas: [null, { name: "Masa 3", points: [[0.1, 0.2], [0.3, "a"], [0.5, 0.6], [0.7, 0.8]], rules: ["lying", "fire", "lying", "handsUp"] }] };
  const got = safetyAreas(src);
  assert.deepEqual(got, [{ name: "Masa 3", points: [[0.1, 0.2], [0.5, 0.6], [0.7, 0.8]], rules: ["lying", "handsUp"] }]);
  got[0].points[0][0] = 0.9;
  assert.equal(src.areas[1].points[0][0], 0.1);
});

test("nextAreaName: kullanılmayan en küçük numara", () => {
  assert.equal(nextAreaName([]), "Alan 1");
  const a = (name) => ({ name, points: [], rules: ["handsUp"] });
  assert.equal(nextAreaName([a("Alan 1"), a("Alan 2")]), "Alan 3");
  assert.equal(nextAreaName([a("Masa 3"), a("Alan 2")]), "Alan 1");
  assert.equal(nextAreaName([a(" Alan 1 "), a("Alan 3")]), "Alan 2");
});

test("addArea: Alan N, kamerada açık kurallar, görüntü içinde boş yuva; 16'da ve açık kural yokken değişmez", () => {
  let areas = addArea([], ["handsUp", "lying"]);
  assert.deepEqual(areas, [{ name: "Alan 1", points: areaSlot(0), rules: ["handsUp", "lying"] }]);
  for (let i = 1; i < MAX_AREAS; i++) areas = addArea(areas, ["phone"]);
  assert.equal(areas.length, 16);
  assert.equal(new Set(areas.map((a) => JSON.stringify(a.points))).size, 16);
  for (const a of areas) for (const [x, y] of a.points) assert.ok(x >= 0 && x <= 1 && y >= 0 && y <= 1);
  assert.equal(addArea(areas, ["phone"]), areas);
  assert.deepEqual(addArea([], []), []);
  // silinen alanın yuvası yeniden kullanılır (yeni alan kalanların üstüne binmez)
  const fewer = removeArea(areas, 1);
  const again = addArea(fewer, ["lying"]);
  assert.deepEqual(again.at(-1), { name: "Alan 2", points: areaSlot(1), rules: ["lying"] });
});

test("renameArea: kırpılır, en çok 40 karakter; boş ad listeyi değiştirmez", () => {
  const areas = addArea([], ["handsUp"]);
  assert.equal(renameArea(areas, 0, "  Masa 3 ")[0].name, "Masa 3");
  assert.equal(renameArea(areas, 0, "x".repeat(50))[0].name.length, AREA_NAME_MAX);
  assert.equal(renameArea(areas, 0, "   "), areas);
  assert.equal(renameArea(areas, 5, "Kasa"), areas);
});

test("toggleAreaRule: kural sırası korunur; son kural kapatılamaz", () => {
  const areas = addArea([], ["lying"]);
  const two = toggleAreaRule(areas, 0, "handsUp", true);
  assert.deepEqual(two[0].rules, ["handsUp", "lying"]);
  assert.deepEqual(toggleAreaRule(two, 0, "handsUp", false)[0].rules, ["lying"]);
  assert.equal(toggleAreaRule(areas, 0, "lying", false), areas);
  assert.equal(toggleAreaRule(areas, 0, "fire", true), areas);
});

test("withAreaPoints ve withAreas: köşeler sırayla yazılır; boş liste profilden düşer", () => {
  const areas = addArea(addArea([], ["handsUp"]), ["handsUp"]);
  const moved = withAreaPoints(areas, [[[0, 0], [1, 0], [1, 1]], areas[1].points]);
  assert.deepEqual(moved[0].points, [[0, 0], [1, 0], [1, 1]]);
  assert.equal(moved[1].name, "Alan 2");
  assert.deepEqual(withAreas(SAFETY, moved).areas, moved);
  const cleared = withAreas({ ...SAFETY, areas: moved }, []);
  assert.equal("areas" in cleared, false);
  assert.deepEqual(cleared, SAFETY);
});

test("areaWatches: alanın kurallarından en az biri kamerada açık mı", () => {
  const area = { name: "Kasa", points: [], rules: ["phone"] };
  assert.equal(areaWatches(area, SAFETY), false);
  assert.equal(areaWatches(area, { ...SAFETY, phone: { enabled: true, seconds: 15 } }), true);
});
