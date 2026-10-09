import type { Metadata } from "next";
import WatchView from "@/components/watch/WatchView";

export const metadata: Metadata = { title: "İzleme" };

export default function WatchPage() {
  return <div className="mx-auto max-w-[1600px]"><WatchView /></div>;
}
