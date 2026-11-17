import type { CountMode } from "@/lib/types";

/**
 * Menüdeki analiz türü: `/live?tur=urun|kisi|guvenlik|telefon|yangin` (Canlı sayımın türe süzülmüş hali). `telefon`,
 * güvenlik modunun telefon kuralı açık kameralarıdır (ayrı bir yöntem değil; kamera "Güvenlik alarmı (poz)"da da görünür).
 */
export type AnalysisKind = "urun" | "kisi" | "guvenlik" | "telefon" | "yangin";

/** Oturumun profil yöntemine göre tür: blob/linescan ürün, detect kişi, safety güvenlik, fire yangın/duman */
export function kindOfMode(mode: CountMode): AnalysisKind {
  if (mode === "detect") return "kisi";
  if (mode === "fire") return "yangin";
  return mode === "safety" ? "guvenlik" : "urun";
}

/** Profil bu türün listesinde mi: yöntem eşleşir; `telefon` için ayrıca telefon kuralı açık olmalı */
export function matchesKind(p: { countMode?: CountMode; safety?: { phone?: { enabled?: boolean } } }, kind: AnalysisKind): boolean {
  const own = kindOfMode(p.countMode ?? "blob");
  if (kind === "telefon") return own === "guvenlik" && p.safety?.phone?.enabled === true;
  return own === kind;
}

/** Sayfa başlığı ve sekme adı: menüdeki öğenin adı (src/lib/nav.ts) */
export const KIND_TITLE: Record<AnalysisKind, string> = {
  urun: "Ürün sayımı",
  kisi: "Kişi sayımı",
  guvenlik: "Güvenlik alarmı (poz)",
  telefon: "Telefon kullanımı",
  yangin: "Yangın / duman",
};

/** Cümle içinde tür adı ("Henüz … yok.") */
export const KIND_NOUN: Record<AnalysisKind, string> = {
  urun: "ürün sayımı",
  kisi: "kişi sayımı",
  guvenlik: "güvenlik alarmı",
  telefon: "telefon kullanımı izlemesi",
  yangin: "yangın/duman izlemesi",
};

/** Başlatma penceresindeki profil kataloğu kategorisi (`/api/live/catalog` kimliği) */
export const KIND_CATEGORY: Record<AnalysisKind, string> = {
  urun: "belt", kisi: "people", guvenlik: "safety", telefon: "safety", yangin: "fire",
};

/** Türün yönteme göre ana türü (`telefon` bir güvenlik kamerasıdır) */
export const KIND_MODE_OF: Record<AnalysisKind, AnalysisKind> = {
  urun: "urun", kisi: "kisi", guvenlik: "guvenlik", telefon: "guvenlik", yangin: "yangin",
};

/** Başlatma penceresinde yalnız bu hazır profil sunulur (yoksa kategorinin hepsi) */
export const KIND_PRESET: Partial<Record<AnalysisKind, string>> = { telefon: "phone" };

/**
 * `?tur=` değeri; geçersiz ya da yoksa `null` (süzme yok, eski bağlantılar çalışır). Tekrarlanan parametrede (`?tur=a&tur=b`)
 * ilki geçerlidir (sunucu dizi verir, tarayıcının `URLSearchParams.get` de ilkini).
 */
export function parseKind(q: string | string[] | null | undefined): AnalysisKind | null {
  const v = Array.isArray(q) ? q[0] : q;
  return v === "urun" || v === "kisi" || v === "guvenlik" || v === "telefon" || v === "yangin" ? v : null;
}
