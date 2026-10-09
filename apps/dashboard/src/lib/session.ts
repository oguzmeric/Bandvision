/**
 * Tek şifreli panel girişi (yayına hazırlık; docs/13-web-platform.md).
 * `DASHBOARD_PASSWORD` tanımlıysa panelin tüm sayfaları ve API'si giriş ister; tanımlı değilse (yerel demo) açık.
 * Oturum çerezi şifreden türetilir: şifre değişince tüm oturumlar düşer. Edge (middleware) ve Node'da çalışır.
 * Telefondan erişim açıkken (Ayarlar) başlatıcı şifrenin yalnızca scrypt özetini ve rastgele bir oturum sırrını verir
 * (hash kipi); `DASHBOARD_PASSWORD` tanımlıysa o önceliklidir. Edge'de `node:crypto` yok: yalnızca Web Crypto kullanılır.
 */
export const SESSION_COOKIE = "bv_session";
export const SESSION_MAX_AGE = 7 * 24 * 60 * 60; // 7 gün

export function panelPassword(): string | null {
  const pw = process.env.DASHBOARD_PASSWORD;
  return pw && pw.length > 0 ? pw : null;
}

export async function sessionToken(password: string): Promise<string> {
  const data = new TextEncoder().encode(`bandvision-panel:v1:${password}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Giriş türü: ortamdaki DASHBOARD_PASSWORD (öncelikli) ya da başlatıcının verdiği şifre özeti + oturum sırrı. */
export type AuthMode = { kind: "env"; password: string } | { kind: "hash"; secret: string; salt: string; hash: string } | null;

export function authMode(): AuthMode {
  const pw = panelPassword();
  if (pw) return { kind: "env", password: pw };
  const secret = process.env.PANEL_SESSION_SECRET, salt = process.env.PANEL_PASSWORD_SALT, hash = process.env.PANEL_PASSWORD_HASH;
  return secret && salt && hash ? { kind: "hash", secret, salt, hash } : null;
}

/** Beklenen oturum çerezi: env kipinde şifreden (eskisi gibi), hash kipinde sırdan HMAC (şifre değişince sır da değişir) */
export async function expectedToken(mode: NonNullable<AuthMode>): Promise<string> {
  if (mode.kind === "env") return sessionToken(mode.password);
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(mode.secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode("bandvision-panel:v2"));
  return Array.from(new Uint8Array(sig), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Çerez değerini sabit sürede karşılaştır (zamanlamadan belirteç sızmasın). Edge'de timingSafeEqual yok. */
export function sameToken(given: string | undefined, expected: string): boolean {
  if (given === undefined || given.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) diff |= given.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0;
}

/** Yalnızca bu sitedeki bir yola yönlendir (açık yönlendirme olmasın). */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return "/videos";
  return next;
}
