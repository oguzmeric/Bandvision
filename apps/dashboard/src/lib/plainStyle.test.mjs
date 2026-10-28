import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

/**
 * Sade arayüz bekçisi: panel sayfalarında ve onların bileşenlerinde eski kart görünümünün izleri kalmaz
 * (büyük yuvarlak köşe, gölge, yarı saydam beyaz zemin, bulanık arka plan, lavanta/mor renkler, .card/.eyebrow).
 * İzleme sayfası (app/(panel)/watch, components/watch) ayrı yeniden yapılır; burada taranmaz.
 */
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ROOTS = [
  "app/(panel)",
  "components/live",
  "components/video",
  "components/settings",
  "components/geometry",
  "components/about",
];
const SKIP = new Set([path.join("app", "(panel)", "watch")]);

const IDIOMS = [
  { name: "rounded-3xl", re: /\brounded-3xl\b/ },
  { name: "rounded-2xl", re: /\brounded-2xl\b/ },
  { name: "shadow-", re: /\bshadow-/ },
  { name: "bg-white/70", re: /\bbg-white\/70\b/ },
  { name: "backdrop-blur", re: /\bbackdrop-blur/ },
  { name: "eyebrow", re: /\beyebrow\b/ },
  { name: "brand-gradient", re: /\bbrand-gradient\b/ },
  { name: "card sınıfı", re: /className=(?:"|\{`|\{")(?:[^"`]*\s)?card(?:[\s"`]|$)/ },
  // lavanta zemin ve mor vurgu: sade görünüm gri-mavi (pl-*) renkleri kullanır
  { name: "canvas zemin", re: /\b(?:bg|from|to|via)-canvas\b|\bbg-canvas-2\b/ },
  { name: "brand rengi", re: /\b(?:bg|text|border|accent|ring|outline|fill|stroke|from|to|via|decoration)-brand-\d/ },
  { name: "eski gri tonlar", re: /\b(?:text|border|bg|divide)-(?:ink|muted|faint|line|card)\b/ },
  { name: "mor/lavanta renk kodu", re: /#(?:6d3bf0|9b3be6|e0368c|5b2bd6|eeeafb|fbfaff|2b2740|cfc7f3|0e0c17|1d1a2e|f6f5fc|efedfa|e7e4f3)\b/i },
];

/** @param {string} dir */
function walk(dir) {
  /** @type {string[]} */
  const out = [];
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (SKIP.has(path.relative(SRC, p))) continue;
    if (e.isDirectory()) out.push(...walk(p));
    else if (e.name.endsWith(".tsx")) out.push(p);
  }
  return out;
}

test("panel sayfaları ve bileşenleri: eski kart görünümü yok", () => {
  const files = ROOTS.flatMap((r) => walk(path.join(SRC, r)));
  assert.ok(files.length >= 30, `taranan dosya az: ${files.length}`);
  const hits = [];
  for (const f of files) {
    readFileSync(f, "utf8").split(/\r?\n/).forEach((line, i) => {
      for (const { name, re } of IDIOMS) {
        if (re.test(line)) hits.push(`${path.relative(SRC, f)}:${i + 1}: ${name}`);
      }
    });
  }
  assert.deepEqual(hits, [], `eski görünüm izleri:\n${hits.join("\n")}`);
});

test("globals.css: düz beyaz zemin, .eyebrow yok", () => {
  const css = readFileSync(path.join(SRC, "app", "globals.css"), "utf8");
  const body = css.match(/html,\s*body\s*\{([^}]*)\}/);
  assert.ok(body, "html, body kuralı yok");
  assert.match(body[1], /background:\s*var\(--color-pl-bg\);/);
  assert.doesNotMatch(body[1], /gradient|canvas/);
  assert.doesNotMatch(css, /\.eyebrow\b/);
});

test("bekçi kalıpları: eski izleri yakalar, sade sınıflara takılmaz", () => {
  const bad = ['<div className="card p-4">', '<section className="card overflow-x-auto">', "className={`card ${x}`}",
    '<p className="eyebrow">', "rounded-2xl", "shadow-sm", "bg-white/70", "backdrop-blur-sm", "bg-canvas", "bg-canvas-2",
    "text-brand-600", "accent-brand-500", "text-muted", "border-line", "text-ink", "text-faint",
    'color: "#6d3bf0"', "bg-[#FBFAFF]"];
  const good = ['<div className="pl-section">', "text-pl-muted", "border-pl-line", "text-pl-ink", "bg-pl-head",
    "UploadCard", 'className="cards-x"', "rounded-[3px]", "text-nok-600", "bg-warn-50", "border-pl-line-soft",
    'color: "#2c5aa0"', "bg-[#f7f8fa]"];
  for (const s of bad) assert.ok(IDIOMS.some(({ re }) => re.test(s)), `yakalanmadı: ${s}`);
  for (const s of good) assert.ok(!IDIOMS.some(({ re }) => re.test(s)), `yanlış yakalandı: ${s}`);
});
