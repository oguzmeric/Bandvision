"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

type NavItem = { href: string; label: string; icon: React.ReactNode; soon?: boolean };

const icon = (d: string) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round"
       strokeLinejoin="round" className="h-5 w-5" aria-hidden="true">
    <path d={d} />
  </svg>
);

const NAV: NavItem[] = [
  { href: "/live", label: "Canlı sayım", icon: icon("M12 12m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0M6.3 6.3a8 8 0 0 0 0 11.4M17.7 6.3a8 8 0 0 1 0 11.4M3.5 3.5a12 12 0 0 0 0 17M20.5 3.5a12 12 0 0 1 0 17") },
  { href: "/cameras", label: "Kameralar", icon: icon("M3 7h11a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H3zM16 11l5-3v8l-5-3M6 11h.01") },
  // siren (kubbe, taban, ışık çizgileri); kalkan simgesi "Kalite"de kullanılıyor
  { href: "/alarms", label: "Alarmlar", icon: icon("M7 18v-6a5 5 0 0 1 10 0v6M5 18h14v3H5zM12 12v3M12 2v2M4.2 5.2l1.4 1.4M19.8 5.2l-1.4 1.4M2 12h2M20 12h2") },
  { href: "/notifications", label: "Bildirimler", icon: icon("M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0") },
  { href: "/videos", label: "Video analizi", icon: icon("M4 6h11a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2zM17 10l5-3v10l-5-3") },
  { href: "/quality", label: "Kalite (NOK)", icon: icon("M12 3l8 4v5c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V7zM9 12l2 2 4-4"), soon: true },
  { href: "/reports", label: "Raporlar", icon: icon("M4 20V10M10 20V4M16 20v-7M22 20H2"), soon: true },
];

export default function Sidebar({ canLogout = false }: { canLogout?: boolean }) {
  const path = usePathname();
  return (
    <aside className="sticky top-0 flex h-screen flex-col items-center gap-2.5 border-r border-line bg-white py-4">
      <Link href="/videos" aria-label="BandVision ana sayfa" className="mb-4">
        <Image src="/brand/logo-mark.png" alt="BandVision" width={46} height={36} priority />
      </Link>
      <nav className="flex flex-col items-center gap-2.5" aria-label="Ana menü">
        {NAV.map((item) => {
          const active = path?.startsWith(item.href);
          const base = "grid h-10 w-10 place-items-center rounded-xl transition";
          if (item.soon) {
            return (
              <span key={item.href} title={`${item.label} (yakında)`} aria-disabled="true"
                    className={`${base} cursor-not-allowed text-faint/60`}>
                {item.icon}
                <span className="sr-only">{item.label} (yakında)</span>
              </span>
            );
          }
          return (
            <Link key={item.href} href={item.href} title={item.label} aria-current={active ? "page" : undefined}
                  className={`${base} ${active
                    ? "bg-brand-500 text-white shadow-[0_6px_14px_rgba(109,59,240,0.25)]"
                    : "text-muted hover:bg-brand-50 hover:text-brand-500"}`}>
              {item.icon}
              <span className="sr-only">{item.label}</span>
            </Link>
          );
        })}
      </nav>
      {canLogout && (
        <button type="button" title="Çıkış" aria-label="Çıkış"
                onClick={async () => {
                  await fetch("/api/logout", { method: "POST" }).catch(() => undefined);
                  window.location.assign("/login");          // göreli: ana makine adı değişmez
                }}
                className="mt-auto grid h-10 w-10 place-items-center rounded-xl text-muted transition hover:bg-brand-50 hover:text-brand-500">
          {icon("M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9")}
        </button>
      )}
    </aside>
  );
}
