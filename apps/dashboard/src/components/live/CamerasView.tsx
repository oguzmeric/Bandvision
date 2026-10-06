"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, RECORDER_BRANDS, type Channel, type LiveSession, type Source } from "@/lib/live";
import SourceForm from "./SourceForm";
import StartSessionDialog from "./StartSessionDialog";

function describe(s: Source): string {
  if (s.kind === "recorder") {
    const b = RECORDER_BRANDS.find((x) => x[0] === s.recorderBrand);
    return `${b?.[1] ?? s.recorderBrand} · ${s.host}`;
  }
  return s.brand === "custom" ? "RTSP adresi" : `${s.brand[0].toUpperCase()}${s.brand.slice(1)} · ${s.host} · kanal ${s.channel}`;
}

/** Kamerada canlı sayım zaten açıksa: yeniden başlatmak yerine o sayıma git (birden çok kamera aynı anda sayılabilir) */
function CountingLink({ session }: { session: LiveSession }) {
  return (
    <Link href={`/live?s=${session.id}`}
          className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-[9px] border border-[#bfe8d3] bg-ok-50 px-3 text-[12.5px] font-semibold text-ok-600 hover:brightness-95">
      <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-ok-600" />Sayılıyor
    </Link>
  );
}

/**
 * Küçük resimler sırayla (en çok 3 aynı anda): tarayıcı aynı adrese 6 bağlantı açar; görüntüsü gelmeyen kameralar
 * hepsini tutunca profil listesi, kaydet gibi istekler sırada bekliyordu.
 */
const MAX_THUMBS = 3;
let activeThumbs = 0;
const waitingThumbs: Array<() => void> = [];

function thumbSlot(): Promise<() => void> {
  return new Promise((resolve) => {
    const go = () => {
      activeThumbs++;
      let released = false;
      resolve(() => {
        if (released) return;
        released = true;
        activeThumbs--;
        waitingThumbs.shift()?.();
      });
    };
    if (activeThumbs < MAX_THUMBS) go();
    else waitingThumbs.push(go);
  });
}

/** Küçük resim: kayıt cihazının görüntü API'si ya da RTSP'den ilk kare */
function Thumb({ src, alt }: { src: string; alt: string }) {
  const [state, setState] = useState<"waiting" | "loading" | "ok" | "error">("waiting");
  const release = useRef<(() => void) | null>(null);
  useEffect(() => {
    let cancelled = false;
    thumbSlot().then((r) => {
      if (cancelled) { r(); return; }
      release.current = r;
      setState("loading");
    });
    return () => { cancelled = true; release.current?.(); release.current = null; };
  }, [src]);
  const done = (ok: boolean) => { setState(ok ? "ok" : "error"); release.current?.(); release.current = null; };
  return (
    <div className="relative aspect-video overflow-hidden rounded-xl bg-[#111]">
      {(state === "loading" || state === "ok") && (
        // eslint-disable-next-line @next/next/no-img-element -- kamera küçük resmi (yerel sunucudan)
        <img src={src} alt={alt} onLoad={() => done(true)} onError={() => done(false)}
             className={`h-full w-full object-cover transition-opacity ${state === "ok" ? "opacity-100" : "opacity-0"}`} />
      )}
      {(state === "waiting" || state === "loading") && <div className="absolute inset-0 animate-pulse bg-white/5" />}
      {state === "error" && <p className="absolute inset-0 grid place-items-center px-3 text-center text-xs text-white/60">Görüntü yok</p>}
    </div>
  );
}

function RecorderChannels({ source, sessions, onStart }: {
  source: Source; sessions: LiveSession[]; onStart: (ch: Channel) => void;
}) {
  const [channels, setChannels] = useState<Channel[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const load = useCallback((refresh: boolean) => {
    setError(null);
    setChannels(null);
    api<Channel[]>(`sources/${source.id}/channels${refresh ? "?refresh=true" : ""}`)
      .then(setChannels).catch((e: Error) => setError(e.message));
  }, [source.id]);
  useEffect(() => { load(false); }, [load]);

  const shown = (channels ?? []).filter((c) => c.title.toLocaleLowerCase("tr").includes(query.toLocaleLowerCase("tr")));
  return (
    <div className="mt-4">
      <div className="mb-3 flex items-center gap-2">
        <input aria-label="Kamera ara" placeholder="Kamera ara" value={query} onChange={(e) => setQuery(e.target.value)}
               className="h-9 flex-1 rounded-[10px] border border-line bg-white px-3 text-sm outline-none focus:border-brand-500" />
        <button type="button" onClick={() => load(true)} className="h-9 rounded-[10px] border border-line px-3 text-[13px] font-medium hover:border-brand-100">Yenile</button>
      </div>
      {error && <p role="alert" className="rounded-xl bg-nok-50 px-3 py-2 text-sm text-nok-600">{error}</p>}
      {channels === null && !error && <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="aspect-video animate-pulse rounded-xl bg-canvas" />)}</div>}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {shown.map((c) => (
          <div key={c.id} className="rounded-2xl border border-line bg-white p-2.5">
            <Thumb src={`/api/live/sources/${source.id}/snapshot?channel=${encodeURIComponent(c.id)}`} alt={c.title} />
            <div className="mt-2 flex items-center justify-between gap-2 px-0.5">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{c.title}</p>
                {c.number !== null && <p className="text-xs text-faint">Kanal {c.number}</p>}
              </div>
              {(() => {
                const active = sessions.find((x) => x.sourceId === source.id && x.channelId === c.id);
                return active ? <CountingLink session={active} /> : (
                  <button type="button" onClick={() => onStart(c)}
                          className="h-8 shrink-0 rounded-[9px] bg-brand-500 px-3 text-[12.5px] font-semibold text-white hover:bg-brand-600">
                    Canlı sayım
                  </button>
                );
              })()}
            </div>
          </div>
        ))}
      </div>
      {channels && channels.length > 0 && shown.length === 0 && <p className="text-sm text-muted">Aramayla eşleşen kamera yok.</p>}
    </div>
  );
}

export default function CamerasView() {
  const [sources, setSources] = useState<Source[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [editing, setEditing] = useState<Source | null>(null);
  const [starting, setStarting] = useState<{ source: Source; channel: Channel | null } | null>(null);

  const [sessions, setSessions] = useState<LiveSession[]>([]);

  const load = useCallback(() => {
    api<Source[]>("sources").then((s) => { setSources(s); setError(null); }).catch((e: Error) => setError(e.message));
    api<LiveSession[]>("sessions").then(setSessions).catch(() => undefined);
  }, []);
  useEffect(() => { load(); }, [load]);

  async function remove(s: Source) {
    if (!confirm(`"${s.name}" silinsin mi? Kayıtlı şifresi de silinir.`)) return;
    try {
      await api(`sources/${s.id}`, { method: "DELETE" });
      if (open === s.id) setOpen(null);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="grid items-start gap-5 lg:grid-cols-[380px_minmax(0,1fr)]">
      <div className="min-w-0">
        <SourceForm key={editing?.id ?? "new"} editing={editing}
                    onCancel={editing ? () => setEditing(null) : undefined}
                    onSaved={(s) => { setEditing(null); load(); if (s.kind === "recorder") setOpen(s.id); }} />
        <p className="mt-3 px-1 text-xs text-faint">
          Görüntü yalnızca bu bilgisayarda işlenir. Bilgisayar kameralarla aynı ağda olmalı (ofis ağı ya da VPN).
        </p>
      </div>
      <section className="min-w-0" aria-labelledby="sources-title">
        <p id="sources-title" className="eyebrow mb-2">Kaynaklar</p>
        {error && <p role="alert" className="mb-3 rounded-xl bg-nok-50 px-3 py-2 text-sm text-nok-600">{error}</p>}
        {sources === null && !error && <div className="h-24 animate-pulse rounded-2xl bg-white/70" />}
        {sources?.length === 0 && (
          <div className="card grid min-h-[200px] place-items-center p-8 text-center text-muted">
            <div>
              <p className="font-medium text-ink">Henüz kaynak yok</p>
              <p className="mt-1 text-sm">Soldan kayıt cihazını (NVR) ya da IP kamerayı ekle; kameralar burada listelenir.</p>
            </div>
          </div>
        )}
        <div className="grid gap-3">
          {sources?.map((s) => (
            <article key={s.id} className="card p-4" data-testid="source-card">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-semibold text-brand-500">
                      {s.kind === "recorder" ? "Kayıt cihazı" : "IP kamera"}
                    </span>
                    <h3 className="truncate font-semibold">{s.name}</h3>
                  </div>
                  <p className="mt-0.5 truncate text-[13px] text-muted">{describe(s)}{s.hasPassword ? " · şifre kayıtlı" : ""}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {s.kind === "recorder" ? (
                    <button type="button" onClick={() => setOpen(open === s.id ? null : s.id)} aria-expanded={open === s.id}
                            className="h-9 rounded-[10px] bg-brand-500 px-3 text-[13px] font-semibold text-white hover:bg-brand-600">
                      {open === s.id ? "Kameraları gizle" : "Kameraları göster"}
                    </button>
                  ) : sessions.find((x) => x.sourceId === s.id) ? (
                    <CountingLink session={sessions.find((x) => x.sourceId === s.id)!} />
                  ) : (
                    <button type="button" onClick={() => setStarting({ source: s, channel: null })}
                            className="h-9 rounded-[10px] bg-brand-500 px-3 text-[13px] font-semibold text-white hover:bg-brand-600">
                      Canlı sayım
                    </button>
                  )}
                  <button type="button" onClick={() => setEditing(s)} className="h-9 rounded-[10px] border border-line px-3 text-[13px] font-medium hover:border-brand-100">Düzenle</button>
                  <button type="button" onClick={() => remove(s)} className="h-9 rounded-[10px] border border-line px-3 text-[13px] font-medium text-nok-600 hover:border-nok-50">Sil</button>
                </div>
              </div>
              {s.kind === "camera" && (
                <div className="mt-3 max-w-[360px]"><Thumb src={`/api/live/sources/${s.id}/snapshot`} alt={s.name} /></div>
              )}
              {s.kind === "recorder" && open === s.id && (
                <RecorderChannels source={s} sessions={sessions} onStart={(c) => setStarting({ source: s, channel: c })} />
              )}
            </article>
          ))}
        </div>
      </section>
      {starting && (
        <StartSessionDialog sourceId={starting.source.id} channelId={starting.channel?.id ?? null}
                            substream={starting.source.substream}
                            streamChoice={starting.source.kind === "recorder" ? (starting.channel?.hasSubstream ?? true) : starting.source.brand !== "custom"}
                            title={`${starting.source.name}${starting.channel ? ` · ${starting.channel.title}` : ""}`}
                            onClose={() => setStarting(null)} />
      )}
    </div>
  );
}
