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
  const field = "pl-input h-8 w-full";
  /** Alan etiketi: üstte küçük gri yazı, altında denetim */
  const lbl = "block text-[12.5px] text-pl-muted";

  return (
    <section className="pl-section pb-2.5" aria-labelledby="upload-title">
      <h2 id="upload-title">Yeni analiz</h2>
      <div
        role="button"
        tabIndex={0}
        aria-label="Video seç ya da buraya sürükle"
        onClick={() => input.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0]); }}
        className={`cursor-pointer rounded-[2px] border border-dashed px-4 py-4 text-center ${
          drag ? "border-pl-accent bg-pl-sel" : "border-pl-ctl bg-pl-side hover:bg-pl-sel"}`}
      >
        <div className="mx-auto grid h-8 w-8 place-items-center text-pl-accent" aria-hidden="true">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M12 16V4M7 9l5-5 5 5M4 20h16" /></svg>
        </div>
        {file ? (
          <>
            <p className="mt-1.5 font-semibold break-all">{file.name}</p>
            <p className="text-xs text-pl-muted">{bytes(file.size)} · değiştirmek için tıkla</p>
          </>
        ) : (
          <>
            <p className="mt-1.5 font-semibold">Videoyu sürükle ya da seç</p>
            <p className="text-xs text-pl-muted">MP4, MOV, AVI, MKV · en fazla 2 GB</p>
          </>
        )}
        <input ref={input} type="file" accept={ACCEPT} className="hidden" data-testid="file-input"
               onChange={(e) => pick(e.target.files?.[0])} />
      </div>

      <label className={`${lbl} mt-3`}>Ürün
        <select aria-label="Ürün" className={`${field} mt-1`} value={preset} onChange={(e) => { setPreset(e.target.value as Preset); setMode(""); }}>
          {(Object.keys(PRESET_LABELS) as Preset[]).map((p) => <option key={p} value={p}>{PRESET_LABELS[p]}</option>)}
        </select>
      </label>
      {people ? (
        <>
          <label className={`${lbl} mt-2.5`}>Kamera
            <select aria-label="Kamera konumu" className={`${field} mt-1`} value={anchor}
                    onChange={(e) => setAnchor(e.target.value as CountAnchor)}>
              {(Object.keys(ANCHOR_LABELS) as CountAnchor[]).map((a) => <option key={a} value={a}>{ANCHOR_LABELS[a]}</option>)}
            </select>
          </label>
          <p className="mt-1 text-xs text-pl-faint">
            Giren ve çıkan kişiler ayrı sayılır; görüntü saklanmaz. Sayım çizgisi yataydır: kişilerin tamamen geçtiği
            yere koy (kapı eşiğine değil).
          </p>
        </>
      ) : (
        <>
          <label className={`${lbl} mt-2.5`}>Sayım yöntemi
            <select aria-label="Sayım yöntemi" className={`${field} mt-1`} value={mode || PRESET_MODE[preset]}
                    onChange={(e) => setMode(e.target.value as CountMode)}>
              {BELT_MODES.map((m) => <option key={m} value={m}>{MODE_LABELS[m]}</option>)}
            </select>
          </label>
          <p className="mt-1 text-xs text-pl-faint">
            {(mode || PRESET_MODE[preset]) === "linescan"
              ? "Torba, koli gibi tek sıra gelen ürünler; bitişik ya da üst üste olabilir. Boş bant gerekmez, ürün boyu videodan öğrenilir."
              : "Yumurta gibi ayrık ürünler; arka plan videodan öğrenilir."}
          </p>
        </>
      )}
      <div className="mt-2.5 grid grid-cols-2 gap-2.5">
        <label className={lbl}>{people ? "Doğru giriş" : "Doğru adet"} <span className="text-pl-faint">(isteğe bağlı)</span>
          <input className={`${field} mt-1`} inputMode="numeric" placeholder={people ? "12" : "100"} value={truth}
                 onChange={(e) => setTruth(e.target.value.replace(/\D/g, ""))} />
        </label>
        <label className={lbl}>{people ? "Giriş yönü" : "Akış yönü"}
          <select aria-label={people ? "Giriş yönü" : "Akış yönü"} className={`${field} mt-1`} value={geom ? geom.direction : direction}
                  disabled={!!geom?.countLine} onChange={(e) => changeDirection(e.target.value as Direction | "")}>
            <option value="" disabled={!!geom}>{people ? "Yukarıdan aşağı (varsayılan)" : "Otomatik bul"}</option>
            {(Object.keys(DIRECTION_LABELS) as Direction[]).map((d) => <option key={d} value={d}>{DIRECTION_LABELS[d]}</option>)}
          </select>
        </label>
      </div>
      <div className="mt-2.5 flex items-center justify-between gap-3 rounded-[2px] border border-pl-line-soft bg-pl-side px-2.5 py-1.5">
        <div className="min-w-0">
          <p className="font-medium">Alan ve sayım çizgisi</p>
          <p className="truncate text-xs text-pl-faint" data-testid="geometry-summary">
            {geom
              ? `${geom.roiPolygon ? `${geom.roiPolygon.length} köşeli çokgen` : "Dikdörtgen alan"} · ${geom.countLine ? "açılı çizgi" : "düz çizgi"}`
              : "Tüm görüntü · çizgi ortada"}
          </p>
        </div>
        <div className="flex shrink-0 gap-1.5">
          {geom && (
            <button type="button" onClick={() => setGeom(null)} className="pl-btn h-7 text-xs">Kaldır</button>
          )}
          <button type="button" disabled={!file} onClick={() => setEditing(true)}
                  title={file ? undefined : "Önce bir video seç"}
                  className="pl-btn h-7 font-semibold">
            Ayarla
          </button>
        </div>
      </div>
      {editing && file && (
        <GeometryDialog file={file} initial={geom} twoWay={people} allowAngled={effectiveMode !== "linescan"}
                        onSave={(g) => { setGeom(g); setDirection(g.direction); }} onClose={() => setEditing(false)} />
      )}
      {people ? null : (
      <details className="mt-2.5">
        <summary className="cursor-pointer text-pl-muted">Gelişmiş: boş bant aralığı</summary>
        <p className="mt-2 text-xs text-pl-faint">Bant çok doluysa, videoda bandın boş göründüğü aralığı yaz (saniye). Arka plan oradan öğrenilir.</p>
        <div className="mt-2 grid grid-cols-2 gap-2.5">
          <input className={field} inputMode="decimal" placeholder="Başlangıç (ör. 0)" value={bgStart} onChange={(e) => setBgStart(e.target.value)} aria-label="Boş bant başlangıcı (saniye)" />
          <input className={field} inputMode="decimal" placeholder="Bitiş (ör. 1,5)" value={bgEnd} onChange={(e) => setBgEnd(e.target.value)} aria-label="Boş bant bitişi (saniye)" />
        </div>
      </details>
      )}
      <p className="mt-2 text-xs text-pl-faint">{people ? "Doğru girişi" : "Doğru adeti"} yazarsan hata yüzdesi hesaplanır. Videolar 7 gün sonra silinir; sonuç özeti kalır.</p>

      {error && <p role="alert" data-testid="upload-error" className="mt-2.5 rounded-[2px] border border-nok-line bg-nok-50 px-3 py-2 text-[13px] text-nok-600">{error}</p>}

      {uploading ? (
        <div className="mt-3" aria-live="polite">
          <div className="flex justify-between text-xs text-pl-muted"><span>Yükleniyor…</span><span>%{Math.round((progress ?? 0) * 100)}</span></div>
          <div className="mt-1 h-2 overflow-hidden rounded-[1px] border border-pl-line-soft bg-white">
            <div className="h-full bg-pl-accent transition-[width]" style={{ width: `${(progress ?? 0) * 100}%` }} />
          </div>
        </div>
      ) : (
        <button type="button" onClick={submit} className="pl-btn pl-btn-primary mt-3 h-8 w-full justify-center">
          Analizi başlat
        </button>
      )}
    </section>
  );
}
