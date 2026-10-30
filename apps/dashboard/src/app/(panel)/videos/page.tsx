import type { Metadata } from "next";
import PageHeader from "@/components/PageHeader";
import VideoAnalysis from "@/components/video/VideoAnalysis";

export const metadata: Metadata = { title: "Video ile test" };

export default function VideosPage() {
  return (
    <div className="mx-auto max-w-[1280px]">
      <PageHeader title="Video ile test"
                  text="Banttan çekilmiş bir videoyu yükle; telefondaki ile aynı algoritma sayar, işaretli videoyu ve sonuçları gösterir. Sayılan her ürünün üstünde sıra numarası görünür." />
      <VideoAnalysis />
    </div>
  );
}
