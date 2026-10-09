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
export function buildIsStale(dashDir: string): boolean;
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
