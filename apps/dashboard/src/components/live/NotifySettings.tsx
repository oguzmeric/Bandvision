"use client";

import { useEffect, useState } from "react";
import { api, stamp, type NotifyConfig } from "@/lib/live";

const field = "h-10 w-full rounded-[10px] border border-line bg-white px-3 text-sm outline-none focus:border-brand-500";

/** Telegram ayarları: anahtar yalnızca analiz sunucusunda saklanır, geri gösterilmez. */
export default function NotifySettings() {
  const [cfg, setCfg] = useState<NotifyConfig | null>(null);
  const [token, setToken] = useState("");
  const [chatId, setChatId] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => {
    api<NotifyConfig>("notify").then((c) => { setCfg(c); setChatId(c.chatId); setEnabled(c.enabled); }).catch((e: Error) => setMsg({ ok: false, text: e.message }));
  }, []);
  async function save() {
    try {
      const c = await api<NotifyConfig>("notify", { method: "PUT", json: { enabled, chatId, token: token === "" ? null : token } });
      setCfg(c); setToken(""); setMsg({ ok: true, text: "Kaydedildi." });
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }
  async function run(path: string, ok: string) {
    try { await api(path, { method: "POST", json: {} }); setMsg({ ok: true, text: ok }); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    api<NotifyConfig>("notify").then(setCfg).catch(() => undefined);   // son gönderim hatası güncellensin
  }
  /** Kayıtlı anahtarı siler (token: ""); kayıtlı sohbet kimliği ve aç/kapa değişmez */
  async function removeToken() {
    if (!cfg || !confirm("Kayıtlı bot anahtarı silinsin mi? Yeni anahtar girilene kadar Telegram'a bildirim gitmez.")) return;
    try {
      const c = await api<NotifyConfig>("notify", { method: "PUT", json: { enabled: cfg.enabled, chatId: cfg.chatId, token: "" } });
      setCfg(c); setToken(""); setMsg({ ok: true, text: "Anahtar silindi." });
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }
  return (
    <div className="grid items-start gap-5 lg:grid-cols-[420px_minmax(0,1fr)]">
      <section className="card grid gap-3 p-5">
        <p className="eyebrow">Telegram</p>
        <label className="block text-sm font-medium">Bot anahtarı
          <input aria-label="Bot anahtarı" type="password" autoComplete="new-password" className={`${field} mt-1.5`} value={token}
                 placeholder={cfg?.hasToken ? "Kayıtlı (değiştirmek için yaz)" : "123456:ABC…"} onChange={(e) => setToken(e.target.value)} />
        </label>
        {cfg?.hasToken && (
          <p className="flex items-center justify-between gap-2 text-[12px] text-ok-600">
            Anahtar kayıtlı
            <button type="button" onClick={removeToken} className="font-medium text-nok-600 hover:underline">Anahtarı sil</button>
          </p>
        )}
        <label className="block text-sm font-medium">Sohbet / grup kimliği
          <input aria-label="Sohbet / grup kimliği" className={`${field} mt-1.5`} value={chatId} placeholder="-1001234567890" onChange={(e) => setChatId(e.target.value)} />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" aria-label="Bildirimler açık" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="h-4 w-4 accent-brand-500" />
          Bildirimler açık
        </label>
        <div className="grid grid-cols-3 gap-2">
          <button type="button" onClick={save} className="brand-gradient h-10 rounded-[10px] text-sm font-semibold text-white">Kaydet</button>
          <button type="button" onClick={() => run("notify/test", "Deneme mesajı gönderildi.")} className="h-10 rounded-[10px] border border-line text-sm font-medium">Deneme mesajı gönder</button>
          <button type="button" onClick={() => run("alarms/test", "Deneme alarmı oluşturuldu.")} className="h-10 rounded-[10px] border border-line text-sm font-medium">Deneme alarmı</button>
        </div>
        {msg && <p role="status" className={`rounded-xl px-3 py-2 text-sm ${msg.ok ? "bg-ok-50 text-ok-600" : "bg-nok-50 text-nok-600"}`}>{msg.text}</p>}
        {cfg?.lastError && (
          <p data-testid="notify-last-error" className="rounded-xl border border-nok-50 bg-white px-3 py-2 text-[12.5px] text-nok-600">
            Son gönderim hatası ({stamp(cfg.lastError.at)}): {cfg.lastError.text}
          </p>
        )}
        <p className="text-[11.5px] text-faint">Anahtar yalnızca bu bilgisayarda saklanır; panele geri gösterilmez.</p>
      </section>
      <section className="card p-5 text-sm leading-relaxed">
        <p className="eyebrow mb-2">Kurulum</p>
        <ol className="list-decimal space-y-1.5 pl-5">
          <li>Telegram&apos;da <b>@BotFather</b>&apos;a yazın, <b>/newbot</b> ile bir bot oluşturun; verdiği anahtarı soldaki alana yapıştırın.</li>
          <li>Alarmların gideceği grubu açın ve botu gruba ekleyin (ya da bota doğrudan bir mesaj yazın).</li>
          <li>Grup kimliği için gruba <b>@userinfobot</b>&apos;u ekleyin ya da gruba yazdıktan sonra <code>https://api.telegram.org/bot&lt;anahtar&gt;/getUpdates</code> adresindeki <code>chat.id</code> değerini kullanın (grup kimlikleri genelde -100 ile başlar).</li>
          <li>&quot;Bildirimler açık&quot;ı işaretleyip Kaydet&apos;e, sonra &quot;Deneme mesajı gönder&quot;e basın.</li>
        </ol>
        <p className="mt-3 text-[12px] text-faint">Olay resmi yalnızca kamera ayarında &quot;Olay resmini Telegram&apos;a gönder&quot; açıksa gider; resimler bu bilgisayarda 7 gün saklanır.</p>
      </section>
    </div>
  );
}
