# 11 — Pazar notları: Enao Vision

Kaynak: enaovision.com/tr (ana sayfa, ürün, fiyatlandırma, montaj/aydınlatma/iPhone modeli blog yazıları), 2026-10-01'de incelendi.
Enao Vision (Almanya), iPhone'u yapay zekâ destekli kalite kontrol + üretim izleme cihazına çeviren bir SaaS. Bizim "düşük bütçe" senaryomuzun (iPhone + lamba + kıskaç) doğrudan rakibi.
Bu dosya bir özet ve fikir listesidir. Karar değildir, yol haritasına giren maddeler ayrıca `01-roadmap.md`'ye işlenir.

## 1. Ne sunuyorlar (kısa)

| Konu | Enao | BantVision karşılığı |
|---|---|---|
| Yöntem | Cihaz üstü ML (Neural Engine), "iyi/kötü örnek işaretle → dakikalar içinde öğrenir" | Klasik görüntü işleme önce, ML F7'de |
| Modlar | Hat (otomatik tetik), manuel istasyon (ürün girince algıla), elde (deklanşör) | Yalnızca hat modu |
| Kurulum vaadi | Kutudan muayeneye < 1 saat, "ürünün iki fotoğrafı" | Boş bant + 8 örnek kalibrasyonu (~1 dk) |
| Hız | Tek iPhone ile ≤ 600 ürün/dk iddiası; blogda üst sınır olarak ~500/dk ve < 1 ms pozlama gerektiren işler dışarıda bırakılıyor | Hedef ölçülmedi (F0.1: iPhone 12'de ≥ 45 fps) |
| Üretim izleme | Sayım, OEE, mikro duruşlar, **duruş anında hattın fotoğrafı**, vardiya özeti | `state` olayı + dashboard (F3) |
| İzlenebilirlik | **Her ürünün** zaman damgalı fotoğrafı, barkodla aranabilir | Yalnızca NOK görseli (F4.4) |
| Kalite kuralları | Kullanıcı tanımlı mantık (ör. "5'ten fazla A tipi hata = ret", şiddet seviyeleri) | Sabit `reasons` listesi, her neden tek başına NOK |
| Kod okuma | Barkod, QR, basılı metin (lot, SKT) | F4.3 |
| Çıkış | 24V veya OPC-UA, < 50 ms; "Bridge" donanımı iPhone 15+ USB-C ile, 2 izole çıkış | ESP32 I/O köprüsü, ağ üzerinden (F5) |
| Entegrasyon | Webhook, API, Excel, Power BI, Grafana, Snowflake, MCP; sohbet ajanı ("A hattında son 1 saatte en büyük sorun?") | Supabase + n8n (F3) |
| Uyarılar | SMS/anlık bildirim (ör. makine > 5 dk durdu, hurda eşiği aşıldı) | n8n akışları (F3.3) |
| Cihaz yönetimi | QR ile cihazı hatta bağlama, iPhone'u hatlar arasında taşıma | F1.4 QR eşleme |

**Fiyat (cihaz başına/ay):** Basic €0 (1 cihaz, ayda 10.000 ürün, sayım + duruş), Essential €199 (sınırsız, barkod/OCR, pano, SMS, entegrasyonlar), Pro €349 (özel hata tespiti, kalite kuralları, ürün başına görüntü, OPC-UA/24V). Türkiye pazarında konumlandırma için referans.

## 2. Sahadan alınacak pratik bilgiler → `10-field-setup.md` adayları

- **Montaj.** Tekrarlanabilir konum, doğruluğun "sessiz" bozulma nedenlerinin başında geliyor (titreşim/kayma haftalar içinde yanlış karar üretir).
  - Başlangıç: mafsallı kol + kıskaç (~40 €, ör. SmallRig Magic Arm), aylarca dayanıyor.
  - Kalıcı: bakım ekibinin elindeki alüminyum sigma profil + telefon tutucu.
  - Hatlar arası taşıma: hızlı bağlantılı bisiklet/motosiklet tutucuları (SP Connect). Telefon her takışta aynı yere oturuyor, **yeniden kalibrasyon gerekmiyor**.
  - Çok vardiyalı işte darbe sönümleyici pedli rijit kıskaç, mıknatıslı tutucudan iyi.
- **Aydınlatma.**
  - Standart yüzeyde ~80 €'luk 30 cm LED halka ışık yeterli; halka ışık kıskaç koluna takılabiliyor.
  - Göçük, kabarma, kalıntı ile **beyaz/parlak yüzeylerde** tepeden ışık hatayı "yıkıyor". Kameraya ~90° açıyla, yüzeyi yalayan yan spot gölge oluşturup hatayı görünür kılıyor. **Yumurta beyaz ve parlak olduğu için bu bizim için doğrudan geçerli** (çatlak/kir tespiti, F4.2).
  - Parlaklıktan çok **tutarlılık** önemli: ışık telefonla aynı hattan beslensin, tüm istasyonlarda aynı renk sıcaklığı olsun (ör. 4000K). Farklı ışıkta öğrenilen model başka ışıkta aynı başarıyı vermiyor.
- **Çözünürlük kuralı.** Aranan hata görüntüde **en az ~10 piksel** kaplamalı. Kaplamıyorsa kamerayı yaklaştır ya da makro (Pro) kullan. Bizde `processingWidth=240` sayım için yeterli olsa da leke/çatlak QC'si tam çözünürlüklü kırpıntıda yapılmalı (`03-algorithm.md` §6.3 ile uyumlu).
- **Cihaz seçimi.** iPhone 12 kararlı alt sınır, eski modeller hızlı hatlarda ısınıyor. iPhone 15+ USB-C ile **şarj + kablolu Ethernet** (Wi-Fi'si kötü salonlar için) ve kablolu I/O. iPad'in sahada ek faydası yok. Pro yalnızca geniş açı (büyük ürün) veya makro (çok küçük hata) için.
- **Ortam.** Tozlu ortamda lensi haftalık sil, telefonu sıcak bölgeden uzak tut. Enao pozlama histogramını izleyip kayma olunca uyarı veriyor.
- **Devreye alma.** Bir haftalık pilot: 1. gün donanım, 2. gün kurulum, 3. gün **gölge modu** (sistem kararını operatörle karşılaştır, fiziksel çıkış yok), 4. gün sistem birincil + operatör ikinci görüş, 5. gün PLC/webhook. Bizde `io.eject.enabled=false` zaten gölge moduna karşılık geliyor; bunu kabul testine (`10-field-setup.md` §6) yöntem olarak eklemek mantıklı.

## 3. Ürün fikirleri (öneri, öncelik sırasıyla)

1. **Ekrandan oynatılan test bandı.** Enao'nun canlı demosu ekranda bir konveyör videosu oynatıp telefonu ona tutturuyor. Bizde bunun karşılığı: `sim.py` senaryolarını tarayıcıda oynatan, **bilinen toplam sayıyı** gösteren bir sayfa. Bununla iPhone sayımı bant olmadan masa başında doğrulanır (F0.1 kabulü ve satış demosu). Ekran yenileme/titreme ve moiré gerçek banttan farklıdır; yalnızca uçtan uca duman testi olarak kullanılmalı.
2. **Işık kayması uyarısı.** Heartbeat'e ROI ortalama parlaklığı ve kalibrasyon anına göre sapma eklenir; eşik aşılınca "yeniden kalibre et" uyarısı gönderilir. Sözleşme değişikliği gerektirir (`event.schema.json` → `heartbeat`).
3. **Duruş anı fotoğrafı.** `state` olayında `running=false` olduğunda düşük çözünürlüklü bir kare (`imageRef`). Sözleşme değişikliği gerektirir.
4. **Kalite kuralı motoru.** `reasons` + sayılar + şiddet üzerinden basit kural ifadesi (ör. `spots>=2 or area_low`). F4 sonrası.
5. **Manuel istasyon modu.** Ürün kadraja girip durunca tek muayene; konveyör gerektirmez. Mevcut çekirdekle "hareket durdu → en iyi kare" mantığıyla yapılabilir.
6. **Hatlar arası taşıma.** Profil cihaza değil **hatta** bağlansın: QR ile eşlenince hattın profili backend'den insin (F1.4/F6 tasarımına not).
7. **Kablolu I/O seçeneği.** iPhone 15+ için USB-C üzerinden I/O, ESP32 Wi-Fi gecikmesine alternatif (F5 değerlendirmesi).
8. **Doğal dille soru sorma.** Supabase verisi üzerinde Claude + MCP ile "dün gece vardiyasında neden düştük?" türü sorular (F3 sonrası, düşük öncelik).

## 4. Konumlandırma notu

Enao'nun güçlü yanı, ML ile "örnek göster, öğrensin" deneyimi ve hazır SaaS. BantVision'ın ayrışabileceği noktalar:
- Mevcut **IP/AHD/CCTV kameraları** kullanma (edge kutusu). Enao yalnızca iPhone.
- Yerel/çevrimdışı çalışma ve veri sahipliği (Supabase self-host mümkün).
- TRASSIR gibi bölgede yaygın VMS'lerle entegrasyon (F8).
- Türkçe saha desteği ve yerel fiyatlandırma.
