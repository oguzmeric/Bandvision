import type { Metadata } from "next";
import Image from "next/image";
import VideoAnalysis from "@/components/video/VideoAnalysis";

export const metadata: Metadata = { title: "Video analizi" };

export default function VideosPage() {
  return (
    <div className="mx-auto max-w-[1280px]">
      <div className="mb-4 flex items-center gap-2.5">
        <Image src="/brand/logo-mark.png" alt="" width={34} height={26} />
        <span className="text-[17px] font-semibold">Band<span className="text-brand-500">Vision</span></span>
      </div>
      <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-50 px-2.5 py-1 text-[11px] font-semibold tracking-wider text-brand-500">
        <i className="h-1.5 w-1.5 rounded-full bg-brand-500" />VİDEO ANALİZİ
      </span>
      <h1 className="mt-2.5 text-2xl font-semibold">Videodan sayım ve doğruluk</h1>
      <p className="mb-6 mt-1 max-w-3xl text-sm text-muted">
        Banttan çekilmiş bir videoyu yükle; telefondaki ile aynı algoritma sayar, işaretli videoyu ve sonuçları gösterir.
        Sayılan her ürünün üstünde sıra numarası görünür.
      </p>
      <VideoAnalysis />
    </div>
  );
}
