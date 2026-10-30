import type { Metadata } from "next";
import PageHeader from "@/components/PageHeader";
import AnalyzerVersion from "@/components/about/AnalyzerVersion";
import { PANEL_VERSION, getPanelCommit } from "@/lib/panelVersion";

export const metadata: Metadata = { title: "Hakkında" };

/** Sürüm bilgisi: panel sürümü sunucuda okunur (analiz sunucusu kapalıyken de görünür), analiz sunucusununki tarayıcıda istenir. */
export default async function AboutPage() {
  const commit = await getPanelCommit();
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="Hakkında" text="BandVision panelinin ve analiz sunucusunun sürümü." />
      <section className="pl-section max-w-2xl">
        <h2>Sürüm</h2>
        <div className="pl-row">
          <span>Panel</span>
          <span data-testid="about-panel">{PANEL_VERSION} ({commit})</span>
        </div>
        <div className="pl-row">
          <span>Analiz sunucusu</span>
          <AnalyzerVersion />
        </div>
      </section>
    </div>
  );
}
