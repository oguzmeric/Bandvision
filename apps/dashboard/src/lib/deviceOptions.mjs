// Cihaz ayarları sayfasının saf metin/seçenek mantığı (Cihaz ayarları: src/components/devices/DeviceSettings.tsx).

const CPU_NAME = "İşlemci";

/**
 * "Kullanım" açılır kutusunun seçenekleri: Otomatik (seçilecek cihazın adı), İşlemci, sonra listedeki her ekran kartı.
 * Kayıtlı seçim listede olmayan bir ekran kartıysa (kart sökülmüş, sürücü değişmiş) kaybolmaz: "Bulunamayan ekran kartı (<kimlik>)"
 * olarak sonda yer alır; çözümleme sunucuda işlemciye düşer.
 * @param {Array<{id: string, kind: string, name: string}>} devices
 * @param {string} auto  "Otomatik"in şu an çözüldüğü cihazın kimliği
 * @param {string} saved  sunucuda kayıtlı seçim: "auto", "cpu" ya da ekran kartı kimliği
 */
export function choiceOptions(devices, auto, saved) {
  const nameOf = (id) => devices.find((d) => d.id === id)?.name ?? (id === "cpu" ? CPU_NAME : id);
  const options = [
    { value: "auto", label: `Otomatik (${nameOf(auto)})` },
    { value: "cpu", label: CPU_NAME },
    ...devices.filter((d) => d.kind === "gpu").map((d) => ({ value: d.id, label: d.name })),
  ];
  if (saved !== "auto" && saved !== "cpu" && !devices.some((d) => d.id === saved)) {
    options.push({ value: saved, label: `Bulunamayan ekran kartı (${saved})` });
  }
  return options;
}

/**
 * Canlı modelin şu an hangi cihazda çalıştığını anlatan satır. `warn`: uyarı rengi (not ya da hata).
 * @param {{state: string, device: {name: string}|null, note: string|null}} status
 */
export function inUseText(status) {
  const { state, device, note } = status;
  if (state === "error") return { text: note ?? "Model açılamadı.", warn: true };
  if (state === "loading") {
    return { text: device ? `Şu an: ${device.name} (yeni cihaz yükleniyor…)` : "Şu an: yükleniyor…", warn: false };
  }
  if (state === "ready") {
    const name = device?.name ?? "bilinmiyor";
    return note ? { text: `Şu an: ${name} — ${note}`, warn: true } : { text: `Şu an: ${name}`, warn: false };
  }
  return { text: "Şu an: kullanılmıyor", warn: false };
}

/**
 * Hız testi sonucu satırı: "12.3 ms/kare (2.0 sn açılış)". Cihaz işlemciye düşmüşse (not var) sayı değil not gösterilir,
 * uyarı renginde: kullanıcı ekran kartı hızı sandığı bir sayıya bakmasın.
 * @param {{device: {note: string|null}, msPerFrame: number, loadS: number}} result
 */
export function benchText(result) {
  const note = result.device.note;
  if (note) return { text: note, warn: true };
  return { text: `${result.msPerFrame.toFixed(1)} ms/kare (${result.loadS.toFixed(1)} sn açılış)`, warn: false };
}
