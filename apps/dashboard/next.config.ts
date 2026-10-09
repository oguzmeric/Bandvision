import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

/**
 * Geliştirme sunucusu (`npm run dev`, tools/panel_run.mjs yerel kipi) ayrı klasörde derler: aynı anda çalışan
 * `next build` / e2e testleri çalışan paneli bozmasın ("Cannot read properties of undefined (reading 'call')").
 * Başlatıcının üretim derlemesi (yerel ağ kipi) `BV_DIST_DIR=.next-lan` ile kendi klasöründedir; `next start` da aynı
 * değişkenle o klasörü okur. Yalnızca `.next` ya da `.next-<ad>` biçimi kabul edilir; yoksa `.next`.
 */
export default function config(phase: string): NextConfig {
  const dist = process.env.BV_DIST_DIR;
  const prodDir = dist && /^\.next(-[a-z0-9]+)?$/.test(dist) ? dist : ".next";
  return { distDir: phase === PHASE_DEVELOPMENT_SERVER ? ".next-dev" : prodDir };
}
