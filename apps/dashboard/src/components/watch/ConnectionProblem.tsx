"use client";

import { usePathname } from "next/navigation";
import type { Problem } from "@/lib/views";

export const DOWN_TEXT = "Analiz sunucusuna ulaşılamıyor; yeniden deneniyor…";
export const AUTH_TEXT = "Oturum süresi doldu — yeniden giriş yapın.";

/**
 * Analiz sunucusuyla konuşulamıyor: sunucu yok ("yeniden deneniyor") ile oturum süresi dolmuş (401: yeniden denemek
 * işe yaramaz, giriş sayfasına bağlantı) ayrı söylenir; `AlarmBanner` ile aynı ayrım. Yalnız metin; kabı çağıran çizer.
 */
export default function ConnectionProblem({ problem }: { problem: Problem }) {
  const path = usePathname();
  if (problem === "down") return <>{DOWN_TEXT}</>;
  return (
    <>
      {AUTH_TEXT}{" "}
      <a href={`/login?next=${encodeURIComponent(path || "/watch")}`} className="pointer-events-auto font-semibold underline">Giriş yap</a>
    </>
  );
}
