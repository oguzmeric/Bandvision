/**
 * Tek şifreli panel girişi (yayına hazırlık; docs/13-web-platform.md).
 * `DASHBOARD_PASSWORD` tanımlıysa panelin tüm sayfaları ve API'si giriş ister; tanımlı değilse (yerel demo) açık.
 * Oturum çerezi şifreden türetilir: şifre değişince tüm oturumlar düşer. Edge (middleware) ve Node'da çalışır.
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

/** Yalnızca bu sitedeki bir yola yönlendir (açık yönlendirme olmasın). */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return "/videos";
  return next;
}
