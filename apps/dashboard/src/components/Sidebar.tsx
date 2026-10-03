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
  { href: "/lines", label: "Hatlar", icon: icon("M3 6h18M3 12h18M3 18h12"), soon: true },
  { href: "/videos", label: "Video analizi", icon: icon("M4 6h11a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2zM17 10l5-3v10l-5-3") },
  { href: "/quality", label: "Kalite (NOK)", icon: icon("M12 3l8 4v5c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V7zM9 12l2 2 4-4"), soon: true },
  { href: "/reports", label: "Raporlar", icon: icon("M4 20V10M10 20V4M16 20v-7M22 20H2"), soon: true },
  { href: "/devices", label: "Cihazlar", icon: icon("M8 2h8a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zM11 18h2"), soon: true },
];

export default function Sidebar() {
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
    </aside>
  );
}
