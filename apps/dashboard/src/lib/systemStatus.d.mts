export type AnalyzerState = "up" | "down" | "auth" | "old";
export function classify(r: { ok: boolean; status: number } | { error: unknown }): AnalyzerState;
export function parseStatus(
  json: unknown,
): { cpuPercent: number | null; uptimeS: number; version: string; commit: string } | null;
export type AnalyzerLog = { message: string; what: string } | null;
export type AnalyzerSummary =
  | { analyzer: "up"; cpuPercent: number | null; uptimeS: number | null; version: string; commit: string; log: AnalyzerLog }
  | { analyzer: "down" | "auth"; log: AnalyzerLog };
export function analyzerSummary(
  get: (path: string) => Promise<{ ok: boolean; status: number; json: () => Promise<unknown> }>,
): Promise<AnalyzerSummary>;
