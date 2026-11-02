"use client";

import { usePathname } from "next/navigation";
import { KEEP_UNSAVED_ATTR } from "@/components/UnsavedGuard";
import { refusalText } from "@/lib/analyzerRefusal.mjs";
import type { Problem } from "@/lib/views";

export const DOWN_TEXT = "Analiz sunucusuna ulaşılamıyor; yeniden deneniyor…";
export const AUTH_TEXT = "Oturum süresi doldu — yeniden giriş yapın.";

/**
 * Analiz sunucusuyla konuşulamıyor: sunucu yok ("yeniden deneniyor") ile oturum süresi dolmuş (401: yeniden denemek
 * işe yaramaz, giriş sayfasına bağlantı) ayrı söylenir; `AlarmBanner` ile aynı ayrım. Analiz sunucusu panelin anahtarını
 * ya da adresini reddettiyse ("key", "host") yalnızca ne düzeltileceği yazar: giriş işe yaramaz (yoklama sürer, ayar
 * düzeltilince yazı kalkar). Yalnız metin; kabı çağıran çizer.
 * "Giriş yap" kaydedilmemiş düzenlemeyi sormadan korur: girişten sonra Canlı izlemeye dönünce geri yüklenir.
 */
export default function ConnectionProblem({ problem }: { problem: Problem }) {
  const path = usePathname();
  switch (problem) {
    case "down":
      return <>{DOWN_TEXT}</>;
    case "key":
    case "host":
      return <>{refusalText(problem)}</>;
    case "auth":
      return (
        <>
          {AUTH_TEXT}{" "}
          <a href={`/login?next=${encodeURIComponent(path || "/watch")}`} {...{ [KEEP_UNSAVED_ATTR]: "" }}
             className="pointer-events-auto font-semibold underline">Giriş yap</a>
        </>
      );
    default: {
      // Yeni bir sorun türü derlenmez: giriş bağlantısı yalnızca panelin kendi 401'inde çıkar
      const unknown: never = problem;
      return unknown;
    }
  }
}
