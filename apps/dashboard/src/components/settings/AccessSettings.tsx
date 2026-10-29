"use client";

import { useEffect, useState } from "react";
import QRCode from "qrcode";

interface AccessView {
  enabled: boolean; hasPassword: boolean; envPassword: boolean; lanActive: boolean; runner: boolean; addresses: string[];
  /** Başlatıcının son durumu (tools/panel_run.mjs): derleme sürüyor ya da yerel ağ derlemesi/denetimi başarısız */
  buildState: "building" | "failed" | "listening" | null; buildMessage: string | null;
}

/** Ayarlar → Telefondan erişim: panel şifresi, açma/kapama, telefon adresi ve QR kodu */
export default function AccessSettings() {
  const [v, setV] = useState<AccessView | null>(null);
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const load = async () => setV(await (await fetch("/api/access", { cache: "no-store" })).json());
  useEffect(() => { load().catch(() => setMsg({ ok: false, text: "Ayarlar okunamadı." })); }, []);
  useEffect(() => {
    const url = v?.addresses[0];
    if (v?.lanActive && url) QRCode.toDataURL(url, { margin: 1, width: 220 }).then(setQr).catch(() => setQr(null));
    else setQr(null);
  }, [v]);
  const save = async (enabled: boolean) => {
    if (pw && pw !== pw2) return setMsg({ ok: false, text: "Şifreler aynı değil." });
    try {
      const res = await fetch("/api/access", { method: "PUT", headers: { "content-type": "application/json" },
        body: JSON.stringify({ enabled, password: pw || null }) });
      const body = await res.json();
      if (!res.ok) return setMsg({ ok: false, text: body.detail ?? "Kaydedilemedi." });
      setPw(""); setPw2(""); setV(body);
      setMsg({ ok: true, text: body.runner
        ? (enabled ? "Kaydedildi. Panel yeniden başlıyor; yerel ağ kipi için üretim derlemesi gerekirse 1-2 dakika sürebilir. Sayfayı sonra yenileyin."
                   : "Kaydedildi. Panel birkaç saniye içinde yeniden başlıyor; sayfayı sonra yenileyin.")
        : "Kaydedildi. Geçerli olması için paneli masaüstü kısayoluyla yeniden başlatın." });
    } catch {
      // Panel kaydın hemen ardından yeniden başlar: bağlantının kopması beklenen bir durum
      setMsg({ ok: false, text: "Panel yeniden başlıyor olabilir; birkaç saniye sonra sayfayı yenileyin." });
    }
  };
  if (!v) return null;
  return (
    <section className="pl-section max-w-[760px]">
      <h2>Telefondan erişim</h2>
      <p className="py-1 text-pl-muted">Açıkken panel ofis ağındaki telefon ve bilgisayarlardan açılır ve herkesten (bu bilgisayar dahil) şifre ister.</p>
      {v.envPassword
        ? <p className="py-1 text-pl-faint">Panel şifresi bu bilgisayarın ayarında (DASHBOARD_PASSWORD) tanımlı.</p>
        : (
          <>
            <div className="pl-row">
              <label htmlFor="access-pw">{v.hasPassword ? "Yeni panel şifresi" : "Panel şifresi"}</label>
              <input id="access-pw" aria-label="Panel şifresi" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)}
                     className="pl-input h-8 w-full max-w-[320px]" />
            </div>
            <div className="pl-row">
              <label htmlFor="access-pw2">Şifre (tekrar)</label>
              <input id="access-pw2" aria-label="Şifre (tekrar)" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)}
                     className="pl-input h-8 w-full max-w-[320px]" />
            </div>
            <p className="py-1 text-[12px] text-pl-faint">En az 8 karakter. Şifre bu bilgisayarda yalnızca özeti olarak saklanır.</p>
          </>
        )}
      <div className="flex flex-wrap gap-2 pt-1.5">
        <button type="button" onClick={() => save(true)} className="pl-btn pl-btn-primary h-8">
          {v.enabled ? "Kaydet" : "Telefondan erişimi aç"}</button>
        {v.enabled && <button type="button" onClick={() => save(false)} className="pl-btn h-8">Erişimi kapat</button>}
      </div>
      {msg && <p role="status" className={`mt-2 rounded-[2px] border px-3 py-1.5 text-[13px] ${msg.ok ? "border-ok-line bg-ok-50 text-ok-600" : "border-nok-line bg-nok-50 text-nok-600"}`}>{msg.text}</p>}
      {v.buildState === "building" && (
        <p data-testid="build-state" className="mt-2 rounded-[2px] border border-warn-line bg-warn-50 px-3 py-1.5 text-[13px] text-warn-700">
          {v.buildMessage || "Panel derleniyor (ilk açılış 1-2 dk)…"} Yerel ağ erişimi derleme bitince açılır.</p>
      )}
      {v.buildState === "failed" && (
        <p data-testid="build-state" className="mt-2 rounded-[2px] border border-nok-line bg-nok-50 px-3 py-1.5 text-[13px] text-nok-600">
          {v.buildMessage || "Yerel ağ için derleme başarısız; panel yalnızca bu bilgisayarda açık."}</p>
      )}
      {v.lanActive && v.addresses.length > 0 && (
        <div className="mt-2 grid gap-2 border-t border-pl-head pt-2 sm:grid-cols-[220px_1fr] sm:items-center">
          {/* eslint-disable-next-line @next/next/no-img-element -- yerel üretilen QR (data URL) */}
          {qr && <img src={qr} alt="Telefonla okutun" width={220} height={220} className="border border-pl-line-soft" />}
          <div>
            <p>Telefonun kamerasıyla QR&apos;ı okutun ya da tarayıcıya yazın:</p>
            <ul className="mt-1 font-mono text-[13px]">{v.addresses.map((a) => <li key={a}>{a}</li>)}</ul>
          </div>
        </div>
      )}
      <p className="mt-2 text-[12px] text-pl-faint">İlk açılışta Windows güvenlik duvarı &quot;özel ağda izin ver&quot; diye sorabilir; izin verin. Bağlantı ofis ağında şifrelenmemiş http&apos;dir; dışarıdan erişim ayrıca kurulmalıdır.</p>
    </section>
  );
}
