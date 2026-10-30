import type { Metadata } from "next";
import PageHeader from "@/components/PageHeader";
import AccessSettings from "@/components/settings/AccessSettings";

export const metadata: Metadata = { title: "Telefondan erişim" };

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="Telefondan erişim"
                  text="Panelin ofis ağındaki telefon ve bilgisayarlardan açılması ve şifresi." />
      <AccessSettings />
    </div>
  );
}
