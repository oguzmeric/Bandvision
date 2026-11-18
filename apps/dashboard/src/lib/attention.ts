/**
 * Alarmın dikkat çekme seçenekleri — yalnızca BU TARAYICIDA (çerez; erişilemezse kapalı sayılır). Çerez port'a bağlı
 * değildir: panelin portu değişse (3300 doluysa 3301…) ayarlar kaybolmaz (localStorage port başına ayrı olurdu):
 * - masaüstü bildirimi (varsayılan kapalı): sekme arka plandayken yeni alarmda işletim sistemi bildirimi;
 * - sesli uyarı (varsayılan kapalı; alarm tasarım gereği sessiz): alarm türünün grubuna (yangın/duman, kişi, telefon)
 *   seçilen alarm sesi (`alarmSounds.mjs`; panelle gelen WAV) ve ses düzeyi (varsayılan %80); seçim ve düzey de çerezdir.
 * Sekme başlığının yanıp sönmesi her zaman açıktır (ayar yok).
 */

import { DEFAULT_VOLUME, parseSound, parseVolume, soundFile, type SoundGroup } from "./alarmSounds.mjs";

export type AttentionPref = "desktop" | "sound";

const COOKIES: Record<AttentionPref, string> = { desktop: "bv_alarm_desktop", sound: "bv_alarm_sound" };
/** Önceki sürüm ayarı localStorage'da tutuyordu; çerez yoksa bir kez taşınır */
const LEGACY_KEYS: Record<AttentionPref, string> = { desktop: "bv.alarm.desktop", sound: "bv.alarm.sound" };

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

const SOUND_COOKIE = (group: SoundGroup) => `bv_alarm_sound_${group}`;
const VOLUME_COOKIE = "bv_alarm_volume";

function setValue(name: string, value: string): void {
  try {
    document.cookie = `${name}=${encodeURIComponent(value)}; Path=/; Max-Age=31536000; SameSite=Lax`;
  } catch {
    // çerez engellenmiş: seçim yalnızca bu sayfa açıkken geçerli olmaz, varsayılan kalır
  }
}

function readValue(name: string): string | null {
  try {
    const c = cookieValue(name);
    return c === null ? null : decodeURIComponent(c);
  } catch {
    return null;
  }
}

/** Grubun seçili alarm sesi (geçersiz ya da eksikse grubun varsayılanı) */
export function readSound(group: SoundGroup): string {
  return parseSound(group, readValue(SOUND_COOKIE(group)));
}

export function writeSound(group: SoundGroup, id: string): void {
  setValue(SOUND_COOKIE(group), parseSound(group, id));
}

/** Ses düzeyi 0–1 (geçersiz ya da eksikse 0,8) */
export function readVolume(): number {
  return parseVolume(readValue(VOLUME_COOKIE));
}

export function writeVolume(v: number): void {
  setValue(VOLUME_COOKIE, String(Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : DEFAULT_VOLUME));
}

/** Ses başına tek oynatıcı: tekrarlarda dosya yeniden indirilmez, aynı ses üst üste binmez (baştan çalar) */
const players = new Map<string, HTMLAudioElement>();

/**
 * Alarm sesini çalar. Tarayıcı sesi engellerse (sayfayla hiç etkileşim olmadan otomatik oynatma kuralı) ya da dosya
 * çalınamazsa `false` döner; çağıran "sayfaya bir kez tıklayın" uyarısını gösterir.
 */
export async function playAlarmSound(id: string, volume: number): Promise<boolean> {
  const file = soundFile(id);
  if (file === null || typeof Audio === "undefined") return false;
  try {
    let a = players.get(id);
    if (!a) {
      a = new Audio(file);
      players.set(id, a);
    }
    a.volume = Math.min(1, Math.max(0, volume));
    a.currentTime = 0;
    await a.play();
    return true;
  } catch (e) {
    // AbortError: çalma başlamadan susturuldu (pause; Gördüm / Küçült) — engel değil
    return e instanceof DOMException && e.name === "AbortError";
  }
}

/** Çalan alarm seslerini keser (Gördüm / Küçült susturunca ses sonuna dek sürmesin) */
export function stopAlarmSounds(): void {
  for (const a of players.values()) {
    try { a.pause(); } catch { /* oynatıcı yok */ }
  }
}
