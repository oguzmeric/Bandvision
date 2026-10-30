"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/live";
import { sameContent } from "@/lib/templateEdit.mjs";
import { DRAFT_DEBOUNCE_MS, STREAM_RETRY_MS, type TileRef, type ViewDraft } from "@/lib/views";

/** Taslağa yazılan içerik (ad sunucuya gitmez: taslağın adı hep "Taslak") */
export interface DraftBody { layout: string; tiles: Array<TileRef | null> }
type Want = { owner: string; body: DraftBody };

const draftPath = (id: string) => `views/drafts/${encodeURIComponent(id)}`;

/** Taslağı arka planda siler; sayfa kapanırken de gitsin diye `keepalive` (silinemezse sunucu 10 dk sonra kendisi siler) */
function dropDraft(id: string): void {
  void api(draftPath(id), { method: "DELETE", keepalive: true }).catch(() => undefined);
}

/**
 * Kaydedilmemiş düzenlemenin analiz sunucusundaki canlı taslağı. `edit` kayıtlı şablondan farklıysa (null değilse)
 * taslak açılır ya da güncellenir (DRAFT_DEBOUNCE_MS durulunca); ızgara bu sırada taslağın birleşik akışını ve
 * durumunu gösterir (`draftId`). `edit` null olunca (kaydedildi, geri alındı, vazgeçildi) taslak hemen silinir ve
 * `draftId` null olur: ızgara yeniden şablonu akıtır. Ortak kameralar sunucuda aynı okuyucuyu kullanır, kopmaz.
 * `owner` (sekme): taslak yalnız açıldığı sekmeye verilir; başka sekmenin düzenlemesi kendi taslağını açar.
 *
 * Taslak sunucuda bulunamazsa (10 dk boşta kaldı, sunucu yeniden başladı: güncelleme 404 ya da çağıran `lost(id)`
 * der) sessizce yenisi açılır; o ana dek eski kimlik kalır (ızgara şablona dönüp tekrar taslağa atlamasın).
 * İstekler sırayla gider (aynı anda iki taslak açılmaz). Sunucuya ulaşılamazsa STREAM_RETRY_MS sonra yeniden denenir;
 * sunucu içeriği reddederse (4xx) ileti `error`'a yazılır ve içerik değişene dek yeniden gönderilmez. Sunucu şimdilik
 * kabul etmiyorsa (503: ör. bütün tarayıcılarda en çok 32 taslak açık) ileti `error`'a yazılır ve STREAM_RETRY_MS sonra
 * yeniden denenir; başarınca ileti kalkar.
 */
export function useDraft(owner: string | null, edit: DraftBody | null, sessionLost = false): {
  draftId: string | null; error: string | null; lost: (id: string) => void; release: () => void;
} {
  const [current, setCurrent] = useState<{ owner: string; id: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** İstenen (null: taslak istenmiyor), sunucudaki taslak ve ona son yazılan içerik */
  const want = useRef<Want | null>(null);
  const draft = useRef<{ owner: string; id: string } | null>(null);
  const sent = useRef<DraftBody | null>(null);
  /** Sunucunun reddettiği içerik: değişmeden yeniden gönderilmez */
  const rejected = useRef<DraftBody | null>(null);
  const running = useRef(false);
  const again = useRef(false);
  const alive = useRef(true);
  const retry = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  /** Onaylı çıkış (`release`): sayfa gidiyor, yeni taslak açılmaz */
  const released = useRef(false);
  /** Oturum düştü (401): sayfa kapanırken silme isteği gönderilmez (girişsiz istek 401 alırdı; taslak 10 dk'da silinir) */
  const noSession = useRef(sessionLost);
  noSession.current = sessionLost;
  /** Sayfadan çıkarken (kapanış, söküm) taslağı siler; oturum düştüyse göndermez */
  const leaving = (id: string) => { if (!noSession.current) dropDraft(id); };

  const sync = useCallback(async () => {
    if (running.current) { again.current = true; return; }
    running.current = true;
    clearTimeout(retry.current);
    try {
      do {
        again.current = false;
        if (!alive.current) break;
        const w = released.current ? null : want.current;
        // İstenmiyor ya da başka sekmenin taslağı: eskisi silinir
        if (draft.current && (w === null || draft.current.owner !== w.owner)) {
          dropDraft(draft.current.id);
          draft.current = null;
          sent.current = null;
          setCurrent(null);
        }
        if (w === null) { rejected.current = null; setError(null); continue; }
        if (draft.current && sent.current && sameContent(w.body, sent.current)) continue;
        if (rejected.current && sameContent(w.body, rejected.current)) continue;
        const target = draft.current;                     // güncellenen taslak (yoksa yenisi açılır)
        try {
          if (target) {
            await api<ViewDraft>(draftPath(target.id), { method: "PUT", json: w.body });
          } else {
            const d = await api<ViewDraft>("views/drafts", { method: "POST", json: w.body });
            draft.current = { owner: w.owner, id: d.id };
            if (alive.current) setCurrent(draft.current);
          }
          sent.current = w.body;
          rejected.current = null;
          setError(null);
          // bu sırada içerik değişti (güncel hâli de yazılır) ya da çıkış onaylandı (yeni açılan taslak silinir)
          if (want.current !== w || released.current) again.current = true;
        } catch (e) {
          if (e instanceof ApiError && e.status === 503) {
            // analiz sunucusu şimdilik kabul etmiyor ("Çok fazla açık taslak var…"): söylenir ve yeniden denenir
            setError(e.message);
            retry.current = setTimeout(() => void sync(), STREAM_RETRY_MS);
          } else if (!(e instanceof ApiError) || e.status >= 500 || e.status === 401) {
            // sunucu yok / oturum doldu: sayfanın durum yoklaması bunu zaten söyler; sessizce yeniden denenir
            retry.current = setTimeout(() => void sync(), STREAM_RETRY_MS);
          } else if (e.status === 404 && target) {
            // taslak sunucuda yok: yenisi açılır (kimlik o ana dek kalır). `lost` bu arada bırakmış da olabilir.
            if (draft.current === target) { draft.current = null; sent.current = null; }
            again.current = true;
          } else {
            rejected.current = w.body;
            setError(e.message);
          }
        }
      } while (again.current);
    } finally {
      running.current = false;
    }
    if (!alive.current && draft.current) { leaving(draft.current.id); draft.current = null; }
  }, []);

  // İçerik değişince (durulduktan sonra) taslağa yazılır; vazgeçince ya da sekme değişince hemen
  const key = edit && owner !== null ? JSON.stringify([owner, edit]) : null;
  useEffect(() => {
    if (key === null) {
      want.current = null;
      void sync();
      return;
    }
    const [o, body] = JSON.parse(key) as [string, DraftBody];
    if (draft.current && draft.current.owner !== o) {    // sekme değişti: eski taslak beklemeden bırakılır
      want.current = null;
      void sync();
    }
    const t = setTimeout(() => {
      want.current = { owner: o, body };
      void sync();
    }, DRAFT_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [key, sync]);

  // Sayfadan çıkınca (ve sekme kapanırken) taslak silinir. Sayfa geri/ileri önbelleğinden dönerse kimlik durur: durum
  // yoklaması 404 alır ve `lost` yenisini açar (onaylı çıkıştan sonra dönülmüşse de: taslak yeniden açılabilir).
  useEffect(() => {
    alive.current = true;
    const onHide = () => { if (draft.current) leaving(draft.current.id); };
    const onShow = (e: PageTransitionEvent) => {
      if (!e.persisted || !released.current) return;
      released.current = false;
      void sync();
    };
    window.addEventListener("pagehide", onHide);
    window.addEventListener("pageshow", onShow);
    return () => {
      alive.current = false;
      clearTimeout(retry.current);
      window.removeEventListener("pagehide", onHide);
      window.removeEventListener("pageshow", onShow);
      if (draft.current) { leaving(draft.current.id); draft.current = null; sent.current = null; }
    };
  }, [sync]);

  /** Çağıran taslağın sunucuda olmadığını gördü (durum 404): yenisi açılır */
  const lost = useCallback((gone: string) => {
    if (draft.current?.id !== gone) return;
    draft.current = null;
    sent.current = null;
    void sync();
  }, [sync]);

  /**
   * Sayfadan onaylı çıkış (menü bağlantısı, Çıkış): taslak HEMEN, oturum hâlâ geçerliyken silinir ve sayfa gidene dek yenisi
   * açılmaz (süren açma isteği bitince o taslak da silinir). Çıkış'ta oturum çerezi az sonra silinir; taslak sayfa
   * kapanırken (pagehide) silinmeye bırakılsaydı istek girişsiz gider (401), taslak sunucuda 10 dk kalırdı; tarayıcı bağlantıyı
   * yarıda keserse Next bu girişsiz isteği "uncaughtException: aborted ECONNRESET" diye günlüğe yazıyordu.
   */
  const release = useCallback(() => {
    released.current = true;
    clearTimeout(retry.current);
    void sync();
  }, [sync]);

  return { draftId: current && current.owner === owner ? current.id : null, error, lost, release };
}
