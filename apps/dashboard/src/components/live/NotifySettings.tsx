"use client";

import { useEffect, useState } from "react";
import { api, stamp, type NotifyConfig } from "@/lib/live";

const field = "pl-input h-8 w-full";

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
    // Form satırları alt alta (dar ekranda etiket üstte); düğmeler satıra sığmazsa alta kayar
    <div className="max-w-[760px]">
      <section className="pl-section">
        <h2>Telegram</h2>
        <div className="pl-row">
          <label htmlFor="notify-token">Bot anahtarı</label>
          <div className="min-w-0">
            <input id="notify-token" aria-label="Bot anahtarı" type="password" autoComplete="new-password" className={field} value={token}
                   placeholder={cfg?.hasToken ? "Kayıtlı (değiştirmek için yaz)" : "123456:ABC…"} onChange={(e) => setToken(e.target.value)} />
            {cfg?.hasToken && (
              <p className="mt-1 flex items-center justify-between gap-2 text-[12px] text-ok-600">
                Anahtar kayıtlı
                <button type="button" onClick={removeToken} className="font-medium text-nok-600 hover:underline">Anahtarı sil</button>
              </p>
            )}
          </div>
        </div>
        <div className="pl-row">
          <label htmlFor="notify-chat">Sohbet / grup kimliği</label>
          <input id="notify-chat" aria-label="Sohbet / grup kimliği" className={field} value={chatId} placeholder="-1001234567890" onChange={(e) => setChatId(e.target.value)} />
        </div>
        <div className="pl-row">
          <span>Durum</span>
          <label className="flex items-center gap-2">
            <input type="checkbox" aria-label="Bildirimler açık" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="h-4 w-4 accent-pl-accent" />
            Bildirimler açık
          </label>
        </div>
        <div className="flex flex-wrap gap-2 pt-2">
          <button type="button" onClick={save} className="pl-btn pl-btn-primary h-8">Kaydet</button>
          <button type="button" onClick={() => run("notify/test", "Deneme mesajı gönderildi.")} className="pl-btn h-8">Deneme mesajı gönder</button>
          <button type="button" onClick={() => run("alarms/test", "Deneme alarmı oluşturuldu.")} className="pl-btn h-8">Deneme alarmı</button>
        </div>
        {msg && <p role="status" className={`mt-2 rounded-[2px] border px-3 py-1.5 text-[13px] ${msg.ok ? "border-ok-line bg-ok-50 text-ok-600" : "border-nok-line bg-nok-50 text-nok-600"}`}>{msg.text}</p>}
        {cfg?.lastError && (
          <p data-testid="notify-last-error" className="mt-2 rounded-[2px] border border-nok-line bg-white px-3 py-1.5 text-[12.5px] text-nok-600">
            Son gönderim hatası ({stamp(cfg.lastError.at)}): {cfg.lastError.text}
          </p>
        )}
        <p className="mt-2 text-[11.5px] text-pl-faint">Anahtar yalnızca bu bilgisayarda saklanır; panele geri gösterilmez.</p>
      </section>
      <section className="pl-section leading-relaxed">
        <h2>Kurulum</h2>
        <ol className="list-decimal space-y-1 pl-5">
          <li>Telegram&apos;da <b>@BotFather</b>&apos;a yazın, <b>/newbot</b> ile bir bot oluşturun; verdiği anahtarı yukarıdaki alana yapıştırın.</li>
          <li>Alarmların gideceği grubu açın ve botu gruba ekleyin (ya da bota doğrudan bir mesaj yazın).</li>
          <li>Grup kimliği için gruba <b>@userinfobot</b>&apos;u ekleyin ya da gruba yazdıktan sonra <code className="break-all">https://api.telegram.org/bot&lt;anahtar&gt;/getUpdates</code> adresindeki <code>chat.id</code> değerini kullanın (grup kimlikleri genelde -100 ile başlar).</li>
          <li>&quot;Bildirimler açık&quot;ı işaretleyip Kaydet&apos;e, sonra &quot;Deneme mesajı gönder&quot;e basın.</li>
        </ol>
        <p className="mt-2 text-[12px] text-pl-faint">Olay resmi yalnızca kamera ayarında &quot;Olay resmini Telegram&apos;a gönder&quot; açıksa gider; resimler bu bilgisayarda 7 gün saklanır.</p>
      </section>
    </div>
  );
}
