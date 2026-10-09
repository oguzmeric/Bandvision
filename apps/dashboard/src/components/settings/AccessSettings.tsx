"use client";

import { useEffect, useState } from "react";
import QRCode from "qrcode";

interface AccessView { enabled: boolean; hasPassword: boolean; envPassword: boolean; lanActive: boolean; runner: boolean; addresses: string[] }

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
    <section className="card grid max-w-[640px] gap-3 p-5">
      <p className="eyebrow">Telefondan erişim</p>
      <p className="text-sm text-muted">Açıkken panel ofis ağındaki telefon ve bilgisayarlardan açılır ve herkesten (bu bilgisayar dahil) şifre ister.</p>
      {v.envPassword
        ? <p className="text-[13px] text-faint">Panel şifresi bu bilgisayarın ayarında (DASHBOARD_PASSWORD) tanımlı.</p>
        : (
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="text-sm font-medium">{v.hasPassword ? "Yeni panel şifresi" : "Panel şifresi"}
              <input aria-label="Panel şifresi" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)}
                     className="mt-1.5 h-10 w-full rounded-[10px] border border-line bg-white px-3 text-sm" />
            </label>
            <label className="text-sm font-medium">Şifre (tekrar)
              <input aria-label="Şifre (tekrar)" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)}
                     className="mt-1.5 h-10 w-full rounded-[10px] border border-line bg-white px-3 text-sm" />
            </label>
            <p className="text-[12px] text-faint sm:col-span-2">En az 8 karakter. Şifre bu bilgisayarda yalnızca özeti olarak saklanır.</p>
          </div>
        )}
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => save(true)} className="brand-gradient h-10 rounded-[10px] px-4 text-sm font-semibold text-white">
          {v.enabled ? "Kaydet" : "Telefondan erişimi aç"}</button>
        {v.enabled && <button type="button" onClick={() => save(false)} className="h-10 rounded-[10px] border border-line px-4 text-sm">Erişimi kapat</button>}
      </div>
      {msg && <p role="status" className={`rounded-xl px-3 py-2 text-sm ${msg.ok ? "bg-ok-50 text-ok-600" : "bg-nok-50 text-nok-600"}`}>{msg.text}</p>}
      {v.lanActive && v.addresses.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-[220px_1fr] sm:items-center">
          {/* eslint-disable-next-line @next/next/no-img-element -- yerel üretilen QR (data URL) */}
          {qr && <img src={qr} alt="Telefonla okutun" width={220} height={220} />}
          <div className="text-sm">
            <p>Telefonun kamerasıyla QR&apos;ı okutun ya da tarayıcıya yazın:</p>
            <ul className="mt-1 font-mono text-[13px]">{v.addresses.map((a) => <li key={a}>{a}</li>)}</ul>
          </div>
        </div>
      )}
      <p className="text-[12px] text-faint">İlk açılışta Windows güvenlik duvarı &quot;özel ağda izin ver&quot; diye sorabilir; izin verin. Bağlantı ofis ağında şifrelenmemiş http&apos;dir; dışarıdan erişim ayrıca kurulmalıdır.</p>
    </section>
  );
}
