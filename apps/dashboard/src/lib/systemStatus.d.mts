export type AnalyzerState = "up" | "down" | "auth";
export function classify(r: { ok: boolean; status: number } | { error: unknown }): AnalyzerState;
export function parseStatus(
  json: unknown,
): { cpuPercent: number; uptimeS: number; version: string; commit: string } | null;
