"use client";

import { streamUrl, type PlayerView } from "@/lib/archive";
import { clock, dateLabel } from "@/lib/archiveTime.mjs";
import { isActive } from "./useArchivePlayer";

export const EXPORT_UNSUPPORTED = "Bu kayıt cihazında dışa aktarma henüz desteklenmiyor.";
const EXPORT_NEEDS_PLAYER = "Dışa aktarmak için önce kaydı oynatın.";
const NO_NEXT = "Bu günde sonraki kayıt yok.";

/** Durum satırının metni (öncelik: istek reddi → kamera yok → oynatıcı yok → oynatıcı durumu) */
function statusText({ error, hasCamera, view, opening, seeking }: {
  error: string | null; hasCamera: boolean; view: PlayerView | null; opening: boolean; seeking: boolean;
}): { text: string; bad: boolean } {
  if (error) return { text: error, bad: true };
  if (!hasCamera) return { text: "Önce bir kamera seçin.", bad: false };
  if (!view) return { text: opening ? "Bağlanıyor…" : "Oynatmak için çizelgede bir ana tıklayın ya da Oynat'a basın.", bad: false };
  switch (view.state) {
    case "connecting": return { text: seeking ? "Sarılıyor…" : "Bağlanıyor…", bad: false };
    case "playing": return { text: view.speed > 1 ? `Oynatılıyor (${view.speed}×)` : "Oynatılıyor", bad: false };
    case "paused": return { text: "Duraklatıldı", bad: false };
    case "ended": return { text: "Kayıt bitti", bad: false };
    default: return { text: view.message || "Kayıt oynatılamadı.", bad: true };
  }
}

/**
 * Oynatıcı: üstte durum satırı (`aria-live="polite"`) ve sağda saat/tarih, ortada MJPEG `<img>`, altta kumanda.
 * `<img>` duraklatma, sürdürme ve sarmada yerinde kalır (sunucu bağlantıyı açık tutar); yalnız `streamKey` değişince
 * (yeni oynatıcı, hatadan sonra sürdürme, sekmeye dönüş, `<img>` hatası) yeniden açılır. Sekme gizliyken (`visible`
 * false) `<img>` hiç çizilmez. "Kayıt bitti"de ana düğme "Sonraki kayda git"tir (sonraki kayıt yoksa pasif "Sürdür").
 */
export default function Player({ name, hasCamera, view, opening, seeking, error, notice, streamKey, visible, onStreamError,
  at, speed, nextAt, onToggle, onStep, onSpeed, onNext, onExport }: {
  name: string; hasCamera: boolean; view: PlayerView | null; opening: boolean; seeking: boolean; error: string | null;
  notice: string | null; streamKey: number; visible: boolean; onStreamError: () => void; at: number; speed: number;
  /** "Kayıt bitti"nde sonraki kaydın başı (yoksa null) */
  nextAt: number | null;
  onToggle: () => void; onStep: (seconds: number) => void; onSpeed: (speed: number) => void; onNext: () => void;
  onExport: () => void;
}) {
  const status = statusText({ error, hasCamera, view, opening, seeking });
  const active = isActive(view);
  const speeds = view?.speeds.length ? view.speeds : [speed];
  const exportTitle = !view ? EXPORT_NEEDS_PLAYER : view.canExport ? undefined : EXPORT_UNSUPPORTED;
  const off = !hasCamera;
  const ended = view?.state === "ended";

  return (
    <section className="pl-section mb-0 min-w-0" aria-label="Oynatıcı">
      <div className="-mx-2.5 mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-pl-line bg-pl-head px-2.5 py-1.5">
        <h2 className="min-w-0 flex-1 truncate font-semibold">{name || "Oynatıcı"}</h2>
        <p className="shrink-0 font-mono tabular-nums" data-testid="player-clock">
          <span className="font-semibold">{clock(at)}</span> <span className="text-pl-muted">{dateLabel(at)}</span>
        </p>
      </div>
      <div className="mb-2 flex min-h-7 flex-wrap items-center gap-2">
        <div role="status" aria-live="polite" data-testid="player-status" className="min-w-0 flex-1">
          <p className={status.bad ? "font-semibold text-nok-ink" : "font-semibold"}>{status.text}</p>
          {notice && <p className="text-pl-muted">{notice}</p>}
        </div>
      </div>
      <div className="relative aspect-video w-full overflow-hidden bg-black">
        {view && visible && (
          // eslint-disable-next-line @next/next/no-img-element -- MJPEG akışı, Next görüntü iyileştirmesi uygun değil
          <img key={`${view.id}-${streamKey}`} src={streamUrl(view.id, streamKey)} alt={`${name} kaydı`} data-testid="player-stream"
               onError={onStreamError} className="absolute inset-0 h-full w-full object-contain" />
        )}
        {!view && (
          <p className="absolute inset-0 grid place-items-center p-4 text-center text-[13px] text-white/80">
            {hasCamera ? "Kayıt oynatılmıyor" : "Kamera seçilmedi"}
          </p>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5" role="group" aria-label="Oynatma kumandası">
        <button type="button" disabled={off} onClick={() => onStep(-60)} aria-label="1 dakika geri" className="pl-btn h-8">⏮ 1 dk</button>
        <button type="button" disabled={off} onClick={() => onStep(-10)} aria-label="10 saniye geri" className="pl-btn h-8">◀ 10 sn</button>
        {ended && nextAt !== null ? (
          <button type="button" disabled={off} onClick={onNext} className="pl-btn pl-btn-primary h-8 min-w-20 justify-center">
            Sonraki kayda git
          </button>
        ) : (
          <button type="button" disabled={off || opening || ended} onClick={onToggle} title={ended ? NO_NEXT : undefined}
                  className="pl-btn pl-btn-primary h-8 min-w-20 justify-center">
            {!view ? "Oynat" : active ? "Duraklat" : "Sürdür"}
          </button>
        )}
        <button type="button" disabled={off} onClick={() => onStep(10)} aria-label="10 saniye ileri" className="pl-btn h-8">10 sn ▶</button>
        <button type="button" disabled={off} onClick={() => onStep(60)} aria-label="1 dakika ileri" className="pl-btn h-8">1 dk ⏭</button>
        <label className="flex items-center gap-1">
          <span className="text-pl-muted">Hız</span>
          <select value={view?.speed ?? speed} disabled={!view} onChange={(e) => onSpeed(Number(e.target.value))} className="pl-input h-8">
            {speeds.map((s) => <option key={s} value={s}>{s}×</option>)}
          </select>
        </label>
        <button type="button" disabled={!view?.canExport} title={exportTitle} onClick={onExport} aria-haspopup="dialog"
                className="pl-btn h-8 sm:ml-auto">
          Dışa aktar…
        </button>
      </div>
      {exportTitle && view && <p className="mt-1 text-xs text-pl-faint">{exportTitle}</p>}
    </section>
  );
}
