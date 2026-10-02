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
Üst çubuktaki film simgesi → **Video ile test** sayfası: **Fotoğraflar'dan seç** (dönüştürmeden, orijinal biçimde alınır) ya da **Dosyalar'dan seç**. Hazırlanırken "Video hazırlanıyor…" görünür; video açılınca kamera durur ve video baştan oynar.
- Sayfadaki **"Videonun başında bant boş"** anahtarı (varsayılan açık, hatırlanır): açıksa baştan oynatmada arka plan ilk ~1 sn'den öğrenilir (§5). Video ürünle başlıyorsa kapatılır; oynarken bant boş göründüğünde Kalibre → Boş bandı öğren kullanılır.
- **Oynatıcı:** baştan oynat, oynat/duraklat, sürüklenebilir zaman çubuğu, hız 1×/2×/hızlı. Bir noktaya atlamak sayacı sıfırlar ve sayımı oradan başlatır ("sayım başlangıcı 0:45"); doğruluk yalnızca baştan oynatmada gösterilir. Ortadan başlarken önceden öğrenilen arka plan korunur. Kalibrasyon sırasında da oynatıcı görünür.
- `Camera/VideoFileSource.swift`: `AVAssetReader` + video kompozisyonu (videonun yönü uygulanır), kareler kamerayla aynı biçimde (420f). Her oynatma (`play(from:)`) yeni bir okuyucu ve "nesil" başlatır; önceki okuma bir sonraki karede durur. Okuma ayrı kuyrukta, her kare `processingQueue.sync` ile işlenir; zaman damgası her zaman videonunkidir (§7 ölçekleme doğru çalışır).
- Video sayımı canlı oturumdan ayrıdır: kayıt/webhook'a yazılmaz; **Kamera** düğmesi önceki sayıyı geri yükler. Geçici video kopyaları çıkışta silinir.
- Sonuçta isteğe bağlı "Doğru adet" → doğruluk % (≥ %98 yeşil).
- Masaüstü karşılığı: `python -m bantvision.video` (README). Sayısı bilinen test videoları: `tools/make_test_video.py`.

## 1c. Kalite kontrol A1: sekmeler, ürün kartları, örnekle öğretme
Sekmeler: **Canlı · Genel bakış · Öğret · Ayarlar** (`UI/RootView.swift`). Kamera ve sayım sekme değişse de sürer.
- **Kırpıntı:** ürün çizgiyi ilk geçtiğinde (`CountEvent.isFirstCrossing`) lekenin kutusu %15 payla tam çözünürlüklü kareden kırpılır, JPEG (uzun kenar ≤ 256 px) olarak `FrameProcessor.onCrop` ile gelir. `CountEvent` artık `trackId` ve `bbox` taşır.
- **Kartlar** (`Core/Inspection.swift`, `UI/OverviewView.swift`): son 50 ürün bellekte; fotoğraf, Geçti/Kaldı, saat, kısa kimlik (`hexID`, Python işaretli videoyla aynı), güven %. Dokununca büyük görünüm ve öğretme. Sayaç sıfırlanınca kartlar da sıfırlanır.
- **Öğretme** (`Core/Teach.swift`, `UI/TeachView.swift`): profile özel kusur türleri; örnekler `Application Support/teach/<profil-id>/` (index.json, jpg, Vision feature print arşivi). Karar `AppearanceClassifier`: en yakın 5 örneğin 1/uzaklık ağırlıklı oyu; yalnızca iyi örnek varsa anomali modu (en yakın iyiye uzaklık, iyilerin kendi aralarındaki tipik uzaklığın 1,8 katını aşarsa "Beklenmedik"). Hazır olma: ≥ 3 iyi + bir kusur türünde ≥ 2 örnek, ya da ≥ 5 iyi. Vision işleri kendi kuyruğunda; sayımı yavaşlatmaz.
- A1 cihaza özeldir; profil/olay sözleşmesine F1.1 ve B aşamasında girer (kusur türleri, `inspection` olayı, NOK görseli).
- Ekranda iz kimlikleri (F1.2).

## 1e. Ağ kamerası (telefon IP kamerayı kaynak olarak kullanır)
Karar (2026-10-02): önce **telefon + 1 IP kamera**; çoklu kamera gerekirse web/edge tarafına (F2) taşınır.
- **Ayarlar → Görüntü kaynağı:** iPhone kamerası / Ağ kamerası. Ağ kamerası formu: marka şablonu (Hikvision, Dahua, Axis, Vivotek, Milesight; uymazsa "Diğer" ile tam `rtsp://` adresi), IP, port, kanal, alt/ana akış, kullanıcı adı; şifre Keychain'de (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`). **Bağlantıyı test et:** ilk kare, çözünürlük, codec; hata olursa kontrol listesi.
- **Erişim:** telefon kameranın RTSP portuna ağ üzerinden ulaşabilmeli (aynı yerel ağ ya da VPN; misafir Wi-Fi çoğu zaman kameralara erişemez; port yönlendirme önerilmez). `NSLocalNetworkUsageDescription`. Otomatik bulma (ONVIF WS-Discovery) Apple'ın multicast iznini gerektirir; şimdilik IP elle girilir.
- `Camera/RTSPClient.swift` (dış kütüphane yok): RTSP/1.0, RTP/AVP/TCP interleaved, Basic ve Digest (qop=auth; birden çok `WWW-Authenticate` gelirse Digest tercih), SDP (`sprop-parameter-sets`, `sprop-vps/sps/pps`), H.264 (tekil, STAP-A, FU-A) ve H.265 (tekil, AP, FU), sıra numarası boşluğunda yarım NAL atılır, OPTIONS ile canlı tutma.
- `Camera/NetworkCameraSource.swift`: VideoToolbox ile 420f'ye çözme (kamera ile aynı biçim), parametre seti değişince yeniden kurulum, ilk anahtar kareyi bekleme, RTP zaman damgası taşma açma; koparsa 1, 2, 4 … 30 sn aralıkla yeniden bağlanma (yanlış şifre ve geçersiz adreste denemez). `FrameGate`: işleme meşgulse kare atlanır, gecikme birikmez.
- Uygulama açık ve telefon şarjda kalmalı (iOS arka plandaki uygulamayı durdurur); Rehberli Erişim önerilir.
- Test: CI'da MediaMTX, test klibini Digest korumalı RTSP olarak yayınlar; UI testi sayımın Python referansıyla aynı olduğunu ve yanlış şifrede anlaşılır hata verildiğini doğrular. Klip 4 sn boş bantla başlar: canlı yayına geç katılan okuyucu da boş bant öğrenmesini (§5) ürün gelmeden bitirebilsin. **Sahada da aynı kural:** boş bant öğrenmesi bant gerçekten boşken yapılmalı; ürün varken öğrenilen arka plan sayımı ciddi düşürür (Python benzetiminde 28 yerine 2).

## 1g. Kayıt cihazı (NVR/XVR) ekleme
Saha gerçeği: kameraların çoğu bir kayıt cihazına bağlı (TRASSIR, Dahua, Hikvision; 4–128 kanal). Ağ kamerası formunda **Kamera | Kayıt cihazı** seçimi.
- **Akış:** marka, IP, kullanıcı/şifre (bir kez) → **Kameraları listele** → kameralar adları ve küçük görüntüleriyle (8'den fazlaysa arama: ad ya da kanal no) → bantı gören kameraya dokun → Bağlantıyı test et → Kaydet. Cihaz kimliği (marka/IP/portlar/kullanıcı) değişince liste ve seçim sıfırlanır.
- **Küçük görüntüler:** yalnızca ekranda görünen satırlar, aynı anda en fazla 3 istek (`AsyncLimiter`). Önce cihazın anlık görüntü API'si, olmazsa akışın ilk karesi (RTSP); görüntü vermeyen (boş) kanal "görüntü yok".
- `Core/Recorder.swift`: türler ve ağdan bağımsız ayrıştırıcılar (birim testli). `Camera/RecorderClient.swift`: `DeviceHTTPClient` (URLSession; Digest/Basic yerleşik; kendinden imzalı sertifika **yalnızca kullanıcının girdiği adres için**), marka istemcileri. `Camera/NetworkStreamPlan.swift`: ayarlardan akış planı (canlı yayın ve sınama aynı yoldan).
- **TRASSIR SDK** (`08-trassir-integration.md`): HTTPS 8080 `/login?username&password` → `sid` (15 dk, her istekle uzar) → `/channels?sid` (`channels` + `remote_channels`; `zombies` listelenmez) → `/get_video?channel=<guid>&container=rtsp&stream=sub|main&sid` → `token` (~10 sn) → `rtsp://sunucu:555/<token>`. Yanıt sonundaki `/* … */` açıklaması ayıklanır. Adres **her bağlanışta yeniden alınır** (`NetworkCameraSource(resolver:)`); yayın açıkken 5 sn'de bir `http://sunucu:555/<token>?ping`. Oturum düşmüşse bir kez yeniden giriş. Şart: TRASSIR'da Ayarlar → Web sunucusu (SDK) açık.
- **Hikvision ISAPI** (HTTP Digest, port 80): `/ISAPI/ContentMgmt/InputProxy/channels` (IP kanalları) + `/ISAPI/System/Video/inputs/channels` (analog); akış `/Streaming/Channels/<n>0<2|1>`; anlık görüntü `/ISAPI/Streaming/channels/<n>01/picture`.
- **Dahua CGI** (HTTP Digest, port 80): `/cgi-bin/configManager.cgi?action=getConfig&name=ChannelTitle` (`table.ChannelTitle[i].Name`, kanal = i+1); akış `/cam/realmonitor?channel=<n>&subtype=<1|0>`; anlık görüntü `/cgi-bin/snapshot.cgi?channel=<n>`.
- **Ayar kaydı:** `NetworkCameraConfig` eski sürümlerin kaydını okur (eksik alan = varsayılan; derleme 12 kaydı birim testli). Kayıt cihazı şifresi Keychain'de ayrı hesapta (`recorder`).
- **ATS:** `NSAllowsLocalNetworking` — kayıt cihazlarının web API'si yerel ağda çoğunlukla düz HTTP.
- **Test:** birim (`BantSayacTests`: ayrıştırıcılar, geriye uyum, akış adresleri) ve uçtan uca UI (`BS_TEST_FORMS`; ayar ekranı gerçek kullanıcı gibi doldurulur). CI'da `tools/mock_nvr.py` sahte TRASSIR (HTTPS) ve Hikvision/Dahua (Digest), MediaMTX akışları (TRASSIR jetonları 555'te).
- **Doğrulanmamış:** gerçek TRASSIR'da hata kodlarının metni, `?ping`'in gerekliliği, `container=jpeg` anlık görüntü yolu (olmazsa RTSP'ye düşülür). Gerçek bir TRASSIR (4.x) ile denenmeli.

## 1h. Çokgen ilgi alanı (ROI)
Eğik bant ya da kenarda insan/makine hareketi varsa dikdörtgen ROI fazlasını içine alır. Kalibre panelinde **Alan: Dikdörtgen | Çokgen**.
- Çokgene geçince mevcut dikdörtgenin 4 köşesiyle başlar. Köşeler sürüklenir; kenar ortasındaki sarı **+** sürüklenince köşe eklenir (en çok 12); köşeye çift dokunma köşeyi siler (en az 3). "Köşeleri sıfırla".
- `ProductProfile.roiPolygon: [NormPoint]?` (sözleşmedeki `{x, y}` biçimi; eski kayıtlarda yok → dikdörtgen). `setPolygon` `roi`'yi sınır kutusu yapar ve sayım çizgisini kutunun içine çeker.
- `BackgroundSegmenter.roiMask`: §2.0 kuralı (piksel merkezi, çift-tek), önbellekli; eşik ve boş bant öğrenmesinin yüzdeliği yalnızca maske içinde. Python `roi_mask` ile aynı pikseller: `BantSayacTests/RoiPolygonTests` ↔ `services/edge/tests/test_roi_polygon.py` aynı sayıları doğrular.

## 1i. Açılı sayım çizgisi
Eğik bakan IP/CCTV kamerada bant görüntüde çapraz akar. Kalibre panelinde **Sayım çizgisi: Düz | Açılı** (algoritma §4.8, sözleşme `countLine`).
- Açılıya geçince düz çizgi aynı yerde ve aynı akış yönüyle açılı çizgiye dönüşür (`straightCountLine`). Uçlar ayrı sürüklenir, ortadan tutulunca bütün taşınır; turuncu ok akışı gösterir (a→b'nin sağ eli), **Yönü çevir** uçları değiştirir. `direction` akışa en yakın eksene güncellenir (uyumluluk).
- `Vision/LineFrame.swift`: çerçeve (Python `lineframe.py` ile aynı işlem sırası); segmentasyon açılı çizgide her bileşenin çerçeve kutusunu piksellerden hesaplar (`frameBBox`); izleyici çerçevede "aşağı, çizgi 0" ile çalışır; iz işaretleri ekrana geri çevrilir; sayım kırpıntısı görüntüdeki özgün kutudan (`sourceBBox`).
- Eşdeğerlik: `BantSayacTests/LineFrameTests` ↔ `services/edge/tests/test_angled_line.py`.

## 1f. Görünüm yakınlaştırma
Kamera alanında iki parmakla 1×–6× yakınlaştırma, yakınken tek parmakla kaydırma, çift dokunuşla sıfırlama. Görüntü, maske ve ROI/çizgi/izler birlikte ölçeklenir. Yalnızca görünümdür; sayım tam kare üzerinden sürer. Kalibrasyonda tek parmak ROI'yi sürüklediği için kaydırma kapalıdır. Ekran karesi (video/ağ kamerası) ayrı kuyrukta üretilir; sayım ekranı beklemez.

## 1d. Uçtan uca UI testi
`BantSayacUITests` (simülatör): `tools/make_ui_test_clip.py` ile üretilen dik klibi (28 yumurta; tek, arka arkaya ve yan yana bitişik) DEBUG test kancasıyla (`BS_TEST_VIDEO`, `BS_TEST_EXPECTED_AREA`) kamera izni istemeden en hızlı modda saydırır; sayı Python referansıyla aynı olmalı (Swift ↔ Python eşdeğerliğinin çalıştırılarak doğrulanması). Ardından sekmeleri ve video sayfasını açıp kapatır. CI: `ios-uitest.yml` (elle) ve **TestFlight yüklemesinden önce zorunlu**.

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
