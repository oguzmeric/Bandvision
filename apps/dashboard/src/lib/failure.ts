import { problemFrom } from "./analyzerRefusal.mjs";

/**
 * Başarısız bir panel isteğinin ekranda görünecek hali: metin, ya da panelin KENDİ 401'i (oturum doldu; `AUTH_LOST`).
 * Oturum doluşu metin değil nesnedir: ekran "Giriş yap" bağlantısını (`ConnectionProblem`) onunla çizer. Analiz sunucusunun
 * reddi (vekilin 502 + `analyzer_key`/`analyzer_host`) ise metindir ve giriş bağlantısı taşımaz.
 */
export type Failure = string | { readonly auth: true };
export const AUTH_LOST: Failure = { auth: true };

/** Hata gövdesindeki okunur metin: vekilin/analiz sunucusunun `detail`ı ya da panelin kendi reddinin `error`ı; yoksa undefined */
export function bodyText(body: unknown): string | undefined {
  const { detail, error } = (body ?? {}) as { detail?: unknown; error?: unknown };
  if (typeof detail === "string") return detail;
  return typeof error === "string" ? error : undefined;
}

/** Hata yanıtı → gösterilecek hal. `fallback`: gövde okunur bir metin taşımıyorsa (JSON değil, boş) yazılacak ileti */
export function failureOf(status: number, body: unknown, fallback: string): Failure {
  const code = (body as { code?: unknown } | null)?.code;
  if (problemFrom(status, typeof code === "string" ? code : null) === "auth") return AUTH_LOST;
  return bodyText(body) ?? fallback;
}
