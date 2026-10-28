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
      { label: "Bildirimler (Telegram)", href: "/notifications" },
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
