import { Suspense } from "react";
import type { Metadata } from "next";
import ArchiveView from "@/components/archive/ArchiveView";

export const metadata: Metadata = { title: "Kayıttan izleme" };

export default function ArchivePage() {
  // Derin bağlantı (`?source=&channel=&t=`) `useSearchParams` ile okunur: istemcide çizilir
  return (
    <Suspense fallback={null}>
      <ArchiveView />
    </Suspense>
  );
}
