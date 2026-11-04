import assert from "node:assert/strict";
import test from "node:test";
import { isResultFile } from "./resultFile.mjs";

test("isResultFile: sabit sonuç dosyaları ve alarms.csv", () => {
  for (const n of ["annotated.mp4", "counts.csv", "alarms.csv", "profile.json", "background.png"]) assert.equal(isResultFile(n), true, n);
});

test("isResultFile: alarm-N.jpg (1-2 basamak) kabul edilir", () => {
  for (const n of ["alarm-1.jpg", "alarm-9.jpg", "alarm-10.jpg", "alarm-50.jpg", "alarm-99.jpg"]) assert.equal(isResultFile(n), true, n);
});

test("isResultFile: tam eşleşme — yol, uzantı, büyük harf, 3 basamak, boşluk, nokta, satır sonu reddedilir", () => {
  const bad = ["../x", "../alarm-1.jpg", "alarm-1.jpg.exe", "ALARM-1.JPG", "Alarm-1.jpg", "alarm-100.jpg", "alarm-.jpg",
               "alarm-1.jpg ", " alarm-1.jpg", "alarm-1.jpg.", "alarm-1.jpg\n", "alarm-1.jpg\0", "alarm-1.JPG",
               "alarm-a.jpg", "alarm-1.jpeg", "xalarm-1.jpg", "alarm-1.jpgx", "a/alarm-1.jpg", "..\alarm-1.jpg",
               "alarms.csv ", "ALARMS.CSV", "alarmlar.csv", "job.json", "input.mp4", "", "annotated.mp4/", "%2e%2e"];
  for (const n of bad) assert.equal(isResultFile(n), false, JSON.stringify(n));
});

test("isResultFile: dize olmayan değer reddedilir", () => {
  for (const v of [undefined, null, 1, {}, ["alarm-1.jpg"]]) assert.equal(isResultFile(v), false);
});
