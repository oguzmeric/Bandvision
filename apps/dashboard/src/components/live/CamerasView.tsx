"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { KIND_TITLE, kindOfMode, parseKind } from "@/lib/analysisKind";
import { api, RECORDER_BRANDS, safetyHealth, type Channel, type LiveSession, type Source } from "@/lib/live";
import SourceForm from "./SourceForm";
import Thumb from "./Thumb";
import StartSessionDialog from "./StartSessionDialog";

function describe(s: Source): string {
  if (s.kind === "recorder") {
    const b = RECORDER_BRANDS.find((x) => x[0] === s.recorderBrand);
    return `${b?.[1] ?? s.recorderBrand} · ${s.host}`;
  }
  return s.brand === "custom" ? "RTSP adresi" : `${s.brand[0].toUpperCase()}${s.brand.slice(1)} · ${s.host} · kanal ${s.channel}`;
}

/**
 * Kamerada canlı sayım zaten açıksa: yeniden başlatmak yerine o sayıma git (birden çok kamera aynı anda sayılabilir).
 * Güvenlik kamerası "Nöbette" (gerçekten izleniyor) ya da "Uyarı" (izlenmiyor; neden üstüne gelince) gösterir.
 */
/** Sayımı süren kamera: o oturuma gider, oturumun türüne süzülmüş canlı sayım sayfasında (menüde o tür seçili) */
function CountingLink({ session }: { session: LiveSession }) {
  const safety = session.profile.countMode === "safety";
  const health = safety ? safetyHealth(session) : null;
  const warn = health !== null && !health.healthy;
  return (
    <Link href={`/live?s=${session.id}&tur=${kindOfMode(session.profile.countMode ?? "blob")}`}
          title={warn ? health.reason ?? undefined : undefined}
          className={`inline-flex h-7 shrink-0 items-center gap-1.5 rounded-[2px] border px-2.5 text-[12.5px] font-semibold hover:brightness-95 ${warn ? "border-warn-line bg-warn-50 text-warn-ink" : "border-ok-line bg-ok-50 text-ok-ink"}`}>
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${warn ? "bg-warn-700" : "bg-ok-600"}`} />
      {!safety ? "Sayılıyor" : warn ? "Uyarı" : "Nöbette"}
    </Link>
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
    <div className="mt-2.5">
      <div className="mb-2 flex items-center gap-2">
        <input aria-label="Kamera ara" placeholder="Kamera ara" value={query} onChange={(e) => setQuery(e.target.value)}
               className="pl-input h-8 flex-1" />
        <button type="button" onClick={() => load(true)} className="pl-btn h-8">Yenile</button>
      </div>
      {error && <p role="alert" className="rounded-[2px] border border-nok-line bg-nok-50 px-3 py-2 text-[13px] text-nok-ink">{error}</p>}
      {channels === null && !error && <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="aspect-video animate-pulse rounded-[2px] bg-pl-side" />)}</div>}
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {shown.map((c) => (
          <div key={c.id} className="rounded-[2px] border border-pl-line-soft bg-white p-1.5">
            <Thumb src={`/api/live/sources/${source.id}/snapshot?channel=${encodeURIComponent(c.id)}`} alt={c.title} />
            <div className="mt-1.5 flex items-center justify-between gap-2 px-0.5">
              <div className="min-w-0">
                <p className="truncate text-[13px] font-medium">{c.title}</p>
                {c.number !== null && <p className="text-xs text-pl-faint">Kanal {c.number}</p>}
              </div>
              {(() => {
                const active = sessions.find((x) => x.sourceId === source.id && x.channelId === c.id);
                return active ? <CountingLink session={active} /> : (
                  <button type="button" onClick={() => onStart(c)} className="pl-btn pl-btn-primary h-7 shrink-0 text-[12.5px]">
                    Canlı sayım
                  </button>
                );
              })()}
            </div>
          </div>
        ))}
      </div>
      {channels && channels.length > 0 && shown.length === 0 && <p className="text-[13px] text-pl-muted">Aramayla eşleşen kamera yok.</p>}
    </div>
  );
}

export default function CamerasView() {
  const kind = parseKind(useSearchParams().get("tur"));      // /cameras?tur=kisi: başlatma penceresi o türün profilleriyle açılır
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
    <div className="grid items-start gap-3 lg:grid-cols-[380px_minmax(0,1fr)]">
      {kind && (
        // Menüden "Yeni analiz" ile gelindi: başlatma penceresi yalnız bu türün profillerini sunar; "Tümü" süzmeyi kaldırır
        <p data-testid="kind-filter" className="flex flex-wrap items-center gap-x-2 border border-pl-sel-line bg-pl-sel px-3 py-1.5 text-[13px] text-pl-ink lg:col-span-2">
          <span className="min-w-0 flex-1">Yeni analiz: <b>{KIND_TITLE[kind]}</b>. &quot;Canlı sayım&quot; yalnız bu türün profilleriyle başlar.</span>
          <Link href="/cameras" className="font-semibold text-pl-accent underline">Tümü</Link>
        </p>
      )}
      <div className="min-w-0">
        <SourceForm key={editing?.id ?? "new"} editing={editing}
                    onCancel={editing ? () => setEditing(null) : undefined}
                    onSaved={(s) => { setEditing(null); load(); if (s.kind === "recorder") setOpen(s.id); }} />
        <p className="px-1 text-xs text-pl-faint">
          Görüntü yalnızca bu bilgisayarda işlenir. Bilgisayar kameralarla aynı ağda olmalı (ofis ağı ya da VPN).
        </p>
      </div>
      <section className="pl-section mb-0 min-w-0" aria-labelledby="sources-title">
        <h2 id="sources-title">Kaynaklar</h2>
        {error && <p role="alert" className="mb-2 rounded-[2px] border border-nok-line bg-nok-50 px-3 py-2 text-[13px] text-nok-ink">{error}</p>}
        {sources === null && !error && <div className="h-24 animate-pulse rounded-[2px] bg-pl-side" />}
        {sources?.length === 0 && (
          <div className="grid min-h-[160px] place-items-center p-6 text-center text-pl-muted">
            <div>
              <p className="font-medium text-pl-ink">Henüz kaynak yok</p>
              <p className="mt-1 text-[13px]">Soldan kayıt cihazını (NVR) ya da IP kamerayı ekle; kameralar burada listelenir.</p>
            </div>
          </div>
        )}
        <div className="grid">
          {sources?.map((s) => (
            <article key={s.id} className="border-b border-pl-line-soft py-2.5 first:pt-0.5 last:border-b-0" data-testid="source-card">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="rounded-[2px] border border-pl-sel-line bg-pl-sel px-1.5 text-[11px] font-semibold text-pl-accent">
                      {s.kind === "recorder" ? "Kayıt cihazı" : "IP kamera"}
                    </span>
                    <h3 className="truncate font-semibold">{s.name}</h3>
                  </div>
                  <p className="mt-0.5 truncate text-[12.5px] text-pl-muted">{describe(s)}{s.hasPassword ? " · şifre kayıtlı" : ""}</p>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {s.kind === "recorder" ? (
                    <button type="button" onClick={() => setOpen(open === s.id ? null : s.id)} aria-expanded={open === s.id}
                            className="pl-btn pl-btn-primary h-8">
                      {open === s.id ? "Kameraları gizle" : "Kameraları göster"}
                    </button>
                  ) : sessions.find((x) => x.sourceId === s.id) ? (
                    <CountingLink session={sessions.find((x) => x.sourceId === s.id)!} />
                  ) : (
                    <button type="button" onClick={() => setStarting({ source: s, channel: null })} className="pl-btn pl-btn-primary h-8">
                      Canlı sayım
                    </button>
                  )}
                  <button type="button" onClick={() => setEditing(s)} className="pl-btn h-8">Düzenle</button>
                  <button type="button" onClick={() => remove(s)} className="pl-btn h-8 text-nok-ink">Sil</button>
                </div>
              </div>
              {s.kind === "camera" && (
                <div className="mt-2 max-w-[360px]"><Thumb src={`/api/live/sources/${s.id}/snapshot`} alt={s.name} /></div>
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
                            kind={kind} onClose={() => setStarting(null)} />
      )}
    </div>
  );
}
