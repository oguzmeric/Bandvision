import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

/**
 * Sade arayüz bekçisi: panel sayfalarında, giriş sayfasında ve onların bileşenlerinde eski kart görünümünün izleri
 * kalmaz (büyük yuvarlak köşe, gölge, yarı saydam beyaz zemin, bulanık arka plan, lavanta/mor renkler, .card/.eyebrow).
 * Dosyanın her satırı taranır: sınıf adı className'de, sabitte, şablon dizgisinde ya da çok satırlı dizgide olsa da yakalanır.
 */
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ROOTS = [
  "app/(panel)",
  "app/login",
  "components",
];
/** src/lib (alt klasörleri dahil; .ts, .tsx, .mjs; birim testleri ve tür bildirimleri hariç): sınıf adı ya da renk sabitleri
 * burada da tutulabilir */
const LIB = "lib";
const LIB_EXTS = [".ts", ".tsx", ".mjs"];

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
  // Durum renklerinin -600/-700 tonları yazıda 4,5:1'i tutmaz (açık zeminde 3,2–4,0): yazı -ink tonuyla yazılır, beyaz
  // yazılı dolgu da -ink'tir. -600/-700 yalnız yazı olmayan işaretler (nokta, halka, çerçeve) içindir
  { name: "yazıda durum rengi -600/-700 (yerine -ink)", re: /\btext-(?:ok-600|nok-600|warn-700)\b/ },
  { name: "beyaz yazılı açık dolgu (yerine bg-*-ink)",
    re: /\bbg-(?:ok-600|warn-700)\b[^"'`]*\btext-white\b|\btext-white\b[^"'`]*\bbg-(?:ok-600|warn-700)\b/ },
];

/**
 * Klasördeki kaynak dosyaları, alt klasörler dahil. `exts`: alınan uzantılar; birim testleri (.test.mjs) ve tür bildirimleri
 * (.d.mts) alınmaz (bekçinin kendi örnekleri taranmaz).
 * @param {string} dir @param {string[]} [exts]
 */
function walk(dir, exts = [".tsx"]) {
  /** @type {string[]} */
  const out = [];
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...walk(p, exts));
    else if (exts.some((x) => e.name.endsWith(x)) && !/\.(?:test\.mjs|d\.mts)$/.test(e.name)) out.push(p);
  }
  return out;
}

test("bekçinin dosya taraması alt klasörlere iner; birim testleri ve tür bildirimleri alınmaz", () => {
  const dir = mkdtempSync(path.join(os.tmpdir(), "bv-bekci-"));
  try {
    mkdirSync(path.join(dir, "alt", "daha"), { recursive: true });
    for (const f of ["a.ts", "alt/b.ts", "alt/daha/c.mjs", "alt/d.tsx", "e.test.mjs", "alt/f.d.mts", "g.css"]) {
      writeFileSync(path.join(dir, f), "");
    }
    const got = walk(dir, LIB_EXTS).map((f) => path.relative(dir, f).split(path.sep).join("/")).sort();
    assert.deepEqual(got, ["a.ts", "alt/b.ts", "alt/d.tsx", "alt/daha/c.mjs"]);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("panel sayfaları, giriş sayfası ve bileşenleri: eski kart görünümü yok", () => {
  const lib = walk(path.join(SRC, LIB), LIB_EXTS);
  const files = [...ROOTS.flatMap((r) => walk(path.join(SRC, r))), ...lib];
  assert.ok(lib.length >= 10, `taranan lib dosyası az: ${lib.length}`);
  assert.ok(lib.some((f) => f.endsWith(path.join("lib", "layoutGrid.mjs"))), "lib'deki .mjs dosyaları taranmadı");
  assert.ok(files.some((f) => f.includes(`${path.sep}login${path.sep}`)), "giriş sayfası taranmadı");
  assert.ok(files.some((f) => f.endsWith(path.join("components", "watch", "WatchView.tsx"))), "izleme bileşenleri taranmadı");
  assert.ok(files.some((f) => f.endsWith(path.join("app", "(panel)", "watch", "page.tsx"))), "izleme sayfası taranmadı");
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

test("globals.css: düz beyaz zemin; .eyebrow, .card, .brand-gradient ve lavanta/mor renkler yok", () => {
  const css = readFileSync(path.join(SRC, "app", "globals.css"), "utf8");
  const body = css.match(/html,\s*body\s*\{([^}]*)\}/);
  assert.ok(body, "html, body kuralı yok");
  assert.match(body[1], /background:\s*var\(--color-pl-bg\);/);
  assert.doesNotMatch(body[1], /gradient|canvas/);
  assert.doesNotMatch(css, /\.eyebrow\b/);
  assert.doesNotMatch(css, /\.card\b|\.brand-gradient\b/);
  assert.doesNotMatch(css, /--color-(?:canvas|card|line|ink|muted|faint|brand|accent)\b/);
});

test("bekçi kalıpları: eski izleri yakalar, sade sınıflara takılmaz", () => {
  const bad = ['<div className="card p-4">', '<section className="card overflow-x-auto">', "className={`card ${x}`}",
    'const box = "card";', "`x card`", "  card p-4 rounded", "brand-gradient h-10",
    '<p className="eyebrow">', "rounded-2xl", "rounded-3xl", "shadow-sm", "bg-white/70", "backdrop-blur-sm", "bg-canvas",
    "bg-canvas-2", "text-brand-600", "accent-brand-500", "text-muted", "border-line", "text-ink", "text-faint",
    "ring-line", "outline-line", "fill-ink", 'color: "#6d3bf0"', "bg-[#FBFAFF]",
    "shadow-[0_8px_18px_rgba(109,59,240,0.25)]", "rgba(109, 59, 240, 0.2)", "text-ok-600", "text-nok-600",
    "text-warn-700", 'ok: "bg-ok-600 text-white"', "text-white bg-warn-700"];
  const good = ['<div className="pl-section">', "text-pl-muted", "border-pl-line", "text-pl-ink", "bg-pl-head",
    "UploadCard", 'className="cards-x"', 'data-testid="source-card"', "session-card", "cardinal", "rounded-[3px]",
    "text-nok-ink", "bg-warn-50", "border-pl-line-soft", "border-nok-line", "border-warn-line", "ring-pl-accent",
    "outline-pl-accent", 'color: "#2c5aa0"', "bg-[#f7f8fa]", "bg-ok-600", "border-warn-700", "bg-ok-ink text-white",
    "ring-nok-600", 'live: "bg-ok-600"'];
  for (const s of bad) assert.ok(IDIOMS.some(({ re }) => re.test(s)), `yakalanmadı: ${s}`);
  for (const s of good) assert.ok(!IDIOMS.some(({ re }) => re.test(s)), `yanlış yakalandı: ${s}`);
});

/** globals.css `@theme` renk belirteçleri (ad → #rrggbb) */
function tokens() {
  const css = readFileSync(path.join(SRC, "app", "globals.css"), "utf8");
  return Object.fromEntries([...css.matchAll(/--color-([\w-]+):\s*(#[0-9a-f]{6})\b/gi)].map((m) => [m[1], m[2].toLowerCase()]));
}
/** WCAG 2 bağıl parlaklık karşıtlığı (#rrggbb) */
function contrast(a, b) {
  const lum = (hex) => {
    const [r, g, bl] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
      .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

test("yazı/zemin karşıtlığı ≥4,5:1 (WCAG 1.4.3): durum kutuları, rozetler, alarm şeridi, yardım yazısı", () => {
  const t = tokens();
  const WHITE = "#ffffff";
  /** [yazı, zemin, nerede] */
  const pairs = [
    ["warn-ink", "warn-50", "uyarı/bilgi kutuları (role=status)"], ["warn-ink", WHITE, "\"Kaydedilmemiş değişiklik var\""],
    ["nok-ink", "nok-50", "hata kutuları (role=alert)"], ["nok-ink", WHITE, "hata yazısı"], ["nok-ink", "pl-side", "Sil düğmesi"],
    ["ok-ink", "ok-50", "\"Canlı\" çipi, başarı kutuları"], ["ok-ink", WHITE, "başarı yazısı"],
    [WHITE, "ok-ink", "rozet \"Nöbette\", Başlat"], [WHITE, "warn-ink", "rozet \"Uyarı\""], [WHITE, "nok-600", "alarm şeridi ve etiketi"],
    ["pl-faint", "pl-head", "başlık şeridinde yardım yazısı"], ["pl-faint", "pl-side", "menü ve durum şeridi"],
    ["pl-faint", WHITE, "yardım yazısı"], ["pl-faint", "pl-sel", "seçili satırda yardım"], ["pl-muted", "pl-head", "ikincil yazı"],
    ["pl-ink", "pl-head", "başlık"],
  ];
  const low = [];
  for (const [fg, bg, where] of pairs) {
    const f = fg.startsWith("#") ? fg : t[fg];
    const b = bg.startsWith("#") ? bg : t[bg];
    assert.ok(f && b, `belirteç yok: ${fg} / ${bg}`);
    const c = contrast(f, b);
    if (c < 4.5) low.push(`${fg} / ${bg} (${where}): ${c.toFixed(2)}`);
  }
  assert.deepEqual(low, []);
  // -600/-700 yalnız yazı olmayan işaretlerde (nokta, halka, çerçeve): beyaz zeminde ≥3:1 (WCAG 1.4.11)
  for (const mark of ["ok-600", "warn-700", "nok-600"]) assert.ok(contrast(t[mark], WHITE) >= 3, mark);
});
