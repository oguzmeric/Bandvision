"use client";

import { useRef, useState } from "react";
import { bytes } from "@/lib/format";
import { DIRECTION_LABELS, PRESET_LABELS, type AnalysisJob, type Direction, type JobOptions, type Preset } from "@/lib/types";

const ACCEPT = ".mp4,.mov,.m4v,.avi,.mkv,.webm,.3gp,.mts,.ts,video/*";

/** FastAPI hata gövdesi: {detail: "..."} ya da doğrulama listesi */
function errorText(body: unknown, status: number): string {
  const d = (body as { detail?: unknown })?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => (x as { msg?: string }).msg ?? String(x)).join("; ");
  return `Yükleme başarısız (HTTP ${status}).`;
}

export default function UploadCard({ onCreated }: { onCreated: (job: AnalysisJob) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [preset, setPreset] = useState<Preset>("egg");
  const [truth, setTruth] = useState("");
  const [direction, setDirection] = useState<Direction | "">("");
  const [bgStart, setBgStart] = useState("");
  const [bgEnd, setBgEnd] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  function pick(f: File | undefined | null) {
    if (!f) return;
    setFile(f);
    setError(null);
  }

  function options(): JobOptions | string {
    const o: JobOptions = { preset };
    if (truth.trim()) {
      const n = Number(truth);
      if (!Number.isInteger(n) || n < 1) return "Doğru adet pozitif bir tam sayı olmalı.";
      o.truth = n;
    }
    if (direction) o.direction = direction;
    if (bgStart.trim() || bgEnd.trim()) {
      const a = Number(bgStart.replace(",", ".")), b = Number(bgEnd.replace(",", "."));
      if (!(a >= 0) || !(b > a)) return "Boş bant aralığı: başlangıç ≥ 0 ve bitiş başlangıçtan büyük olmalı (saniye).";
      o.bgRange = [a, b];
    }
    return o;
  }

  function submit() {
    if (!file) {
      setError("Önce bir video seç.");
      return;
    }
    const o = options();
    if (typeof o === "string") {
      setError(o);
      return;
    }
    const form = new FormData();
    form.append("file", file);
    form.append("options", JSON.stringify(o));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/jobs");
    xhr.upload.onprogress = (e) => e.lengthComputable && setProgress(e.loaded / e.total);
    xhr.onload = () => {
      setProgress(null);
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* gövde JSON değil */
      }
      if (xhr.status === 202) {
        setFile(null);
        if (input.current) input.current.value = "";
        onCreated(body as AnalysisJob);
      } else {
        setError(errorText(body, xhr.status));
      }
    };
    xhr.onerror = () => {
      setProgress(null);
      setError("Bağlantı hatası: video gönderilemedi.");
    };
    setError(null);
    setProgress(0);
    xhr.send(form);
  }

  const uploading = progress !== null;
  const field = "h-10 w-full rounded-[10px] border border-line bg-white px-3 text-sm outline-none focus:border-brand-500 focus:ring-3 focus:ring-brand-50";

  return (
    <section className="card p-5" aria-labelledby="upload-title">
      <p id="upload-title" className="eyebrow mb-3">Yeni analiz</p>
      <div
        role="button"
        tabIndex={0}
        aria-label="Video seç ya da buraya sürükle"
        onClick={() => input.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0]); }}
        className={`cursor-pointer rounded-2xl border-[1.5px] border-dashed px-4 py-6 text-center transition ${
          drag ? "border-brand-500 bg-brand-50" : "border-[#cfc7f3] bg-[#fbfaff] hover:bg-brand-50"}`}
      >
        <div className="mx-auto grid h-11 w-11 place-items-center rounded-xl bg-brand-50 text-brand-500" aria-hidden="true">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M12 16V4M7 9l5-5 5 5M4 20h16" /></svg>
        </div>
        {file ? (
          <>
            <p className="mt-2.5 font-semibold break-all">{file.name}</p>
            <p className="text-xs text-muted">{bytes(file.size)} · değiştirmek için tıkla</p>
          </>
        ) : (
          <>
            <p className="mt-2.5 font-semibold">Videoyu sürükle ya da seç</p>
            <p className="text-xs text-muted">MP4, MOV, AVI, MKV · en fazla 2 GB</p>
          </>
        )}
        <input ref={input} type="file" accept={ACCEPT} className="hidden" data-testid="file-input"
               onChange={(e) => pick(e.target.files?.[0])} />
      </div>

      <label className="mt-4 block text-sm font-medium">Ürün
        <select className={`${field} mt-1.5`} value={preset} onChange={(e) => setPreset(e.target.value as Preset)}>
          {(Object.keys(PRESET_LABELS) as Preset[]).map((p) => <option key={p} value={p}>{PRESET_LABELS[p]}</option>)}
        </select>
      </label>
      <div className="mt-3 grid grid-cols-2 gap-2.5">
        <label className="block text-sm font-medium">Doğru adet <span className="font-normal text-faint">(isteğe bağlı)</span>
          <input className={`${field} mt-1.5`} inputMode="numeric" placeholder="100" value={truth}
                 onChange={(e) => setTruth(e.target.value.replace(/\D/g, ""))} />
        </label>
        <label className="block text-sm font-medium">Akış yönü
          <select className={`${field} mt-1.5`} value={direction} onChange={(e) => setDirection(e.target.value as Direction | "")}>
            <option value="">Otomatik bul</option>
            {(Object.keys(DIRECTION_LABELS) as Direction[]).map((d) => <option key={d} value={d}>{DIRECTION_LABELS[d]}</option>)}
          </select>
        </label>
      </div>
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-muted">Gelişmiş: boş bant aralığı</summary>
        <p className="mt-2 text-xs text-faint">Bant çok doluysa, videoda bandın boş göründüğü aralığı yaz (saniye). Arka plan oradan öğrenilir.</p>
        <div className="mt-2 grid grid-cols-2 gap-2.5">
          <input className={field} inputMode="decimal" placeholder="Başlangıç (ör. 0)" value={bgStart} onChange={(e) => setBgStart(e.target.value)} aria-label="Boş bant başlangıcı (saniye)" />
          <input className={field} inputMode="decimal" placeholder="Bitiş (ör. 1,5)" value={bgEnd} onChange={(e) => setBgEnd(e.target.value)} aria-label="Boş bant bitişi (saniye)" />
        </div>
      </details>
      <p className="mt-2 text-xs text-faint">Doğru adeti yazarsan hata yüzdesi hesaplanır. Videolar 7 gün sonra silinir; sonuç özeti kalır.</p>

      {error && <p role="alert" data-testid="upload-error" className="mt-3 rounded-xl bg-nok-50 px-3 py-2 text-sm text-nok-600">{error}</p>}

      {uploading ? (
        <div className="mt-4" aria-live="polite">
          <div className="flex justify-between text-xs text-muted"><span>Yükleniyor…</span><span>%{Math.round((progress ?? 0) * 100)}</span></div>
          <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-brand-50">
            <div className="brand-gradient h-full transition-[width]" style={{ width: `${(progress ?? 0) * 100}%` }} />
          </div>
        </div>
      ) : (
        <button type="button" onClick={submit}
                className="brand-gradient mt-4 h-11 w-full rounded-[11px] text-sm font-semibold text-white shadow-[0_8px_18px_rgba(109,59,240,0.25)] transition hover:brightness-105 active:scale-[0.99]">
          Analizi başlat
        </button>
      )}
    </section>
  );
}
