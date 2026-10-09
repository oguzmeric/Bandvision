import { Suspense } from "react";
import Sidebar from "@/components/Sidebar";
import AlarmBanner from "@/components/live/AlarmBanner";
import AlarmCenter from "@/components/live/AlarmCenter";
import { authMode } from "@/lib/session";

// Şifre (DASHBOARD_PASSWORD ya da telefondan erişim şifresi) derlemede değil çalışırken okunur: "Çıkış" düğmesi ona göre
export const dynamic = "force-dynamic";

export default function PanelLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="grid min-h-screen grid-cols-[72px_1fr]">
      <Sidebar canLogout={authMode() !== null} />
      {/* Alarm şeridi main içinde yapışkan (sticky): main'in hiçbir atası overflow kırpmamalı. AlarmCenter alarmları
          tek yoklamayla alır; şerit ve alarm penceresi aynı veriyi gösterir. */}
      <main className="min-w-0 px-5 py-6 md:px-9 md:py-7">
        <AlarmCenter>
          <Suspense fallback={null}><AlarmBanner /></Suspense>
          {children}
        </AlarmCenter>
      </main>
    </div>
  );
}
