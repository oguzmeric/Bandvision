import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

/**
 * Geliştirme sunucusu (`npm run dev`, tools/panel_baslat.bat) ayrı klasörde derler: aynı anda çalışan
 * `next build` / e2e testleri çalışan paneli bozmasın ("Cannot read properties of undefined (reading 'call')").
 */
export default function config(phase: string): NextConfig {
  return { distDir: phase === PHASE_DEVELOPMENT_SERVER ? ".next-dev" : ".next" };
}
