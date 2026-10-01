# Bant Sayaç

iPhone kamerasıyla banttan geçen ürünleri sayan iOS uygulaması. Model eğitimi gerekmez; her ürün tipi (yumurta, un torbası, genel) için sahada **kalibre edilen profillerle** çalışır. Tüm işleme cihaz üzerinde yapılır, internet gerekmez.

## Kurulum

Gereksinimler: Xcode 15+, iOS 17+ iPhone (iPhone 12 ve üstü önerilir).

**XcodeGen ile (önerilen)**
```bash
brew install xcodegen
cd BantSayac
xcodegen
open BantSayac.xcodeproj
```
Signing & Capabilities sekmesinden Team'i seç, iPhone'a çalıştır.

**Elle**: Xcode → New Project → iOS App (SwiftUI, adı `BantSayac`), oluşan `ContentView.swift` ve `BantSayacApp.swift` dosyalarını sil, `BantSayac/` altındaki klasörleri projeye sürükle. Info'ya `NSCameraUsageDescription` ekle, deployment target 17.0, yalnızca Portrait.

> Hız için sahada **Release** yapılandırmasıyla çalıştır (Edit Scheme → Run → Build Configuration → Release). Debug'da görüntü işleme belirgin şekilde yavaştır.

## Mimari

```
Kamera (720p/60fps, portreye döndürülmüş, kısa pozlama)
  → GrayFrame        Y düzleminden kutu-ortalama ile küçültme (160/240/360 px genişlik)
  → BackgroundSegmenter  arka plan farkı → eşik → açma/kapama → bağlı bileşenler
  → alan filtresi + çarpan  (bitişik ürün: leke alanı / tek ürün alanı)
  → BlobTracker      konum + sabit hız tahmini, açgözlü eşleştirme
  → çizgi geçişi     yalnızca çizgiden ÖNCE doğan izler sayılır (çift sayım koruması)
  → CountLogger      dakikalık özet, adet/dk, CSV, webhook
```

| Klasör | İçerik |
|---|---|
| `Camera/` | AVFoundation oturumu, format/fps seçimi, pozlama, fener, odak |
| `Vision/` | Görüntü işleme hattı (UI'dan bağımsız, saf Swift) |
| `Core/` | Profil modeli ve deposu, ayarlar, kayıt/webhook |
| `UI/` | SwiftUI ekranları, sürüklenebilir ROI/çizgi bindirmesi |

## Saha kurulumu

1. iPhone'u bandın **tam tepesine**, kamera aşağı bakacak şekilde sabitle. Montajı bandın şasesine değil ayrı bir stand/kola bağla; bant titreşimi sayımı bozar.
2. Ürün kadrajda en az 4–5 kare görünecek yükseklikte olmalı. Tipik: 0,8–1,5 m.
3. Işık sabit olsun. Fener yeterli değilse ya da uzun vardiya varsa harici LED/halka ışık kullan. Gün ışığı alan pencere kenarlarından kaçın.
4. Bant hızlıysa Ayarlar → Pozlama 1/1000 s (gerekirse 1/2000 s). Odağı kilitle.
5. Telefonu şarja bağla. Kılıfı çıkarmak ısınmayı azaltır.

## Kalibrasyon (her ürün profili için bir kez)

1. **Kalibre** → sarı alanı (ROI) bandın üzerine, turuncu çizgiyi ortaya sürükle. Akış yönünü seç.
2. **Boş bandı öğren**: bant boşken bas, ~1 sn. Gürültü ölçülür ve eşik otomatik ayarlanır.
3. **Örnek geçir**: 8 ürünü **tek tek, aralıklı** geçir. Tek ürünün alanı öğrenilir; bitişik ürünler bu alana göre ayrılır.
4. Yeşil maskeyi kontrol et: ürün tam dolu görünmeli, bant boş görünmeli. Gerekirse eşiği oynat. **Kaydet**.

## Ürüne özel ipuçları

**Yumurta** – Beyaz yumurta açık renkli bantta zayıf kontrast verir; koyu bant/arka plan ya da yandan ışık çok fark eder. Çok şeritli hatlarda ROI'yi tüm şeritleri kapsayacak şekilde aç; şerit ayrımı gerekmez. Bitişik ayırma açık, kapama 0.

**Un torbası** – Büyük ve dokulu ürün; "Hızlı (160)" çözünürlük yeterli. Torba yüzeyi parçalı görünürse kapamayı 2–3'e çıkar. Torbalar üst üste biniyorsa maks. çarpanı 2–3 tut.

**Genel** – Ürün banttan belirgin şekilde farklı renk/parlaklıktaysa doğrudan çalışır. Bant ile aynı renkteki ürünlerde (ör. siyah ürün, siyah bant) ışık açısıyla gölge/yansıma kontrastı yarat.

## Entegrasyon

Ayarlar'a bir webhook URL'si girilirse olaylar 5 sn'de bir POST edilir; ağ yoksa birikir (5000 olaya kadar) ve sonra gönderilir:

```json
{
  "device": "IDFV-UUID",
  "line": "Hat-1",
  "events": [
    { "ts": "2026-10-01T09:15:02Z", "delta": 1, "total": 1532, "profile": "Yumurta" }
  ]
}
```

n8n Webhook düğümü, Supabase Edge Function ya da kendi FastAPI uç noktan doğrudan alabilir. Dakikalık özet Ayarlar → Rapor'dan CSV olarak paylaşılır (Excel için `;` ayraçlı).

## Bilinen sınırlar

- Arka plan farkına dayanır: kamera sabit, ışık stabil olmalı. Kamera oynarsa "Boş bandı öğren"i tekrarla.
- Yoğun, iç içe yığılmış ürünlerde (dökme yumurta, üst üste torba) alan oranı yaklaşık sonuç verir.
- Banttan geri giden ürün sayılmaz; çizgiyi ileri yönde geçen her iz bir kez sayılır.

## Yol haritası

1. Sahada doğruluk testi: elle sayımla 3–4 vardiya karşılaştırma.
2. `Detector` protokolü ile CoreML dedektörü (YOLO11n) takılabilir hale getirme; sahada kaydedilen karelerle ürüne özel ince ayar. Yoğun/üst üste senaryolar için.
3. Duruş tespiti ve OEE (kullanılabilirlik/performans).
4. QR ile cihaz-hat eşleme, bulut panel (VMS Analitik altyapısı).
5. ESP32 + optokuplör ile 24V darbe çıkışı, OPC-UA köprüsü.
