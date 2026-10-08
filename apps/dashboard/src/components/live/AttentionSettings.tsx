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
    <section className="card mt-5 grid max-w-[420px] gap-3 p-5" aria-label="Bu tarayıcıda">
      <p className="eyebrow">Bu tarayıcıda</p>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" aria-label="Masaüstü bildirimi" className="mt-0.5 h-4 w-4 accent-brand-500" checked={desktop}
               onChange={(e) => void toggleDesktop(e.target.checked)} />
        <span>Masaüstü bildirimi
          <span className="block text-[11.5px] text-faint">Panel sekmesi arka plandayken yeni alarm Windows bildirimiyle gelir; tıklayınca alarm penceresi açılır.</span>
        </span>
      </label>
      <div className="flex items-start gap-2 text-sm">
        <input id="alarm-sound" type="checkbox" aria-label="Sesli uyarı" className="mt-0.5 h-4 w-4 accent-brand-500" checked={sound}
               onChange={(e) => toggleSound(e.target.checked)} />
        <label htmlFor="alarm-sound" className="flex-1">Sesli uyarı
          <span className="block text-[11.5px] text-faint">Yeni alarmda kısa iki tonlu bip (en çok 10 saniyede bir). Alarm varsayılan olarak sessizdir.</span>
        </label>
        <button type="button" onClick={() => playBeep(true)} className="h-8 rounded-[9px] border border-line px-2.5 text-[12.5px] font-medium hover:border-brand-100">Dene</button>
      </div>
      <p className="text-[11.5px] text-faint">Onaylanmamış alarm varken sekme başlığı «🚨 ALARM — kamera adı» ile yanıp söner (her zaman açık).
        Bu ayarlar yalnızca bu tarayıcıda saklanır.</p>
      {msg && <p role="status" className={`rounded-xl px-3 py-2 text-[13px] ${msg.ok ? "bg-ok-50 text-ok-600" : "bg-nok-50 text-nok-600"}`}>{msg.text}</p>}
    </section>
  );
}
