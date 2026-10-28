"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { NAV, isCurrent, type NavItem } from "@/lib/nav";

/** Kapalı grupların başlıkları (JSON dizi); her tarayıcıda ayrı hatırlanır */
const COLLAPSED_KEY = "bv.nav.collapsed";
/** Gri öğeye tıklanınca "yakında" yazısı bu kadar görünür */
const SOON_MS = 3000;

function loadCollapsed(): string[] {
  try {
    const v: unknown = JSON.parse(window.localStorage.getItem(COLLAPSED_KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function saveCollapsed(titles: string[]): void {
  try {
    window.localStorage.setItem(COLLAPSED_KEY, JSON.stringify(titles));
  } catch {
    // depolama yok: yalnızca bu sayfa açıkken hatırlanır
  }
}

const ITEM = "block w-full rounded-[2px] border px-2 py-1 pl-6 text-left text-[13px] leading-5";

/**
 * Soldaki yazılı, gruplu menü (TRASSIR gibi; taslak duzen.html): üstte logo, gruplar açılır-kapanır, altta Çıkış.
 * Masaüstünde 230 px sütun; dar ekranda (md altı) üstteki "Menü" düğmesinin arkasına katlanır ve içeriğin üstünde açılır.
 */
export default function Sidebar({ canLogout = false }: { canLogout?: boolean }) {
  const pathname = usePathname() ?? "";
  const params = useSearchParams();
  const [collapsed, setCollapsed] = useState<string[]>([]);
  const [open, setOpen] = useState(false);
  const [soon, setSoon] = useState<string | null>(null);
  const soonTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // Depo yalnızca tarayıcıda okunur (sunucu çıktısıyla uyum için ilk çizimde tüm gruplar açık)
  useEffect(() => setCollapsed(loadCollapsed()), []);
  useEffect(() => () => clearTimeout(soonTimer.current), []);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const toggle = (title: string) => {
    const next = collapsed.includes(title) ? collapsed.filter((t) => t !== title) : [...collapsed, title];
    setCollapsed(next);
    saveCollapsed(next);
  };
  const showSoon = (label: string) => {
    clearTimeout(soonTimer.current);
    setSoon(label);
    soonTimer.current = setTimeout(() => setSoon(null), SOON_MS);
  };

  const renderItem = (item: NavItem) => {
    if (item.href === null || item.soon) {
      return (
        // aria-disabled değil: tıklanabilir olmalı (tıklanınca "yakında" der)
        <button type="button" data-label={item.label} data-soon="" onClick={() => showSoon(item.label)}
                className={`${ITEM} cursor-default border-transparent text-pl-faint`}>
          {item.label}
          {soon === item.label && <span role="status" className="ml-1.5 text-[11px] italic">yakında</span>}
        </button>
      );
    }
    const current = isCurrent(item.href, pathname, params);
    return (
      <Link href={item.href} data-label={item.label} aria-current={current ? "page" : undefined}
            onClick={() => setOpen(false)}
            className={`${ITEM} ${current
              ? "border-pl-sel-line bg-pl-sel text-pl-ink"
              : "border-transparent text-pl-ink hover:bg-pl-head"}`}>
        {item.label}
      </Link>
    );
  };

  return (
    <>
      {/* Dar ekran: üst çubuk (logo + Menü düğmesi) */}
      <div className="flex items-center gap-2 border-b border-pl-line bg-pl-side px-3 py-2 md:hidden">
        <button type="button" aria-expanded={open} aria-controls="bv-menu" onClick={() => setOpen((v) => !v)}
                className="pl-btn">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"
               className="h-4 w-4" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
          Menü
        </button>
        <span className="text-[15px] font-semibold text-pl-ink">Band<span className="text-pl-accent">Vision</span></span>
      </div>

      {/* Dar ekranda menü açıkken arka plan: tıklanınca kapanır */}
      {open && (
        <div data-testid="menu-backdrop" aria-hidden="true" onClick={() => setOpen(false)}
             className="fixed inset-0 z-50 bg-black/30 md:hidden" />
      )}

      <aside id="bv-menu" data-testid="sidebar"
             className={`${open ? "fixed inset-y-0 left-0 z-50 flex w-[230px] max-w-[85vw]" : "hidden"} flex-col border-r
                         border-pl-line bg-pl-side md:sticky md:top-0 md:bottom-auto md:h-screen md:z-auto md:flex md:w-auto md:max-w-none`}>
        <Link href="/videos" aria-label="BandVision ana sayfa" onClick={() => setOpen(false)}
              className="flex items-center gap-2 border-b border-pl-line px-3 py-2.5">
          <Image src="/brand/logo-mark.png" alt="" width={30} height={23} priority />
          <span className="text-[15px] font-semibold text-pl-ink">Band<span className="text-pl-accent">Vision</span></span>
        </Link>
        <nav aria-label="Ana menü" className="min-h-0 flex-1 overflow-y-auto py-1.5">
          {NAV.map((group, gi) => {
            const isCollapsed = collapsed.includes(group.title);
            const listId = `bv-nav-${gi}`;
            return (
              <div key={group.title} data-nav-group="">
                <button type="button" aria-expanded={!isCollapsed} aria-controls={listId} onClick={() => toggle(group.title)}
                        className="flex w-full items-center gap-1 px-2 pb-1 pt-2 text-left text-sm font-bold text-pl-ink hover:text-pl-accent">
                  <svg viewBox="0 0 12 12" aria-hidden="true"
                       className={`h-3 w-3 shrink-0 text-pl-muted transition-transform ${isCollapsed ? "-rotate-90" : ""}`}>
                    <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth={1.6} />
                  </svg>
                  {group.title}
                </button>
                <ul id={listId} hidden={isCollapsed} className="px-1">
                  {group.items.map((item) => <li key={item.label}>{renderItem(item)}</li>)}
                </ul>
              </div>
            );
          })}
        </nav>
        {canLogout && (
          <button type="button"
                  onClick={async () => {
                    await fetch("/api/logout", { method: "POST" }).catch(() => undefined);
                    window.location.assign("/login");          // göreli: ana makine adı değişmez
                  }}
                  className="flex items-center gap-2 border-t border-pl-line px-3 py-2 text-left text-[13px] text-pl-ink hover:bg-pl-head">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round"
                 strokeLinejoin="round" className="h-4 w-4 text-pl-muted" aria-hidden="true">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
            </svg>
            Çıkış
          </button>
        )}
      </aside>
    </>
  );
}
