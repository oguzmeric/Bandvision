import { Suspense } from "react";
import Sidebar from "@/components/Sidebar";
import AlarmBanner from "@/components/live/AlarmBanner";
import { panelPassword } from "@/lib/session";

// Şifre (DASHBOARD_PASSWORD) derlemede değil çalışırken okunur: "Çıkış" düğmesi ona göre
export const dynamic = "force-dynamic";

export default function PanelLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="grid min-h-screen grid-cols-[72px_1fr]">
      <Sidebar canLogout={panelPassword() !== null} />
      {/* Alarm şeridi main içinde yapışkan (sticky): main'in hiçbir atası overflow kırpmamalı */}
      <main className="min-w-0 px-5 py-6 md:px-9 md:py-7"><Suspense fallback={null}><AlarmBanner /></Suspense>{children}</main>
    </div>
  );
}
