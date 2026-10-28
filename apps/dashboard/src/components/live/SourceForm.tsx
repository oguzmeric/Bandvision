"use client";

import { useState } from "react";
import {
  api, CAMERA_BRANDS, RECORDER_BRANDS,
  type CameraBrand, type RecorderBrand, type Source, type SourceForm as Form, type SourceKind,
} from "@/lib/live";

const field = "pl-input h-8 w-full";
/** Alan etiketi: üstte küçük gri yazı, altında denetim */
const lbl = "mt-2.5 block text-[12.5px] text-pl-muted";

const EMPTY: Form = {
  kind: "recorder", name: "", brand: "hikvision", host: "", port: 554, channel: 1, substream: true, customUrl: "",
  recorderBrand: "trassir", httpPort: null, rtspPort: null, username: "admin", password: "",
};

/** Kayıtlı kaynaktan form: yalnızca düzenlenebilir alanlar (kimlik, oluşturma zamanı, "şifre kayıtlı" gönderilmez). */
function toForm(s: Source): Form {
  const { kind, name, brand, host, port, channel, substream, customUrl, recorderBrand, httpPort, rtspPort, username } = s;
  return { kind, name, brand, host, port, channel, substream, customUrl, recorderBrand, httpPort, rtspPort, username,
           password: null };
}

/**
 * IP kamera ya da kayıt cihazı (NVR/XVR) ekleme/düzenleme — telefondaki ağ kamerası formunun karşılığı.
 * Şifre yalnızca bu bilgisayardaki analiz sunucusuna gider; düzenlemede boş bırakılırsa kayıtlı şifre korunur.
 */
export default function SourceForm({ editing, onSaved, onCancel }: {
  editing: Source | null; onSaved: (s: Source) => void; onCancel?: () => void;
}) {
  const [f, setF] = useState<Form>(() => (editing ? toForm(editing) : EMPTY));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((x) => ({ ...x, [k]: v }));
  const rec = RECORDER_BRANDS.find((b) => b[0] === f.recorderBrand)!;

  async function save() {
    setError(null);
    if (f.kind === "camera" && f.brand === "custom" ? !f.customUrl.trim() : !f.host.trim()) {
      setError(f.kind === "camera" && f.brand === "custom" ? "RTSP adresini yaz." : "Cihazın IP adresini yaz.");
      return;
    }
    setBusy(true);
    try {
      const body = { ...f, password: f.password === "" && editing ? null : f.password };
      const s = editing
        ? await api<Source>(`sources/${editing.id}`, { method: "PUT", json: body })
        : await api<Source>("sources", { method: "POST", json: body });
      onSaved(s);
      if (!editing) setF(EMPTY);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const seg = (k: SourceKind, label: string) => (
    <button type="button" role="radio" aria-checked={f.kind === k} onClick={() => set("kind", k)}
            className={`h-7 text-[13px] ${f.kind === k ? "bg-pl-sel font-semibold text-pl-ink" : "bg-[#f7f8fa] text-pl-muted hover:bg-pl-head hover:text-pl-ink"}`}>
      {label}
    </button>
  );

  return (
    <section className="pl-section pb-2.5" aria-labelledby="source-form-title">
      <h2 id="source-form-title">{editing ? "Kaynağı düzenle" : "Yeni kaynak"}</h2>
      <div role="radiogroup" aria-label="Kaynak türü" className="grid grid-cols-2 divide-x divide-pl-ctl overflow-hidden rounded-[2px] border border-pl-ctl">
        {seg("recorder", "Kayıt cihazı (NVR)")}
        {seg("camera", "IP kamera")}
      </div>

      <label className={lbl}>Ad <span className="text-pl-faint">(isteğe bağlı)</span>
        <input className={`${field} mt-1`} value={f.name} maxLength={80} placeholder={f.kind === "recorder" ? "Ofis NVR" : "Bant 1 kamerası"}
               onChange={(e) => set("name", e.target.value)} />
      </label>

      {f.kind === "recorder" ? (
        <>
          <label className={lbl}>Marka
            <select aria-label="Kayıt cihazı markası" className={`${field} mt-1`} value={f.recorderBrand}
                    onChange={(e) => setF((x) => ({ ...x, recorderBrand: e.target.value as RecorderBrand, httpPort: null, rtspPort: null }))}>
              {RECORDER_BRANDS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
            </select>
          </label>
          <label className={lbl}>IP adresi
            <input aria-label="Cihaz adresi" className={`${field} mt-1`} value={f.host} placeholder="192.168.1.10" inputMode="url"
                   autoComplete="off" onChange={(e) => set("host", e.target.value)} />
          </label>
          <div className="grid grid-cols-2 gap-2.5">
            <label className={lbl}>{f.recorderBrand === "trassir" ? "SDK portu" : "Web portu"}
              <input className={`${field} mt-1`} inputMode="numeric" placeholder={String(rec[2])}
                     value={f.httpPort ?? ""} onChange={(e) => set("httpPort", e.target.value ? Number(e.target.value.replace(/\D/g, "")) : null)} />
            </label>
            <label className={lbl}>Görüntü portu
              <input className={`${field} mt-1`} inputMode="numeric" placeholder={String(rec[3])}
                     value={f.rtspPort ?? ""} onChange={(e) => set("rtspPort", e.target.value ? Number(e.target.value.replace(/\D/g, "")) : null)} />
            </label>
          </div>
          {f.recorderBrand === "trassir" && (
            <p className="mt-1 text-[11.5px] text-pl-faint">TRASSIR&apos;da Ayarlar → Web sunucusu (SDK) açık olmalı.</p>
          )}
        </>
      ) : (
        <>
          <label className={lbl}>Marka
            <select aria-label="Kamera markası" className={`${field} mt-1`} value={f.brand}
                    onChange={(e) => set("brand", e.target.value as CameraBrand)}>
              {CAMERA_BRANDS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
            </select>
          </label>
          {f.brand === "custom" ? (
            <label className={lbl}>RTSP adresi
              <input aria-label="RTSP adresi" className={`${field} mt-1`} value={f.customUrl} placeholder="rtsp://192.168.1.64:554/stream1"
                     autoComplete="off" onChange={(e) => set("customUrl", e.target.value)} />
              <span className="mt-1 block text-[11.5px] text-pl-faint">Kullanıcı adı ve şifreyi adrese yazma; aşağıdaki alanlara gir.</span>
            </label>
          ) : (
            <>
              <label className={lbl}>IP adresi
                <input aria-label="Kamera adresi" className={`${field} mt-1`} value={f.host} placeholder="192.168.1.64"
                       autoComplete="off" onChange={(e) => set("host", e.target.value)} />
              </label>
              <div className="grid grid-cols-2 gap-2.5">
                <label className={lbl}>RTSP portu
                  <input className={`${field} mt-1`} inputMode="numeric" value={f.port}
                         onChange={(e) => set("port", Number(e.target.value.replace(/\D/g, "")) || 554)} />
                </label>
                <label className={lbl}>Kanal
                  <input className={`${field} mt-1`} inputMode="numeric" value={f.channel}
                         onChange={(e) => set("channel", Number(e.target.value.replace(/\D/g, "")) || 1)} />
                </label>
              </div>
            </>
          )}
        </>
      )}

      <label className="mt-2.5 flex items-center gap-2 text-[13px]">
        <input type="checkbox" checked={f.substream} onChange={(e) => set("substream", e.target.checked)} className="h-4 w-4 accent-pl-accent" />
        Alt akış (önerilir: sayım için yeterli, ağ ve işlemci dostu)
      </label>

      <div className="grid grid-cols-2 gap-2.5">
        <label className={lbl}>Kullanıcı adı
          <input className={`${field} mt-1`} value={f.username} autoComplete="off" onChange={(e) => set("username", e.target.value)} />
        </label>
        <label className={lbl}>Şifre
          <input aria-label="Şifre" type="password" className={`${field} mt-1`} autoComplete="new-password"
                 placeholder={editing?.hasPassword ? "Kayıtlı (değiştirmek için yaz)" : ""}
                 value={f.password ?? ""} onChange={(e) => set("password", e.target.value)} />
        </label>
      </div>
      <p className="mt-1 text-[11.5px] text-pl-faint">Şifre yalnızca bu bilgisayarda saklanır; panele geri gösterilmez.</p>

      {error && <p role="alert" className="mt-2.5 rounded-[2px] border border-[#f3c2c7] bg-nok-50 px-3 py-2 text-[13px] text-nok-600">{error}</p>}

      <div className="-mx-2.5 mt-3 flex gap-2 border-t border-pl-line-soft px-2.5 pt-2.5">
        {onCancel && (
          <button type="button" onClick={onCancel} className="pl-btn h-8 flex-1 justify-center">Vazgeç</button>
        )}
        <button type="button" onClick={save} disabled={busy} className="pl-btn pl-btn-primary h-8 flex-1 justify-center">
          {busy ? "Kaydediliyor…" : editing ? "Kaydet" : f.kind === "recorder" ? "Kaydet ve kameraları listele" : "Kaydet"}
        </button>
      </div>
    </section>
  );
}
