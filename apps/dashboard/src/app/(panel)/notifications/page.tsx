import type { Metadata } from "next";
import AttentionSettings from "@/components/live/AttentionSettings";
import NotifySettings from "@/components/live/NotifySettings";
import PageHeader from "@/components/PageHeader";

export const metadata: Metadata = { title: "Bildirimler" };

export default function NotificationsPage() {
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader eyebrow="BİLDİRİMLER" title="Bildirimler"
                  text="Güvenlik alarmları (eller yukarı, yerde yatan kişi) panelde alarm penceresiyle ve Telegram'da kamera adı ve saatle görünür." />
      <NotifySettings />
      <AttentionSettings />
    </div>
  );
}
