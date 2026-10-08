"use client";

import { useEffect, useState } from "react";
import { ALARM_LABELS, NOTIFY_LABELS, STATE_LABELS, api, safetyHealth, stateDot, type Alarm, type LiveSession, type SafetyConfig } from "@/lib/live";

export const SAFETY_DEFAULTS: SafetyConfig = { handsUp: { enabled: true, seconds: 3 }, lying: { enabled: true, seconds: 10 }, sendImage: false };

/** Güvenlik oturumunun yan paneli: izleniyor (ve izlenmiyorsa nedeni), süren durumlar, son alarmlar, deneme alarmı */
export function SafetyPanel({ session }: { session: LiveSession }) {
  // liste hangi oturuma ait olduğunu taşır: kamera değişince önceki kameranın alarmları bir an bile görünmez
  const [loaded, setLoaded] = useState<{ id: string; list: Alarm[] }>({ id: session.id, list: [] });
  const [reload, setReload] = useState(0);
  const [test, setTest] = useState<{ id: string; ok: boolean; text: string } | null>(null);
  useEffect(() => {
    let alive = true;
    // sunucu `sessionId` ile süzer (genel 50 sınırı başka kameralar yüzünden bu kameranın alarmlarını kesmesin);
    // eski analiz sunucusu parametreyi yok sayarsa istemci de süzer
    const load = () => api<Alarm[]>(`alarms?sessionId=${encodeURIComponent(session.id)}`)
      .then((a) => alive && setLoaded({ id: session.id, list: a.filter((x) => x.sessionId === session.id).slice(0, 10) }))
      .catch(() => undefined);
    load();
    const t = setInterval(load, 3000);
    return () => { alive = false; clearInterval(t); };
  }, [session.id, reload]);
  const alarms = loaded.id === session.id ? loaded.list : [];
  const active = session.safety?.active ?? [];
  const health = safetyHealth(session);
  // ekler gerekçeyi üreten koşula göre (bağımsız bayraklara göre değil): yalnızca model hatası yeniden denenir
  const loading = health.cause === "loading";
  const modelFailed = health.cause === "modelError";

  /** Bu kameranın karesiyle deneme alarmı: şeritte ve bu kameranın "Son alarmlar"ında görünür */
  async function testAlarm() {
    const id = session.id;
    try {
      await api("alarms/test", { method: "POST", json: { sessionId: id } });
      setTest({ id, ok: true, text: "Deneme alarmı oluşturuldu." });
      setReload((x) => x + 1);
    } catch (e) {
      setTest({ id, ok: false, text: (e as Error).message });
    }
  }

  return (
    <section className="card p-4" aria-label="Güvenlik">
      <p className="flex items-center gap-2 font-semibold"><span className={`h-2 w-2 rounded-full ${stateDot(session.state)}`} aria-hidden="true" />İzleniyor</p>
      {session.state !== "live" ? (
        <p className={`mt-1 text-[12.5px] ${session.state === "error" ? "text-nok-600" : "text-muted"}`} data-testid="safety-state">
          Kamera: {STATE_LABELS[session.state]}{session.message ? ` — ${session.message}` : ""}
        </p>
      ) : !health.healthy && health.reason && (
        // gerçek neden (model yükleniyor/yüklenemedi, görüntü işlenemiyor…); model hatasında sunucunun Türkçe iletisi
        <p className={`mt-1 text-[12.5px] ${loading ? "text-muted" : "text-nok-600"}`} data-testid="safety-reason">
          {health.reason}{loading ? "…" : ""}{modelFailed ? " · 1 dakika sonra yeniden denenir." : ""}
        </p>
      )}
      {active.length > 0 && (
        <ul className="mt-2 grid gap-1 text-[13px]">
          {active.map((a) => <li key={`${a.trackId}-${a.type}`}>{ALARM_LABELS[a.type]}: {a.seconds.toFixed(1)} sn</li>)}
        </ul>
      )}
      <p className="mb-1.5 mt-4 text-xs font-medium text-muted">Son alarmlar</p>
      {alarms.length === 0 ? <p className="text-[13px] text-faint">Henüz alarm yok.</p> : (
        <ul className="grid gap-2">
          {alarms.map((a) => (
            <li key={a.id} className="flex items-center gap-2.5 rounded-xl border border-line p-2">
              {a.image
                // eslint-disable-next-line @next/next/no-img-element -- yerel olay resmi
                ? <img src={`/api/live/alarms/${a.id}/image.jpg`} alt="" className="h-12 w-16 rounded-lg object-cover" />
                : <span className="grid h-12 w-16 place-items-center rounded-lg bg-canvas text-lg" aria-hidden="true">🚨</span>}
              <span className="min-w-0 text-[13px]">
                <b>{ALARM_LABELS[a.type]}</b> · {new Date(a.firedAt * 1000).toLocaleTimeString("tr-TR")}
                <span className="block text-[11.5px] text-faint">{NOTIFY_LABELS[a.notify]}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      <button type="button" onClick={testAlarm}
              className="mt-3 h-9 w-full rounded-[10px] border border-line text-[13px] font-medium hover:border-brand-100">
        Deneme alarmı
      </button>
      {test && test.id === session.id && (
        <p role="status" className={`mt-2 text-[12px] ${test.ok ? "text-ok-600" : "text-nok-600"}`}>{test.text}</p>
      )}
    </section>
  );
}

/** Ayarla panelinde güvenlik kuralları */
export function SafetySettings({ value, onChange }: { value: SafetyConfig | undefined; onChange: (v: SafetyConfig) => void }) {
  const v = value ?? SAFETY_DEFAULTS;
  const rule = (k: "handsUp" | "lying", label: string, min: number, max: number) => (
    <div className="grid gap-1">
      <label className="flex items-center gap-2 text-sm font-medium">
        <input type="checkbox" className="h-4 w-4 accent-brand-500" checked={v[k].enabled}
               onChange={(e) => onChange({ ...v, [k]: { ...v[k], enabled: e.target.checked } })} />
        {label}
      </label>
      <label className="text-[13px]">{label} süresi: <b>{v[k].seconds} sn</b>
        <input type="range" aria-label={`${label} süresi`} min={min} max={max} step={1} value={v[k].seconds} disabled={!v[k].enabled}
               className="mt-1 w-full accent-brand-500" onChange={(e) => onChange({ ...v, [k]: { ...v[k], seconds: Number(e.target.value) } })} />
      </label>
    </div>
  );
  return (
    <div role="group" aria-label="Güvenlik kuralları" className="grid gap-3">
      {rule("handsUp", "Eller yukarı", 3, 5)}
      {rule("lying", "Yerde yatan kişi", 5, 30)}
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-0.5 h-4 w-4 accent-brand-500" checked={v.sendImage} onChange={(e) => onChange({ ...v, sendImage: e.target.checked })} />
        <span>Olay resmini Telegram&apos;a gönder
          <span className="block text-[11.5px] text-faint">Kapalıyken yalnızca kamera adı ve saat gider. Resimler bu bilgisayarda 7 gün saklanır.</span>
        </span>
      </label>
    </div>
  );
}
