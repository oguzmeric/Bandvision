"use client";

import { useRef, useState } from "react";
import GeometryDialog from "@/components/geometry/GeometryDialog";
import { bytes } from "@/lib/format";
import { clampLine, type Geometry } from "@/lib/geometry";
import {
  ANCHOR_LABELS, BELT_MODES, DIRECTION_LABELS, MODE_LABELS, PRESET_LABELS, PRESET_MODE,
  type AnalysisJob, type CountAnchor, type CountMode, type Direction, type JobOptions, type Preset,
} from "@/lib/types";

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
  const [mode, setMode] = useState<CountMode | "">("");          // "" = hazır profilin yöntemi
  const [truth, setTruth] = useState("");
  const [direction, setDirection] = useState<Direction | "">("");
  const [bgStart, setBgStart] = useState("");
  const [bgEnd, setBgEnd] = useState("");
  const [anchor, setAnchor] = useState<CountAnchor>("center");
  const [geom, setGeom] = useState<Geometry | null>(null);       // null: tüm görüntü, çizgi ortada
  const [editing, setEditing] = useState(false);
  const people = preset === "people";
  const effectiveMode = people ? "detect" : (mode || PRESET_MODE[preset]);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  function pick(f: File | undefined | null) {
    if (!f) return;
    setFile(f);
    setGeom(null);                       // başka video: alan ve çizgi yeniden ayarlanır
    setError(null);
  }

  function changeDirection(d: Direction | "") {
    setDirection(d);
    if (geom && d && !geom.countLine) setGeom(clampLine({ ...geom, direction: d }));
  }

  function options(): JobOptions | string {
    const o: JobOptions = { preset };
    if (!people && mode && mode !== PRESET_MODE[preset]) o.countMode = mode;
    if (truth.trim()) {
      const n = Number(truth);
      if (!Number.isInteger(n) || n < 1) return `${people ? "Doğru giriş" : "Doğru adet"} pozitif bir tam sayı olmalı.`;
      o.truth = n;
    }
    if (direction) o.direction = direction;
    if (geom) {                          // düzenleyiciden: alan, çokgen, düz ya da açılı çizgi ve yön
      o.roi = geom.roi;
      if (geom.roiPolygon) o.roiPolygon = geom.roiPolygon;
      if (geom.countLine && effectiveMode !== "linescan") o.countLine = geom.countLine;
      else o.line = geom.linePosition;
      o.direction = geom.direction;
    }
    if (people) {
      o.countAnchor = anchor;
    } else if (bgStart.trim() || bgEnd.trim()) {
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
        <select aria-label="Ürün" className={`${field} mt-1.5`} value={preset} onChange={(e) => { setPreset(e.target.value as Preset); setMode(""); }}>
          {(Object.keys(PRESET_LABELS) as Preset[]).map((p) => <option key={p} value={p}>{PRESET_LABELS[p]}</option>)}
        </select>
      </label>
      {people ? (
        <>
          <label className="mt-3 block text-sm font-medium">Kamera
            <select aria-label="Kamera konumu" className={`${field} mt-1.5`} value={anchor}
                    onChange={(e) => setAnchor(e.target.value as CountAnchor)}>
              {(Object.keys(ANCHOR_LABELS) as CountAnchor[]).map((a) => <option key={a} value={a}>{ANCHOR_LABELS[a]}</option>)}
            </select>
          </label>
          <p className="mt-1 text-xs text-faint">
            Giren ve çıkan kişiler ayrı sayılır; görüntü saklanmaz. Sayım çizgisi yataydır: kişilerin tamamen geçtiği
            yere koy (kapı eşiğine değil).
          </p>
        </>
      ) : (
        <>
          <label className="mt-3 block text-sm font-medium">Sayım yöntemi
            <select aria-label="Sayım yöntemi" className={`${field} mt-1.5`} value={mode || PRESET_MODE[preset]}
                    onChange={(e) => setMode(e.target.value as CountMode)}>
              {BELT_MODES.map((m) => <option key={m} value={m}>{MODE_LABELS[m]}</option>)}
            </select>
          </label>
          <p className="mt-1 text-xs text-faint">
            {(mode || PRESET_MODE[preset]) === "linescan"
              ? "Torba, koli gibi tek sıra gelen ürünler; bitişik ya da üst üste olabilir. Boş bant gerekmez, ürün boyu videodan öğrenilir."
              : "Yumurta gibi ayrık ürünler; arka plan videodan öğrenilir."}
          </p>
        </>
      )}
      <div className="mt-3 grid grid-cols-2 gap-2.5">
        <label className="block text-sm font-medium">{people ? "Doğru giriş" : "Doğru adet"} <span className="font-normal text-faint">(isteğe bağlı)</span>
          <input className={`${field} mt-1.5`} inputMode="numeric" placeholder={people ? "12" : "100"} value={truth}
                 onChange={(e) => setTruth(e.target.value.replace(/\D/g, ""))} />
        </label>
        <label className="block text-sm font-medium">{people ? "Giriş yönü" : "Akış yönü"}
          <select aria-label={people ? "Giriş yönü" : "Akış yönü"} className={`${field} mt-1.5`} value={geom ? geom.direction : direction}
                  disabled={!!geom?.countLine} onChange={(e) => changeDirection(e.target.value as Direction | "")}>
            <option value="" disabled={!!geom}>{people ? "Yukarıdan aşağı (varsayılan)" : "Otomatik bul"}</option>
            {(Object.keys(DIRECTION_LABELS) as Direction[]).map((d) => <option key={d} value={d}>{DIRECTION_LABELS[d]}</option>)}
          </select>
        </label>
      </div>
      <div className="mt-3 flex items-center justify-between gap-3 rounded-xl border border-line bg-canvas px-3 py-2.5">
        <div className="min-w-0 text-sm">
          <p className="font-medium">Alan ve sayım çizgisi</p>
          <p className="truncate text-xs text-faint" data-testid="geometry-summary">
            {geom
              ? `${geom.roiPolygon ? `${geom.roiPolygon.length} köşeli çokgen` : "Dikdörtgen alan"} · ${geom.countLine ? "açılı çizgi" : "düz çizgi"}`
              : "Tüm görüntü · çizgi ortada"}
          </p>
        </div>
        <div className="flex shrink-0 gap-1.5">
          {geom && (
            <button type="button" onClick={() => setGeom(null)} className="h-8 rounded-[9px] px-2 text-xs text-muted hover:text-ink">Kaldır</button>
          )}
          <button type="button" disabled={!file} onClick={() => setEditing(true)}
                  title={file ? undefined : "Önce bir video seç"}
                  className="h-8 rounded-[9px] border border-line bg-white px-3 text-[13px] font-semibold text-brand-500 hover:border-brand-100 disabled:cursor-not-allowed disabled:opacity-50">
            Ayarla
          </button>
        </div>
      </div>
      {editing && file && (
        <GeometryDialog file={file} initial={geom} twoWay={people} allowAngled={effectiveMode !== "linescan"}
                        onSave={(g) => { setGeom(g); setDirection(g.direction); }} onClose={() => setEditing(false)} />
      )}
      {people ? null : (
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-muted">Gelişmiş: boş bant aralığı</summary>
        <p className="mt-2 text-xs text-faint">Bant çok doluysa, videoda bandın boş göründüğü aralığı yaz (saniye). Arka plan oradan öğrenilir.</p>
        <div className="mt-2 grid grid-cols-2 gap-2.5">
          <input className={field} inputMode="decimal" placeholder="Başlangıç (ör. 0)" value={bgStart} onChange={(e) => setBgStart(e.target.value)} aria-label="Boş bant başlangıcı (saniye)" />
          <input className={field} inputMode="decimal" placeholder="Bitiş (ör. 1,5)" value={bgEnd} onChange={(e) => setBgEnd(e.target.value)} aria-label="Boş bant bitişi (saniye)" />
        </div>
      </details>
      )}
      <p className="mt-2 text-xs text-faint">{people ? "Doğru girişi" : "Doğru adeti"} yazarsan hata yüzdesi hesaplanır. Videolar 7 gün sonra silinir; sonuç özeti kalır.</p>

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
