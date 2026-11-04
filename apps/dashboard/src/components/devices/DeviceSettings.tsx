"use client";

import { useCallback, useEffect, useState } from "react";
import { useUnsavedGuard } from "@/components/UnsavedGuard";
import { fetchDevices, runBenchmark, saveDevices, type BenchResult, type Choices, type DevicesState, type InUse } from "@/lib/devices";
import { benchText, choiceOptions, inUseText } from "@/lib/deviceOptions.mjs";
import { useRetryWhileFailed } from "@/lib/useRetryWhileFailed";

/** Kullanım satırları: anahtar sunucudaki `choices` anahtarıdır; `live`: altında "Şu an:" satırı olan canlı model */
const ROWS: { key: keyof Choices; label: string; live: "detector" | "pose" | null }[] = [
  { key: "detector", label: "Kişi ve araç tanıma (canlı)", live: "detector" },
  { key: "pose", label: "Poz — güvenlik alarmı (canlı)", live: "pose" },
  { key: "video", label: "Video ile test", live: null },
];

/** Yükleme sürerken "Şu an" satırlarının yenilenme aralığı */
const LOADING_POLL_MS = 2000;

type Bench = { ok: true; result: BenchResult } | { ok: false; text: string };

/** Cihaz ayarları: cihaz listesi + hız testi ve hangi modelin hangi cihazda çalışacağı. */
export default function DeviceSettings() {
  const [data, setData] = useState<DevicesState | null>(null);
  /** Kullanıcının değiştirdiği satırlar: geç gelen okuma bunların üstüne yazmaz */
  const [draft, setDraft] = useState<Partial<Choices>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  /** Ayarlar sunucudan okunamadı: okunana dek kendiliğinden yeniden denenir (son işlemin sonucundan ayrı satır) */
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  /** Hız testi: çalışan cihazın kimliği (aynı anda tek test) ve her cihazın son sonucu */
  const [benching, setBenching] = useState<string | null>(null);
  const [bench, setBench] = useState<Record<string, Bench>>({});
  const guard = useUnsavedGuard();

  /** Sunucudan gelen durum: ayarı okuyan HER istek buradan geçer (hata kalkar, yeniden deneme durur) */
  const apply = useCallback((d: DevicesState) => { setData(d); setLoadError(null); }, []);
  const load = useCallback(() => fetchDevices().then(apply).catch((e: Error) => setLoadError(e.message)), [apply]);
  useEffect(() => { void load(); }, [load]);
  useRetryWhileFailed(loadError !== null, load);

  // Bir model yeni cihaza yüklenirken "Şu an" satırı sonucu gösterene dek yenilenir
  const loading = data !== null && (data.inUse.detector.state === "loading" || data.inUse.pose.state === "loading");
  useEffect(() => {
    if (!loading) return;
    const timer = setInterval(() => { fetchDevices().then(apply).catch(() => undefined); }, LOADING_POLL_MS);
    return () => clearInterval(timer);
  }, [loading, apply]);

  /** Okunmadan form boştur: Kaydet o boş değerleri gönderip kayıtlı seçimleri silerdi */
  const ready = data !== null && loadError === null;
  const value = (k: keyof Choices): string => draft[k] ?? data?.choices[k] ?? "auto";
  const dirty = data !== null && ROWS.some(({ key }) => draft[key] !== undefined && draft[key] !== data.choices[key]);

  // Kaydedilmemiş değişiklikle menüden ayrılırken sorulur
  useEffect(() => { guard.setDirty(dirty, () => setDraft({})); }, [dirty, guard]);
  useEffect(() => () => guard.setDirty(false), [guard]);

  const lines = [loadError !== null ? { ok: false, text: loadError } : null, msg].filter((l) => l !== null);

  async function save() {
    if (!data) return;
    setSaving(true);
    try {
      const d = await saveDevices({ detector: value("detector"), pose: value("pose"), video: value("video") });
      apply(d); setDraft({}); setMsg({ ok: true, text: "Kaydedildi." });
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setSaving(false); }
  }

  async function measure(id: string) {
    setBenching(id);
    try {
      const result = await runBenchmark(id);
      setBench((b) => ({ ...b, [id]: { ok: true, result } }));
    } catch (e) {
      setBench((b) => ({ ...b, [id]: { ok: false, text: (e as Error).message } }));
    } finally { setBenching(null); }
  }

  return (
    <div className="max-w-[760px]">
      <section className="pl-section">
        <h2>Cihazlar</h2>
        {data !== null && !data.gpuSupport.available && data.gpuSupport.reason && (
          <p data-testid="gpu-support" className="px-3 pt-2 text-[12.5px] text-pl-faint">{data.gpuSupport.reason}</p>
        )}
        {data === null ? (
          <p className="p-3 text-[13px] text-pl-muted">{loadError === null ? "Yükleniyor…" : "Cihazlar okunamadı."}</p>
        ) : (
          <div className="overflow-x-auto p-3">
            <table className="pl-table min-w-[560px]">
              <thead>
                <tr><th>Ad</th><th>Tür</th><th>Bellek</th><th>Hız testi</th></tr>
              </thead>
              <tbody>
                {data.devices.map((d) => {
                  const b = bench[d.id];
                  const shown = b?.ok ? benchText(b.result) : b ? { text: b.text, warn: true } : null;
                  return (
                    <tr key={d.id} data-testid={`device-row-${d.id}`}>
                      <td>{d.name}</td>
                      <td>{d.kind === "gpu" ? "Ekran kartı" : "İşlemci"}</td>
                      <td className="tabular-nums">{d.memoryMb === undefined ? "—" : `${d.memoryMb} MB`}</td>
                      <td>
                        <button type="button" className="pl-btn h-7" disabled={benching !== null} onClick={() => measure(d.id)}>
                          {benching === d.id ? "Ölçülüyor…" : "Hız testi"}
                        </button>
                        {shown && (
                          <p role="status" data-testid={`bench-${d.id}`}
                             className={`mt-1 text-[12.5px] ${shown.warn ? "text-nok-ink" : "text-pl-muted"}`}>{shown.text}</p>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="pl-section">
        <h2>Kullanım</h2>
        {ROWS.map(({ key, label, live }) => {
          const status: InUse | null = live && data ? data.inUse[live] : null;
          const line = status ? inUseText(status) : null;
          return (
            <div key={key} className="pl-row">
              <label htmlFor={`use-${key}`}>{label}</label>
              <div className="min-w-0">
                <select id={`use-${key}`} data-testid={`use-${key}`} className="pl-input h-8 w-full" disabled={!ready} value={value(key)}
                        onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}>
                  {data && choiceOptions(data.devices, data.auto, data.choices[key]).map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
                {line && (
                  <p data-testid={`inuse-${key}`} className={`mt-1 text-[12px] ${line.warn ? "text-nok-ink" : "text-pl-faint"}`}>{line.text}</p>
                )}
              </div>
            </div>
          );
        })}
        <div className="flex flex-wrap gap-2 px-3 py-2">
          <button type="button" onClick={save} disabled={!ready || !dirty || saving} title={ready ? undefined : "Ayarlar henüz okunamadı"}
                  className="pl-btn pl-btn-primary h-8">Kaydet</button>
        </div>
        {lines.map((line, i) => (
          <p key={i} role="status" className={`mx-3 mb-2 rounded-[2px] border px-3 py-1.5 text-[13px] ${line.ok ? "border-ok-line bg-ok-50 text-ok-ink" : "border-nok-line bg-nok-50 text-nok-ink"}`}>{line.text}</p>
        ))}
        <p className="px-3 pb-2 text-[11.5px] text-pl-faint">
          Yeni seçim kaydedilince canlı modeller kesintisiz yeni cihaza geçer; yükleme sürerken eski cihaz çalışmaya devam eder.
          Ürün sayımı model kullanmaz, bu ayardan etkilenmez.
        </p>
      </section>
    </div>
  );
}
