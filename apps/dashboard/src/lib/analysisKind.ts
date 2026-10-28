import type { CountMode } from "@/lib/types";

/** Menüdeki analiz türü: `/live?tur=urun|kisi|guvenlik` (Canlı sayımın türe süzülmüş hali) */
export type AnalysisKind = "urun" | "kisi" | "guvenlik";

/** Oturumun profil yöntemine göre tür: blob/linescan ürün, detect kişi, safety güvenlik */
export function kindOfMode(mode: CountMode): AnalysisKind {
  if (mode === "detect") return "kisi";
  return mode === "safety" ? "guvenlik" : "urun";
}

/** Sayfa başlığı */
export const KIND_TITLE: Record<AnalysisKind, string> = {
  urun: "Ürün sayımı",
  kisi: "Kişi sayımı",
  guvenlik: "Güvenlik alarmı",
};

/** Başlatma penceresindeki profil kataloğu kategorisi (`/api/live/catalog` kimliği) */
export const KIND_CATEGORY: Record<AnalysisKind, string> = { urun: "belt", kisi: "people", guvenlik: "safety" };

/** `?tur=` değeri; geçersiz ya da yoksa `null` (süzme yok, eski bağlantılar çalışır) */
export function parseKind(q: string | null): AnalysisKind | null {
  return q === "urun" || q === "kisi" || q === "guvenlik" ? q : null;
}
