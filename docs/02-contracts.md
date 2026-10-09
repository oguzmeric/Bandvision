# 02 — Sözleşmeler (v1)

Tüm bileşenler bu formatlarla konuşur. JSON Schema dosyaları `contracts/` altında; örnekler `contracts/examples/`.
Alan adları **camelCase**. Zaman damgaları ISO 8601 UTC (`2026-10-01T09:15:02.123Z`). Koordinatlar ve alanlar normalize (0–1).

## 1. Ürün profili — `product-profile.schema.json`

Bir ürün tipinin tüm kalibrasyon ve QC ayarları. iOS'ta da edge'de de aynı JSON.

| Alan | Tür | Açıklama |
|---|---|---|
| `schema` | `"bantvision.profile.v1"` | |
| `id`, `name` | uuid, string | |
| `roi` | `{x,y,width,height}` | Döndürülmüş (dik) görüntüde ilgi alanı |
| `roiPolygon` | `[{x,y}]`, 3–12 köşe, isteğe bağlı | Çokgen ilgi alanı (eğik bant, kenarda hareket). Varsa maske = `roi` ∩ çokgen ve `roi` çokgenin sınır kutusudur (algoritma §2.0). Yoksa davranış eskisi gibi |
| `countMode` | `blob` / `linescan` / `detect` / `safety`, isteğe bağlı | Sayım yöntemi. `blob` (varsayılan): arka plan farkı + izleme, ayrık ürünler. `linescan` (§4.9): şerit tarama, tek sıra gelen bitişik/aralıklı hacimli ürünler (torba, koli); boş bant öğrenmesi gerekmez, açılı çizgiyle (`countLine`) kullanılmaz. Hazır profiller: un torbası ve koli `linescan`. `detect` (§4.10): nesne tanıma + iki yönlü geçiş (kişi, araç, hayvan); `direction` yönünde geçen giriş, ters yönde geçen çıkış. Hazır profiller: mağaza girişi (kişi), araç, hayvan. `safety`: poz güvenlik alarmı (eller yukarı, yerde yatan kişi; sayım yapmaz, **alarm** üretir: sayım olayı değil, alarm günlüğü kaydı; olay şeması değişmez); hazır profil: Kuyumcu güvenliği |
| `detectClasses` | COCO adları dizisi, isteğe bağlı | `detect`: sayılan sınıflar. Kişi `person`; araç `car, truck, bus, motorcycle, bicycle`; hayvan `cow, sheep, horse, dog, cat, bird` |
| `detectConfidence` | 0,05–0,95, isteğe bağlı | `detect`: yeni iz başlatan en düşük tanıma güveni (varsayılan 0,35); daha düşükler yalnızca mevcut izi sürdürür |
| `countAnchor` | `center` / `bottom`, isteğe bağlı | `detect`: çizgiye göre konum noktası. `center` tepeden kamera; `bottom` yatık kamera (ayak; çizgi zemine çizilir) |
| `safety` | nesne, isteğe bağlı | `countMode = safety`: `handsUp {enabled, seconds 3–5}`, `lying {enabled, seconds 5–30}`, `sendImage` (olay resmi Telegram'a; resim bilgisayarda her zaman saklanır). Varsayılan: açık/3 sn, açık/10 sn, resim kapalı. Bu yöntemde `roi` / `roiPolygon` / `countLine` yok sayılır, alan kısıtı yoktur: kural karedeki herkese uygulanır (alan alanları eski profillerin okunabilmesi için geçerli kalır) |
| `staffColors` | dizi (en çok 3) `{L, a, b}`, isteğe bağlı | `detect`: personel üniforma renkleri (CIE Lab, D65). Bu renkteki kişilerin geçişi giriş/çıkışa eklenmez, ayrı "personel geçişi" sayılır (§4.10 eki). Yoksa/boşsa kapalı; boş dizi yazılmaz |
| `productLength` | 0–2, isteğe bağlı | `linescan`: tek ürünün akış boyunca boyu, ROI'nin akış uzunluğuna oranla; 0 = otomatik öğrenilir ("Ürün boyunu öğren" kalibrasyonu bunu yazar) |
| `linePosition` | 0–1 | Sayım çizgisinin akış eksenindeki konumu |
| `countLine` | `{a:{x,y}, b:{x,y}}`, isteğe bağlı | Açılı sayım çizgisi (algoritma §4.8). Akış, a'dan b'ye yürürken sağ el tarafı. Varsa `direction`/`linePosition` sayımda kullanılmaz (uyumluluk için yine yazılır: akışa en yakın eksen) |
| `direction` | `down/up/right/left` | Akış yönü |
| `diffThreshold` | 5–120 | Arka plan farkı eşiği (gri seviye) |
| `expectedArea` | ≥0 | Tek ürün normalize alanı; 0 = örnek kalibrasyonu yok |
| `minAreaFactor`, `minAreaAbs` | | Leke filtresi (bkz. algoritma §3) |
| `splitTouching`, `maxMultiplicity` | | Bitişik ürün ayırma |
| `closeIterations` | 0–4 | Morfolojik kapama |
| `processingWidth` | 160/240/360 | İşleme genişliği (px) |
| `minHits` | 1–6 | Sayım için min. görülme |
| `maxMatchDistance` | 0.03–0.3 | **Referans 60 fps** için eşleştirme mesafesi |
| `backgroundRate` | 0.002–0.1 | **Referans 60 fps** için arka plan uyum hızı |
| `source` | obje | `rotation` (0/90/180/270), `referenceFps` (varsayılan 60) |
| `qc` | obje | Bkz. aşağı; yoksa QC kapalı |
| `scale` | obje | `mmPerPixel` (tam çözünürlükte), boy sınıflandırma için |
| `io` | obje | Sayım darbesi ve ejektör ayarları |

`qc` alt alanları:
```json
{
  "enabled": true,
  "geometry": { "areaMinFactor": 0.8, "areaMaxFactor": 1.25, "aspectMin": 1.15, "aspectMax": 1.5, "solidityMin": 0.92 },
  "spots":    { "enabled": true, "darkDelta": 35, "maxSpotAreaRatio": 0.004 },
  "barcode":  { "required": false, "symbologies": ["ean13","code128","qr"], "pattern": null },
  "text":     { "required": false, "pattern": "^LOT\\s?\\d{6}$" },
  "sizeClasses": [ {"name":"S","maxMm":42}, {"name":"M","maxMm":45}, {"name":"L","maxMm":48}, {"name":"XL","maxMm":999} ],
  "saveNokImages": true
}
```
`io` alt alanları:
```json
{ "countPulse": { "enabled": false, "channel": 1, "widthMs": 50 },
  "eject": { "enabled": false, "channel": 2, "distanceMm": 600, "widthMs": 80, "latencyCompensationMs": 0 },
  "bridgeHost": "192.168.1.50" }
```

**Uyumluluk:** Mevcut iOS v1 kodundaki `ProductProfile` bu şemanın alt kümesidir (`schema`, `source`, `qc`, `scale`, `io` eksik). F1'de eklenir; eksik alanlar varsayılanlarla okunur.

## 2. Olay — `event.schema.json`

Her olay bağımsızdır ve `eventId` ile tekilleştirilir.

Ortak alanlar: `schema` (`bantvision.event.v1`), `eventId`, `ts`, `deviceId`, `cameraId`, `lineId` (biliniyorsa), `profileId`, `type`.

| `type` | Ek alan | Ne zaman |
|---|---|---|
| `count` | `count: {delta, total, trackId, direction?}` | İz çizgiyi geçti ya da çarpanı arttı. `direction` (iki yönlü sayım, `countMode = detect`): `in` giriş, `out` çıkış; yoksa `in`. `total` o yönün toplamı. Backend çıkışları `count`'a değil `minute_stats.count_out`'a ekler |
| `inspection` | `inspection: {trackId, result, reasons[], metrics{}, sizeClass?, imageRef?}` | QC açıkken her sayılan ürün için |
| `state` | `state: {running, reason}` | Bant durdu/başladı (hareket yok süresi), kalibrasyon başladı/bitti |
| `heartbeat` | `heartbeat: {fps, temperatureState, queueDepth, uptimeSec, appVersion}` | 60 sn'de bir |

`reasons` sabit sözlük: `area_low`, `area_high`, `aspect_out`, `solidity_low`, `spots`, `barcode_missing`, `barcode_mismatch`, `text_missing`, `text_mismatch`, `anomaly`.

`total`, cihazın oturum sayacıdır; backend toplamları **delta** üzerinden hesaplar, `total` yalnızca tutarlılık kontrolü içindir.

## 3. Gönderim paketi — `batch.schema.json`

```json
{ "schema": "bantvision.batch.v1", "deviceId": "dev_...", "sentAt": "...", "events": [ ... en fazla 500 ... ] }
```
- `POST {ingestUrl}` başlıklar: `Content-Type: application/json`, `X-Device-Key: <cihaz anahtarı>`.
- Yanıt `200 {"accepted": n, "duplicates": m}`. 4xx → paketi düşür ve logla (yeniden deneme yok), 5xx/ağ hatası → üstel bekleme ile yeniden dene (1, 2, 4 … en fazla 60 sn).
- NOK görselleri ayrı yüklenir: önce `POST {ingestUrl}/upload-url` → imzalı URL → `PUT` JPEG. `imageRef` = depo yolu.
- Webhook modu (backend yerine doğrudan n8n vb.) aynı paketi gönderir.

## 4. Cihaz kaydı — `device.schema.json`

1. Dashboard'da hat için **eşleme QR'ı** üretilir: `bantvision://pair?url=<ingestUrl>&code=<tek kullanımlık 8 hane>`.
2. Cihaz (iPhone ya da edge) `POST {ingestUrl}/pair {code, deviceInfo}` → `{deviceId, deviceKey, lineId, orgId}`.
3. `deviceKey` iOS'ta Keychain'de, edge'de `0600` izinli dosyada saklanır. Backend'de yalnızca hash'i durur.

## 5. Edge yerel API
Bkz. `05-edge-service.md` §4. iOS uygulaması bu API'nin istemcisidir; profil gövdeleri §1 ile aynıdır.

## 6. Doğrulama (CI)

```bash
pip install "jsonschema[format-nongpl]" pytest
python tools/validate_contracts.py   # şemalar + tüm örnekler
pytest -q tools/tests                # olumlu + olumsuz (bozulmuş örnek) testleri
```

- Örnekler `contracts/examples/` altında; hangi şemaya ait oldukları **dosya adı önekinden** anlaşılır:
  `profile-*` → profil, `event-*` → olay, `batch*` → paket, `device-pair-request*` / `device-pair-response*` → `device.schema.json` içindeki `$defs`, `analysis-job*` → analiz işi, `view-template*` → çoklu izleme şablonu (§8).
  Veri dosyaları (`view-layouts.json`) örnek değildir; `DATA_FILES` ile kendi şemalarına karşı doğrulanır.
  Eşlenmeyen bir örnek dosyası CI'ı kırar (eşleme: `tools/validate_contracts.py` → `EXAMPLE_SCHEMAS`).
- `uuid` ve `date-time` formatları denetlenir. `format-nongpl` eki kurulu değilse `date-time` sessizce geçer, bu yüzden CI bu eki kurar.
- `tools/tests/test_contracts.py` içindeki olumsuz testler, geçerli bir örneği tek noktadan bozup şemanın doğru kuraldan reddettiğini kontrol eder. Bir kısıtı gevşetirsen ilgili test kırılır; bilinçli bir değişiklikse testi de güncelle.
- `services/edge/tests/test_profile_contract.py`, Python `Profile` modelinin ürettiği JSON'un şemaya uyduğunu ve örneklerin model üzerinden kayıpsız gidip geldiğini doğrular. Swift tarafı için aynı test F0.2/F1'de eklenecek.

## 7. Video analiz işi — `analysis-job.schema.json`
Web'den yüklenen videonun analizi (`13-web-platform.md`). Analiz sunucusu (`bantvision.analyzer`) üretir, panel okur.

| Alan | Açıklama |
|---|---|
| `status` | `queued` → `running` → `done` / `failed`; saklama süresi dolunca `expired` (dosyalar silinir, özet kalır) |
| `video` | ad, bayt; analizden sonra `seconds`, `fps`, `width`, `height` |
| `options` | isteğe bağlı: `preset` (`generic/egg/flour/box/people`), `countMode` (`people` için `detect`), `countAnchor` (`detect`: `center` tepeden / `bottom` yandan), `productLength` (profildeki anlamıyla), `truth` (iki yönlüde doğru giriş), `direction` (iki yönlüde giriş yönü), `roi`, `roiPolygon`, `countLine` (profil şemasındakiyle aynı), `line`, `bgRange` |
| `progress`, `stage` | 0–1; `calibrating` / `counting` / `encoding` |
| `result` | `count` (iki yönlüde giriş), `countOut` (yalnızca iki yönlü sayımda: çıkış), `truth`, `errorPct`, `calibration`, `processingFps`, `files` (yalnızca `annotated.mp4`, `counts.csv`, `profile.json`, `background.png`). İki yönlü sayımda `counts.csv` sütunları `zaman_sn;iz;yon;giris_toplam;cikis_toplam` (`yon`: `giris`/`cikis`) |
| `expiresAt` | oluşturma + saklama süresi (varsayılan 7 gün) |

`done` ise `result`, `failed` ise `error` zorunlu. Örnekler: `examples/analysis-job-*.json`.

## 8. Çoklu izleme — `view-layouts.json`, `view-template.schema.json`
Birden çok kamerayı tek ekranda şablonlu ızgarada izlemek için ortak dil (web ve ileride iPhone). Tasarım: `superpowers/specs/2026-10-08-coklu-izleme-design.md`.

**Düzen kataloğu** (`view-layouts.json`, şema: `view-layouts.schema.json`, `version: 1`). Düzen, birim ızgarada hücre listesidir: `{id, name, cols, rows, cells: [[x, y, w, h], …]}`.
- Hücre `(x, y, w, h)` birim ızgarada verilir; **hücre sırası kutu sırasıdır** (şablondaki `tiles[i]`, `cells[i]` hücresine konur).
- Tuval herhangi bir boyutta olabilir; hücreler `cols × rows` ızgarasına oranlanarak yerleşir. Hücreler ızgarayı boşluksuz ve çakışmasız kaplar; kutu sayısı `id`'ye eşittir (testlerle denetlenir).
- `version` kırıcı değişiklikte artar. Var olan bir düzenin hücrelerini değiştirmek kırıcıdır: kayıtlı şablonlardaki kutu sırası bozulur.

| id | Ad | cols×rows | Hücreler `[x, y, w, h]` |
|---|---|---|---|
| `1` | Tek | 1×1 | `[0,0,1,1]` |
| `2` | 2'li (yan yana) | 2×1 | `[0,0,1,1]` `[1,0,1,1]` |
| `3` | 3'lü (1 büyük + 2) | 3×2 | `[0,0,2,2]` `[2,0,1,1]` `[2,1,1,1]` |
| `4` | 4'lü | 2×2 | 2×2 eşit |
| `6` | 6'lı (1 büyük + 5) | 3×3 | `[0,0,2,2]` `[2,0,1,1]` `[2,1,1,1]` `[0,2,1,1]` `[1,2,1,1]` `[2,2,1,1]` |
| `8` | 8'li (1 büyük + 7) | 4×4 | `[0,0,3,3]` `[3,0,1,1]` `[3,1,1,1]` `[3,2,1,1]` `[0,3,1,1]` `[1,3,1,1]` `[2,3,1,1]` `[3,3,1,1]` |
| `9` | 9'lu | 3×3 | 3×3 eşit |
| `12` | 12'li | 4×3 | 4×3 eşit |
| `16` | 16'lı | 4×4 | 4×4 eşit |

"Eşit" düzenlerde hücreler soldan sağa, yukarıdan aşağıya `[x, y, 1, 1]` sırasıyla dizilir.

**Şablon** (`view-template.schema.json`): `{id, name, layout, tiles, createdAt, updatedAt}`.
- `name` 1–60 karakter; `layout` yukarıdaki düzen kimliklerinden biri; `createdAt` / `updatedAt` Unix saniyesi.
- `tiles` uzunluğu düzenin hücre sayısına eşittir. Her öğe `null` (boş kutu) ya da `{sourceId, channelId}` olur; tek kamerada (kanalsız kaynak) `channelId` `null`'dır.
- Aynı kamera (`sourceId` + `channelId`) bir şablonda en fazla bir kez yer alır.
- Şema yalnızca biçimi denetler. `tiles` uzunluğunun düzenle uyumu ve kameranın tekrarsızlığı alanlar arası kurallardır; şablonu kaydeden taraf (web'de analiz sunucusu) denetler.
- Kamera kimlikleri **platforma özgüdür**: web'de analiz sunucusunun kaynak kimliği kullanılır, iPhone kendi kimliklerini kullanacak. Biçim ortaktır.

Örnekler: `examples/view-template-*.json` (önek `view-template` → `view-template.schema.json`). `view-layouts.json` bir örnek değil veri dosyasıdır; `tools/validate_contracts.py` içindeki `DATA_FILES` ile kendi şemasına karşı doğrulanır.

**Python kataloğu** `services/edge/bantvision/live/layouts.py` aynı düzenleri taşır; `services/edge/tests/test_layouts.py` onu `view-layouts.json` ile birebir eşitlik için karşılaştırır. Düzen eklemek ya da değiştirmek için önce `view-layouts.json` ve şemadaki `id` listesi, sonra Python kataloğu ve diğer uygulamalar aynı değişiklikte güncellenir. Geometri değişmezleri (tam kaplama, çakışmasızlık, kutu sayısı) `tools/tests/test_contracts.py` içinde.
