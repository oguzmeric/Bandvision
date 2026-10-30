"use client";

import { useEffect, useState } from "react";
import { desktopSupported, playBeep, readPref, writePref } from "@/lib/attention";

/**
 * Bildirimler sayfasında "Bu tarayıcıda": alarmın bu bilgisayarda/tarayıcıda nasıl dikkat çekeceği. Ayarlar yalnızca
 * bu tarayıcıda saklanır (diğer bilgisayarları etkilemez); ikisi de varsayılan kapalı.
 */
export default function AttentionSettings() {
  const [desktop, setDesktop] = useState(false);
  const [sound, setSound] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    const granted = desktopSupported() && Notification.permission === "granted";
    setDesktop(readPref("desktop") && granted);
    setSound(readPref("sound"));
    if (readPref("desktop") && !granted) {
      setMsg({ ok: false, text: "Masaüstü bildirimi açık ama tarayıcı izni yok; izni tarayıcının site ayarlarından verin." });
    }
  }, []);

  async function toggleDesktop(on: boolean) {
    setMsg(null);
    if (!on) {
      writePref("desktop", false);
      setDesktop(false);
      return;
    }
    if (!window.isSecureContext) {
      // tarayıcılar bildirimi yalnızca güvenli adreste verir: başka bilgisayardan http://192.168… ile açılan panelde olmaz
      setMsg({ ok: false, text: "Masaüstü bildirimi yalnızca güvenli adreste çalışır: paneli analiz bilgisayarında http://localhost ile ya da https ile açın." });
      return;
    }
    if (!desktopSupported()) {
      setMsg({ ok: false, text: "Bu tarayıcı masaüstü bildirimini desteklemiyor." });
      return;
    }
    let permission = Notification.permission;
    if (permission !== "granted") {
      try { permission = await Notification.requestPermission(); } catch { permission = "denied"; }
    }
    const granted = permission === "granted";
    writePref("desktop", granted);
    setDesktop(granted);
    setMsg(granted
      ? { ok: true, text: "Masaüstü bildirimi açık: bu sekme arka plandayken yeni alarm işletim sistemi bildirimiyle gelir." }
      : { ok: false, text: "Tarayıcı bildirim izni vermedi. İzni tarayıcının site ayarlarından açabilirsiniz." });
  }

  function toggleSound(on: boolean) {
    writePref("sound", on);
    setSound(on);
    setMsg(null);
    if (on) playBeep(true);                             // tıklama tarayıcıda sesi de açar
  }

  return (
    <section className="pl-section max-w-[760px]" aria-label="Bu tarayıcıda">
      <h2>Bu tarayıcıda</h2>
      <label className="flex items-start gap-2 border-b border-pl-head pb-2">
        <input type="checkbox" aria-label="Masaüstü bildirimi" className="mt-0.5 h-4 w-4 accent-pl-accent" checked={desktop}
               onChange={(e) => void toggleDesktop(e.target.checked)} />
        <span>Masaüstü bildirimi
          <span className="block text-[11.5px] text-pl-faint">Panel sekmesi arka plandayken yeni alarm Windows bildirimiyle gelir; tıklayınca alarm penceresi açılır.</span>
        </span>
      </label>
      <div className="flex items-start gap-2 border-b border-pl-head py-2">
        <input id="alarm-sound" type="checkbox" aria-label="Sesli uyarı" className="mt-0.5 h-4 w-4 accent-pl-accent" checked={sound}
               onChange={(e) => toggleSound(e.target.checked)} />
        <label htmlFor="alarm-sound" className="flex-1">Sesli uyarı
          <span className="block text-[11.5px] text-pl-faint">Yeni alarmda kısa iki tonlu bip (en çok 10 saniyede bir). Alarm varsayılan olarak sessizdir.</span>
        </label>
        <button type="button" onClick={() => playBeep(true)} className="pl-btn h-7 text-[12.5px]">Dene</button>
      </div>
      <p className="mt-2 text-[11.5px] text-pl-faint">Onaylanmamış alarm varken sekme başlığı «🚨 ALARM — kamera adı» ile yanıp söner (her zaman açık).
        Bu ayarlar yalnızca bu tarayıcıda saklanır.</p>
      {msg && <p role="status" className={`mt-2 rounded-[2px] border px-3 py-1.5 text-[13px] ${msg.ok ? "border-ok-line bg-ok-50 text-ok-ink" : "border-nok-line bg-nok-50 text-nok-ink"}`}>{msg.text}</p>}
    </section>
  );
}
