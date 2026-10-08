"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ALARM_LABELS, ALARM_LIST_LIMIT, NOTIFY_LABELS, alarmImageUrl, api, type Alarm, type AlarmType } from "@/lib/live";
import { useAlarmCenter } from "./AlarmCenter";
import AlarmViewer from "./AlarmViewer";

const POLL_MS = 5000;
const DAY_MS = 86_400_000;
const field = "h-10 rounded-[10px] border border-line bg-white px-3 text-sm outline-none focus:border-brand-500";

/** Yerel tarih → "yyyy-mm-dd" (tarih kutusu biçimi) */
function ymd(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function duration(a: Alarm): string {
  if (a.endedAt !== null) return `${Math.max(0, Math.round(a.endedAt - a.startedAt))} sn`;
  return a.type === "test" ? "—" : "devam ediyor";
}

function state(a: Alarm): { text: string; tone: string } {
  if (a.falseAlarm) return { text: "Yanlış alarm", tone: "bg-canvas-2 text-muted" };
  return a.acked ? { text: "Onaylandı", tone: "bg-ok-50 text-ok-600" } : { text: "Onay bekliyor", tone: "bg-warn-50 text-warn-700" };
}

/**
 * Alarm geçmişi (en çok 7 gün saklanır): kamera, tür, tarih aralığı (varsayılan son 7 gün) ve "Yalnızca onaylanmamış"
 * süzgeçleri; görünen aralığın sayıları (toplam, tür başına, yanlış alarm). Satıra tıklayınca alarm penceresi (göz
 * atma) açılır: kayıt, Gördüm, Yanlış alarm.
 */
export default function AlarmsView() {
  const [from, setFrom] = useState(() => ymd(new Date(Date.now() - 6 * DAY_MS)));
  const [to, setTo] = useState(() => ymd(new Date()));
  const [camera, setCamera] = useState("");
  const [type, setType] = useState<AlarmType | "">("");
  const [unacked, setUnacked] = useState(false);
  const [loaded, setLoaded] = useState<{ key: string; list: Alarm[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [viewing, setViewing] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const center = useAlarmCenter();

  const query = useMemo(() => {
    const since = new Date(`${from}T00:00:00`).getTime() / 1000;
    const until = new Date(`${to}T23:59:59.999`).getTime() / 1000;
    const q = new URLSearchParams({ limit: String(ALARM_LIST_LIMIT) });
    if (Number.isFinite(since)) q.set("since", String(since));
    if (Number.isFinite(until)) q.set("until", String(until));
    if (type) q.set("type", type);
    if (unacked) q.set("active", "1");
    return q.toString();
  }, [from, to, type, unacked]);

  useEffect(() => {
    let alive = true;
    const load = () => api<Alarm[]>(`alarms?${query}`)
      .then((list) => { if (alive) { setLoaded({ key: query, list }); setError(null); } })
      .catch((e: Error) => { if (alive) setError(e.message); });
    load();
    const t = setInterval(load, POLL_MS);
    return () => { alive = false; clearInterval(t); };
  }, [query, reload]);

  // süzgeç değişince eski sonuç bir an bile yeni süzgeçle görünmez
  const list = useMemo(() => (loaded?.key === query ? loaded.list : null), [loaded, query]);
  const cameras = useMemo(() => {
    const names = new Set((list ?? []).map((a) => a.camera));
    if (camera) names.add(camera);
    return [...names].sort((x, y) => x.localeCompare(y, "tr"));
  }, [list, camera]);
  const visible = useMemo(() => (list ?? []).filter((a) => !camera || a.camera === camera), [list, camera]);
  const counts = useMemo(() => ({
    total: visible.length,
    hands_up: visible.filter((a) => a.type === "hands_up").length,
    lying: visible.filter((a) => a.type === "lying").length,
    test: visible.filter((a) => a.type === "test").length,
    false: visible.filter((a) => a.falseAlarm).length,
  }), [visible]);

  const changed = useCallback(() => { setReload((x) => x + 1); center?.refresh(); }, [center]);
  const ack = useCallback(async (a: Alarm) => {
    try { await api(`alarms/${a.id}/ack`, { method: "POST" }); changed(); return true; } catch { return false; }
  }, [changed]);
  const markFalse = useCallback(async (a: Alarm) => {
    try { await api(`alarms/${a.id}/false-alarm`, { method: "POST" }); changed(); return true; } catch { return false; }
  }, [changed]);
  const close = useCallback(() => setViewing(null), []);

  return (
    <div className="grid gap-4">
      <section className="card flex flex-wrap items-end gap-3 p-4" aria-label="Süzgeçler">
        <label className="grid gap-1 text-[12.5px] font-medium text-muted">Kamera
          <select aria-label="Kamera" className={field} value={camera} onChange={(e) => setCamera(e.target.value)}>
            <option value="">Tüm kameralar</option>
            {cameras.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label className="grid gap-1 text-[12.5px] font-medium text-muted">Tür
          <select aria-label="Tür" className={field} value={type} onChange={(e) => setType(e.target.value as AlarmType | "")}>
            <option value="">Tüm türler</option>
            {(Object.keys(ALARM_LABELS) as AlarmType[]).map((k) => <option key={k} value={k}>{ALARM_LABELS[k]}</option>)}
          </select>
        </label>
        <label className="grid gap-1 text-[12.5px] font-medium text-muted">Başlangıç
          <input type="date" aria-label="Başlangıç tarihi" className={field} value={from} max={to} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="grid gap-1 text-[12.5px] font-medium text-muted">Bitiş
          <input type="date" aria-label="Bitiş tarihi" className={field} value={to} min={from} onChange={(e) => setTo(e.target.value)} />
        </label>
        <label className="flex h-10 items-center gap-2 text-sm">
          <input type="checkbox" className="h-4 w-4 accent-brand-500" checked={unacked} onChange={(e) => setUnacked(e.target.checked)} />
          Yalnızca onaylanmamış
        </label>
      </section>

      <section aria-label="Sayılar" data-testid="alarm-counts" className="flex flex-wrap gap-2 text-[13px]">
        <span className="rounded-full bg-white px-3 py-1.5 font-semibold shadow-sm">Toplam <b data-testid="count-total">{counts.total}</b></span>
        <span className="rounded-full bg-white px-3 py-1.5 shadow-sm">{ALARM_LABELS.hands_up} <b data-testid="count-hands_up">{counts.hands_up}</b></span>
        <span className="rounded-full bg-white px-3 py-1.5 shadow-sm">{ALARM_LABELS.lying} <b data-testid="count-lying">{counts.lying}</b></span>
        <span className="rounded-full bg-white px-3 py-1.5 shadow-sm">{ALARM_LABELS.test} <b data-testid="count-test">{counts.test}</b></span>
        <span className="rounded-full bg-white px-3 py-1.5 shadow-sm">Yanlış alarm <b data-testid="count-false">{counts.false}</b></span>
      </section>

      {error && <p role="status" className="rounded-xl bg-nok-50 px-3 py-2 text-sm text-nok-600">{error}</p>}
      {list !== null && list.length >= ALARM_LIST_LIMIT && (
        <p className="text-[12.5px] text-warn-700">İlk {ALARM_LIST_LIMIT} alarm gösteriliyor; tarih aralığını daraltın.</p>
      )}

      <section className="card overflow-x-auto">
        {list === null ? (
          <p className="p-5 text-sm text-muted">Yükleniyor…</p>
        ) : visible.length === 0 ? (
          <p className="p-5 text-sm text-muted">Bu süzgeçle alarm yok.</p>
        ) : (
          <table className="w-full min-w-[760px] text-left text-[13px]">
            <thead className="text-[11.5px] uppercase tracking-wider text-faint">
              <tr>
                <th className="px-4 py-3 font-semibold">Görüntü</th>
                <th className="px-3 py-3 font-semibold">Tür</th>
                <th className="px-3 py-3 font-semibold">Kamera</th>
                <th className="px-3 py-3 font-semibold">Tarih ve saat</th>
                <th className="px-3 py-3 font-semibold">Süre</th>
                <th className="px-3 py-3 font-semibold">Telegram</th>
                <th className="px-3 py-3 font-semibold">Durum</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((a) => {
                const st = state(a);
                return (
                  <tr key={a.id} data-testid="alarm-row" onClick={() => setViewing(a.id)}
                      className="cursor-pointer border-t border-line hover:bg-canvas">
                    <td className="px-4 py-2">
                      <button type="button" aria-label={`Kaydı izle: ${ALARM_LABELS[a.type]} — ${a.camera}`} onClick={(e) => { e.stopPropagation(); setViewing(a.id); }}
                              className="relative block h-12 w-20 overflow-hidden rounded-lg bg-canvas">
                        {a.image
                          // eslint-disable-next-line @next/next/no-img-element -- yerel olay resmi
                          ? <img src={alarmImageUrl(a.id)} alt="" className="h-full w-full object-cover" />
                          : <span className="grid h-full place-items-center text-lg" aria-hidden="true">🚨</span>}
                        {a.clip && <span className="absolute bottom-0.5 right-0.5 rounded bg-black/70 px-1 text-[10px] text-white" aria-hidden="true">▶</span>}
                      </button>
                    </td>
                    <td className="px-3 py-2 font-semibold">{ALARM_LABELS[a.type]}</td>
                    <td className="px-3 py-2">{a.camera}</td>
                    <td className="px-3 py-2 tabular-nums">{new Date(a.firedAt * 1000).toLocaleString("tr-TR")}</td>
                    <td className="px-3 py-2 tabular-nums">{duration(a)}</td>
                    <td className="px-3 py-2 text-muted">{NOTIFY_LABELS[a.notify]}</td>
                    <td className="px-3 py-2"><span className={`rounded-full px-2.5 py-0.5 text-[12px] font-medium ${st.tone}`}>{st.text}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      {viewing && visible.some((a) => a.id === viewing) && (
        <AlarmViewer alarms={visible} id={viewing} mode="browse" onSelect={setViewing} onClose={close} onAck={ack} onFalseAlarm={markFalse} />
      )}
    </div>
  );
}
