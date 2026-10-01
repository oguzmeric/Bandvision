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
| `linePosition` | 0–1 | Sayım çizgisinin akış eksenindeki konumu |
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
| `count` | `count: {delta, total, trackId}` | İz çizgiyi geçti ya da çarpanı arttı |
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
  `profile-*` → profil, `event-*` → olay, `batch*` → paket, `device-pair-request*` / `device-pair-response*` → `device.schema.json` içindeki `$defs`.
  Eşlenmeyen bir örnek dosyası CI'ı kırar (eşleme: `tools/validate_contracts.py` → `EXAMPLE_SCHEMAS`).
- `uuid` ve `date-time` formatları denetlenir. `format-nongpl` eki kurulu değilse `date-time` sessizce geçer, bu yüzden CI bu eki kurar.
- `tools/tests/test_contracts.py` içindeki olumsuz testler, geçerli bir örneği tek noktadan bozup şemanın doğru kuraldan reddettiğini kontrol eder. Bir kısıtı gevşetirsen ilgili test kırılır; bilinçli bir değişiklikse testi de güncelle.
- `services/edge/tests/test_profile_contract.py`, Python `Profile` modelinin ürettiği JSON'un şemaya uyduğunu ve örneklerin model üzerinden kayıpsız gidip geldiğini doğrular. Swift tarafı için aynı test F0.2/F1'de eklenecek.
