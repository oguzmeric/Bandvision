# 12 — Durum Özeti (2026-10-02)

Bu oturumda yapılan her şeyin toplu dökümü: ne bitti, nasıl doğrulandı, neler açık, sırada ne var.
Repo: `github.com/oguzmeric/Bandvision` (2026-10-02'den beri geçici olarak **herkese açık**: özel repoda aylık 2.000 Actions dakikası bitmek üzereydi, macOS dakikası 10 kat sayılıyor. Yayımlamadan önce tüm geçmiş tarandı; anahtar/şifre yok. Kullanıcı daha sonra yeniden özele alabilir). Ayrıntılar ilgili dokümanlarda; burası giriş noktası.

## 1. Altyapı

| Konu | Durum |
|---|---|
| Repo | Zip'ten kalıcı klasöre (`C:\Users\MSI-LAPTOP\bantvision`) taşındı, git + GitHub (özel) |
| CI `ci` | Her push'ta: edge çekirdek testleri + ruff, sözleşme doğrulaması |
| CI `ios` | Her iOS değişikliğinde macOS'ta Xcode 26 ile imzasız Release derleme + **sıkı concurrency denetimi (uyarı = hata)** |
| CI `testflight` | Elle tetiklenir (Actions → testflight → Run workflow): arşiv, otomatik imzalama, App Store Connect'e yükleme |
| Apple | Bundle ID `com.oguzmeric.bantsayac`, App Store Connect kaydı "Bant Sayaç" (mağaza adı orada ayrıca değiştirilir), Internal Testing grubu. Ana ekran adı derleme 12'den itibaren **BandVision** |
| Marka | Logo `docs/brand/bandvision-logo.png`; uygulama ikonu yazılı logo (karşılaştırma: `docs/brand/ikon-karsilastirma.png`) |
| Secret'lar | `APPLE_TEAM_ID`, `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_P8` (GitHub Actions secret; değerler repoda yok) |

TestFlight kurulumunda çözülen sorunlar: .p8 anahtarı tarayıcı formunda CRLF'e dönüşüyordu (workflow artık her yapıştırma biçimini normalize ediyor), `ASC_KEY_ID` başka anahtarındı (401; teşhis adımı eklendi), Apple iOS 26 SDK şartı (Xcode 26.3 seçiliyor).

## 2. TestFlight derlemeleri

| Derleme | İçerik |
|---|---|
| 6 | İlk yükleme: uygulama derleniyor, açılıyor; ikon |
| 7 | Yoğun akışta arka plan kayması düzeltmesi |
| 8 | Bitişik ürünlerde birleşme/bölünme izleme, Swift yuvarlaması Python ile aynı |
| 9 | Video modu (Fotoğraflar/Dosyalar'dan video sayımı) + §7 fps ölçeklemesi |
| 10 | Kullanıcı geri bildirimi: "Video ile test" sayfası (tepkisiz menü giderildi), oynatıcı (baştan, oynat/duraklat, zaman çubuğu, atlama), sayısal klavyede Tamam |
| **11** | **Kalite kontrol A1**: sekmeler (Canlı · Genel bakış · Öğret · Ayarlar), ürün kartları, örnekle öğretme; düz videolarda kompozisyonsuz okuma; düğme yazıları bölünmüyor. **Uçtan uca UI testinden geçmeden yüklenmez.** |
| **12** | **Ağ kamerası (RTSP)**: telefon, mevcut IP kameranın yayınını alıp sayar ve kalite kontrol yapar (marka şablonları, Digest/Basic, H.264/H.265, yeniden bağlanma). Video ve kamerada yakınlaştırma/kaydırma; Canlı ekranda son ürün kartları ve ürünün yanında OK/NOK etiketi; QC kırpıntısı artık sayımı bekletmiyor; yeni ikon ve ad (BandVision) |
| **13** | **Kayıt cihazı (NVR/XVR) ekleme**: TRASSIR (SDK, jetonlu RTSP 555), Hikvision (ISAPI), Dahua (CGI); cihaz bir kez girilir, kameralar adları ve küçük görüntüleriyle listelenir (arama), dokunarak seçilir. RTSP el sıkışma 15 sn. Uçtan uca UI testi: sahte TRASSIR/Hikvision/Dahua (`tools/mock_nvr.py`) ile listele → seç → test → kaydet → canlı. Gerçek TRASSIR'da henüz denenmedi |
| **14** | **Çokgen ROI** (sözleşme `roiPolygon`, algoritma §2.0; Python ↔ Swift piksel eşdeğerliği testli), **logolu açılış animasyonu**, **ilk kurulum sihirbazı** (kaynak → ürün → montaj → kalibrasyon; önceden kullanılan uygulamada kendiliğinden açılmaz). Paralel kod incelemesinde bulunan 4 hata düzeltildi; Swift birim testleri her iOS gönderiminde CI'da |
| 15, 16 | Yüklenmedi (15: ağ kamerası UI testi zamanlaması; 16: CI her çalışmada yeni geliştirme sertifikası oluşturduğu için hesap sınırı doldu → arşiv imzasız, imza bulut dağıtım sertifikasıyla). İçerikleri 17'de |
| **17** | **Açılı sayım çizgisi** (`countLine`, §4.8; Python ↔ Swift eşdeğer), **sayılan ürünün üstünde sıra numarası** (34; bitişik çiftte 35–36; kartlarda aynı), sayım çizgisi çokgenin içinde çizilir, kalibrasyon yazıları kırpılmaz. TRASSIR gerçek cihazda doğrulandı (derleme 13 ile) |
| **18** | **Şerit tarama sayımı** (bitişik/üst üste torba, koli; §4.9): kalibrasyonda "Sayım yöntemi" ve "Ürün boyunu öğren"; un torbası ve yeni "Koli / kutu" profili bu yöntemle. **Her ürüne kendi numarası** (yapışıkta "34·35", ayrılınca her biri kendi numarasıyla). **Kaydedilen eşik video başında değişmez** (100'e kaçma hatası); bantta ürün varken "Boş bandı öğren" eşiği bozmaz, uyarır |
| **19** | Kalibrasyon paneli ekranın en çok üçte biri (kayar, Kaydet/İptal sabit); şerit taramada **alan bandın dışına taşsa da yalnızca hareketli bant** kullanılır (ekran kaydı, menüler, raylar, siyah ilk kare) |
| **20** | Şerit tarama: **aralıklı ürünler ve güçlü perspektif** (ikinci gerçek video 11 → 8–9, doğru 9), açık/koyu kararı satır içi yayılım ipucuyla, ön sayım yalnızca ilk ürün |
| **21** | Şerit tarama: sayılar topluca gelmesin — video modunda oynatmadan önce **ön tarama** (ürün boyu), canlıda **güvenilir erken öğrenme** (≥ 4 tam ürün, tutarlı boylar) |
| **22** | **Kişi sayımı (mağaza girişi)**: Giriş/Çıkış sayaçları, giriş yönünü tek dokunuşla çevirme, kamera konumu (tepeden/yandan), kişi kutuları ve G/Ç rozetleri, yan yana gruplarda mükerrer sayım yok (§4.10; Swift izleyici Python ile eşdeğer). Sayım türü kategorileri (bant üstü ürün, kişi; araç/hayvan/stok "yakında"); kişi sayımına uygun montaj listesi |
| 23 | Yüklenmedi (açılı çizginin alana uyması eklensin diye iptal edildi; içeriği 24'te) |
| **24** | **Kişi sayımı mevcut kullanıcıya da görünür**: kayıtlı profillere "Mağaza girişi" eklenir, profiller sayım türüne göre gruplu (bant üstü ürün / kişi), ana ekranda kişi sayımı ipucu kartı, Ayarlar → Hakkında'da sürüm ve derleme numarası. **Açılı sayım çizgisi alanla birlikte uzar** (alan büyütülünce/taşınınca çizgi kenardan kenara; Python ve web aynı) |
| **25** | **Personel rengi** (kişi sayımı, §4.10 eki): Ayarlar'da personelin gövdesine dokunarak üniforma rengi öğretilir (en çok 3); o renkteki kişinin geçişi Giriş/Çıkış'a eklenmez, "Personel geçişi: N" ayrı görünür, kutusu gri "P". Yaygın renk uyarısı, karanlık/duraklatılmış video geri bildirimi. Hareket desteği yalnızca tepeden kamerada (Python ile eşdeğer). Gerçek açı ölçümü (≥ %95) bekliyor |
| **26** | **Poz güvenlik alarmı tanınır** (eller yukarı, yerde yatan kişi; alarm bilgisayardaki web panelinde çalışır): sözleşmedeki `safety` yöntemindeki profil açılır ama bu cihazda çalışmaz ("Bu cihazda desteklenmiyor" uyarısı, kalkan simgesi, kalibrasyon denetimleri gizli). Kısmi `safety` bloğu varsayılanlarla okunur; bozuk tek bir profil kaydı artık bütün profil listesini silmez (okunabilenler korunur, ham veri yedeklenir) |

## 3. Yol haritası (F0) ve sözleşmeler

- **F0.1 iOS derleme:** ✅ Xcode 16.4 ve 26.3'te hatasız; sıkı concurrency 9 uyarı → 0. Kabul kriterleri (gerçek iPhone'da ROI, kalibrasyon akışı, ≥ 45 fps) **kullanıcı testi bekliyor**.
- **F0.2 Swift testleri:** ⏳ yapılmadı. Swift çekirdeği Python'a satır satır uyarlandı ve derleniyor, ama Swift'te otomatik test yok.
- **F0.3 Sözleşme doğrulaması:** ✅ `tools/validate_contracts.py`; eski CI `uuid`/`date-time` formatlarını hiç denetlemiyordu. 8 örnek, 23 olumsuz test (bozulmuş örnek doğru kuraldan reddediliyor mu), Python `Profile` ↔ şema gidiş-dönüş testi.
- **Genel kabul ölçütü eklendi** (`01-roadmap.md`): her ürün profili için sayım doğruluğu **≥ %98, hedef %99**; ölçüm sahadan ≥ 3 video × ≥ 200 ürün, `--truth` ile.

## 4. Sayım algoritmasında bulunan ve düzeltilen hatalar

Hepsi `03-algorithm.md`'de (bağlayıcı referans), Python'da ve Swift'te birlikte değişti; her biri için eski kodda kırmızı olan regresyon testi var.

| # | Hata | Etki (önce → sonra) | Bölüm |
|---|---|---|---|
| 1 | Ürün altındaki arka plan güncellemesi çok hızlıydı (0,05): yoğun akışta arka plan ürüne kayıyor, şerit tek lekeye dönüşüyordu | %76 dolulukta 60 üründen **26** → **60** (≤ %95 doluluğa kadar %100) | §2.4 |
| 2 | Birbirine değen ürünler kareden kareye bir ×2 bir ayrık görünüyor; her birleşmede yeni iz doğuyor, izler lekeden kopuyordu | 100 yumurtalık render videoda **110** → **100**; 4 farklı videoda **400/400** | §4.0, §4.5, §4.7 |
| 3 | Swift `.rounded()` 2,5'i 3'e, Python `round` 2'ye yuvarlıyordu | iPhone ile referans aynı durumda farklı sayıyordu → aynı | §4 |
| 4 | Swift her kaynağı 60 fps varsayıyordu (§7 ölçekleme yoktu) | 30 fps videoda/yavaş telefonda eşleştirme ve arka plan hızı yanlıştı → Python ile aynı | §5, §7 |

Doğrulama durumu: sentetik senaryolar (tek sıra, üç şerit, arka arkaya/yan yana bitişik, titreşen çiftler) **60/30/25 fps'te %100**; render videolar %100. Swift tarafı yalnızca derleme + kod incelemesiyle doğrulandı (bkz. F0.2).

## 5. Video ile test araçları

| Araç | Kullanım |
|---|---|
| `python -m bantvision.video video.mp4 --truth N` | Masaüstünde videodan sayım: otomatik kalibrasyon (arka plan, eşik, yön, tek ürün alanı), işaretli MP4, `ozet.json` (hata %), sözleşmeye uygun `profil.json`, `sayimlar.csv`. Yoğun bantta `--bg-range`, ayrı kalibrasyon videosu için `--profile`. |
| `python tools/make_test_video.py` | Sayısı bilinen test bandı videoları: `1_kalibrasyon.mp4` (boş bant + 8 yumurta), `2_test_100_yumurta.mp4` (%70 tek, %20 arka arkaya, %10 yan yana bitişik), `manifest.json`. Ekranda oynatıp telefonla çekmek ya da video moduna yüklemek için. |
| iPhone video modu (derleme 9) | Üst çubuk → film simgesi → video seç; boş bantla başlıyorsa arka planı ilk 1 sn'den öğrenir; sonunda "Doğru adet" → doğruluk %. Video sayımı canlı kayda karışmaz. |

Gerçek video denemesi: Pexels'ten 4 video indirildi (`data/videos/`, repoda değil). Hiçbiri sayım düzeneğine uygun değildi (eğik/yükleme ucundan bakış, hareketli kamera, kurgu). Ama video aracının eşik tahmininde bir zayıflığı ortaya çıkardılar (eşik 82–100 → 12, ardışık kare farkıyla).

Test sayısı: Python 30 test (çekirdek, video aracı, render), sözleşme 38 test; hepsi CI'da yeşil.

## 5b. Kalite kontrol A1 ve uçtan uca test (2026-10-02)

- **Enao incelemesi** (ekran görüntüleri): kalite kontrolleri bulutta eğitilen nesne tespiti modeline dayanıyor (Full mode: kadrajı dolduran üründe kusur; Small mode: ürünleri tek tek). Bizim klasik hat Small mode'a karşılık geliyor. Karar: önce **A — cihazda, bulutsuz** (`04-ios-app.md` §1c), sonra **B — bulutlu etiketleme ve model eğitimi**.
- **A1:** sekmeler; sayılan her ürünün kırpıntısı ve kartı (fotoğraf, Geçti/Kaldı, saat, kısa kimlik, güven %); profile özel kusur türleri; iyi/kusurlu örnek işaretleme; Vision feature print ile en yakın komşu kararı (eğitimsiz), yalnızca iyi örnekle anomali modu.
- **Uçtan uca UI testi** (`04-ios-app.md` §1d): simülatörde 28 yumurtalık klip Swift çekirdeğiyle sayılıyor; sonuç Python referansıyla aynı (**28/28**). Swift tarafı ilk kez çalıştırılarak doğrulandı. TestFlight yüklemesi bu teste bağlı.
- Test sırasında bulunanlar: CI'da video saniyede ~0,7 kare işleniyordu. Ölçüm: Debug derlemesi (optimizasyonsuz) ve GPU'suz sanal makine; test artık Release ile çalışıyor (çekirdek ~6 ms/kare). Ayrıca düz videolar için gereksiz kompozisyon kaldırıldı, ekran karesi küçültülerek üretiliyor, dar ekranda düğme yazılarının hecelenmesi giderildi, menüden açılan pencereler menü kapandıktan sonra açılıyor.

## 5c. Ağ kamerası ve uçtan uca RTSP testi (2026-10-02)

- Tek kamera, telefonda (çoklu kamera gerekirse web/edge'e taşınacak). Ayarlar → Görüntü kaynağı → Ağ kamerası; ayrıntı `04-ios-app.md` §1e.
- CI'da MediaMTX, test klibini Digest korumalı RTSP olarak yayınlar. Üç test: ağdan sayım (**28/28**), yanlış şifrede anlaşılır hata, video sayımı (**28/28**).
- Teşhis sırasında bulunanlar:
  - İmzasız simülatörde Keychain yazılamıyor (-34018): şifre oturum boyunca bellekte de tutuluyor; Keychain hatası kullanıcıya gösteriliyor.
  - Klip 1,5 sn boş bantla başlıyordu; yayına ≥ 1 sn geç katılınca boş bant öğrenmesi ürünlerle yapılıyor, sayım 28 → 2'ye düşüyordu (Python benzetimi). Klip 4 sn boş bantla başlıyor. **Sahada kural:** boş bant öğrenmesi bant gerçekten boşken.
  - **Gerçek hata:** QC kırpıntısının JPEG'i sayım kuyruğunda, ekranla ortak bağlamda üretiliyordu. Canlı kaynakta sayım saniyelerce duruyor, aradaki kareler atlanıyordu (5,7 sn boşluk, 10/28). Artık sayım kuyruğu yalnızca küçük bir bellek kopyası alıyor (en uzun boşluk 0,13 sn, çekirdek 39 → 2 ms). Telefon kamerasında da aynı risk vardı.

## 5d. Şerit tarama: bitişik torba/koli sayımı (2026-10-03)
- **Sorun:** bitişik/üst üste gelen un torbaları (TRASSIR ekran kaydı, 16 sn). Bant hiç boş görünmüyor: arka plan öğrenilemiyor, bitişik torbalar tek leke. Eski yöntem 11 (ROI'siz 76), kayıttaki TRASSIR sayacı 6; karelerden elle sayılan **7**.
- **Çözüm:** yeni sayım yöntemi `countMode = "linescan"` (algoritma §4.9). Çizgi çevresinde bant kayması ölçülür, çizgiden geçen satırlar "geçen mesafe" sinyaline eklenir, ek yeri/boşluk çukurlarından ürünler ayrılır. Boş bant gerekmez; ürün boyu, ürünün banttan açık/koyu oluşu ve akış yönü kendiliğinden bulunur. Ön sayım: numara ürün çizgiyi geçerken görünür.
- **Sonuç:** aynı videoda **7/7** (çizgi alanın %40–60'ında, iki işleme çözünürlüğünde). Sentetik: bitişik, üst üste binmiş, düzensiz aralıklı torbalar; açık bantta koyu, koyu bantta açık koliler; ekran kaydı (tekrarlanan kareler), duran ve hızlanan bant; dört yön, çokgen ROI — hepsi tam. Swift ile eşdeğerlik vektörü 24/24.
- **Bilinen sınır:** videonun ilk/son karesinde çizgiye yarım binen ürün ±1 sapabilir.
- **Kalibrasyon düzeltmesi:** video her baştan başladığında boş bant yeniden öğreniliyor ve ürünle başlayan videoda eşik 100'e kaçıyordu (sonra hiçbir şey sayılmıyordu). Artık otomatik öğrenme yalnızca arka plan görüntüsünü yeniler, **Kaydet edilen eşik sabit kalır**; bantta ürün varken "Boş bandı öğren" eşiği bozmaz, uyarır.
- Hazır profiller: un torbası ve yeni "Koli / kutu" şerit taramayla. iPhone kalibrasyonunda "Sayım yöntemi" ve "Ürün boyunu öğren"; web panelinde yöntem seçimi.

## 5e. Kişi sayımı: mağaza girişi, giriş/çıkış (2026-10-05)

Algoritma `03-algorithm.md` §4.10; sözleşmede `countMode: "detect"`, `detectClasses`, `detectConfidence`, `countAnchor`, olayda `count.direction` (in/out), Supabase `minute_stats.count_out`.

- **Tanıma:** web/Python YOLOX-S (Apache-2.0, ONNX Runtime; model ilk kullanımda indirilir, SHA-256 doğrulanır), iPhone Apple Vision insan dikdörtgeni. Görüntü saklanmaz; yalnızca sayılar.
- **İzleyici** (Python ↔ Swift eşdeğer):
  - Tek turda eşleştirme: silik tespiti olan kişinin izi yanındakinin güçlü tespitine atlamaz.
  - Parça (yarım gövde) kutu bastırma; uzun tabanlı hız; hızla büyüyen arama kapısı.
  - Çizgi yanının iki gözlemle teyidi ve boya göre tampon bant (titreme sayılmaz).
  - Alandan çıkan iz silinir.
- **Hareket desteği** (yalnızca tepeden kamerada): kameranın tam altındaki kişiyi hareket lekesi taşır, sayım yine gerçek tanımayla doğrulanınca yapılır.
  - Yaşam sınırı var; grup lekesi izi sürüklemez.
  - Yatık kamerada kapalı (kapı, ekran, gölge hareketi hayalet iz üretiyordu).
- **Doğrulama:**
  - Yan yana 2–3 kişilik gruplar, sentetik, kusurlu tanıma: mükerrer sayım 0.
  - Kör bölgeli tepeden simülasyon: %1,4 hata.
  - Gerçek videolar:
    - Tepeden mağaza girişi: 3 giriş + 3 çıkış, birebir ve zamanları doğru.
    - Yatık koridor: 9 giriş + 3 çıkış, 12 geçişin hepsi doğru, sahte olay 0. Kapıya kadar gidip dönen iki kişi giriş + çıkış sayıldı.
- **Personel rengi** (2026-10-06; main'e birleştirildi, TestFlight derleme 25):
  - Üniforma/yelek rengi kamera (web) ya da profil (iPhone) başına bir kez öğretilir (en çok 3 renk, isteğe bağlı); o renkteki kişilerin geçişi müşteri Giriş/Çıkış'a eklenmez, ayrı "Personel geçişi" sayılır. Renk yoksa davranış değişmez. Algoritma `03-algorithm.md` §4.10 eki.
  - Web: `staffIn`/`staffOut`, CSV'de `personel_giris`/`personel_cikis`; iPhone yalnızca ekranda gösterir (CSV/webhook değişmez). Personel geçişi olay olarak gönderilmez.
  - Python ↔ Swift eşdeğerliği `staff_parity.json` ile sınanır.
  - **Gerçek ölçüm BEKLİYOR:** kabul ölçütü her kamera açısında (tepeden, eğik ~45°, yandan) personel yakalama ≥ %95 ve yanlış hariç tutma ≤ %5; etiketli kayıtlar (açı başına ≥ 20 personel + ≥ 20 müşteri geçişi) kullanıcıdan gelmeli. Sonuçlar ölçülünce buraya yazılacak; şimdilik doğruluk iddiası yok.
  - **Ölçüm protokolü:**
    1. Her açı için bir kayıt; her gerçek geçiş elle etiketlenir: `VIDEO.staff.json` = `[{"t": saniye, "dir": "in"|"out", "staff": true|false}]`. Sınıf başına 20'den az etiket varsa araç ölçmez.
    2. Profil: web panelinde o kameranın canlı sayımında personel rengi öğretilip **Kaydet**'e basılır. Profil JSON'u ya `<ANALYZER_DATA_DIR>/live/camera_profiles.json` dosyasındaki kamera kaydıdır (`--camera` ile anahtar parçası seçilir) ya da oturumun `GET /api/v1/live/sessions/{id}` yanıtı (içindeki `profile`) olduğu gibi dosyaya kaydedilir.
    3. **Python/web yolu:** `python tools/eval_staff.py VIDEO --profile PROFİL.json --labels VIDEO.staff.json --angle tepeden` (isteğe bağlı `--every 2`: canlıdaki kare atlamayı taklit eder). Kaçan personel yakalamayı düşürür; kaçan müşteri ayrı "sayım kaçağı", eşlenmeyen tahminler personel/müşteri "fazla" olarak yazılır.
    4. **iPhone yolu:** aynı video iPhone uygulamasının video modunda, aynı renkler öğretilmiş kişi sayımı profiliyle oynatılır; bitince Giriş, Çıkış ve Personel geçişi sayaçları okunur ve etiketlerdeki toplamlarla karşılaştırılır (personel giriş+çıkış ≈ personel etiketleri; Giriş/Çıkış ≈ müşteri etiketleri). Eşdeğerlik testleri (`staff_parity.json`) iki tarafın aynı kararı verdiğini zaten sınar; bu adım cihazdaki görüntü yolunu (YUV → RGB, kutular) doğrular.
- **Kurulum dersi:** çizgi kişilerin tamamen geçtiği yere, yürüme alanının ortasına konmalı — kapı eşiğinde kişi durup kaybolduğundan geçiş tamamlanmaz (aynı videoda 8/4 ve yanlış olaylar).
- **Kullanıcı kararları:** yalnızca Giriş ve Çıkış (kapasite/doluluk yok); giriş yönü kullanıcı tarafından tek dokunuşla çevrilir.
- **Arayüz:**
  - iPhone: "Kişi sayımı → Mağaza girişi" profili, Giriş/Çıkış sayaçları, kamera konumu (tepeden/yandan), kişi kutuları ve "G3"/"Ç2" rozetleri, CSV'de giriş/çıkış sütunları.
  - Web paneli: "Kişi (mağaza girişi)" profili, kamera, giriş yönü, çizgi konumu; sonuçta Giriş/Çıkış ve iki çizgili grafik.
  - Video aracı: `--mode detect`, Türkçe bindirme.

## 5f. Poz güvenlik alarmı: eller yukarı, yerde yatan kişi (web + Telegram) (2026-10-07/08)

Algoritma `03-algorithm.md` §4.11; sözleşmede `countMode: "safety"` ve `safety` nesnesi (`02-contracts.md`); web tarafı `13-web-platform.md` "Güvenlik alarmı ve Bildirimler". Tasarım: `docs/superpowers/specs/2026-10-06-poz-guvenlik-design.md` (sonundaki "Değişiklikler (2026-10-07/08)" bölümü dahil). Kuyumcu gibi mağazalarda sessiz alarm: soygun sırasında "eller yukarı" ve düşme/bayılma sonrası yerde yatan kişi.

- **Ne var:**
  - Analiz sunucusu (yalnızca bilgisayar): kişi tanıma (YOLOX) + izleyici + poz (MoveNet SinglePose Thunder, Apache-2.0; ONNX'e GitHub Actions'ta çevrilir, GitHub sürümü `models-v1`den indirilir, SHA-256 doğrulanır) + kural durum makinesi. İki model de ortak indirme yardımcısıyla (zaman aşımlı, SHA-256) arka planda yüklenir; hata Türkçe gösterilir ve 60 sn sonra yeniden denenir.
  - Kurallar: eller yukarı varsayılan 3 sn (ayar 3–5), yerde yatma 10 sn (ayar 5–30). **Alan kısıtı yok:** kural karedeki herkese uygulanır (kullanıcı kararı, 2026-10-07). Eller yukarı eşikleri `0,20·s` (bilek) ve `0,30·s` (dirsek); gerçek bir kamera ölçümüyle gevşetildi, yanlış alarma etkisi ölçülecek. Alarmdan sonra 3 sn'lik kopma affı: tek olay tek alarm kaydı.
  - Alarm günlüğü (`alarms.json`, 7 gün); **olay resmi her zaman bu bilgisayarda 7 gün**; **olay kaydı (video): alarmdan 8 sn önce ve 4 sn sonra, en çok 10 kare/sn, bu bilgisayarda 7 gün, en çok 500 dosya, Telegram'a hiç gitmez**; Telegram bildirimi (bot anahtarı yalnızca `secrets.json`'da, çevrimdışı kuyruk, aynı kamera ve tür için 60 sn tekrar önleme; Telegram'a fotoğraf yalnızca kamerada "Olay resmini Telegram'a gönder" açıksa).
  - Telegram hataları: yanlış anahtar, bulunamayan sohbet ve gruptan atılmış bot hemen "Gönderilemedi" olur (24 saat "Gönderiliyor" kalmaz), iletiler Türkçe; ağ hataları 24 saate kadar yeniden denenir; son hata Bildirimler sayfasında görünür.
  - İzleme sağlığı: kamera kartı "Nöbette" yazısını yalnızca kamera gerçekten izlenirken gösterir (canlı, iki model hazır, işleme hatası yok, son 10 sn'de kare işlendi), aksi halde "Uyarı" ve nedeni. Bir güvenlik kamerası 60 sn'den uzun süre izlenmezse alarm şeridinde sarı uyarı çıkar.
  - Yeniden başlatma: güvenlik kameraları `watch.json`'a yazılır ve analiz sunucusu yeniden başlayınca kendiliğinden yeniden izlemeye alınır (kayıt cihazı kameraları bağlanana kadar yeniden dener); önceki çalışmadan "devam ediyor" kalmış alarmlar açılışta kapatılır. Windows `watch.json`'u açılışta kilitlerse (virüs tarayıcısı, yedekleme) izlenen kameralar kaybolmaz: dosya ezilmez, değişiklikler bellekte tutulur ve dosya okunabilince (5 sn'de bir, en çok 30 dakika) liste birleştirilip kameralar kendiliğinden açılır.
  - Web paneli:
    - Güvenlik kategorisi ve "Kuyumcu güvenliği" profili; Ayarla'da yalnızca kurallar (alan düzenleyicisi yok); iskeletli akış; "İzleniyor" yan paneli (neden, süren durumlar, son alarmlar, kamera karesiyle Deneme alarmı).
    - Her sayfada yapışkan alarm şeridi (izlenmeyen kamera ve bağlantı kopması uyarıları).
    - **Alarm penceresi:** tarayıcının yerel modal penceresidir, açık başka bir pencerenin (ör. "Canlı sayımı başlat") üstünde açılır; Esc yalnızca onu küçültür ("Gördüm" sayılmaz, alttaki pencere kapanmaz). Yeni alarmda kendiliğinden açılır, ihlal anının kaydını oynatır, zaman çizelgesi; Gördüm / Kamerayı aç / Yanlış alarm / Küçült. Kayıt durumu görünür: "Kayıt hazırlanıyor…" (kayıt yazılana dek) ya da "Kayıt alınamadı; olay resmi gösteriliyor."
    - **Alarmlar sayfası:** geçmiş, süzgeçler, sayılar, aynı kayıt penceresi.
    - Bildirimler sayfası: Telegram kurulumu, Anahtarı sil, son gönderim hatası, deneme mesajı ve deneme alarmı; "Bu tarayıcıda": masaüstü bildirimi ve sesli uyarı (ikisi de varsayılan kapalı); sekme başlığı alarm varken yanıp söner.
  - iPhone: profili tanır, çalıştırmaz ("Yalnızca bilgisayarda").
- **Kullanıcı kararları (2026-10-06/07/08):** poz modeli MoveNet Thunder (RTMPose/RTMO ağırlık lisansı belirsiz olduğundan elendi); ilk etapta yalnızca Telegram (WhatsApp ileride); Telegram'a resim varsayılan kapalı; iPhone kapsam dışı; yanlış alarm hedefi kamera başına 8 saatte en fazla 1. Sonradan (2026-10-07): **alan kısıtı yok**; **daha profesyonel alarm: alarm penceresi ve ihlal anının kaydı ekranda**; ses isteğe bağlı (varsayılan kapalı, alarm sessiz kalır); eller yukarı eşikleri gerçek kamera ölçümüyle ayarlandı.
- **Doğrulama durumu:** birim ve entegrasyon testleri (kurallar, çözümleyici, model indirme, alarm günlüğü, olay kaydı, Telegram sahte sunucusu, izleme sağlığı, yeniden başlatmada geri yükleme, uç noktalar) ve panel uçtan uca testleri kuralların ve altyapının tasarıma uygun çalıştığını sınar. Gerçek kamerada doğruluğu **sınamaz**. Olay kaydının VP8 WebM kodlaması Linux CI'da (atlanmadan) ve Windows'ta doğrulandı. Tek bir gerçek kameranın karelerinden yalnızca eller yukarı eşikleri ayarlandı (2026-10-07); bu bir kabul ölçümü değildir.
- **Gerçek ölçüm BEKLİYOR; şimdilik doğruluk iddiası yok.** Kabul ölçütü: olayların ≥ %95'i kural süresi + 2 sn içinde alarm verir; normal harekette kamera başına 8 saatte ≤ 1 yanlış alarm; sayım yapan kameralarla birlikte güvenlik oturumu ≥ 5 kare/sn. Ölçüm için kullanıcıdan gerekenler:
  - ≥ 20 eller yukarı olayı (farklı kişiler; önden, yandan, tezgâh arkası);
  - ≥ 20 yerde yatma olayı (farklı yönler);
  - **her kamera için** ≥ 1 saat normal hareket (yürüme, eğilme, çömelme, oturma, rafa uzanma);
  - hepsi ofisteki bullet/dome kameradan (eğik bakış) alınmış kayıtlar; hangi kaydın hangi kameraya ait olduğu bilinmeli.
- **Ölçüm protokolü:**
  1. **Kamera başına kayıt.** Her kamera için ayrı kayıt(lar); olay kayıtları ve normal hareket kayıtları kameraya göre ayrılır. Yanlış alarm kamera başına sınanır.
  2. **Etiket.** Her kayıtta olayın başladığı an elle etiketlenir: `VIDEO.pose.json` = `[{"t": saniye, "type": "hands_up"|"lying", "end": saniye (isteğe bağlı)}]`. `end` olayın bittiği andır; yazılırsa o olayın içinde gelen ikinci alarm "tekrar" sayılır, yanlış alarm olmaz (yazılmazsa olay `t + süre + 2 + 10` sn kabul edilir). Tür başına 20'den az etiket varsa ya da bir kameranın videosu 1 saatten kısaysa (tek video kipinde: video 1 saatten kısaysa) araç "KALDI" der (kapı kalır).
  3. **Profil.** Web panelinde o kameranın güvenlik oturumunda ayarlar yapılıp **Kaydet**'e basılır. Profil JSON'u ya `<ANALYZER_DATA_DIR>/live/camera_profiles.json` içindeki kamera kaydıdır ya da oturumun `GET /api/v1/live/sessions/{id}` yanıtı (içindeki `profile`) olduğu gibi dosyaya kaydedilir.
  4. **Manifest.** Birden çok kayıt ve kamera için bir `MANIFEST.json` yazılır: `[{"video": "yol", "labels": "yol", "profile": "yol", "camera": "ad"}]` (yollar manifest dosyasının klasörüne göre; `camera` yazılmazsa video dosya adı kamera sayılır, aynı kameranın kayıtları aynı adı taşımalıdır).
  5. **Çalıştırma.** `python tools/eval_pose.py --manifest MANIFEST.json` (tek video için `python tools/eval_pose.py VIDEO --profile PROFİL.json --labels VIDEO.pose.json`; isteğe bağlı `--every 2`: canlıdaki kare atlamayı taklit eder). Yakalama tüm kayıtlardan tür başına toplanır; yanlış alarm kamera başına toplanıp 8 saate çevrilir ve kamera tablosu yazılır; "tekrar" ayrı satırdır. Çıkış kodu yalnızca ölçütler tutuyorsa 0: her tür ≥ %95 (≥ 20 etiket) ve **her** kamera en az 1 saat videoya sahip ve ≤ 1 / 8 saat. 1 saatten kısa bir kamera, toplam süre yetse bile, sonucu KALDI yapar ("yetersiz süre: <kamera> <dk> dk (en az 60 dk)"); süreler kameralar arasında toplanmaz.
  6. **Kare hızı denetimi.** Ölçüm sırasında sayım yapan kameralar da çalışırken güvenlik oturumunun `fps` değeri (canlı sayfa ya da `GET /api/v1/live/sessions`) okunur; hedef ≥ 5 kare/sn. Altındaysa doğruluk ölçümü `--every N` ile o kare hızını taklit ederek de yapılır.
  7. Sonuçlar ölçülünce buraya yazılacak. Kayıtlar kullanıcınındır; public repoya konmaz.
- **Bilinen risk:** MoveNet ağırlıklı olarak fitness/dans/yoga videolarıyla eğitildi; eğik ve uzak güvenlik kamerasında doğruluk ölçülene kadar bilinmiyor. Eller yukarı eşikleri tek bir kameranın ölçümüyle gevşetildi ve alan kısıtı kaldırıldı: ikisinin yanlış alarma etkisi de ölçülene kadar bilinmiyor. Tutmazsa eşikler yalnızca ölçümle ayarlanır, o da yetmezse model seçimi yeniden değerlendirilir.
- **Sınırlar:**
  - Analiz sunucusunun çalışıyor olması gerekir. Windows oturumu açılınca kendiliğinden başlatma **sağlanmıyor**: bilgisayar yeniden başlayınca sunucu elle başlatılır (başlayınca güvenlik kameraları kendiliğinden yeniden izlemeye alınır).
  - Poz ve kişi tanıma modelleri ilk kullanımda internetten indirilir (indirilemezse alarm olmaz, kart "Uyarı" der ve neden yan panelde yazar). Adres çözümleme (DNS) indirme zaman aşımına dahil değildir: bu aşamada takılırsa model "yükleniyor" kalır.
  - Alarm şeridi ve penceresi panel açıkken görünür (Telegram kapalıysa tek kanal). Masaüstü bildirimi yalnızca analiz bilgisayarında `http://localhost` ya da https adresinde çalışır; başka bilgisayardan düz http ile açılan panelde açılmaz.
  - Sesli uyarı isteğe bağlıdır (varsayılan kapalı); tarayıcı, sayfaya bir kez tıklanana kadar sesi engelleyebilir ("Dene" düğmesi sesi açar).
  - İzleyici olayın ortasında aynı kişiye yeni kimlik verirse tek olay için ikinci bir alarm kaydı doğabilir (Telegram'a 60 sn tekrar önleme içinde gitmez).
  - Son Telegram gönderim hatası bellekte tutulur (sunucu yeniden başlayınca sıfırlanır).
  - Supabase'e olay gönderimi yok; video yükleme (analiz) formunda güvenlik yok; aynı kamerada aynı anda sayım ve güvenlik yok.

## 6. Araştırma ve tasarım notları

- **Enao Vision** (iPhone ile kalite kontrol, rakip): `11-market-notes-enao.md`. Saha ipuçları (montaj, yumurta için yandan ışık, ≥ 10 px kuralı, gölge modu), fiyatlar, ürün fikirleri.
- **"Örnekle öğret" (Teach)**: `09-ml-roadmap.md` §4b. Apple Vision `VNGenerateImageFeaturePrint` ile eğitimsiz iyi/kötü sınıflandırma; arayüz Enao'daki Teach/Overview düzenine benzer.
- **Kamera markaları** (Dahua, Hikvision, Axis, Pelco, TRASSIR, Vivotek, Karel, Milesight, Mobotix): `10-field-setup.md` §3b. Birincil yol ONVIF ile akış adresini otomatik almak; marka bazında tipik RTSP adresleri, akıllı kodek adları, uygunluk ön testi.

## 7. Açık konular

- **Telefonda doğrulama bekleniyor:** derleme 9 ile test videoları (kalibrasyon + 100 yumurta) — uygulama kaç sayıyor? F0.1 kabul kriterleri (fps ≥ 45).
- **Swift otomatik testleri yok (F0.2):** Python ile aynı sentetik senaryoları Swift'te koşturan test hedefi gerekli.
- **Gerçek saha videosu yok:** %98–99 hedefi ancak gerçek hattan, sabit kamerayla çekilmiş videolarla kanıtlanabilir.
- Swift `ProductProfile` hâlâ sözleşmenin alt kümesi (`source`, `qc`, `scale`, `io` yok; F1.1).
- Yerel ortam notu: Windows'ta Python venv `%TEMP%\claude\venv-bv` altında; repoda `.venv` yok. `pip install -e ".[dev]"` ile kurulabilir.

## 7b. Bilinen sınırlar (A1)
- Örnekle öğretme, ürünün **genel görünümüne** bakar; çok küçük kusurlar (kılcal çatlak, tek saç teli) genel benzerlikte kaybolabilir. Bunlar için ölçüme dayalı kontrol (A2) ya da kutu etiketli model (B) gerekir.
- Anomali eşiği (iyilerin tipik uzaklığının 1,8 katı) sahada ayarlanması gereken bir başlangıç değeri.
- Kartlar ve istatistikler cihazda, son 50 ürün; panele gönderim F1.1/F3 ile.

## 8. Sırada

1. Derleme 13'ün telefonda denenmesi: gerçek kayıt cihazı (TRASSIR: Ayarlar → Web sunucusu (SDK) açık olmalı), video oynatıcı, kartlar, öğretme.
2. **Web platformu** (`13-web-platform.md`): W1 video analiz sunucusu ✅ → W2 web paneli (video analizi sayfası, BandVision kimliği) → W3 canlı hat (yerel Supabase) → W4 barındırma, NOK galerisi. **Canlı sayım (kamera / kayıt cihazı) panelde hazır** (2026-10-06, `13-web-platform.md` "Canlı sayım"): Kameralar sayfası, canlı akış, alan/çizgi düzenleyici, Giriş/Çıkış. Kalan: QC (OK/NOK) kartları ve öğretme web'de yok.
2. **A2:** Python'daki ölçüme dayalı QC'nin (boy, en-boy, kırık/ezik, leke, boy sınıfı) iPhone'a aktarılması (F4); kusur nedeni kartlarda.
3. **Edge kutusu (F2):** RTSP/ONVIF kamera kaynağı, yeniden bağlanma, outbox, tarayıcıda önizleme, Docker. Gerçek bir kamerayla (IP + marka) geliştirmek en sağlıklısı.
4. F0.2 Swift testleri, F1.1 sözleşme v1 + outbox, F1.2 ekranda iz kimlikleri.
5. **Poz güvenlik ölçümü** (§5f): ofis bullet/dome kameralarından, kamera başına etiketli kayıtlar (toplam ≥ 20 eller yukarı, ≥ 20 yerde yatma; her kamera için ≥ 1 saat normal hareket) → `tools/eval_pose.py --manifest`; ayrıca kare hızı denetimi (hedef ≥ 5 kare/sn).
