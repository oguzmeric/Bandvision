import type { Metadata } from "next";
import WatchView from "@/components/watch/WatchView";

export const metadata: Metadata = { title: "Canlı izleme" };

export default function WatchPage() {
  return <WatchView />;
}
