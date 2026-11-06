/**
 * Alarmın dikkat çekme seçenekleri — yalnızca BU TARAYICIDA (çerez; erişilemezse kapalı sayılır). Çerez port'a bağlı
 * değildir: panelin portu değişse (3300 doluysa 3301…) ayarlar kaybolmaz (localStorage port başına ayrı olurdu):
 * - masaüstü bildirimi (varsayılan kapalı): sekme arka plandayken yeni alarmda işletim sistemi bildirimi;
 * - sesli uyarı (varsayılan kapalı; alarm tasarım gereği sessiz): yeni alarmda kısa iki tonlu bip (WebAudio, ses
 *   dosyası yok), en çok 10 sn'de bir.
 * Sekme başlığının yanıp sönmesi her zaman açıktır (ayar yok).
 */

export type AttentionPref = "desktop" | "sound";

const COOKIES: Record<AttentionPref, string> = { desktop: "bv_alarm_desktop", sound: "bv_alarm_sound" };
/** Önceki sürüm ayarı localStorage'da tutuyordu; çerez yoksa bir kez taşınır */
const LEGACY_KEYS: Record<AttentionPref, string> = { desktop: "bv.alarm.desktop", sound: "bv.alarm.sound" };

/** Sesli uyarı en çok bu aralıkla çalar */
export const BEEP_MIN_INTERVAL_MS = 10_000;

function cookieValue(name: string): string | null {
  for (const part of document.cookie.split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k === name) return v.join("=");
  }
  return null;
}

function setCookie(pref: AttentionPref, on: boolean): void {
  document.cookie = on
    ? `${COOKIES[pref]}=1; Path=/; Max-Age=31536000; SameSite=Lax`
    : `${COOKIES[pref]}=; Path=/; Max-Age=0; SameSite=Lax`;
}

export function readPref(pref: AttentionPref): boolean {
  try {
    const c = cookieValue(COOKIES[pref]);
    if (c !== null) return c === "1";
    // çerez yok: eski localStorage ayarı varsa çereze taşı. localStorage origin (port) başınadır: bu yalnızca eski ayar bu
    // portta saklanmışsa işe yarar, ki bu güncellemeden sonra seyrektir (çoğu kez ayar 3000 gibi başka bir portta kalmıştır)
    if (window.localStorage.getItem(LEGACY_KEYS[pref]) === "1") {
      setCookie(pref, true);
      window.localStorage.removeItem(LEGACY_KEYS[pref]);
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

export function writePref(pref: AttentionPref, on: boolean): void {
  try {
    setCookie(pref, on);
    window.localStorage.removeItem(LEGACY_KEYS[pref]);   // eski kopya kalmasın (çerez silinince yeniden taşınmasın)
  } catch {
    // çerez engellenmiş: ayar yalnızca bu sayfa açıkken geçerli olmaz, sessizce kapalı kalır
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
