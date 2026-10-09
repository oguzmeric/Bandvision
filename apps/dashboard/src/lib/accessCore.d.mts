export interface Access { enabled: boolean; salt?: string; hash?: string; secret?: string; updatedAt?: number }
export const MIN_PASSWORD: number;
export const MAX_PASSWORD: number;
export function hashPassword(pw: string): { salt: string; hash: string };
export function verifyPassword(pw: string, salt: string | undefined, hash: string | undefined): boolean;
export function verifyPasswordAsync(pw: string, salt: string | undefined, hash: string | undefined): Promise<boolean>;
export function newSecret(): string;
export function accessFile(env: Record<string, string | undefined>, cwd: string): string;
export function panelPlan(access: Access | null, env: Record<string, string | undefined>): { host: "127.0.0.1" | "0.0.0.0"; env: Record<string, string> };
export function panelCommand(plan: { host: string }, opts?: { prod?: boolean }): { mode: "dev" | "start"; host: "127.0.0.1" | "0.0.0.0" };
export const LAUNCHER_DIST: string;
export const BUILD_MARKER: string;
export function buildIsStale(dashDir: string, distDir?: string): boolean;
export function middlewareReady(manifestText: string | null | undefined): boolean;
export const LOCK_HEARTBEAT_MS: number;
export const LOCK_STALE_MS: number;
export const LOCK_FRESH_MS: number;
export function lockDecision(existingPid: number | null | undefined, alive: boolean, ageMs?: number): "running" | "stale";
export type PanelBuildState = "building" | "failed" | "listening";
export function panelStateFile(env: Record<string, string | undefined>, cwd: string): string;
export function panelState(text: string | null | undefined): { state: PanelBuildState; message: string } | null;
export function isJsonContentType(value: string | null | undefined): boolean;
export interface LoginThrottle {
  /** 0: deneme başlatıldı (bitince `end` çağır). >0: kilitli, beklenecek ms (scrypt çalıştırma). */
  begin(): number;
  end(ok: boolean): void;
}
export function createLoginThrottle(opts?: { now?: () => number; free?: number; baseMs?: number; maxMs?: number }): LoginThrottle;
export function hostAllowed(hostHeader: string | null | undefined, ownIps?: string[]): boolean;
export function updateAccess(
  cur: Access | null,
  body: { enabled?: unknown; password?: unknown } | null,
  envPassword: boolean,
  now?: number,
): { next: Access } | { error: string; status: 422 };
