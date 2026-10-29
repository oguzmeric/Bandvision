"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAlarmCenter } from "@/components/live/AlarmCenter";
import { api, type Channel, type LiveSession, type Source } from "@/lib/live";
import { refKey } from "@/lib/templateEdit.mjs";
import type { TileRef } from "@/lib/views";

/** Sürüklenen kamera (listeden kutuya): `{ ref, name }` JSON */
export const CAMERA_MIME = "application/x-bv-camera";

/** Listedeki kameranın durumu: yalnız ızgaradaki kameralar için bilinir (tek durum yoklaması) */
export type CamState = "live" | "problem";

const DOT = { live: "bg-ok-600", problem: "bg-warn-700", unknown: "bg-pl-ctl" } as const;
const DOT_TEXT = { live: "canlı", problem: "sorunlu" } as const;
/** Gri nokta: ızgaradaki kamera henüz bağlanıyor; ızgarada olmayan (ve analiz oturumu olmayan) kameranın durumu yoklanmaz */
const UNKNOWN_IN_GRID = "bağlanıyor";
const UNKNOWN_OUTSIDE = "bu şablonda izlenmiyor";
const LEGEND_UNKNOWN = `bağlanıyor / bilinmiyor (${UNKNOWN_OUTSIDE})`;

function sessionState(s: LiveSession): CamState | undefined {
  if (s.state === "live") return "live";
  return s.state === "error" || s.state === "reconnecting" ? "problem" : undefined;
}
/** Önem sırası: aynı kamerada birden çok oturum varsa en kötü durum gösterilir (sorunlu > canlı > bilinmiyor) */
const RANK = { problem: 2, live: 1 } as const;
const worse = (a: CamState | undefined, b: CamState | undefined) => ((b ? RANK[b] : 0) > (a ? RANK[a] : 0) ? b : a);

/** Analiz oturumu olan kameraların durumu (kamera → en kötü oturum durumu) */
export function sessionStates(list: LiveSession[]): Map<string, CamState | undefined> {
  const m = new Map<string, CamState | undefined>();
  for (const x of list) {
    if (!x.sourceId) continue;
    const key = refKey({ sourceId: x.sourceId, channelId: x.channelId ?? null });
    m.set(key, worse(m.get(key), sessionState(x)));
  }
  return m;
}

/**
 * Sağdaki yazılı kamera listesi (taslak duzen.html): tek kameralar ve kayıt cihazlarının altında kanalları; yeşil nokta
 * canlı, turuncu sorunlu, gri bilinmiyor (altta açıklaması var). Izgaradaki kameraların durumu sayfanın tek durum
 * yoklamasından; ızgarada olmayan kameralardan yalnız analiz oturumu olanlarınki panelin oturum listesinden (alarm
 * merkezinin 5 sn'lik tek yoklaması; izleme için kamera okuyucusu açılmaz) gelir, diğerleri gri ("bu şablonda
 * izlenmiyor"). Öğe kutuya sürüklenir ya da
 * tıklanır (seçili kutuya, seçili kutu yoksa ilk boş kutuya gider). Şablondaki kamera yine seçilebilir: başka kutuya taşınır.
 * Kayıt cihazları açık gelir (kanallar bir kez alınır); başlığa tıklayınca kapanır/açılır.
 * Etiketler sunucunun kutu adıyla aynı biçimdedir: tek kamera "Kapı", kanal "Ofis NVR · Kasa" (`onLabels`).
 */
export default function CameraList({ used, stateOf, onPick, onSources, onLabels }: {
  used: Set<string>; stateOf: (key: string) => CamState | undefined;
  onPick: (ref: TileRef, label: string) => void;
  /** Kaynak listesi alınınca */
  onSources?: (sources: Source[]) => void;
  /** Bilinen tüm kameraların kutu etiketi (kamera → ad); kanallar geldikçe büyür */
  onLabels?: (labels: Record<string, string>) => void;
}) {
  /** null: henüz alınmadı (alınamazsa `error` dolar; "Henüz kaynak yok" yanlışı söylenmesin) */
  const [sources, setSources] = useState<Source[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [closed, setClosed] = useState<Set<string>>(() => new Set());
  /** Kayıt cihazı → kanallar, hata iletisi ya da (undefined) alınıyor */
  const [channels, setChannels] = useState<Record<string, Channel[] | string | undefined>>({});
  /** Kanal isteği sürenler: kapatıp yeniden açmak ikinci istek göndermez */
  const pending = useRef(new Set<string>());
  /** Analiz oturumu olan kameraların durumu (kamera → durum), panelin oturum yoklamasından */
  const center = useAlarmCenter();
  const allSessions = center?.sessions;
  const sessions = useMemo(() => sessionStates(allSessions ?? []), [allSessions]);

  const fetchChannels = useCallback(async (s: Source) => {
    if (pending.current.has(s.id)) return;
    pending.current.add(s.id);
    setChannels((x) => ({ ...x, [s.id]: undefined }));                 // önceki hata iletisi kalkar, "yükleniyor" görünür
    try { const c = await api<Channel[]>(`sources/${s.id}/channels`); setChannels((x) => ({ ...x, [s.id]: c })); }
    catch (e) { setChannels((x) => ({ ...x, [s.id]: (e as Error).message })); }
    finally { pending.current.delete(s.id); }
  }, []);
  const load = useCallback(() => {
    setError(null);
    api<Source[]>("sources").then((s) => {
      setSources(s);
      onSources?.(s);
      for (const r of s) if (r.kind === "recorder") void fetchChannels(r);
    }).catch((e: Error) => setError(e.message));
  }, [onSources, fetchChannels]);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!sources || !onLabels) return;
    const m: Record<string, string> = {};
    for (const s of sources) {
      if (s.kind === "camera") m[refKey({ sourceId: s.id, channelId: null })] = s.name;
      const c = channels[s.id];
      if (Array.isArray(c)) for (const ch of c) m[refKey({ sourceId: s.id, channelId: ch.id })] = `${s.name} · ${ch.title.trim()}`;
    }
    onLabels(m);
  }, [sources, channels, onLabels]);

  const toggle = (s: Source) => {
    const isClosed = closed.has(s.id);
    setClosed((c) => { const n = new Set(c); if (isClosed) n.delete(s.id); else n.add(s.id); return n; });
    // açılırken kanallar alınamamışsa yeniden denenir
    if (isClosed && typeof channels[s.id] === "string") void fetchChannels(s);
  };

  const item = (ref: TileRef, name: string, label: string) => {
    const key = refKey(ref);
    const inGrid = used.has(key);
    const st = inGrid ? stateOf(key) : sessions.get(key);
    const text = st ? DOT_TEXT[st] : inGrid ? UNKNOWN_IN_GRID : UNKNOWN_OUTSIDE;
    return (
      <li key={key}>
        <button type="button" draggable data-testid="camera-item"
                aria-label={[name, text, inGrid && "şablonda"].filter(Boolean).join(", ")}
                onDragStart={(e) => { e.dataTransfer.setData(CAMERA_MIME, JSON.stringify({ ref, name: label })); e.dataTransfer.effectAllowed = "copyMove"; }}
                onClick={() => onPick(ref, label)}
                className={`flex w-full items-center gap-1.5 border-b border-pl-head px-2 py-1 text-left text-[13px] hover:bg-pl-sel focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-pl-accent ${inGrid ? "font-semibold" : ""}`}>
          <span aria-hidden="true" data-state={st ?? "unknown"} title={text}
                className={`h-2 w-2 shrink-0 rounded-full ${DOT[st ?? "unknown"]}`} />
          <span className="min-w-0 truncate">{name}</span>
        </button>
      </li>
    );
  };
  const channelList = (s: Source) => {
    const c = channels[s.id];
    if (typeof c === "string") return <p className="px-6 py-1 text-[12px] text-nok-600">{c}</p>;
    if (c === undefined) return <p className="px-6 py-1 text-[12px] text-pl-faint">Kanallar yükleniyor…</p>;
    if (c.length === 0) return <p className="px-6 py-1 text-[12px] text-pl-faint">Bu kayıt cihazında kamera yok.</p>;
    return (
      <ul className="pl-4">
        {c.map((ch) => item({ sourceId: s.id, channelId: ch.id }, ch.title, `${s.name} · ${ch.title.trim()}`))}
      </ul>
    );
  };
  return (
    <aside aria-label="Kameralar"
           className="min-w-0 border border-pl-line bg-pl-bg lg:sticky lg:top-2 lg:max-h-[calc(100vh-120px)] lg:w-[230px] lg:shrink-0 lg:overflow-y-auto">
      <h2 className="border-b border-pl-line bg-pl-head px-2 py-1 text-[13px] font-semibold">Kameralar</h2>
      {error && (
        <div role="alert" className="flex flex-wrap items-center gap-2 px-2 py-1.5 text-[13px] text-nok-600">
          <span className="min-w-0 flex-1">{error}</span>
          <button type="button" onClick={load} className="pl-btn">Yeniden dene</button>
        </div>
      )}
      {sources === null && !error && <p className="px-2 py-1.5 text-[13px] text-pl-faint">Kameralar yükleniyor…</p>}
      {sources?.length === 0 && <p className="px-2 py-1.5 text-[13px] text-pl-faint">Henüz kaynak yok. Kameralar sayfasından ekleyin.</p>}
      <ul>
        {(sources ?? []).map((s) => s.kind === "camera"
          ? item({ sourceId: s.id, channelId: null }, s.name, s.name)
          : (
            <li key={s.id}>
              <button type="button" aria-expanded={!closed.has(s.id)} onClick={() => toggle(s)}
                      className="flex w-full items-center gap-1 border-b border-pl-head bg-pl-side px-2 py-1 text-left text-[13px] font-semibold hover:bg-pl-head focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-pl-accent">
                <span aria-hidden="true" className="w-3 text-pl-muted">{closed.has(s.id) ? "▸" : "▾"}</span>
                <span className="min-w-0 truncate">{s.name}</span>
              </button>
              {!closed.has(s.id) && channelList(s)}
            </li>
          ))}
      </ul>
      {/* Noktaların açıklaması */}
      <p data-testid="camera-legend" className="flex flex-wrap gap-x-3 gap-y-0.5 border-t border-pl-line px-2 py-1 text-[11.5px] text-pl-muted">
        {(["live", "problem", "unknown"] as const).map((k) => (
          <span key={k} className="inline-flex items-center gap-1">
            <span aria-hidden="true" className={`h-2 w-2 rounded-full ${DOT[k]}`} />
            {k === "unknown" ? LEGEND_UNKNOWN : DOT_TEXT[k]}
          </span>
        ))}
      </p>
    </aside>
  );
}
