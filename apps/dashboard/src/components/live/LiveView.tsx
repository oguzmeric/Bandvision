"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import GeometryControls from "@/components/geometry/GeometryControls";
import RoiEditor from "@/components/geometry/RoiEditor";
import { int, num } from "@/lib/format";
import { flip, geometryOf, withGeometry, type Geometry } from "@/lib/geometry";
import { StreamChoice } from "./StartSessionDialog";
import StaffColors from "./StaffColors";
import { SafetyPanel, SafetySettings } from "./SafetyPanel";
import { MAX_STAFF_COLORS } from "@/lib/staff";
import { api, STATE_LABELS, stateDot, type LabColor, type LiveSession, type Profile } from "@/lib/live";
import { DIRECTION_LABELS, type CountAnchor, type CountMode } from "@/lib/types";

function Counter({ label, value, tone, hint, testId }: { label: string; value: number; tone: "brand" | "in" | "out"; hint?: string; testId: string }) {
  const tones = {
    brand: "border-brand-100 bg-brand-50 text-brand-600",
    in: "border-[#bfe8d3] bg-ok-50 text-ok-600",
    out: "border-[#f7d9b5] bg-warn-50 text-warn-700",
  };
  return (
    <div className={`rounded-2xl border px-4 py-3 ${tones[tone]}`}>
      <p className="text-[13px] font-semibold">{label}</p>
      <p className="text-[44px] font-semibold leading-none tracking-tight text-ink tabular-nums" data-testid={testId}>{int(value)}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

/** Açık canlı sayımların özeti: her kamerada giriş/çıkış (ya da adet) bir bakışta; tıklayınca o kamera açılır */
function SessionCard({ s, selected, onSelect }: { s: LiveSession; selected: boolean; onSelect: () => void }) {
  const watch = s.profile.countMode === "safety";
  // güvenlik: son 5 dakikada alarm olduysa kırmızı nokta ve "Alarm" (lastAlarmAt: unix saniye)
  const alarmed = s.safety?.lastAlarmAt != null && Date.now() / 1000 - s.safety.lastAlarmAt < 300;
  return (
    <button type="button" role="tab" aria-selected={selected} onClick={onSelect} data-testid="session-card"
            className={`rounded-2xl border px-3.5 py-2.5 text-left transition ${selected ? "border-brand-500 bg-brand-50 shadow-sm" : "border-line bg-white hover:border-brand-100"}`}>
      <span className="flex items-center gap-1.5">
        <span aria-hidden="true" className={`h-2 w-2 shrink-0 rounded-full ${stateDot(s.state)}`} />
        <span className="truncate text-[13px] font-semibold">{s.name}</span>
      </span>
      <span className="mt-1 block truncate text-[11.5px] text-faint">{s.profile.name}{s.counting || watch ? "" : " · duruyor"}</span>
      <span className="mt-1.5 flex gap-3 text-sm tabular-nums">
        {watch ? (
          <>
            {alarmed && (
              <span className="flex items-center gap-1.5 font-semibold text-nok-600">
                <span aria-hidden="true" className="h-2 w-2 rounded-full bg-nok-600" />Alarm
              </span>
            )}
            {s.state !== "live" ? (
              // kamera ölüyse "Nöbette" denmez: gerçek durum yazılır
              <span className={`text-[13px] ${s.state === "error" ? "font-medium text-nok-600" : "text-muted"}`}>{STATE_LABELS[s.state]}</span>
            ) : !alarmed && <span className="text-[13px] text-muted">Nöbette</span>}
          </>
        ) : s.twoWay ? (
          <>
            <span><span className="text-[11.5px] font-medium text-ok-600">Giriş</span> <b>{int(s.total)}</b></span>
            <span><span className="text-[11.5px] font-medium text-warn-700">Çıkış</span> <b>{int(s.totalOut)}</b></span>
          </>
        ) : (
          <span><b>{int(s.total)}</b> <span className="text-[11.5px] text-muted">adet</span></span>
        )}
      </span>
    </button>
  );
}

function Seg<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: Array<[T, string]>; onChange: (v: T) => void }) {
  return (
    <div role="radiogroup" aria-label={label} className="grid auto-cols-fr grid-flow-col rounded-[10px] border border-line bg-canvas p-0.5 text-[13px]">
      {options.map(([v, t]) => (
        <button key={v} type="button" role="radio" aria-checked={v === value} onClick={() => onChange(v)}
                className={`h-8 rounded-[8px] px-2 font-medium transition ${v === value ? "bg-white text-ink shadow-sm" : "text-muted hover:text-ink"}`}>{t}</button>
      ))}
    </div>
  );
}

const btn = "h-10 rounded-[10px] border border-line bg-white px-3 text-sm font-medium transition hover:border-brand-100 disabled:opacity-50";

export default function LiveView() {
  const router = useRouter();
  const params = useSearchParams();
  const [sessions, setSessions] = useState<LiveSession[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selectedId = params.get("s") ?? sessions?.[0]?.id ?? null;
  const session = sessions?.find((s) => s.id === selectedId) ?? null;

  // kalibrasyon taslağı (sunucudaki oturuma anında uygulanır; Kaydet ile profile yazılır, İptal ile geri alınır)
  const [draft, setDraft] = useState<Profile | null>(null);
  const original = useRef<Profile | null>(null);
  const [frameTick, setFrameTick] = useState(0);
  const [teaching, setTeaching] = useState(false);
  const [teachBusy, setTeachBusy] = useState(false);
  // yanıt gelince güncel taslak/oturum okunur (kapanmış ya da başka oturuma geçilmiş olabilir)
  const draftRef = useRef<Profile | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const pushTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // taslak kapanınca (Kaydet/İptal/oturum sekmesi değişimi) öğretme modu da kapanır
  useEffect(() => { if (!draft) setTeaching(false); }, [draft]);
  useEffect(() => { draftRef.current = draft; }, [draft]);
  useEffect(() => { sessionIdRef.current = session?.id ?? null; }, [session?.id]);

  const load = useCallback(() => {
    api<LiveSession[]>("sessions").then((s) => { setSessions(s); setError(null); }).catch((e: Error) => setError(e.message));
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, 1000);
    return () => clearInterval(t);
  }, [load]);

  // kalibrasyonda düzenleyicinin arka planı: işaretsiz son işlenen kare (~1,5/sn). Personel rengi öğretirken görüntü
  // donar: sunucu, en son verdiği kareyi (ve o karenin kişi kutularını) örnekler — tıklanan kare ile aynı.
  useEffect(() => {
    if (!draft || teaching) return;
    const t = setInterval(() => setFrameTick((x) => x + 1), 650);
    return () => clearInterval(t);
  }, [draft, teaching]);

  // öğrenilen değerler (eşik, tek ürün alanı, ürün boyu) sunucudan taslağa
  useEffect(() => {
    if (!draft || !session) return;
    const p = session.profile;
    if (p.diffThreshold !== draft.diffThreshold || p.expectedArea !== draft.expectedArea || p.productLength !== draft.productLength) {
      setDraft((d) => d && { ...d, diffThreshold: p.diffThreshold, expectedArea: p.expectedArea, productLength: p.productLength });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- yalnızca sunucudaki öğrenilen değerler değişince
  }, [session?.profile.diffThreshold, session?.profile.expectedArea, session?.profile.productLength]);

  async function act(action: string) {
    if (!session) return;
    try {
      await api(`sessions/${session.id}/actions`, { method: "POST", json: { action } });
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function pushProfile(p: Profile, save = false) {
    if (!session) return Promise.resolve();
    return api(`sessions/${session.id}/profile${save ? "?save=true" : ""}`, { method: "PUT", json: p })
      .catch((e: Error) => setError(e.message));
  }

  function edit(p: Profile) {
    setDraft(p);
    if (pushTimer.current) clearTimeout(pushTimer.current);
    pushTimer.current = setTimeout(() => pushProfile(p), 200);
  }

  function beginCalibration() {
    if (!session) return;
    original.current = session.profile;
    setDraft(session.profile);
  }

  async function finishCalibration(save: boolean) {
    setTeaching(false);
    if (!draft) return;
    if (pushTimer.current) clearTimeout(pushTimer.current);
    if (save) await pushProfile(draft, true);
    else {
      await act("cancelCalibration");
      if (original.current) await pushProfile(original.current);
    }
    setDraft(null);
    load();
  }

  async function flipEntry() {
    if (!session) return;
    const p = session.profile;
    const g = flip(geometryOf(p), aspect);
    await pushProfile(withGeometry(p, g), true);              // ana ekrandan çevirme hemen kaydedilir (telefondaki gibi)
    load();
  }

  async function teachAt(e: React.MouseEvent<HTMLButtonElement>) {
    if (!session || !draft || teachBusy) return;
    const r = e.currentTarget.getBoundingClientRect();
    const clamp = (v: number) => Math.min(1, Math.max(0, v));
    const x = clamp((e.clientX - r.left) / r.width), y = clamp((e.clientY - r.top) / r.height);
    const sid = session.id;
    setTeachBusy(true);
    try {
      const c = await api<LabColor & { achromatic: boolean }>(`sessions/${sid}/staff-color`, { method: "POST", json: { x, y } });
      const d = draftRef.current;
      if (!d || sessionIdRef.current !== sid) return;           // beklerken Kaydet/İptal/sekme değişti
      const cur = d.staffColors ?? [];
      if (cur.length < MAX_STAFF_COLORS) edit({ ...d, staffColors: [...cur, { L: c.L, a: c.a, b: c.b }] });
      setTeaching(false);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setTeachBusy(false);
    }
  }

  /** Alt ↔ ana akış: aynı oturum yeni akışa bağlanır, sayaçlar sıfırlanmaz */
  async function switchStream(sub: boolean) {
    if (!session || session.substream === sub) return;
    try {
      await api(`sessions/${session.id}/stream`, { method: "PUT", json: { substream: sub } });
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function closeSession() {
    const text = session?.profile.countMode === "safety"
      ? "Canlı sayım kapatılsın mı? Bu kamera izlenmez ve alarm vermez."
      : "Canlı sayım kapatılsın mı? Sayılar sıfırlanır.";
    if (!session || !confirm(text)) return;
    await api(`sessions/${session.id}`, { method: "DELETE" }).catch(() => undefined);
    router.replace("/live");
    load();
  }

  // Canlı akış: oturum bağlanırken açılan istek boş kalabilir → "Canlı" olunca ve akış koparsa yeniden açılır
  const state = session?.state;
  const [streamKey, setStreamKey] = useState(0);
  const prevState = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (state === "live" && prevState.current !== "live") setStreamKey((k) => k + 1);
    prevState.current = state;
  }, [state]);

  const aspect = session && session.width && session.height ? session.width / session.height : 16 / 9;

  if (sessions === null) return error
    ? <p role="alert" className="rounded-xl bg-nok-50 px-3 py-2 text-sm text-nok-600">{error}</p>
    : <div className="h-64 animate-pulse rounded-3xl bg-white/70" />;

  if (!session) {
    return (
      <section className="card grid min-h-[320px] place-items-center p-8 text-center">
        <div>
          <p className="font-medium">Açık canlı sayım yok</p>
          <p className="mt-1 text-sm text-muted">Kameralar sayfasından bir kamera seçip &quot;Canlı sayım&quot;ı başlat.</p>
          <Link href="/cameras" className="brand-gradient mt-4 inline-flex h-10 items-center rounded-[11px] px-4 text-sm font-semibold text-white">Kameralara git</Link>
        </div>
      </section>
    );
  }

  const p = draft ?? session.profile;
  const mode: CountMode = (p.countMode as CountMode | undefined) ?? "blob";
  const twoWay = mode === "detect";
  const safety = mode === "safety";
  const g = geometryOf(p);
  const live = session.state === "live";
  const stateTone = live ? "bg-ok-50 text-ok-600" : session.state === "ended" ? "bg-canvas-2 text-muted" : "bg-warn-50 text-warn-700";

  return (
    <div>
      <div className="mb-4 grid grid-cols-[repeat(auto-fill,minmax(210px,1fr))] gap-2.5" role="tablist" aria-label="Canlı sayımlar">
        {sessions.map((s) => (
          <SessionCard key={s.id} s={s} selected={s.id === session.id}
                       onSelect={() => { setDraft(null); router.replace(`/live?s=${s.id}`); }} />
        ))}
        <Link href="/cameras"
              className="grid min-h-[76px] place-items-center rounded-2xl border border-dashed border-line px-3 text-[13px] font-medium text-muted transition hover:border-brand-100 hover:text-brand-500">
          + Kamera ekle
        </Link>
      </div>
      {error && <p role="alert" className="mb-3 rounded-xl bg-nok-50 px-3 py-2 text-sm text-nok-600">{error}</p>}

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section className="card min-w-0 p-3" aria-label="Canlı görüntü">
          <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2 px-1">
            <div className="min-w-0">
              <h2 className="truncate font-semibold">{session.name}</h2>
              <p className="truncate text-xs text-muted">{p.name}{session.message ? ` · ${session.message}` : ""}</p>
            </div>
            <span className={`rounded-full px-2.5 py-1 text-[11.5px] font-semibold ${stateTone}`} data-testid="live-state">
              {STATE_LABELS[session.state]}{live && session.fps ? ` · ${num(session.fps, 0)} fps` : ""}
            </span>
          </div>
          {draft ? (
            <RoiEditor src={`/api/live/sessions/${session.id}/frame.jpg?t=${frameTick}`} aspect={aspect}
                       value={g} onChange={(ng: Geometry) => edit(withGeometry(p, ng))} twoWay={twoWay} showLine={!safety} editable={!teaching}>
              {teaching && (
                <button type="button" aria-label="Görüntüde personelin üstüne tıklayın" onClick={teachAt} disabled={teachBusy}
                        className="absolute inset-0 cursor-crosshair outline-none ring-2 ring-inset ring-warn-500" />
              )}
            </RoiEditor>
          ) : (
            <div className="relative w-full overflow-hidden rounded-2xl bg-[#111]" style={{ aspectRatio: String(aspect) }}>
              {/* eslint-disable-next-line @next/next/no-img-element -- MJPEG canlı akış */}
              <img src={`/api/live/sessions/${session.id}/stream?k=${streamKey}`} alt="İşaretli canlı görüntü"
                   onError={() => setTimeout(() => setStreamKey((k) => k + 1), 2000)}
                   className="absolute inset-0 h-full w-full" />
            </div>
          )}
        </section>

        <aside className="grid gap-4">
          {!draft ? (
            <>
              {safety && <SafetyPanel session={session} />}
              <section className="card p-4" aria-label={safety ? "Kamera" : "Sayım"}>
                {safety ? null : twoWay ? (
                  <div className="grid grid-cols-2 gap-2.5">
                    <Counter label="Giriş" value={session.total} tone="in" testId="live-in" />
                    <Counter label="Çıkış" value={session.totalOut} tone="out" testId="live-out" />
                  </div>
                ) : (
                  <Counter label="Sayılan" value={session.total} tone="brand" hint={`${int(session.ratePerMinute)} adet/dk`} testId="live-count" />
                )}
                {twoWay && (p.staffColors?.length ?? 0) > 0 && (
                  <p className="mt-2 text-center text-[12.5px] text-muted" data-testid="live-staff">
                    Personel geçişi: <b className="tabular-nums text-ink">{int(session.staffIn + session.staffOut)}</b>
                  </p>
                )}
                {twoWay && (
                  <button type="button" onClick={flipEntry} className={`${btn} mt-3 flex w-full items-center justify-between`}>
                    <span>Giriş yönü: {p.countLine ? "çizgideki ok yönünde" : DIRECTION_LABELS[p.direction].toLocaleLowerCase("tr")}</span>
                    <span className="font-semibold text-brand-500">⇅ Çevir</span>
                  </button>
                )}
                {safety ? (
                  <button type="button" className={`${btn} w-full`} onClick={beginCalibration}>Ayarla</button>
                ) : (
                  <div className="mt-3 grid grid-cols-3 gap-2">
                    <button type="button" onClick={() => act(session.counting ? "stop" : "start")}
                            className={`h-11 rounded-[11px] text-sm font-semibold text-white ${session.counting ? "bg-[#f08a24] hover:brightness-105" : "bg-ok-600 hover:brightness-105"}`}>
                      {session.counting ? "Durdur" : "Başlat"}
                    </button>
                    <button type="button" className={btn} onClick={() => confirm("Sayaç sıfırlansın mı?") && act("reset")}>Sıfırla</button>
                    <button type="button" className={btn} onClick={beginCalibration}>{twoWay ? "Ayarla" : "Kalibre"}</button>
                  </div>
                )}
                {session.substream !== null && (
                  <div className="mt-3">
                    <p className="mb-1.5 text-xs font-medium text-muted">Görüntü</p>
                    <StreamChoice value={session.substream} onChange={switchStream} />
                  </div>
                )}
                {!session.counting && !safety && (
                  <p className="mt-2 text-xs text-faint">Sayım duruyor: görüntü işleniyor ama sayılmıyor. &quot;Başlat&quot; ile sayım başlar.</p>
                )}
                <div className="mt-4 flex items-center justify-between border-t border-line pt-3 text-[13px]">
                  {safety ? <span /> : (
                    <a href={`/api/live/sessions/${session.id}/counts.csv`} className="font-medium text-brand-500 hover:underline">CSV indir</a>
                  )}
                  <button type="button" onClick={closeSession} className="font-medium text-nok-600 hover:underline">Canlı sayımı kapat</button>
                </div>
              </section>
            </>
          ) : (
            <section className="card p-4" aria-label={safety ? "Güvenlik ayarları" : "Kalibrasyon"}>
              <p className="font-semibold">{twoWay || safety ? "Ayarlar" : "Kalibrasyon"}</p>
              {!safety && (session.calibrationMessage || !twoWay) && (
                <p className="mt-2 rounded-xl bg-warn-50 px-3 py-2 text-[12.5px] text-warn-700" aria-live="polite">
                  {session.calibrationMessage || (mode === "linescan"
                    ? "Sarı alanı bandın üstüne, turuncu çizgiyi akışa dik koy. Ürün boyu ilk ürünlerden kendiliğinden öğrenilir."
                    : "Sarı alanı ve turuncu çizgiyi ayarla, sonra boş bandı öğret.")}
                </p>
              )}
              <div className="mt-3 grid gap-3">
                {safety ? (
                  <SafetySettings value={p.safety} onChange={(sf) => edit({ ...p, safety: sf })} />
                ) : twoWay ? (
                  <div>
                    <p className="mb-1.5 text-xs font-medium text-muted">Kamera</p>
                    <Seg label="Kamera konumu" value={(p.countAnchor ?? "center") as CountAnchor}
                         options={[["center", "Tepeden"], ["bottom", "Yandan"]]}
                         onChange={(a) => edit({ ...p, countAnchor: a })} />
                    <p className="mt-1 text-[11.5px] text-faint">
                      {(p.countAnchor ?? "center") === "center"
                        ? "Kamera girişe yukarıdan bakıyor; kameranın tam altında tanınamayan kişi hareketinden izlenir."
                        : "Kamera yandan/eğik bakıyor; kişinin ayağı çizgiyi geçince sayılır (çizgiyi zemine çiz)."}
                    </p>
                    <div className="mt-3">
                      <StaffColors colors={p.staffColors ?? []} teaching={teaching} onTeach={setTeaching}
                                   onRemove={(i) => edit({ ...p, staffColors: (p.staffColors ?? []).filter((_, k) => k !== i) })} />
                    </div>
                  </div>
                ) : (
                  <div>
                    <p className="mb-1.5 text-xs font-medium text-muted">Sayım yöntemi</p>
                    <Seg label="Sayım yöntemi" value={mode} options={[["blob", "Ayrık ürün"], ["linescan", "Bitişik / hacimli"]]}
                         onChange={(m) => {
                           const ng = m === "linescan" ? { ...g, countLine: null } : g;     // şerit tarama açılı çizgiyle çalışmaz
                           edit(withGeometry({ ...p, countMode: m }, ng));
                         }} />
                    <p className="mt-1 text-[11.5px] text-faint">
                      {mode === "linescan" ? "Torba, koli gibi tek sıra gelen ürünler; bitişik olabilir. Boş bant gerekmez."
                        : "Yumurta, meyve gibi ayrık ürünler; bant boşken arka plan öğrenilir."}
                    </p>
                  </div>
                )}
                <GeometryControls value={g} onChange={(ng) => edit(withGeometry(p, ng))} aspect={aspect} twoWay={twoWay}
                                  allowAngled={mode !== "linescan" && !safety} showLine={!safety} compact />
                {safety && (
                  <p className="rounded-xl bg-brand-50 px-3 py-2 text-[12px] text-brand-600">
                    Alan: kural yalnızca alandaki kişilere uygulanır (ör. tezgah arkası).
                  </p>
                )}
                {mode === "blob" && (
                  <>
                    <div className="grid grid-cols-2 gap-2">
                      <button type="button" className={btn} onClick={() => act("learnBackground")}>1. Boş bandı öğren</button>
                      <button type="button" className={btn} onClick={() => act("learnSample")}>2. Örnek geçir (8)</button>
                    </div>
                    <label className="block text-[13px]">Hassasiyet eşiği: <b>{p.diffThreshold}</b> <span className="text-faint">(düşük = daha hassas)</span>
                      <input type="range" min={5} max={120} value={p.diffThreshold} className="mt-1 w-full accent-brand-500"
                             onChange={(e) => edit({ ...p, diffThreshold: Number(e.target.value) })} />
                    </label>
                    <label className="flex items-center gap-2 text-[13px]">
                      <input type="checkbox" checked={p.splitTouching} className="h-4 w-4 accent-brand-500"
                             onChange={(e) => edit({ ...p, splitTouching: e.target.checked })} />
                      Bitişik ürünleri ayır (alan oranıyla)
                    </label>
                    <p className="text-xs text-faint">{p.expectedArea > 0 ? `Tek ürün alanı: ${num(p.expectedArea, 4)}` : "Tek ürün alanı: henüz öğrenilmedi"}</p>
                  </>
                )}
                {mode === "linescan" && (
                  <>
                    <div className="flex gap-2">
                      <button type="button" className={`${btn} flex-1`} onClick={() => act("learnSample")}>Ürün boyunu öğren</button>
                      {(p.productLength ?? 0) > 0 && (
                        <button type="button" className={btn} onClick={() => edit({ ...p, productLength: 0 })}>Otomatik</button>
                      )}
                    </div>
                    <p className="text-xs text-faint">
                      {(p.productLength ?? 0) > 0 ? `Ürün boyu: alanın %${num((p.productLength ?? 0) * 100, 0)}'i (kaydedilince sabit kalır)`
                        : "Ürün boyu: ilk ürünlerden kendiliğinden öğrenilir"}
                    </p>
                  </>
                )}
                {twoWay && (
                  <p className="rounded-xl bg-brand-50 px-3 py-2 text-[12px] text-brand-600">
                    Çizgiyi kişilerin tamamen geçtiği yere, yürüme alanının ortasına koy — kapı eşiğine değil.
                  </p>
                )}
              </div>
              <div className="mt-4 flex gap-2 border-t border-line pt-3">
                <button type="button" className={`${btn} flex-1`} onClick={() => finishCalibration(false)}>İptal</button>
                <button type="button" onClick={() => finishCalibration(true)}
                        className="brand-gradient h-10 flex-1 rounded-[10px] text-sm font-semibold text-white">Kaydet</button>
              </div>
              <p className="mt-2 text-[11.5px] text-faint">
                {safety ? "Alan ve kurallar yalnızca bu kamera için kaydedilir; diğer kameralar etkilenmez."
                  : "Alan, çizgi ve yön yalnızca bu kamera için kaydedilir; diğer kameralar etkilenmez."}
              </p>
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
