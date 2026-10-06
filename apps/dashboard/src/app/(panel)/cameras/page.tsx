import type { Metadata } from "next";
import CamerasView from "@/components/live/CamerasView";
import PageHeader from "@/components/PageHeader";

export const metadata: Metadata = { title: "Kameralar" };

export default function CamerasPage() {
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader eyebrow="KAMERALAR" title="Kameralar ve kayıt cihazları"
                  text="Kayıt cihazını (TRASSIR, Hikvision, Dahua) ya da IP kamerayı ekle; kameralar küçük resimleriyle listelenir. Birini seçip canlı sayımı başlat." />
      <CamerasView />
    </div>
  );
}
