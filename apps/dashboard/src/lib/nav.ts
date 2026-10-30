/** Soldaki yazılı menünün öğesi. `href: null` + `soon`: gri, tıklanınca "yakında" der (sayfası henüz yok). */
export type NavItem = { label: string; href: string | null; soon?: boolean };
export type NavGroup = { title: string; items: NavItem[] };

/** Menü grupları ve öğeleri (spec "Menü grupları", onaylı taslak duzen.html); sıra burada belirlenir. */
export const NAV: NavGroup[] = [
  {
    title: "İzleme",
    items: [
      { label: "Canlı izleme", href: "/watch" },
      { label: "Alarmlar", href: "/alarms" },
    ],
  },
  {
    title: "Analizler",
    items: [
      { label: "Ürün sayımı", href: "/live?tur=urun" },
      { label: "Kişi sayımı", href: "/live?tur=kisi" },
      { label: "Güvenlik alarmı (poz)", href: "/live?tur=guvenlik" },
      { label: "Yangın ve duman", href: null, soon: true },
      { label: "Kalite kontrol", href: null, soon: true },
      { label: "Video ile test", href: "/videos" },
      { label: "Raporlar", href: null, soon: true },
    ],
  },
  {
    title: "Donanım",
    items: [
      { label: "Kameralar ve kayıt cihazları", href: "/cameras" },
      { label: "Cihaz ayarları", href: null, soon: true },
    ],
  },
  {
    title: "Sistem",
    items: [
      { label: "Bildirimler", href: "/notifications" },
      { label: "Telefondan erişim", href: "/settings" },
      { label: "Lisans", href: null, soon: true },
      { label: "Hakkında", href: "/about" },
    ],
  },
];

/**
 * Öğe şu anki sayfa mı: sorgusuz öğe yol (ve alt yolları) ile, sorgulu öğe (`/live?tur=kisi`) yol + sorgudaki her
 * parametre ile eşleşir. Böylece `/live?tur=kisi`de yalnızca "Kişi sayımı" seçili olur; süzmesiz `/live`de hiçbiri.
 */
export function isCurrent(href: string, pathname: string, params: URLSearchParams): boolean {
  const [path, query] = href.split("?", 2);
  if (query === undefined) return pathname === path || pathname.startsWith(`${path}/`);
  if (pathname !== path) return false;
  for (const [k, v] of new URLSearchParams(query)) if (params.get(k) !== v) return false;
  return true;
}

/**
 * Kapalı menü gruplarının başlıkları bu tarayıcıda çerezde tutulur: sunucu menüyü ilk çizimde doğru (kapalı) çizer, grup
 * sayfa açılırken bir an açık görünüp kapanmaz. (Önceki sürüm `localStorage` `bv.nav.collapsed` kullanıyordu; çerez yoksa
 * menü onu bir kez taşır.)
 */
export const NAV_COOKIE = "bv_nav_collapsed";
export const NAV_LEGACY_KEY = "bv.nav.collapsed";

/** Çerezin (ya da eski deponun) değeri → başlıklar; değer yoksa null, bozuksa boş liste */
export function parseCollapsed(raw: string | null | undefined): string[] | null {
  if (raw === null || raw === undefined) return null;
  try {
    const text = raw.includes("%") ? decodeURIComponent(raw) : raw;
    const v: unknown = JSON.parse(text);
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

/** `document.cookie`'ye yazılacak çerez (1 yıl, tüm panel) */
export function collapsedCookie(titles: string[]): string {
  return `${NAV_COOKIE}=${encodeURIComponent(JSON.stringify(titles))}; Path=/; Max-Age=31536000; SameSite=Lax`;
}
