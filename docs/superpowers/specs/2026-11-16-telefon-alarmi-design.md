# Telefon / tablet kullanımı alarmı — tasarım

Tarih: 2026-11-16. Durum: kullanıcı onayladı (2026-11-16); yazılım uygulandı, doğruluk ölçümü kullanıcı kayıtlarıyla bekliyor.

## Amaç ve neden
Kullanıcı, iş güvenliği ve nöbet noktası paketlerinde bulunan "cep telefonu / tablet kullanımı" alarmını BantVision'a
istedi. İş yeri senaryosu: yasak alanda (üretim hattı, makine başı, güvenlik noktası) bir kişi belirli bir süreden uzun
telefona bakıyor ya da telefonla uğraşıyorsa alarm. Önce bu alarm yapılır; "sigara içme şüphesi" kullanıcı test kayıtlarını
gönderince ayrı iş olarak ölçülerek eklenir (bu belgenin kapsamı dışında).

**Başarı:** kullanıcının çekeceği test kayıtlarında (masada / ayakta telefon kullanımı, telefonla konuşma, tablet) Normal
ayarlarla alarm; yanlış alarm denemelerinde (su içmek, yemek, yüz kaşımak, telefon masada dururken klavyede çalışmak,
elinde telefon olmadan durmak) alarm yok. Ölçüm `tools/eval_pose.py` ile yapılır; sayısal kabul eşiği poz alarmıyla
aynıdır (tür başına ≥ %95 yakalama, kamera başına 8 saatte ≤ 1 yanlış alarm) ve ölçülene kadar özellik "deneme" olarak
duyurulur.

## Hedef dışı / anti-hedef
- Yeni model eğitmek yok (ilk sürüm). Telefon, kişi sayımındaki hazır COCO YOLOX-S modelinin "cell phone" sınıfıyla bulunur.
- Ayrı "tablet" sınıfı yok: COCO'da yok; tablet çoğu zaman telefon olarak görünür, görünmezse kaçar. Dizüstü ("laptop")
  sınıfı **eklenmez** (masada dizüstüyle çalışmak olağan iştir, sürekli yanlış alarm üretir).
- iPhone uygulamasında çalıştırma yok (güvenlik modu zaten yalnızca bilgisayarda).
- Görüntü cihazdan çıkmaz; alarm görüntüsü/klibi mevcut güvenlik alarmı kurallarıyla (sendImage) gönderilir.
- Anti-hedef: kuyumcu gibi mevcut güvenlik kullanıcılarına habersiz yeni alarm yağdırmak. Bu yüzden kural varsayılan **kapalı**.

## Kapsam kararları
1. **Yeni mod değil, güvenlik moduna üçüncü kural.** `safety.phone = {enabled, seconds}` — eller yukarı ve yerde
   yatan kişinin yanına. Aynı kişi izleyici, aynı poz modeli, aynı bölüm (episode) mantığı, aynı alarm kaydı, klip,
   bildirim, bekleme süresi (kamera+tür başına 60 sn) ve onay akışı kullanılır. Alan kısıtı yok (güvenlik modundaki
   karar aynen geçerli; kural karedeki her kişiye uygulanır).
2. **Varsayılan:** kapalı, 15 sn (kullanıcı kararı, 2026-11-16: ofis kaydında 40 sn telefon kullanımı, kişi yer değiştiriyor; 15 sn kuralı iki kullanım bölümünü de yakaladı, 20 sn eşik 0,25'te yakalamadı). Aralık 10–600 sn (canlı API, video işi seçenekleri, şema aynı aralık).
3. **Alarm türü adları:** canlı alarm `type = "phone"`, video işi `alarms[].kind = "phone"`. Metinler: büyük başlık
   "TELEFON KULLANIMI", etiket "Telefon kullanımı", görüntü üstü etiket "TELEFON", Telegram satırı mevcut biçimde
   (`🚨 TELEFON KULLANIMI — <kamera> · <tarih>`).
4. **Sözleşme:** eklemeli ve isteğe bağlı alan → şema `bantvision.profile.v1` / `analysis-job.v1` kalır (yangın bloğu da
   böyle eklendi). Değişen yerler: profil şeması `safety.phone`, iş şeması `options.safety.phone` ve `alarms.kind` enumu,
   `docs/02-contracts.md`. iOS `SafetyConfig` alanı taşır (çözer/yazar, işlemez) — yoksa uygulama profili yeniden
   kaydedince alan düşer.

## Fizibilite ölçümü (2026-11-16, kullanıcının ofis kamerasından 2 kayıt, 1150×700–930, tepeden-yandan)
- **Tam karede** COCO YOLOX-S telefonu görmüyor (telefon ~20 px; skorlar ≤ 0,16 ve yanlış nesnelerde). Tam kare
  yaklaşımı (tek çıkarım) bu kamerada **çalışmaz**.
- **Kişi kırpıntısında** (kişi kutusu + %20 pay, model girişine büyütülür) telefon elde/yüz yanında 0,25–0,45 skorla
  bulunuyor; ama kesintili: telefonu 24 sn boyunca elinde tutan kişide 5 kare/sn analiz edilen karelerin ~%25'inde
  isabet, isabetsiz aralıklar 6–9 sn'ye çıkıyor. Telefonsuz iki kişide 24 sn boyunca hiç isabet yok.
- Sonuç: "sürekli görülme + kısa tolerans" mantığı (eller yukarı gibi) uzun bölümü sürekli koparır; **pencere içinde
  yeterince sık görülme** mantığı gerekir.

## Algılama (çekirdek)
- **Kişi kırpıntısında arama:** telefon kuralı açıkken her onaylı ve bu karede görülen kişi için kutu %20 payla
  kırpılır, aynı paylaşılan YOLOX-S modeliyle yalnız `"cell phone"` aranır. Kişi başına en çok `PHONE_FPS = 2` arama/sn
  (ek yük sınırlı; kişi sayısıyla doğrusal). Kural kapalıyken bugünkü davranış birebir aynı kalır. `CLASS_IDS`'e
  `"cell phone": 67` eklenir ama profil `detectClasses` enumuna **eklenmez** (sayım sınıfı değil).
- **İsabet (kırpıntı başına):** telefon skoru ≥ `PHONE_CONF` (başlangıç 0,25) ve merkezi kişinin görünen bileğine ya
  da başına `PHONE_NEAR · ölçek` (başlangıç 0,6) uzaklıktan yakın. Ölçek ya da el/baş görünmüyorsa o arama sayılmaz.
- **Kanıt penceresi (iz başına):** kural süresi `seconds` (S) `PHONE_SLOT_S = 5 sn`'lik dilimlere bölünür. Kişi son S
  saniye boyunca izlenmişse ve bu dilimlerin en az `PHONE_SLOT_RATIO` (başlangıç 0,6) kadarında en az bir isabet varsa
  alarm (bölüm başına bir kez). Bölüm, `PHONE_END_S` (başlangıç 15 sn) boyunca isabet gelmezse ya da iz kaybolursa
  biter (alarm vermiş bölüm mevcut kurallardaki gibi en az `FIRED_GRACE_S`). Bölüm süresi (etkin listesi) ilk isabetten
  beri geçen süredir. Çıktı biçimi diğer kurallarla aynı (`fired`, `ended`, `active`; anahtar `(iz, "phone")`), böylece
  canlı alarm/klip/bildirim yolu değişmez.
- Poz yalnız onaylı ve bu karede görülen izlerde, en az bir kural açıkken çalışır (bugünkü gibi). Telefon kuralı tek
  başına açıksa da poz çalışır (el/baş konumu için gerekli).
- Boş sahnede tanıma atlama (izleme kapısı) aynen geçerli: kişi yoksa telefon da aranmaz.
- Sabitlerin son değerleri kullanıcının ek kayıtlarıyla `tools/eval_pose.py` üzerinden kalibre edilir. Kayıtlar yine
  yetersiz kalırsa (yakalama < %95) ikinci adım: kişi kırpıntısında telefon için ince ayarlı model (ticari lisanslı
  veriyle) — ayrı iş.

## Uçtan uca yerler
- **Çekirdek:** `core/detector.py` (sınıf), yeni `core/phone_rules.py` (kırpıntı araması, isabet kararı, kanıt
  penceresi, sabitler), `core/safety.py` (üçüncü kural; poz sonucu ve izlerle beslenir), `core/profile.py`
  (`SafetyConfig.phone`).
- **Canlı:** `live/api.py` doğrulama (`_check_safety`, aralık 10–600), başlık/mod tabloları, `/alarms` tür filtresi;
  `overlay.py` etiket; klip ve bildirim yolu türden bağımsız (yalnız etiket tabloları).
- **Video ile test:** `analyzer/app.py` seçenek doğrulaması, `analyzer/jobs.py` (`ALARM_KINDS`, CLI bayrakları),
  `video.py` (`--phone N` / `--no-phone`, CSV etiketi), panel `UploadCard` güvenlik kural satırı ve `safetyAlarms.mjs`.
- **Panel canlı:** `SafetySettings` üçüncü satır (açık/kapalı + süre), `ALARM_LABELS` / `ALARM_TITLES`, alarm sayfası
  filtresi (etiket tablosundan otomatik).
- **iOS:** `SafetyConfig.phone` taşıma + test.
- **Ölçüm aracı:** `tools/eval_pose.py` etiket türlerine `"phone"`.
- **Belgeler:** `docs/02-contracts.md`, `docs/03-algorithm.md` §4.11'e telefon alt bölümü, `docs/13-web-platform.md`
  (güvenlik alarmı ve video ile test), `docs/12-durum.md`. Panel yardım metni: kural çalışanları izlediği için
  kullanıcıya "çalışanları bilgilendirin (KVKK)" notu.

## Bilinen riskler
- Telefonla kulakta konuşma: telefon çoğu zaman elin/başın arkasında kalır, nadiren görülür → kanıt penceresi
  dolmayabilir. Kullanıcının "tel 1" kaydı (konuşma, 15 sn) bunu doğruladı: telefon yalnız 2 karede (yüz yanında)
  görüldü. "El kulakta uzun süre" poz ipucu çeneye el dayamakla karışır; **ilk sürüm konuşmayı yakalamayı hedeflemez**
  (belgede ve panel yardımında yazılır), ek kayıtlarla ölçülüp ayrı iş olarak değerlendirilir.
- Telefon masada dururken eli yanında çalışan kişi (klavye) yanlış alarm üretebilir → kullanıcının "telefon masada,
  klavyede çalışma" kaydıyla ölçülür; gerekirse "telefon el/baş hizasında ve bilek ona doğru" gibi ek koşul eklenir.
- Uzak/tepeden kamerada telefon birkaç pikseldir → kaçar. Belgeye kamera şartı yazılır (kişi boyu kabaca kare
  yüksekliğinin ≥ 1/3'ü, 1080p).
- İzleyici kimlik değişimi uzun (60 sn) bölümü yeniden başlatabilir → ölçümde görülürse ele alınır.

## Yapıcıya bırakılanlar
Sabitlerin son değerleri (ölçümle), test ayrıntıları, panel yerleşiminin küçük ayrıntıları (mevcut satır düzeni izlenir).
