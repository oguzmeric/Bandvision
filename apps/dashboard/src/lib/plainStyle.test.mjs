import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

/**
 * Sade arayüz bekçisi: panel sayfalarında, giriş sayfasında ve onların bileşenlerinde eski kart görünümünün izleri
 * kalmaz (büyük yuvarlak köşe, gölge, yarı saydam beyaz zemin, bulanık arka plan, lavanta/mor renkler, .card/.eyebrow).
 * İzleme sayfası (app/(panel)/watch, components/watch) ayrı yeniden yapılır; burada taranmaz.
 * Dosyanın her satırı taranır: sınıf adı className'de, sabitte, şablon dizgisinde ya da çok satırlı dizgide olsa da yakalanır.
 */
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ROOTS = [
  "app/(panel)",
  "app/login",
  "components/live",
  "components/video",
  "components/settings",
  "components/geometry",
  "components/about",
];
const SKIP = new Set([path.join("app", "(panel)", "watch")]);
/** src/lib/*.ts (yalnızca bu klasör, alt klasörsüz): sınıf adı ya da renk sabitleri burada da tutulabilir */
const LIB = "lib";

const IDIOMS = [
  { name: "rounded-3xl", re: /\brounded-3xl\b/ },
  { name: "rounded-2xl", re: /\brounded-2xl\b/ },
  { name: "shadow-", re: /\bshadow-/ },
  { name: "bg-white/70", re: /\bbg-white\/70\b/ },
  { name: "backdrop-blur", re: /\bbackdrop-blur/ },
  { name: "eyebrow", re: /\beyebrow\b/ },
  { name: "brand-gradient", re: /\bbrand-gradient\b/ },
  // tek başına "card" sözcüğü (data-testid="source-card" gibi tireli adlar değil)
  { name: "card sınıfı", re: /(?<![-\w])card(?![-\w])/ },
  // lavanta zemin ve mor vurgu: sade görünüm gri-mavi (pl-*) renkleri kullanır
  { name: "canvas zemin", re: /\b(?:bg|from|to|via)-canvas\b|\bbg-canvas-2\b/ },
  { name: "brand rengi", re: /\b(?:bg|text|border|accent|ring|outline|fill|stroke|from|to|via|decoration)-brand-\d/ },
  { name: "eski gri tonlar", re: /\b(?:text|border|bg|divide|ring|outline|fill|stroke)-(?:ink|muted|faint|line|card)\b/ },
  { name: "mor/lavanta renk kodu", re: /#(?:6d3bf0|9b3be6|e0368c|5b2bd6|eeeafb|fbfaff|2b2740|cfc7f3|0e0c17|1d1a2e|f6f5fc|efedfa|e7e4f3)\b/i },
  { name: "mor gölge rengi", re: /rgba?\(\s*109\s*,\s*59\s*,\s*240\b/ },
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

test("panel sayfaları, giriş sayfası ve bileşenleri: eski kart görünümü yok", () => {
  const lib = readdirSync(path.join(SRC, LIB)).filter((n) => n.endsWith(".ts")).map((n) => path.join(SRC, LIB, n));
  const files = [...ROOTS.flatMap((r) => walk(path.join(SRC, r))), ...lib];
  assert.ok(lib.length >= 10, `taranan lib dosyası az: ${lib.length}`);
  assert.ok(files.some((f) => f.includes(`${path.sep}login${path.sep}`)), "giriş sayfası taranmadı");
  assert.ok(files.length >= 40, `taranan dosya az: ${files.length}`);
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
    'const box = "card";', "`x card`", "  card p-4 rounded", "brand-gradient h-10",
    '<p className="eyebrow">', "rounded-2xl", "rounded-3xl", "shadow-sm", "bg-white/70", "backdrop-blur-sm", "bg-canvas",
    "bg-canvas-2", "text-brand-600", "accent-brand-500", "text-muted", "border-line", "text-ink", "text-faint",
    "ring-line", "outline-line", "fill-ink", 'color: "#6d3bf0"', "bg-[#FBFAFF]",
    "shadow-[0_8px_18px_rgba(109,59,240,0.25)]", "rgba(109, 59, 240, 0.2)"];
  const good = ['<div className="pl-section">', "text-pl-muted", "border-pl-line", "text-pl-ink", "bg-pl-head",
    "UploadCard", 'className="cards-x"', 'data-testid="source-card"', "session-card", "cardinal", "rounded-[3px]",
    "text-nok-600", "bg-warn-50", "border-pl-line-soft", "border-nok-line", "border-warn-line", "ring-pl-accent",
    "outline-pl-accent", 'color: "#2c5aa0"', "bg-[#f7f8fa]"];
  for (const s of bad) assert.ok(IDIOMS.some(({ re }) => re.test(s)), `yakalanmadı: ${s}`);
  for (const s of good) assert.ok(!IDIOMS.some(({ re }) => re.test(s)), `yanlış yakalandı: ${s}`);
});
