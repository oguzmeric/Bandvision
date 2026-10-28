import type { Metadata } from "next";
import { Suspense } from "react";
import LiveView from "@/components/live/LiveView";
import PageHeader from "@/components/PageHeader";
import { KIND_TITLE, parseKind } from "@/lib/analysisKind";

export const metadata: Metadata = { title: "Canlı sayım" };

type Props = { searchParams: Promise<{ tur?: string | string[] }> };

export default async function LivePage({ searchParams }: Props) {
  const { tur } = await searchParams;
  const kind = parseKind(typeof tur === "string" ? tur : null);
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title={kind ? KIND_TITLE[kind] : "Canlı sayım"}
                  text={kind
                    ? "Bu türdeki açık analizler. Kamerada yeni analiz başlatmak için “Yeni analiz”."
                    : "Kayıt cihazındaki ya da IP kameradaki görüntü bu bilgisayarda sayılır. Alanı ve çizgiyi görüntü üstünde ayarla; telefondaki ile aynı algoritma."} />
      <Suspense fallback={<div className="h-64 animate-pulse rounded-3xl bg-white/70" />}>
        <LiveView />
      </Suspense>
    </div>
  );
}
