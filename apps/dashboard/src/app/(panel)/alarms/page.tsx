import type { Metadata } from "next";
import AlarmsView from "@/components/live/AlarmsView";
import PageHeader from "@/components/PageHeader";

export const metadata: Metadata = { title: "Alarmlar" };

export default function AlarmsPage() {
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader eyebrow="ALARMLAR" title="Alarmlar"
                  text="Güvenlik alarmlarının geçmişi (7 gün): ihlal anının kaydı, olay resmi, onay ve yanlış alarm işaretleri. Kayıtlar ve resimler yalnızca bu bilgisayarda saklanır." />
      <AlarmsView />
    </div>
  );
}
