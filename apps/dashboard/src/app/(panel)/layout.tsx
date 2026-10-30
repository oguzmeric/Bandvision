import { cookies } from "next/headers";
import { Suspense } from "react";
import Sidebar from "@/components/Sidebar";
import StatusBar from "@/components/StatusBar";
import { UnsavedGuardProvider } from "@/components/UnsavedGuard";
import AlarmBanner from "@/components/live/AlarmBanner";
import AlarmCenter from "@/components/live/AlarmCenter";
import { NAV_COOKIE, parseCollapsed } from "@/lib/nav";
import { authMode } from "@/lib/session";

// Şifre (DASHBOARD_PASSWORD ya da telefondan erişim şifresi) derlemede değil çalışırken okunur: "Çıkış" düğmesi ona göre
export const dynamic = "force-dynamic";

export default async function PanelLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  // Kapalı menü grupları (çerez): menü ilk çizimde doğru, açık görünüp kapanmaz
  const collapsed = parseCollapsed((await cookies()).get(NAV_COOKIE)?.value);
  return (
    // Dar ekranda: üstte menü çubuğu, altında içerik; md ve üstünde: 230 px menü sütunu + içerik. Kaydedilmemiş değişiklik
    // bekçisi (Canlı izleme şablon düzenleyicisi) menüyü ve içeriği kapsar: oradaki bağlantılar da sorar.
    <UnsavedGuardProvider>
      <div className="grid min-h-screen grid-cols-1 grid-rows-[auto_1fr] md:grid-cols-[230px_1fr] md:grid-rows-1">
        <Sidebar canLogout={authMode() !== null} collapsed={collapsed} />
        {/* Alarm şeridi main içinde yapışkan (sticky): main'in hiçbir atası overflow kırpmamalı. AlarmCenter alarmları
            tek yoklamayla alır; şerit ve alarm penceresi aynı veriyi gösterir. Durum şeridi en altta yapışkan. */}
        <div data-panel-content="" className="flex min-w-0 flex-col">
          <main className="min-w-0 flex-1 px-5 py-6 md:px-9 md:py-7">
            <AlarmCenter>
              <Suspense fallback={null}><AlarmBanner /></Suspense>
              {children}
            </AlarmCenter>
          </main>
          <StatusBar />
        </div>
      </div>
    </UnsavedGuardProvider>
  );
}
