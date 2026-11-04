import type { Metadata } from "next";
import DeviceSettings from "@/components/devices/DeviceSettings";
import PageHeader from "@/components/PageHeader";

export const metadata: Metadata = { title: "Cihaz ayarları" };

export default function DevicesPage() {
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="Cihaz ayarları"
                  text="Kişi ve araç tanıma ile poz modelleri ekran kartında çalışabilir. Ürün sayımı model kullanmaz, işlemcide çalışır." />
      <DeviceSettings />
    </div>
  );
}
