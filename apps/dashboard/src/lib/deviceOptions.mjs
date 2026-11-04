// Cihaz ayarları sayfasının saf metin/seçenek mantığı (Cihaz ayarları: src/components/devices/DeviceSettings.tsx).

const CPU_NAME = "İşlemci";

/**
 * Her cihazın ekranda görünen adı (kimlik → etiket). Aynı adlı iki ya da daha çok ekran kartı karışmasın diye adın sonuna
 * numara eklenir: " (1)", " (2)"… Numara, aynı adlı kartların kimlik sonekleri (`-N`; soneksiz kimlik 1'dir) bu grupta
 * benzersizse o sonektir: aynı model kartlarda etiket listedeki sıradan bağımsız, kalıcıdır. Sonekler çakışıyorsa (aynı adlı
 * ama farklı aygıt kimlikli kartlar, ör. `gpu-10de-2503` ile `gpu-10de-2504`) grup listedeki sırayla 1, 2… numaralanır.
 * Adı benzersiz olanlar olduğu gibi kalır.
 * @param {Array<{id: string, kind: string, name: string}>} devices
 * @returns {Record<string, string>}
 */
export function deviceLabels(devices) {
  /** @type {Record<string, string>} */
  const labels = {};
  /** @type {Map<string, Array<{id: string}>>} */
  const groups = new Map();
  for (const d of devices) {
    labels[d.id] = d.name;
    if (d.kind !== "gpu") continue;
    const group = groups.get(d.name) ?? [];
    group.push(d);
    groups.set(d.name, group);
  }
  for (const [name, group] of groups) {
    if (group.length < 2) continue;
    const suffixes = group.map((d) => /^gpu-[0-9a-f]{4}-[0-9a-f]{4}-(\d+)$/.exec(d.id)?.[1] ?? "1");
    const unique = new Set(suffixes).size === suffixes.length;
    group.forEach((d, i) => {
      labels[d.id] = `${name} (${unique ? suffixes[i] : i + 1})`;
    });
  }
  return labels;
}

/**
 * "Kullanım" açılır kutusunun seçenekleri: Otomatik (seçilecek cihazın adı), İşlemci, sonra listedeki her ekran kartı.
 * Kayıtlı seçim listede olmayan bir ekran kartıysa (kart sökülmüş, sürücü değişmiş) kaybolmaz: "Bulunamayan ekran kartı (<kimlik>)"
 * olarak sonda yer alır; çözümleme sunucuda işlemciye düşer.
 * @param {Array<{id: string, kind: string, name: string}>} devices
 * @param {string} auto  "Otomatik"in şu an çözüldüğü cihazın kimliği
 * @param {string} saved  sunucuda kayıtlı seçim: "auto", "cpu" ya da ekran kartı kimliği
 */
export function choiceOptions(devices, auto, saved) {
  const labels = deviceLabels(devices);
  const options = [
    { value: "auto", label: `Otomatik (${labels[auto] ?? (auto === "cpu" ? CPU_NAME : auto)})` },
    { value: "cpu", label: CPU_NAME },
    ...devices.filter((d) => d.kind === "gpu").map((d) => ({ value: d.id, label: labels[d.id] })),
  ];
  if (saved !== "auto" && saved !== "cpu" && !devices.some((d) => d.id === saved)) {
    options.push({ value: saved, label: `Bulunamayan ekran kartı (${saved})` });
  }
  return options;
}

/**
 * Canlı modelin şu an hangi cihazda çalıştığını anlatan satır. `warn`: uyarı rengi (not ya da hata). `labels`
 * (`deviceLabels`): cihaz adı seçeneklerdeki ve tablodaki etiketle aynı olsun (aynı adlı kartlar numaralı); kimlik
 * listede yoksa sunucunun verdiği ad.
 * @param {{state: string, device: {id: string, name: string}|null, note: string|null}} status
 * @param {Record<string, string>} [labels]
 */
export function inUseText(status, labels = {}) {
  const { state, device, note } = status;
  const label = device ? (labels[device.id] ?? device.name) : null;
  if (state === "error") return { text: note ?? "Model açılamadı.", warn: true };
  if (state === "loading") {
    return { text: label ? `Şu an: ${label} (yeni cihaz yükleniyor…)` : "Şu an: yükleniyor…", warn: false };
  }
  if (state === "ready") {
    const name = label ?? "bilinmiyor";
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
