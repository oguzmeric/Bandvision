// Analiz sunucusunun panelin isteğini reddetmesi (erişim anahtarı, adres): kodlar, metinler ve sınıflandırma; bir de
// `Authorization` değeri. Saf ve içe aktarmasız: hem sunucu (vekil) hem tarayıcı (sayfalar) kullanır, `node --test` ile
// sınanır. Tarayıcı paketine de girdiği için `Buffer` kullanılmaz. docs/13-web-platform.md "Analiz sunucusu API" → Güvenlik.

/** Vekilin 502 yanıtındaki `code` → `detail` (sayfalar da aynı metni gösterir) */
export const ANALYZER_REFUSALS = {
  analyzer_key: "Analiz sunucusu erişim anahtarı uyuşmuyor — panelde ve analiz sunucusunda aynı ANALYZER_TOKEN ayarlanmalı.",
  analyzer_host: "Analiz sunucusu panelin bağlandığı adresi reddetti — erişim anahtarı yokken ANALYZER_URL 127.0.0.1 ya da localhost olmalı.",
};

const refusal = (code) => ({ code, detail: ANALYZER_REFUSALS[code] });

/** Analiz sunucusunun durum kodu → vekilin döneceği `{code, detail}`; reddetme değilse null. Analiz sunucusunun tek 401'i
 * kendi anahtar denetimi, 403'ü `Host` denetimidir (vekil `Origin` iletmez, başka site denetimine buradan takılınmaz). */
export function refusalFor(status) {
  if (status === 401) return refusal("analyzer_key");
  if (status === 403) return refusal("analyzer_host");
  return null;
}

/**
 * Sayfanın bildireceği sorun. "auth" yalnızca panelin KENDİ 401'idir (oturum doldu): vekil analiz sunucusunun reddini 401
 * diye aktarmadığından reddetme kodu taşımaz. Kod durumdan önce gelir. Başka her hata "down".
 */
export function problemFrom(status, code) {
  if (code === "analyzer_key") return "key";
  if (code === "analyzer_host") return "host";
  return status === 401 ? "auth" : "down";
}

/** "key" ve "host" sorununun metni; öteki sorunlarda null (çağıran kendi metnini yazar) */
export function refusalText(problem) {
  if (problem === "key") return ANALYZER_REFUSALS.analyzer_key;
  if (problem === "host") return ANALYZER_REFUSALS.analyzer_host;
  return null;
}

/** Başlık değerinde bulunamayan denetim karakterleri (RFC 9110; sekme hariç). `Headers` CR, LF ve NUL'da hata verir. */
const NOT_A_HEADER_VALUE = /[\0-\x08\x0a-\x1f\x7f]/;

/**
 * `Authorization` değeri; anahtar yoksa null (başlık gönderilmez). Çevresindeki boşluk atılır, geriye bir şey kalmazsa
 * anahtar yoktur (analiz sunucusu da `trim` kümesiyle aynısını yapar). Başlıkta gönderilemeyen anahtar (denetim karakteri)
 * da null: istek anahtarsız gider, analiz sunucusunun 401'i anahtar uyuşmazlığı olarak görünür, hiçbir yol hata atmaz.
 * HTTP başlığı bayt dizisidir ve `Headers` 255'ten büyük kod noktasında hata verir: Türkçe karakterli anahtar UTF-8
 * baytlarıyla (her bayt bir karakter, ByteString) gönderilir; analiz sunucusu da bu baytlarla karşılaştırır.
 */
/** Eski analiz sunucusu yeni bir ön ayarı tanımaz ve ham doğrulama dökümüyle `422` verir ("Seçenekler geçersiz: … preset …");
 * yükleme bunu okunur bir iletiye çevirir. Başka her `422`, başka durum ya da ileti null (olduğu gibi gösterilir). */
export const UNKNOWN_ANALYSIS = "Analiz sunucusu bu analizi tanımıyor; analiz sunucusunu güncelleyin.";
export function optionsRefusal(status, detail) {
  if (status !== 422 || typeof detail !== "string") return null;
  return detail.startsWith("Seçenekler geçersiz:") && /\bpreset\b/.test(detail) ? UNKNOWN_ANALYSIS : null;
}

export function bearerHeader(token) {
  const trimmed = typeof token === "string" ? token.trim() : "";
  if (!trimmed || NOT_A_HEADER_VALUE.test(trimmed)) return null;
  return Array.from(new TextEncoder().encode(`Bearer ${trimmed}`), (b) => String.fromCharCode(b)).join("");
}
