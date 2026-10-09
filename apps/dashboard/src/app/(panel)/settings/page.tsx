import type { Metadata } from "next";
import PageHeader from "@/components/PageHeader";
import AccessSettings from "@/components/settings/AccessSettings";

export const metadata: Metadata = { title: "Ayarlar" };

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader eyebrow="AYARLAR" title="Ayarlar"
                  text="Panelin ofis ağındaki telefon ve bilgisayarlardan açılması ve şifresi." />
      <AccessSettings />
    </div>
  );
}
