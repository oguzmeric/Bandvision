import type { Metadata } from "next";
import { Suspense } from "react";
import LiveView from "@/components/live/LiveView";
import PageHeader from "@/components/PageHeader";

export const metadata: Metadata = { title: "Canlı sayım" };

export default function LivePage() {
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader eyebrow="CANLI SAYIM" title="Kameradan canlı sayım"
                  text="Kayıt cihazındaki ya da IP kameradaki görüntü bu bilgisayarda sayılır. Alanı ve çizgiyi görüntü üstünde ayarla; telefondaki ile aynı algoritma." />
      <Suspense fallback={<div className="h-64 animate-pulse rounded-3xl bg-white/70" />}>
        <LiveView />
      </Suspense>
    </div>
  );
}
