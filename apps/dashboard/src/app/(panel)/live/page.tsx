import type { Metadata } from "next";
import { Suspense } from "react";
import LiveView from "@/components/live/LiveView";
import PageHeader from "@/components/PageHeader";
import { KIND_TITLE, parseKind } from "@/lib/analysisKind";

type Props = { searchParams: Promise<{ tur?: string | string[] }> };

/** Menüdeki öğenin adı = sayfa başlığı = sekme adı: `?tur=kisi` "Kişi sayımı"; süzmesiz `/live` "Canlı sayım" */
async function title(searchParams: Props["searchParams"]): Promise<string> {
  const kind = parseKind((await searchParams).tur);
  return kind ? KIND_TITLE[kind] : "Canlı sayım";
}

export async function generateMetadata({ searchParams }: Props): Promise<Metadata> {
  return { title: await title(searchParams) };
}

export default async function LivePage({ searchParams }: Props) {
  const kind = parseKind((await searchParams).tur);
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title={await title(searchParams)}
                  text={kind
                    ? "Bu türdeki açık analizler. Kamerada yeni analiz başlatmak için “Yeni analiz”."
                    : "Kayıt cihazındaki ya da IP kameradaki görüntü bu bilgisayarda sayılır. Alanı ve çizgiyi görüntü üstünde ayarla; telefondaki ile aynı algoritma."} />
      <Suspense fallback={<div className="h-64 animate-pulse rounded-[3px] border border-pl-line-soft bg-pl-side" />}>
        <LiveView />
      </Suspense>
    </div>
  );
}
