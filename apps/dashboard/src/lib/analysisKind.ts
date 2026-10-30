import type { CountMode } from "@/lib/types";

/** Menüdeki analiz türü: `/live?tur=urun|kisi|guvenlik` (Canlı sayımın türe süzülmüş hali) */
export type AnalysisKind = "urun" | "kisi" | "guvenlik";

/** Oturumun profil yöntemine göre tür: blob/linescan ürün, detect kişi, safety güvenlik */
export function kindOfMode(mode: CountMode): AnalysisKind {
  if (mode === "detect") return "kisi";
  return mode === "safety" ? "guvenlik" : "urun";
}

/** Sayfa başlığı ve sekme adı: menüdeki öğenin adı (src/lib/nav.ts) */
export const KIND_TITLE: Record<AnalysisKind, string> = {
  urun: "Ürün sayımı",
  kisi: "Kişi sayımı",
  guvenlik: "Güvenlik alarmı (poz)",
};

/** Cümle içinde tür adı ("Henüz … yok.") */
export const KIND_NOUN: Record<AnalysisKind, string> = {
  urun: "ürün sayımı",
  kisi: "kişi sayımı",
  guvenlik: "güvenlik alarmı",
};

/** Başlatma penceresindeki profil kataloğu kategorisi (`/api/live/catalog` kimliği) */
export const KIND_CATEGORY: Record<AnalysisKind, string> = { urun: "belt", kisi: "people", guvenlik: "safety" };

/**
 * `?tur=` değeri; geçersiz ya da yoksa `null` (süzme yok, eski bağlantılar çalışır). Tekrarlanan parametrede (`?tur=a&tur=b`)
 * ilki geçerlidir (sunucu dizi verir, tarayıcının `URLSearchParams.get` de ilkini).
 */
export function parseKind(q: string | string[] | null | undefined): AnalysisKind | null {
  const v = Array.isArray(q) ? q[0] : q;
  return v === "urun" || v === "kisi" || v === "guvenlik" ? v : null;
}
