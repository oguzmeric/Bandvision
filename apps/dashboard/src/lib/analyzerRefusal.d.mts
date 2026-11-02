export type AnalyzerRefusalCode = "analyzer_key" | "analyzer_host";
export type AnalyzerProblem = "auth" | "down" | "key" | "host";
export const ANALYZER_REFUSALS: Record<AnalyzerRefusalCode, string>;
export function refusalFor(status: number): { code: AnalyzerRefusalCode; detail: string } | null;
export function problemFrom(status: number, code: string | null | undefined): AnalyzerProblem;
export function refusalText(problem: AnalyzerProblem): string | null;
export function bearerHeader(token: string | null | undefined): string | null;
