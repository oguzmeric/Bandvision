"use client";

import { useEffect, useState } from "react";
import { desktopSupported, playAlarmSound, readPref, readSound, readVolume, writePref, writeSound, writeVolume } from "@/lib/attention";
import { DEFAULT_SOUND, DEFAULT_VOLUME, SOUND_GROUPS, SOUNDS, type SoundGroup } from "@/lib/alarmSounds.mjs";

/**
 * Bildirimler sayfasında "Bu tarayıcıda": alarmın bu bilgisayarda/tarayıcıda nasıl dikkat çekeceği. Ayarlar yalnızca
 * bu tarayıcıda saklanır (diğer bilgisayarları etkilemez); ikisi de varsayılan kapalı. Sesli uyarının altında üç grup için
 * alarm sesi seçimi ve "Dinle", ses düzeyi kaydırıcısı (seçimler de bu tarayıcıda, çerez).
 */
export default function AttentionSettings() {
  const [desktop, setDesktop] = useState(false);
  const [sound, setSound] = useState(false);
  const [choice, setChoice] = useState<Record<SoundGroup, string>>({ ...DEFAULT_SOUND });
  const [volume, setVolume] = useState(DEFAULT_VOLUME);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    const granted = desktopSupported() && Notification.permission === "granted";
    setDesktop(readPref("desktop") && granted);
    setSound(readPref("sound"));
    setChoice({ fire: readSound("fire"), person: readSound("person"), phone: readSound("phone") });
    setVolume(readVolume());
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
  }

  function choose(group: SoundGroup, id: string) {
    writeSound(group, id);
    setChoice((c) => ({ ...c, [group]: id }));
  }

  function changeVolume(percent: number) {
    const v = Math.round(percent) / 100;
    writeVolume(v);
    setVolume(v);
  }

  async function listen(group: SoundGroup) {
    setMsg(null);
    // "Sesli uyarı" kapalıyken de dinlenebilir (seçim yapmak için); tıklama tarayıcıda sesi açar
    if (!(await playAlarmSound(choice[group], volume))) setMsg({ ok: false, text: "Ses çalınamadı. Tarayıcının bu site için sesi kapatılmış olabilir." });
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
      <div className="flex items-start gap-2 py-2">
        <input id="alarm-sound" type="checkbox" aria-label="Sesli uyarı" className="mt-0.5 h-4 w-4 accent-pl-accent" checked={sound}
               onChange={(e) => toggleSound(e.target.checked)} />
        <label htmlFor="alarm-sound" className="flex-1">Sesli uyarı
          <span className="block text-[11.5px] text-pl-faint">Kritik alarmda seçilen ses, alarm penceresi açıkken 3 saniyede bir yinelenir; Gördüm ya da Küçült susturur. Telefon uyarısında bir kez çalar. Alarm varsayılan olarak sessizdir.</span>
        </label>
      </div>
      <div className="grid gap-1.5 border-b border-pl-head pb-2 pl-6">
        {SOUND_GROUPS.map((g) => (
          <div key={g.id} role="group" aria-label={g.name} className="flex flex-wrap items-center gap-2">
            <label htmlFor={`alarm-sound-${g.id}`} className="min-w-[200px] flex-1 text-[13px]">{g.name}
              <span className="block text-[11.5px] text-pl-faint">{g.hint}</span>
            </label>
            <select id={`alarm-sound-${g.id}`} aria-label={`${g.name} sesi`} value={choice[g.id]}
                    onChange={(e) => choose(g.id, e.target.value)} className="pl-input h-7 w-[150px] text-[12.5px]">
              {SOUNDS.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <button type="button" onClick={() => void listen(g.id)} className="pl-btn h-7 text-[12.5px]">Dinle</button>
          </div>
        ))}
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="alarm-volume" className="min-w-[200px] flex-1 text-[13px]">Ses düzeyi</label>
          <input id="alarm-volume" type="range" aria-label="Ses düzeyi" min={10} max={100} step={5} value={Math.round(volume * 100)}
                 onChange={(e) => changeVolume(Number(e.target.value))} className="w-[150px] accent-pl-accent" />
          <span data-testid="sound-volume" className="w-[52px] text-[12.5px] tabular-nums text-pl-muted">%{Math.round(volume * 100)}</span>
        </div>
      </div>
      <p className="mt-2 text-[11.5px] text-pl-faint">Onaylanmamış alarm varken sekme başlığı «ALARM — kamera adı» ile yanıp söner (her zaman açık).
        Bu ayarlar yalnızca bu tarayıcıda saklanır.</p>
      {msg && <p role="status" className={`mt-2 rounded-[2px] border px-3 py-1.5 text-[13px] ${msg.ok ? "border-ok-line bg-ok-50 text-ok-ink" : "border-nok-line bg-nok-50 text-nok-ink"}`}>{msg.text}</p>}
    </section>
  );
}
