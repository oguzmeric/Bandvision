# Yangın / duman algılama — tasarım

Tarih: 2026-11-08 · Dal: `yangin-duman` · Araştırma: `reports/Olay algılama veri seti ve model lisansları.md` (yerel, depoda değil)

## 1. Amaç ve neden

Olay algılama paketinin ilk modülü. Kamera görüntüsünde alev ve dumanı erkenden görüp mevcut güvenlik alarmı yolundan
(panel alarmı, 8 sn önce + 4 sn sonra klip, Telegram, alarm listesi, Video ile test) haber vermek.

Kullanıcı kararları:
- "Her yerde olabilir": depo, fabrika, mutfak, otopark, dükkân. Modül sahneye özel değildir; hassasiyet ve hariç
  bölgeler kamera başına ayarlanır.
- Kapsam iç mekân ve yakın dış mekândır (uzak orman dumanı değil).
- Soruların atlanması istendi; bu belgedeki kararların çoğu benim kararımdır ve öyle işaretlenmiştir.
- TRASSIR yangın modülü yalnızca yan yana doğruluk kıyası için kullanılır, yazılımı ya da modeli asla alınmaz.

## 2. Hedefler, hedef dışı, başarısızlık sayılanlar

**Hedefler**
- Canlı kamerada `fire` analiz türü: alev → "Yangın", duman → "Duman" alarmı.
- Kendi eğittiğimiz, lisansı temiz (Apache-2.0 mimari + ticari kullanıma açık veri) bir model.
- Yanlış alarmı düşük tutan katmanlar: zamansal onay, mekânsal tutarlılık, hareket denetimi, kamera başına hassasiyet,
  hariç bölgeler.
- "Video ile test"te `fire` hazır ayarı ile aynı çekirdeğin ölçülebilmesi.
- Yanlış alarm işaretlenen olayların görüntüsünün cihazda zor örnek olarak saklanması (sonraki eğitim için).

**Hedef dışı**
- Yangın alarm sistemi sertifikası (EN 54 vb.). Ürün metni: "Erken uyarıdır; yangın algılama ve alarm sisteminin yerine
  geçmez."
- Termal kamera, uzak orman dumanı, iPhone'da yangın analizi (iPhone yalnızca profili okuyabilmeli).
- Fiziksel çıkış tetikleme (ejektör/röle) — CLAUDE.md güvenlik kuralı gereği bu modülde yok.

**Başarısızlık sayılanlar (çalışsa bile)**
- Ultralytics kodu ya da ağırlığıyla temas (eğitim dahil). Lisans zinciri YOLOX (Apache-2.0) üzerinde kalır.
- Görüntünün cihazdan çıkması (zor örnekler dahil). Yalnızca alarm resmi, kullanıcı açtıysa Telegram'a gider.
- Sabit bir alev resmi, kırmızı bir ışık ya da beyaz bir duvarın sürekli alarm üretmesi.
- Model yokken sessizce "sağlıklı" görünmek.

## 3. Mimari

```
kare ──► FireDetector (YOLOX-S, 2 sınıf, ONNX, DirectML/CPU)
          │ kutular (fire|smoke, skor)
          ▼
        Hassasiyet eşiği + hariç bölgeler + en küçük boyut
          ▼
        Hareket denetimi (kutu içinde ~1 sn önceki kareye göre değişim)
          ▼
        FireEvidence: sınıf başına ızgara hücrelerinde kayan pencere oyu
          ▼
        Bölüm (episode) → alarm (fired) / bitiş (ended)
          ▼
        mevcut alarm yolu: AlarmStore, ClipBuffer, TelegramNotifier, panel
```

### 3.1 Model (`core/fire_model.py`)
- YOLOX-S, 640 giriş, iki sınıf: `fire` (0), `smoke` (1). Çıktı düzeni mevcut COCO modeliyle aynı (ham ızgara çıktısı,
  kod çözme ve NMS uygulamada; DirectML'de NMS çekirdeği gerekmez).
- Kutu çözme kodu `core/detector.py` ile paylaşılır (ortak yardımcıya çıkarılır, davranışı değişmez).
- Dosya adı `fire_smoke_v1.onnx`, konum `BANTVISION_MODEL_DIR` (yoksa kullanıcı önbelleği).
- İndirme: `pose_model.py` deseni (URL + SHA-256). Model yayımlanana kadar URL boştur; dosya yoksa analiz sağlıksız
  görünür ve nedeni "Yangın/duman modeli kurulu değil" olur. Yayımlama (GitHub sürümüne yükleme) kullanıcı onayıyla yapılır.
- Cihaz seçimi: Cihaz ayarlarına yeni satır `fire` ("Yangın/duman modeli"), varsayılan otomatik.
- Canlıda tek paylaşılan örnek (`SharedPose` deseni, arka planda yükleme, durum/hata).

### 3.2 Profil (`countMode: "fire"`, `Profile.fire: FireConfig`)

| Alan | Tür | Varsayılan | Aralık |
|---|---|---|---|
| `fire` | `{enabled, seconds}` | `{true, 3}` | 2–10 sn |
| `smoke` | `{enabled, seconds}` | `{true, 8}` | 5–30 sn |
| `sensitivity` | `"low" \| "normal" \| "high"` | `"normal"` | — |
| `ignoreZones` | normalize çokgen listesi | `[]` | en çok 8 çokgen, her biri 3–12 nokta |
| `sendImage` | bool | `false` | — |

- `roiPolygon` ve sayım çizgisi bu modda yok sayılır (tam kare analiz); dışarıda bırakma `ignoreZones` ile yapılır.
- `{}` geçerlidir, eksik alan varsayılanla dolar (safety ile aynı tolerans).
- En az bir kural açık olmalı (iki kural da kapalıysa doğrulama hatası: "En az bir kural açık olmalı.").
- Hazır ayar: `Profile.fire_watch()` → "Yangın / duman", katalogda Güvenlik kategorisinde.

### 3.3 Karar katmanı (`core/fire_rules.py`, `core/fire.py`)

Sabitler `fire_rules.py`'de, değerleri model eğitimi sonrası ölçümle kalibre edilir (§5). Başlangıç değerleri:

- **Eşikler** (sınıf başına skor): düşük `fire .60 / smoke .65`, normal `.45 / .50`, yüksek `.35 / .40`.
- **En küçük kutu:** kısa kenarı kare yüksekliğinin %1,5'inden küçük kutular atılır.
- **Hariç bölge:** kutu merkezi bir hariç çokgenin içindeyse atılır.
- **Hareket denetimi:** 160 px genişliğe küçültülmüş gri kare geçmişi tutulur. Kutu içinde ~1 sn önceki kareyle
  mutlak fark > 8 olan piksellerin oranı < %2 ise kutu "durağan" sayılır ve oy vermez. Akış 1 kare/sn'den yavaşsa bir
  önceki kare kullanılır. Kamera kayması/ışık patlaması için: kare genelinde değişen piksel oranı > %40 ise o kare oy
  vermez (ne olumlu ne olumsuz).
- **Mekânsal oy:** kare 8×6 hücreye bölünür. Her geçerli kutu kapladığı hücreleri işaretler; oy sayılırken bir hücre
  komşu hücrelerin işaretini de kabul eder (kutunun küçük kaymaları bölümü bölmesin).
- **Bölüm:** sınıf başına. Bir hücre olumlu olduğunda bölüm başlar. Alarm koşulu: bölüm süresi ≥ kural süresi **ve**
  son `seconds` saniyedeki analiz edilmiş karelerin en az %60'ında aynı hücre (komşuluk dahil) olumlu **ve** en az 3
  olumlu kare. Bölüm başına tek alarm.
- **Bitiş:** sınıfta 10 sn boyunca hiç olumlu kare yoksa bölüm biter (`ended`). Aynı kamera ve türde yeniden alarm için
  mevcut 60 sn soğuma (`api._register`) geçerlidir.
- **Analiz hızı:** yangın modunda en çok 5 kare/sn analiz edilir (fazlası atlanır), çok kamerada GPU'yu korumak için.
- Çıktı `FireResult`: `detections` (bu karede geçerli kutular, sınıf ve skorla), `active` (sınıf, süre, alarm verdi mi,
  kutu), `fired: list[FireAlarm]`, `ended`, ve sağlık bilgisi. `FireAlarm(kind, box, started, ts)`; `kind` ∈
  `"fire" | "smoke"`. Canlı ve video sözleşmesinde de aynı yazım kullanılır (safety'deki `hands_up/handsUp` ikiliği
  tekrarlanmaz).

### 3.4 Canlı yol
- `LiveSession`: `countMode == "fire"` → `_setup_fire()` (paylaşılan yangın modeli + `FireAnalyzer` + `ClipBuffer`).
  `set_profile` ile mod değişimi, `_warm`, `end_all`/stop davranışı safety ile aynı sözleşmeyi izler.
- Alarm sink: mevcut `LiveManager` kayıt yolu genelleştirilir; tür başlıkları `"fire": "🔥 YANGIN"`,
  `"smoke": "💨 DUMAN"`. Telegram metni mevcut biçim + "Görüntüyü hemen kontrol edin." satırı.
- `GET /alarms?type=` listesine `fire`, `smoke` eklenir.
- Klip üstü çizim: `ClipOverlay` safety'ye özel olmaktan çıkar; yangın sonucunda kutular çizilir (yangın turuncu
  "YANGIN", duman gri "DUMAN"). Mevcut 0,7 sn eşleme kuralı aynen geçerli.
- Durum bloğu `snapshot_status()["fire"]`: `active`, `lastAlarmAt`, `model` (durum), `healthy`, `reason`,
  `unhealthyFor`. İzleme duvarındaki karo rozeti safety ile aynı biçimde.
- `watch.json` ile kalıcı izleme: yangın oturumları da yeniden başlatmada geri açılır (safety gibi).

### 3.5 Yanlış alarm → zor örnek
- Mevcut "yanlış alarm" işareti bir `fire`/`smoke` alarmına konduğunda alarm resmi ve klibi
  `<veri>/live/hard-negatives/<id>/` altına kopyalanır, yanına `meta.json` (tür, kamera adı, zaman, skorlar) yazılır.
- Yalnız cihazda kalır, panelde ayrı ekran yok. Belgede eğitime nasıl katılacağı anlatılır.

### 3.6 Video ile test
- Hazır ayar `fire` ("Yangın / duman"), seçenekler `fire{fire, smoke, sensitivity}` (hariç bölge yok, tam kare).
- Sonuç `alarms[]` öğesi `kind ∈ {"fire","smoke"}`; tablo, alarm resimleri ve `alarms.csv` mevcut biçimde.
- Sayım seçenekleriyle karışık istek 422 (safety kuralıyla aynı).

### 3.7 Panel
- Analiz türü `yangin`: menüde Analizler altında "Yangın / duman" (`/live?tur=yangin`), katalogda hazır ayar.
- `FireSettings`: iki kural (aç/kapa + saniye), hassasiyet (Düşük / Normal / Yüksek), "Alarm resmini gönder",
  "Hariç bölgeler" çokgen düzenleyici (mevcut çokgen düzenleyiciden çoklu sürüm), sabit uyarı metni:
  "Erken uyarıdır; yangın algılama ve alarm sisteminin yerine geçmez."
- Model durumu satırı: "Yangın/duman modeli: hazır / yükleniyor / kurulu değil".
- Alarm listesi, alarm merkezi, afiş ve görüntüleyici: etiketler "Yangın", "Duman"; `/alarms` sayfasındaki sabit
  sayaçlar tür listesinden üretilir.
- Video ile test: hazır ayar seçeneği, kural alanları, alarm tablosu etiketleri.
- Cihaz ayarları: "Yangın/duman modeli" satırı.

### 3.8 Sözleşmeler (aynı dalda tüm uygulamalar)
- `product-profile.schema.json`: `countMode` enum'a `fire`, yeni `fire` nesnesi. `analysis-job.schema.json`: `preset`
  enum'a `fire`, `options.fire`, `alarms[].kind` enum'a `fire`, `smoke`, ilgili `if/then` kuralları. Örnek dosya
  `analysis-job-fire-done.json`. `docs/02-contracts.md` güncellenir. Şema sürümü `v1` kalır (ekleme, kırıcı değil).
- iOS: `CountMode.fire` + `FireConfig` Codable (yalnızca okuma, "Yangın / duman (yalnızca bilgisayar)"), test
  `FireProfileTests.swift`. Swift Windows'ta derlenemez; mevcut safety deseninin birebir kopyası olarak yazılır.
- Supabase: `countMode` için kısıt yok, değişiklik gerekmez.

## 4. Model eğitimi (ayrı iş kolu, `tools/fire_train/`)

Yazılım kolundan bağımsız ilerler. **İndirmeler kullanıcı onayı ister** (aşağıdaki liste ile sorulur).

- **Ortam:** ayrı bir eğitim sanal ortamı (ana uygulama ortamına kurulum yok). PyTorch (CUDA), YOLOX kaynak kodu
  (Apache-2.0) ve COCO önceden eğitilmiş `yolox_s.pth`.
- **Eğitim verisi:**
  - D-Fire: yalnız `PublicDataset` ön eki taşımayan görüntüler (yazarların kendi kameraları + web, CC0). `PublicDataset`
    görüntüleri üçüncü taraf koşullarına tabi olduğundan varsayılan olarak dışarıda; bayrakla açılabilir.
  - FireNet (MIT, 502 görüntü).
  - D-Fire'ın "hiçbiri" görüntüleri negatif olarak kalır.
- **Değerlendirme verisi:** D-Fire test bölümü (görüntü düzeyi mAP50) ve FIRESENSE videoları (CC BY 4.0; olay düzeyi:
  pozitif videoda alarm ve alarm süresi, negatif videoda yanlış alarm). Değerlendirme gerçek `FireAnalyzer` ile yapılır.
- **Betikler:** `prepare_data.py` (YOLO txt → COCO json, bölümleme, lisans filtresi, kaynak listesi), `exps/fire_yolox_s.py`,
  `train.md` (adım adım komutlar), `export.py` (ONNX, opset 11, onnxruntime ile doğrulama ve SHA-256), `eval_fire.py`
  (iki düzeyli ölçüm, hassasiyet eşiklerinin kalibrasyonu, Türkçe özet tablo).
- **Kabul hedefleri (v1):** D-Fire test mAP50 (iki sınıf ortalaması) ≥ 0,60; FIRESENSE pozitif videolarının ≥ %80'inde
  normal hassasiyette 15 sn içinde alarm; negatif videolarda normal hassasiyette 0 yanlış alarm. Ölçüm neyse o
  raporlanır; hedef tutmazsa ayrıntılı rapor ile kullanıcıya dönülür, model yayımlanmaz.
- **Atıf:** `docs/` altında model kartı: mimari, veri kaynakları ve lisansları, ölçümler, bilinen zayıflıklar (buhar,
  sis, far, gün batımı, kaynak ışığı).
- Ağırlıklar depoya girmez (`*.onnx` zaten yok sayılıyor).

## 5. Ölçüm ve kıyas
- Eğitim sonrası `eval_fire.py` eşikleri kalibre eder ve `fire_rules.py` sabitlerini günceller (ayrı commit, ölçüm
  tablosuyla).
- TRASSIR kıyası (ofis ağında, kullanıcıyla): aynı sahneye iki sistemin yalnızca alarm çıktıları karşılaştırılır;
  prosedür `docs/12` doğrulama listesine eklenir.
- Saha: zor örnekler biriktikçe yeni sürüm eğitimi (v2) ayrı iştir.

## 6. Test
- Çekirdek: sahte dedektörle `fire_rules`/`FireAnalyzer` birim testleri (eşik, hariç bölge, hareket, oy oranı, komşuluk,
  bitiş, tek alarm, ışık patlaması, 1 kare/sn akış, model yok).
- Canlı: alarm kaydı + klip + bildirim kuyruğu, durum bloğu, mod değişimi, watch geri yükleme.
- Video: sahte dedektörle iş sonucu, CSV ve resimler, 422 karışık seçenek.
- Sözleşme: şema örnekleri ve profil gidiş-dönüş.
- Panel: e2e (sahte rotalarla ayar paneli, alarm etiketleri, video ön ayarı) + birim testleri.
- Eğitim betikleri: küçük sahte veriyle `prepare_data` ve `eval_fire` toplama mantığı testleri (eğitim koşmadan).

## 7. Yapıcıya bırakılanlar
- Ortak kutu çözme yardımcısının adı ve yeri.
- `ClipOverlay` genellemesinin biçimi (birleşik tür ya da çizim işlevi).
- Çoklu çokgen düzenleyicinin mevcut düzenleyiciden nasıl türetileceği.
- Sabitlerin başlangıç değerleri kalibrasyona kadar yukarıdaki gibidir; yapıcı testlerle tutarlı küçük düzeltmeler yapabilir.

## 8. Süre tahmini
- Yazılım kolu: ~1 gün (6–7 görev, görev başına inceleme, son bütün inceleme).
- Model kolu: onaydan sonra indirme ~1 saat, eğitim ~6–10 saat (dizüstü ekran kartı, 6 GB), değerlendirme ~1 saat.
