# 04 — iOS Uygulaması

Konum: `apps/ios` (XcodeGen: `project.yml`). Swift 5 dil modu, SwiftUI, iOS 17+, harici bağımlılık yok.

## 1. Mevcut durum (v1)
| Dosya | Görev |
|---|---|
| `Camera/CameraManager.swift` | 720p/60 fps, portreye döndürme (`videoRotationAngle = 90`), pozlama/fener/odak |
| `Vision/GrayFrame.swift` | Y düzleminden kutu-ortalama küçültme |
| `Vision/BackgroundSegmenter.swift` | §2 segmentasyon |
| `Vision/BlobTracker.swift` | §4 izleme ve sayım |
| `Vision/FrameProcessor.swift` | Hat, kalibrasyon durum makinesi, ana kuyruğa callback |
| `Core/*` | Profil modeli/deposu, ayarlar, kayıt + webhook (eski format) |
| `UI/*` | Ana ekran, sürüklenebilir ROI/çizgi, kalibrasyon paneli, profiller, ayarlar |

Eşzamanlılık modeli: kamera kareleri `processingQueue`'da gelir; `FrameProcessor` durumu yalnızca bu kuyrukta değişir; UI'a `DispatchQueue.main.async` ile `@MainActor` callback'ler gider. ViewModel ve depolar `@MainActor`.

## 1b. Video modu (manuel test)
Üst çubuktaki film simgesi → **Fotoğraflar'dan** ya da **Dosyalar'dan** video. Kamera durur, video aynı işleme hattından geçer.
- `Camera/VideoFileSource.swift`: `AVAssetReader` + video kompozisyonu (videonun yönü uygulanır), kareler kamerayla aynı biçimde (420f). Okuma ayrı kuyrukta, her kare `processingQueue.sync` ile işlenir; kalibrasyon komutları kareler arasında çalışır. Hız 1×/2×/hızlı; zaman damgası her zaman videonunkidir (§7 ölçekleme doğru çalışır).
- Başlarken sorulur: video boş bantla başlıyorsa ilk ~1 sn'den arka plan ve eşik öğrenilir (§5). Video oynarken Kalibre akışı kullanılabilir.
- Video sayımı canlı oturumdan ayrıdır: kayıt/webhook'a yazılmaz, "Kameraya dön" önceki sayıyı geri yükler.
- Sonuçta isteğe bağlı "Doğru adet" girilir; doğruluk % gösterilir (≥ %98 yeşil).
- Masaüstü karşılığı: `python -m bantvision.video` (README). Sayısı bilinen test videoları: `tools/make_test_video.py`.

## 2. Görevler

### F0.1 Derleme
- `xcodegen && open BantSayac.xcodeproj`, derle, hataları düzelt. Swift 6 dil moduna **geçme** (F7 sonrası değerlendirilir).
- Release yapılandırmasında ölç: iPhone 12, 240 px → hedef ≥ 45 fps (ekrandaki fps göstergesi).

### F0.2 Test hedefi + eşdeğerlik
- `BantSayacTests` hedefi ekle (`project.yml`).
- `FrameProcessor`'a test için `process(gray: GrayFrame, ts: Double)` ekle; `process(_ pixelBuffer:)` bunu çağırsın.
- `tools/gen_vectors.py` çıktısını (PNG + `expected.json`) test paketine kaynak olarak ekle; PNG → `GrayFrame` (CGImage'den gri baytlar), `expected.json`'daki profille işle, `warmupFrames` sonrası sayacı sıfırla, toplamı `expectedCount` ile karşılaştır.

### F1.1 Sözleşme v1, outbox, heartbeat
- `ProductProfile`: `schema`, `source{rotation, referenceFps}`, `scale{mmPerPixel}`, `qc`, `io` alanlarını ekle. Özel `init(from:)` ile eksik alanları varsayılanla oku (eski kayıtlı profiller kırılmasın). JSON çıktısı `contracts/product-profile.schema.json` ile doğrulanabilir olmalı (`roi` → `{x,y,width,height}`; `CGRect`'in varsayılan Codable biçimi `[[x,y],[w,h]]` olduğu için **özel kodlama gerekli**).
- `CountEvent`'e `trackId` ekle.
- Olay modeli `contracts/event.schema.json`. `Outbox`: `Application Support/outbox.jsonl` (satır başına bir olay), gönderilenler bir "ack" indeksiyle işaretlenir, dosya 5 MB'ı aşınca sıkıştırılır.
- Gönderici: 5 sn'de bir en fazla 500 olay, `X-Device-Key` başlığı, `02-contracts.md` §3 yeniden deneme kuralları.
- 60 sn'de bir `heartbeat`; `state` olayları (§8, kalibrasyon başlangıç/bitiş).
- §7 fps ölçeklemesi: kare zaman damgası `CMSampleBufferGetPresentationTimeStamp`'ten alınıp `FrameProcessor`'a geçirilir.

### F1.2 İz kimlikleri
- `TrackMarker.id` ekranda `String(id, radix: 16, uppercase: true)` olarak izin yanında; sayılmış iz camgöbeği.

### F1.3 Veri toplama modu
- Ayarlar → "Veri topla". Açıkken her 0,5 sn'de bir, **en az bir leke varsa, tüm lekelerin çarpanı 1 ise ve hiçbir leke ROI kenarına değmiyorsa** kareyi kaydet.
- Görüntü: tam kareden uzun kenarı 640 px JPEG (kalite 85). Etiket: her leke için `0 cx cy w h` (YOLO, görüntüye göre normalize; ROI'ye değil).
- Klasör: `Documents/datasets/<profil>-<tarih>/images|labels`. Paylaşım: `NSFileCoordinator` `.forUploading` ile zip.
- Ayrıntılar: `09-ml-roadmap.md` §2.

### F1.4 Eşleme
- QR: VisionKit `DataScannerViewController` (iOS 16+). `bantvision://pair?...` → `02-contracts.md` §4. Anahtar Keychain'de (`kSecAttrAccessibleAfterFirstUnlock`).

### F4 Kalite kontrol
- Tam çözünürlük için son 3 karenin **Y düzlemini kendi yeniden kullanılan tamponlarına kopyala** (CVPixelBuffer'ları tutma; havuz tükenir ve kare düşer). Kopyalama yalnızca QC açıkken.
- `03-algorithm.md` §6: geometri (özdeğerler kapalı formül: 2×2 kovaryans), solidity (köşe noktaları + monotone chain + shoelace), leke tespiti.
- Barkod/metin: kırpıntıdan `CGImage` → `VNImageRequestHandler` (`VNDetectBarcodesRequest`, `VNRecognizeTextRequest .fast`), ayrı bir kuyrukta, 500 ms zaman aşımı.
- UI: OK/NOK sayaçları, son 20 NOK'un küçük resim şeridi, dokununca büyük görsel + nedenler.
- Kalibrasyonda "mm/piksel": ekranda iki nokta seçip aradaki gerçek mesafeyi (mm) gir.

### F5 I/O köprüsü istemcisi
- `Network.framework` `NWConnection` (UDP). Protokol `07-io-bridge-esp32.md` §4. Ayarlar'da köprü IP'si ve "Test darbesi" düğmesi.
- `Info.plist`: `NSLocalNetworkUsageDescription`.

### F6 Edge kalibrasyon istemcisi
- `NWBrowser` ile `_bantvision._tcp` keşfi (`NSBonjourServices`).
- Kamera listesi → kamera ekranı: `/cameras/{id}/snapshot.jpg` 5 fps yoklama + `/cameras/{id}/state` WebSocket'ten lekeler/izler; mevcut `OverlayView` aynen kullanılır (fitRect, snapshot boyutundan).
- Profil düzenleme aynı panellerle; "Kaydet" → `PUT /cameras/{id}/profile`. Boş bant/örnek kalibrasyonu → `POST /cameras/{id}/calibration/...`.

## 3. Performans notları
- Debug'da piksel döngüleri yavaştır; ölçümleri Release'te yap.
- Gerekirse segmentasyonu `vImage` (Accelerate) ile hızlandır: küçültme `vImageScale_Planar8`, morfoloji `vImageErode_Planar8`/`vImageDilate_Planar8`. Davranış §2 ile aynı kalmalı (eşdeğerlik testi).
- Isınma: `ProcessInfo.thermalState` `serious` olunca işleme genişliğini bir kademe düşür ve `heartbeat`'te bildir.
