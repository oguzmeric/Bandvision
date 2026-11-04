export type AnalyzerRefusalCode = "analyzer_key" | "analyzer_host";
export type AnalyzerProblem = "auth" | "down" | "key" | "host";
export const ANALYZER_REFUSALS: Record<AnalyzerRefusalCode, string>;
export function refusalFor(status: number): { code: AnalyzerRefusalCode; detail: string } | null;
export function problemFrom(status: number, code: string | null | undefined): AnalyzerProblem;
export function refusalText(problem: AnalyzerProblem): string | null;
export const UNKNOWN_ANALYSIS: string;
export function optionsRefusal(status: number, detail: unknown): string | null;
export function bearerHeader(token: string | null | undefined): string | null;
