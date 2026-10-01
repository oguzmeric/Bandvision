# 01 — Yol Haritası, Görevler, Kabul Kriterleri

Fazlar sırayla yapılır. Her görev bağımsız bir PR olacak büyüklüktedir. `[ ]` kutularını PR'da işaretle.

---

## F0 — Temel (repo, sözleşmeler, iOS derleme)

**F0.1 iOS kodunu derle ve düzelt**
- `apps/ios` altında `xcodegen` ile projeyi üret, Xcode 15/16'da derle, derleme hatalarını ve concurrency uyarılarını gider.
- [ ] Release yapılandırmasında gerçek iPhone'da açılıyor, kamera görüntüsü ve sarı ROI görünüyor
- [ ] Kalibrasyon akışı (boş bant → 8 örnek → kaydet) uçtan uca çalışıyor
- [ ] iPhone 12'de 240 px işleme genişliğinde ≥ 45 fps

**F0.2 Swift çekirdeği için birim testleri ve eşdeğerlik testi**
- `Vision/` dosyalarını ayrı bir test hedefinde test et (UI bağımsız).
- `tools/gen_vectors.py` ile üretilen sentetik kare dizilerini (PNG) Swift testinde okuyup çalıştır.
- [ ] 4 sentetik senaryoda Swift ve Python aynı toplam sayıyı veriyor (bkz. `services/edge/tests/test_synthetic.py`)

**F0.3 Sözleşme doğrulama**
- [x] `contracts/*.schema.json` için örnek JSON'lar `contracts/examples/` altında, CI'da şema doğrulaması (Python `jsonschema`)

---

## F1 — iOS v1.1

**F1.1 Olay sözleşmesi v1'e geçiş**
- `CountLogger` webhook formatını `bantvision.batch.v1`'e çevir (`docs/02-contracts.md` §3). Her olaya `event_id` (UUID) ver.
- Outbox'ı bellekten kalıcı depoya taşı (SQLite ya da JSON-lines dosyası), uygulama kapanınca olay kaybolmasın.
- 60 sn'de bir `heartbeat` olayı.
- [ ] Uçak modunda 10 dk sayım → ağ açılınca tüm olaylar bir kez ve sırayla ulaşıyor (backend'de çift kayıt yok)

**F1.2 Ekranda iz kimlikleri**
- Her izin yanında kısa onaltılık kimlik (ör. `3F2A`), sayılmış izler farklı renkte.
- [ ] Görsel kontrol: iz kimliği ürün kadrajdan çıkana kadar değişmiyor

**F1.3 Veri toplama modu**
- `docs/09-ml-roadmap.md` §2'deki biçimde kare + YOLO etiketi kaydı, zip olarak paylaşma.
- [ ] 10 dk modda çalıştırma → zip açılınca `images/` ve `labels/` eşleşiyor, etiketler görselle örtüşüyor (`tools/check_dataset.py`)

**F1.4 Cihaz kaydı**
- İlk açılışta QR okutarak cihazı bir hatta bağlama (`docs/02-contracts.md` §4). Cihaz anahtarı Keychain'de.
- [ ] Kayıtlı cihaz olayları backend'de doğru hatta görünüyor

---

## F2 — Edge servisi MVP

**F2.1 Tek kamera RTSP hattı**
- `services/edge` altında FastAPI servisi; `FrameSource` (RTSP, yeniden bağlanma + üstel bekleme), çekirdek, outbox, gönderici.
- [ ] Bir IP kameradan 25 fps alt akışta 8 saat kesintisiz çalışma; bağlantı kopup gelince otomatik devam
- [ ] Python çekirdeği sentetik testleri geçiyor

**F2.2 Yerel API + önizleme**
- `docs/05-edge-service.md` §4'teki uç noktalar; overlay çizilmiş MJPEG önizleme.
- [ ] Tarayıcıdan `/cameras/{id}/preview` açılınca ROI, çizgi, lekeler ve iz kimlikleri görünüyor

**F2.3 Docker paketleme**
- `docker compose up` ile çalışma; Intel N100'de VAAPI donanım çözme (varsa).
- [ ] Temiz bir Ubuntu 24.04'te README'deki 3 komutla ayağa kalkıyor

---

## F3 — Backend + dashboard + uyarılar

**F3.1 Supabase şeması ve ingest**
- `supabase/migrations/0001_init.sql` uygula; `ingest` Edge Function (TypeScript), cihaz anahtarı doğrulama, idempotent ekleme, dakikalık özet.
- [ ] Aynı batch iki kez gönderilince sayılar değişmiyor
- [ ] 10.000 olay/dk yükte ingest p95 < 500 ms

**F3.2 Dashboard**
- `apps/dashboard` (Next.js 15). Sayfalar `docs/06-backend-dashboard.md` §3.
- [ ] Hat sayfası canlı güncelleniyor (Supabase Realtime), dakikalık grafik, günlük toplam, OK/NOK oranı

**F3.3 n8n uyarıları**
- `n8n/README.md`'deki 4 akış.
- [ ] Bant 5 dk durunca e-posta/Telegram mesajı geliyor; cihaz 2 dk sessiz kalınca "çevrimdışı" uyarısı

---

## F4 — Kalite kontrol aşama 1 (iOS + edge)

**F4.1 Geometrik muayene** (alan, en-boy, düzgünlük/solidity, eğiklik) — `03-algorithm.md` §6.2
**F4.2 Leke/kir tespiti** — §6.3
**F4.3 Barkod / metin (lot, SKT)** — §6.4
**F4.4 NOK görsel kaydı ve gönderimi** — tam çözünürlüklü kırpıntı, Supabase Storage
**F4.5 Boy sınıflandırma (yumurta)** — mm/piksel kalibrasyonu, sınıf sınırları profilde
- [ ] Kabul testi (`10-field-setup.md` §6): 500 ürünlük bir koşuda bilinen 20 hatalı ürünün ≥ 18'i NOK; sağlamlarda yanlış NOK ≤ %1
- [ ] OK/NOK sayaçları ekranda ve dashboard'da

---

## F5 — I/O köprüsü (ESP32)

**F5.1 Firmware** — `docs/07-io-bridge-esp32.md`
**F5.2 iOS ve edge entegrasyonu** — sayım darbesi, gecikmeli ejektör darbesi
- [ ] Her sayımda PLC girişinde 24V darbe; 1000 üründe PLC sayacı ile uygulama sayacı eşit
- [ ] Ejektör testi: 1 m/s bantta hedef ürüne isabet ≥ %98

---

## F6 — iOS ↔ edge kalibrasyon istemcisi, çoklu kamera

- iOS uygulamasında "Edge kameralar" bölümü: Bonjour ile kutuyu bul, kameraları listele, önizleme üzerinde ROI/çizgi düzenle, boş bant/örnek kalibrasyonunu uzaktan başlat, profili gönder.
- Edge: ONVIF keşfi, aynı kutuda 4 kameraya kadar.
- [ ] Teknisyen kutuya dokunmadan, sadece iPhone ile yeni bir IP kamerayı 5 dakikada devreye alıyor

---

## F7 — ML

**F7.1 Anomali tespiti (sadece sağlam ürünle)** — `09-ml-roadmap.md` §3
**F7.2 YOLO dedektör eklentisi** — §4, `Detector` arayüzü, lisans kararı (§5) önce
- [ ] Yoğun/üst üste sentetik + gerçek veri setinde sayım hatası klasik yönteme göre en az yarıya iniyor

---

## F8 — TRASSIR entegrasyonu
- `08-trassir-integration.md` açık soruları yanıtlandıktan sonra planlanır.
