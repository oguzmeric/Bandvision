/**
 * Alarmın dikkat çekme seçenekleri — yalnızca BU TARAYICIDA (localStorage; erişilemezse kapalı sayılır):
 * - masaüstü bildirimi (varsayılan kapalı): sekme arka plandayken yeni alarmda işletim sistemi bildirimi;
 * - sesli uyarı (varsayılan kapalı; alarm tasarım gereği sessiz): yeni alarmda kısa iki tonlu bip (WebAudio, ses
 *   dosyası yok), en çok 10 sn'de bir.
 * Sekme başlığının yanıp sönmesi her zaman açıktır (ayar yok).
 */

export type AttentionPref = "desktop" | "sound";

const KEYS: Record<AttentionPref, string> = { desktop: "bv.alarm.desktop", sound: "bv.alarm.sound" };

/** Sesli uyarı en çok bu aralıkla çalar */
export const BEEP_MIN_INTERVAL_MS = 10_000;

export function readPref(pref: AttentionPref): boolean {
  try {
    return window.localStorage.getItem(KEYS[pref]) === "1";
  } catch {
    return false;
  }
}

export function writePref(pref: AttentionPref, on: boolean): void {
  try {
    if (on) window.localStorage.setItem(KEYS[pref], "1");
    else window.localStorage.removeItem(KEYS[pref]);
  } catch {
    // gizli pencere / engellenmiş depolama: ayar yalnızca bu sayfa açıkken geçerli olmaz, sessizce kapalı kalır
  }
}

export function desktopSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

/** Masaüstü bildirimi gösterilebilir mi: ayar açık, tarayıcı destekliyor ve izin verilmiş */
export function desktopReady(): boolean {
  return readPref("desktop") && desktopSupported() && Notification.permission === "granted";
}

let audio: AudioContext | null = null;
let lastBeep = -Infinity;

/**
 * Kısa iki tonlu bip (880 Hz → 660 Hz). `force` değilse en çok `BEEP_MIN_INTERVAL_MS`'de bir. Tarayıcı, sayfayla hiç
 * etkileşim olmadan sesi engelleyebilir (otomatik oynatma kuralı): "Dene" düğmesi sesi bu sekmede açar.
 */
export function playBeep(force = false): boolean {
  const now = Date.now();
  if (!force && now - lastBeep < BEEP_MIN_INTERVAL_MS) return false;
  try {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return false;
    audio ??= new Ctx();
    if (audio.state === "suspended") void audio.resume().catch(() => undefined);
    const t0 = audio.currentTime + 0.02;
    for (const [i, freq] of [880, 660].entries()) {
      const osc = audio.createOscillator();
      const gain = audio.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      const start = t0 + i * 0.22;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.25, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.2);
      osc.connect(gain).connect(audio.destination);
      osc.start(start);
      osc.stop(start + 0.21);
    }
    lastBeep = now;
    return true;
  } catch {
    return false;
  }
}
