export interface Access { enabled: boolean; salt?: string; hash?: string; secret?: string; updatedAt?: number }
export const MIN_PASSWORD: number;
export function hashPassword(pw: string): { salt: string; hash: string };
export function verifyPassword(pw: string, salt: string | undefined, hash: string | undefined): boolean;
export function newSecret(): string;
export function accessFile(env: Record<string, string | undefined>, cwd: string): string;
export function panelPlan(access: Access | null, env: Record<string, string | undefined>): { host: "127.0.0.1" | "0.0.0.0"; env: Record<string, string> };
export function updateAccess(
  cur: Access | null,
  body: { enabled?: unknown; password?: unknown } | null,
  envPassword: boolean,
  now?: number,
): { next: Access } | { error: string; status: 422 };
