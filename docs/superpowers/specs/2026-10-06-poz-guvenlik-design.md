# Poz güvenlik alarmı: "eller yukarı" ve yerde yatan kişi — tasarım

Tarih: 2026-10-06 (son güncelleme 2026-10-08) · Durum: uygulandı; sonradan alınan kararlar sondaki "Değişiklikler (2026-10-07/08)" bölümünde

## Amaç
Kuyumcu gibi mağazalarda kameradan iki durumu algılayıp sessiz alarm vermek:
- **soygun** sırasında "eller yukarı" duruşu;
- **düşme/bayılma** sonrası yerde yatan kişi.

Alarm, panelde (web) ve **Telegram**'da kamera adı, zaman ve isteğe bağlı olay resmiyle görünür.

**Kullanıcının söyledikleri (2026-10-06):**
- Alarm hem uygulama ekranına hem Telegram'a (WhatsApp Business ileride) olay resmi, kamera adı ve zamanla gitsin.
- Platform mağazadaki bilgisayar + mevcut kameralar/NVR (web analiz sunucusu). iPhone kapsam dışı.
- "Eller yukarı" süresi 3–5 sn arası ayarlanabilir.
- Hem eller yukarı hem yerde yatma ("bayılma, yerde yatıyor vaziyette vs.") ilk sürümde olacak.
- Kameralar genelde bullet ya da dome (eğik bakış); balık gözü değil.
- İlk etapta yalnızca Telegram.
- Olay resmi bilgisayarda 7 gün saklanır; Telegram'a resim gönderimi varsayılan kapalı, kullanıcı açar.
- Yanlış alarm hedefi: kamera başına 8 saatte en fazla 1.

**Varsayımlar:**
- Kişinin üst gövdesi (eller yukarı) ya da tamamı (yerde yatma) kamerada görünür.
- Sahne en azından gri tonlu (gece kızılötesi dahil) poz okunacak kadar net.

## Başarı ölçütü (kabul)
Ofisteki bullet/dome kameralarla canlandırma kayıtlarında:
- eller yukarı ≥ 20 olay (farklı kişiler; önden, yandan, tezgah arkası);
- yerde yatma ≥ 20 olay (farklı yönler);
- ≥ 1 saat normal hareket.

Hedefler:
- olayların **≥ %95'i** kural süresi + 2 sn içinde alarm verir;
- normal harekette yanlış alarm **kamera başına 8 saatte ≤ 1**.

Ölçüm aracı: `tools/eval_pose.py`. Tutmayan senaryoda eşikler ölçümle ayarlanır.

## Kapsam
- **Var:**
  - Python analiz sunucusu (canlı kamera/NVR oturumları): kişi tanıma (mevcut YOLOX) + izleyici (mevcut `MotTracker`) + **MoveNet SinglePose Thunder** poz + kural durum makinesi.
  - Alarm günlüğü, olay resmi ve olay kaydı (video) (7 gün).
  - Telegram bildirimi ve çevrimdışı kuyruk.
  - Web paneli: güvenlik profili, ayarlar, iskelet çizimi, alarm şeridi, alarm penceresi, son alarmlar, "Alarmlar" sayfası, "Bildirimler" sayfası, deneme alarmı.
  - Sözleşme: profilde `countMode: "safety"` ve `safety` ayarları.
  - Dokümanlar.
- **Yok (YAGNI):**
  - iPhone'da çalıştırma (yalnızca sözleşme gereği yeni yöntemi tanır, katalogda göstermez).
  - WhatsApp Business.
  - Supabase'e olay gönderimi.
  - Video analizi (yükleme) formunda güvenlik.
  - Aynı kamerada aynı anda sayım + güvenlik.
  - Ani düşme anı algılama (yerde yatma süresi kapsar).
  - Varsayılan olarak panelde ses (ses isteğe bağlıdır, varsayılan kapalı: bkz. "Değişiklikler").

## Kurallar (bağlayıcı)
Görüntü koordinatı piksel, y aşağı doğru artar. Poz: COCO-17 eklemleri:

| İndeks | Eklem |
|---|---|
| 0 | burun |
| 1–2 | gözler |
| 3–4 | kulaklar |
| 5–6 | omuzlar |
| 7–8 | dirsekler |
| 9–10 | bilekler |
| 11–12 | kalçalar |
| 13–14 | dizler |
| 15–16 | ayak bilekleri |

Bir eklem **görünür** sayılır: güven ≥ `KP_CONF = 0,3`.

**Ölçek `s`:**
- İki kalça görünürse `s = |omuz_orta − kalça_orta|` (gövde boyu).
- Değilse, baş görünürse `s = 2,5 · |baş − omuz_orta|`. "Baş" = burun görünürse burun; değilse görünen göz/kulakların ortalaması.
- İkisi de yoksa karar yok.
- Omuzların ikisi de görünmezse karar yok.

**Kare kararı — eller yukarı** (`True` / `False` / `None` = yetersiz eklem):
- Gerekli: iki omuz, iki bilek görünür ve `s` tanımlı. Değilse `None`.
- `True` ⇔ her iki taraf için:
  - `bilek.y ≤ aynı_taraf_omuz.y − WRIST_UP · s`, **ve** (`WRIST_UP = 0,20`; ilk tasarım 0,35'ti, bkz. "Değişiklikler")
  - dirsek görünürse `dirsek.y ≤ aynı_taraf_omuz.y + ELBOW_DOWN · s` (`ELBOW_DOWN = 0,30`; ilk tasarım 0,15'ti; görünmezse dirsek koşulu aranmaz).

**Kare kararı — yerde yatma:**
- Gerekli: iki omuz ve iki kalça görünür. Değilse `None`; tezgah arkasında ayaktaki kişi böyle olur.
- `θ` = (kalça_orta → omuz_orta) vektörünün görüntü dikeyiyle açısı (0° dik, 90° yatay).
- `True` ⇔ `θ ≥ 60°` **ya da** (baş görünür ve `baş.y ≥ kalça_orta.y − 0,1 · s`). İkinci koşul baş-ayak doğrultusu kameraya dönük yatmayı yakalar.

**Alan: yok** (kullanıcı kararı, 2026-10-07):
- Kural karedeki **herkese** uygulanır; profilde alan (ROI/çokgen) olsa bile yok sayılır. Tanıma ve izleme tam karede çalışır.
- Sözleşme `roi` alanını hâlâ kabul eder (eski profiller bozulmaz).

**Süre durum makinesi** (iz başına, tür başına; zaman = kare zaman damgası):
- `True` kare bir **bölüm** başlatır ya da sürdürür.
- `False` ya da `None` kareler en çok `GRACE = 0,5 sn` affedilir. Daha uzun sürerse bölüm biter. Alarm vermiş bölüm daha uzun affedilir: `FIRED_GRACE_S = 3 sn` (tek olay tek alarm kaydı üretsin).
- Bölüm süresi (ilk `True` → son `True`) ≥ `T` olunca **alarm**; bölüm başına bir kez.
- Varsayılan `T`:
  - eller yukarı: 3 sn (ayar 3–5);
  - yerde yatma: 10 sn (ayar 5–30).
- İz silinirse (kişi kayboldu) bölüm biter (alarm vermiş bölüm `FIRED_GRACE_S` dolunca).
- Kamera yeniden bağlanınca izler sıfırlanır.
- Alarmın **bitişi**: bölüm bitince `endedAt` yazılır; panelde "devam ediyor" kalkar.

**Tekrar önleme:**
- Aynı kamerada aynı tür için son **kuyruğa alınan** bildirimden itibaren (Telegram yapılandırılmışsa) `COOLDOWN = 60 sn` içinde oluşan alarmlar günlüğe ve panele yazılır, Telegram'a gitmez (`notify: "suppressed"`).
- Test alarmı tekrar önlemeye tabi değildir.

## Poz modeli
**Karar (kullanıcı, 2026-10-07):** **MoveNet SinglePose Thunder** (Google). Açıkça Apache-2.0, ticari kullanım serbest; COCO + Google'ın kendi "Active" veri setiyle eğitilmiş.
- RTMPose / RTMO elendi: kod Apache-2.0, ancak ağırlıklar için açık lisans beyanı yok; eğitim verisi (Body7) araştırma amaçlı koşullu setler içeriyor (AI Challenger, MPII, PoseTrack18).
- Kişi kutusu başına çalışır (iki aşamalı tasarım aynen); çıkış COCO-17 eklem (y, x, güven), girdiye göre normalize.
- **Dağıtım:** Google modeli TFLite/SavedModel olarak yayınlar.
  - Bir kez `tf2onnx` ile ONNX'e çevrilir; çevirme betiği depoda (`tools/convert_movenet.py`).
  - Çevrilmiş dosya orijinal modelle aynı çıktıyı verdiği doğrulanarak (sentetik + açık lisanslı örnek görüntülerde eklem farkı < 0,01) projenin GitHub sürüm sayfasına konur: `models-v1`, `movenet_thunder.onnx`, Apache-2.0 lisans metni ve kaynak/değişiklik notu ile.
  - Sunucu ilk kullanımda oradan indirir, SHA-256 doğrular (YOLOX ile aynı düzen: `BANTVISION_MODEL_DIR`).
- **Kırpma:**
  - Kişi kutusu 1,25× genişletilir, kare yapılır (uzun kenar) ve görüntü dışına taşan kısım siyahla doldurulur.
  - 256×256'ya ölçeklenir; RGB, `int32` (Thunder girdisi).
  - Eklemler kare koordinatından görüntü pikseline geri çevrilir.
- **Ne zaman çalışır:**
  - Yalnızca **onaylı ve bu karede tanımayla gözlenen** izlere uygulanır.
  - Boş sahnede (tanıma atlandığında) poz da atlanır.
  - Bütün kameralar tek ortak poz modelini kullanır; kareler sırayla işlenir.
- **Performans hedefi:** ofis bilgisayarında, sayım yapan kameralarla birlikte bir güvenlik kamerası ≥ 5 kare/sn.
- **Bilinen risk:** MoveNet ağırlıklı olarak fitness/dans/yoga videolarıyla eğitildi; eğik/uzak güvenlik kamerasında doğruluk kabul ölçümüyle sınanır. Yetmezse model seçimi yeniden değerlendirilir.

## Sözleşme
`contracts/product-profile.schema.json` değişiklikleri:
- `countMode` enum'una **`safety`** eklenir.
- Yeni isteğe bağlı nesne **`safety`**:

```json
{ "handsUp": { "enabled": true, "seconds": 3 },     // seconds 3–5
  "lying":   { "enabled": true, "seconds": 10 },    // seconds 5–30
  "sendImage": false }
```

- Ek alan yok. `countMode = safety` iken anlamlıdır. Yoksa varsayılanlar geçerlidir: ikisi açık, 3 ve 10 sn, resim kapalı.
- Kırıcı değil: `v1` kalır.
- `docs/02-contracts.md` güncellenir.
- Python `Profile` ve Swift `ProductProfile`/`CountMode` alanı tanır. iPhone `safety` yöntemini katalogda göstermez; böyle bir profil açılırsa "Bu yöntem bu cihazda desteklenmiyor" der.
- Olay şeması değişmez.

**Hazır profil:** "Kuyumcu güvenliği":
- `countMode: safety`, `detectClasses: ["person"]`, `detectConfidence: 0,35`, `countAnchor: bottom`;
- `safety` varsayılanları; alan yok sayılır (alan kısıtı yok).

**Katalog:** yeni kategori `safety`:
- Başlık "Güvenlik", alt başlık "Eller yukarı ve yerde yatan kişi alarmı", `available: true`;
- hazır profil anahtarı `jeweler`.

## Analiz sunucusu (Python)
**Modüller:**
- `core/pose.py`: `PoseEstimator` (MoveNet Thunder). Model indirme ve SHA doğrulama, kare kırpma, çıkarım, görüntüye geri çevirme → `Pose(keypoints: (17,3))`, piksel (x, y, güven). Ayrıca paylaşılan kilitli sarmalayıcı.
- `core/pose_rules.py`: saf fonksiyonlar `scale`, `hands_up`, `lying` (kare kararları) ve `EpisodeTracker` (iz/tür bölüm durum makinesi, GRACE, T). Saf olduğu için birim testli.
- `core/safety.py`: `SafetyAnalyzer.process(frame, profile, ts)`. YOLOX + `MotTracker` + poz + kurallar → `SafetyResult` içinde izler, pozlar, aktif bölümler ve bu karede doğan alarmlar.
- `core/pipeline.py`: `countMode == "safety"` için `_process_safety`. Sayım yok; `FrameResult.safety` dolar.
- `overlay.py`: `draw_safety`. İskelet çizgileri; alarm veren iz kırmızı kutu ve etiket ("ELLER YUKARI" / "YERDE").
- `live/alarms.py`: `AlarmStore`.
  - `<data>/live/alarms.json` ve `<data>/live/alarm-images/<id>.jpg`.
  - Kayıt: `{id, sessionId, camera, type: "hands_up"|"lying"|"test", startedAt, firedAt, endedAt, acked, notify: "disabled"|"queued"|"sent"|"failed"|"suppressed", image, clip, clipStartedAt, falseAlarm}`.
  - 7 günden eski kayıtlar, resimleri ve olay kayıtlarıyla (`alarm-clips/<id>.webm`) mevcut temizlik iş parçacığında silinir.
- `live/notify.py`: `TelegramNotifier`.
  - Ayar `<data>/live/notify.json` = `{enabled, chatId}`; bot anahtarı `secrets.json`'da (`telegram` anahtarı). API hiçbir yanıtta anahtarı döndürmez (`hasToken`).
  - Gönderim: `sendPhoto` (kamerada `sendImage` açık ve resim var) ya da `sendMessage`, httpx.
  - Hata iletilerinde ve günlükte anahtar maskelenir (URL'de geçer).
  - Çevrimdışı kuyruk `<data>/live/outbox.json`; arka plan iş parçacığı artan beklemeyle yeniden dener (5 sn → 5 dk), 24 saatten eski bildirim `failed` olur.
- `live/session.py`: güvenlik oturumunda alarmlar `AlarmStore`'a yazılır. Olay resmi = o karenin işaretli görüntüsü (JPEG); HER ZAMAN `AlarmStore`'a yazılır (7 gün), Telegram'a yalnızca `sendImage` açıksa gider. Bildirim kuyruğa alınır.

**Mesaj:** `🚨 ELLER YUKARI — <kamera adı> · 06.10.2026 15:42:07`; yerde yatma için `🚨 YERDE YATAN KİŞİ — …`; test için `🧪 DENEME ALARMI — …`.

**API** (`/api/v1/live`):

| Yöntem | Yol | Açıklama |
|---|---|---|
| `GET` | `/alarms?active=&since=` | Son alarmlar (yeniden eskiye); `active=1` yalnızca onaylanmamışlar |
| `POST` | `/alarms/{id}/ack` | "Gördüm" |
| `GET` | `/alarms/{id}/image.jpg` | Olay resmi (7 gün) |
| `POST` | `/alarms/test` | Deneme alarmı `{sessionId?}`: oturum varsa onun son karesiyle; kayıt, panel şeridi ve (yapılandırılmışsa) Telegram |
| `GET` / `PUT` | `/notify` | `{enabled, chatId, hasToken}` / `{enabled, chatId, token?}` (token `null`: korunur, `""`: silinir) |
| `POST` | `/notify/test` | Telegram deneme mesajı; hata Türkçe ve anahtarsız |

Durum (`/sessions`): güvenlik oturumunda `safety: {active: [{type, trackId, seconds}], lastAlarmAt, model, modelError, detector, detectorError, processingError, lastOkAt, healthy, reason, unhealthyFor}` (model ve sağlık alanları: bkz. "Değişiklikler").

## Web paneli
- **Başlatma:** "Canlı sayımı başlat"ta "Güvenlik" kategorisi ve "Kuyumcu güvenliği".
- **Ayarla paneli** (güvenlik oturumunda):
  - Eller yukarı aç/kapa + süre (3–5);
  - Yerde yatan kişi aç/kapa + süre (5–30);
  - alan düzenleyicisi yok (alan kısıtı yok);
  - "Olay resmini Telegram'a gönder" (kapalı, açıklamalı).
  - Kaydet kamera başına.
- **Canlı:** iskeletli akış; yan panelde "İzleniyor" durumu, aktif bölümler ve son 10 alarm (saat, tür, küçük resim, bildirim durumu).
- **Alarm şeridi:** panel düzeninde (her sayfada).
  - 2 sn'de bir `GET /alarms?active=1`.
  - Kırmızı şerit "🚨 Eller yukarı — Tezgah kamerası · 15:42:07"; tıklayınca o kamera açılır; "Gördüm" ile kapanır.
  - Kamera kartında kırmızı işaret.
  - **Ses isteğe bağlı, varsayılan kapalı** (Bildirimler › "Bu tarayıcıda"; bkz. "Değişiklikler").
- **Bildirimler sayfası** (kenar çubuğu):
  - bot anahtarı (parola alanı, "kayıtlı" gösterimi), sohbet/grup kimliği, aç/kapa;
  - "Deneme mesajı gönder", "Deneme alarmı";
  - BotFather ile bot oluşturma ve sohbet kimliğini bulma adımları (Türkçe).

## Hata ve sınır durumları
- **Poz modeli yüklenemiyor:** oturum "Poz modeli yüklenemedi: <neden>" mesajıyla işlemeyi sürdürür (görüntü akar, alarm yok); durum panelde görünür.
- **Telegram:** anahtar ya da sohbet kimliği yanlışsa deneme mesajı Türkçe hata verir. Alarm bildirimi `failed` olur; panel kaydı yine oluşur.
- **İnternet yok:** bildirim kuyrukta kalır (`queued`), gelince gönderilir.
- **Eksik eklem:** karar yok (`None`); kısa ise affedilir, uzunsa bölüm biter. Belirsizlikte alarm verilmez.
- **Disk:** resimler ve olay kayıtları 7 günde silinir (olay kaydı dosyası en çok 500); günlük satırları da 7 günden eskiyse budanır.

## Test
**Python birim:**
- `pose_rules`:
  - eller yukarı: iki el baş üstü, teslim (dirsek omuz hizası), tek el, tek el rafa uzanma, kalçasız (tezgah arkası) ölçek, eksik bilek → `None`;
  - yerde yatma: yatay, kameraya doğru (baş kalça altında), eğilme, çömelme, oturma, kalçasız → `None`;
  - `EpisodeTracker`: T eşiği, GRACE affı, uzun kopma bitişi, iz kaybı, bölüm başına tek alarm.
- `alarms`/`notify`: sahte Telegram sunucusu (httpx MockTransport):
  - mesaj ve resim biçimi;
  - kuyruk ve yeniden deneme;
  - 24 saat `failed`;
  - anahtar hiçbir API yanıtında yok, hata metninde maskeli;
  - tekrar önleme 60 sn;
  - 7 gün temizliği.
- `pose`: kare kırpma ve geri çevirme saf birim testleri (sentetik çıktı dizisi); ONNX çevirisinin orijinal modelle eşleştiği `tools/convert_movenet.py` doğrulamasıyla.
  - Model dosyası CI'da indirilebiliyorsa bir uçtan uca çıkarım testi.
  - Lisansı uygun, depoya konabilir küçük bir kişi görüntüsü yoksa bu test modeli yalnızca yükler ve çıktı şeklini doğrular.
- API: uç noktalar, deneme alarmı, `PUT notify` anahtar koruma/silme.

**Panel e2e:**
- Güvenlik oturumu (test klibi) başlar, iskelet katmanı çizilir.
- Bildirimler sayfası: anahtarsız kaydet, "Deneme alarmı" → kırmızı şerit ve son alarmlarda kayıt → "Gördüm" ile kapanır.

**Gerçek ölçüm:** `tools/eval_pose.py VIDEO --profile … --labels VIDEO.pose.json`.
- Etiket: `[{"t": sn, "type": "hands_up"|"lying"}]` ve normal hareket süresi.
- Rapor: tür başına yakalama (T + 2 sn içinde), yanlış alarm / 8 saat.
- Kayıtlar kullanıcının; repoya konmaz.

## Gizlilik (KVKK)
- Görüntü bilgisayarda işlenir.
- Olay resmi **ve olay kaydı (video: alarmdan 8 sn önce, 4 sn sonra, en çok 10 kare/sn)** yalnızca bilgisayarda durur: 7 gün, en çok 500 kayıt dosyası.
- Telegram'a video hiçbir zaman gitmez; resim yalnızca kullanıcı açarsa gider (kamera başına `sendImage`).
- Bot anahtarı yalnızca bu bilgisayarda (`secrets.json`).
- Mağazada mevcut kamera uyarı levhası yeterlidir; alarm kişiyi tanımaz, yalnızca duruşa bakar.

## Değişiklikler (2026-10-07/08)
Uygulama sırasında, ilk gerçek kamera denemesinden ve son incelemeden sonra alınan kullanıcı kararları ve bunlardan doğan değişiklikler. Yukarıdaki bağlayıcı kurallar ve satırlar bu bölüme göre güncellendi; çelişki varsa bu bölüm kazanır.

**Kullanıcı kararları**
- **Alan kısıtı yok (2026-10-07).** Kural karedeki herkese uygulanır; profildeki alan (ROI/çokgen) yok sayılır, sözleşme `roi` alanını hâlâ kabul eder. Ayarla panelinde alan düzenleyicisi ve alan ipucu yoktur; canlı akış iskeletiyle yerinde kalır.
- **Daha profesyonel alarm; ihlal anının kaydı ekranda (2026-10-07).** Kullanıcı isteği: "Daha profesyonel bir yöntemle alarm verilebilmeli; ayrıca ihlalin olduğu zamandan kayıt görüntüsü ekrana gelmeli."
  - **Alarm penceresi:** yeni onaylanmamış alarmda her panel sayfasında kendiliğinden açılır; kırmızı başlık (tür, kamera, tarih-saat, "devam ediyor" ya da süre), ihlal anının kaydı, kayıt içinde "Durum başladı" ve "Alarm anı" zaman çizelgesi, düğmeler: Gördüm / Kamerayı aç / Yanlış alarm / Küçült. Birden çok alarmda gezinme.
  - **İhlal anının kaydı:** güvenlik kamerasının alarmdan 8 sn önceki ve 4 sn sonraki görüntüsü (en çok 10 kare/sn, VP8 WebM), `<data>/live/alarm-clips/<id>.webm`. Yalnızca bu bilgisayarda; 7 gün, en çok 500 dosya; Telegram'a hiç gitmez.
  - **Alarm kaydı:** `clip`, `clipStartedAt`, `falseAlarm` alanları. Yeni uç noktalar: `GET /alarms/{id}/clip.webm` (`Range` destekli) ve `POST /alarms/{id}/false-alarm`; `GET /alarms` süzgeçleri `until`, `type`, `limit` kazandı.
  - **Alarmlar sayfası:** geçmiş, kamera/tür/tarih/onay süzgeçleri, sayılar, aynı kayıt penceresi.
- **Ses isteğe bağlı (2026-10-07).** "Panelde ses yok" kararı güncellendi: alarm varsayılan olarak sessizdir; Bildirimler › "Bu tarayıcıda"dan sesli uyarı (iki tonlu bip, en çok 10 sn'de bir) ve masaüstü bildirimi açılabilir, ikisi de varsayılan kapalıdır. Sekme başlığı alarm varken yanıp söner (her zaman açık). Masaüstü bildirimi yalnızca `localhost` ya da https adresinde çalışır.
- **Eşikler gerçek kamera ölçümüyle ayarlandı (2026-10-07).** Ofiste yüksekte duran, eğik bakan bir kameranın karelerinde klasik teslim duruşunda bilek omuzun yalnızca 0,19–0,37·s üstünde, dirsek omuzun 0,14·s altına kadar görüldü; bu yüzden eller yukarı eşikleri `0,35 / 0,15` yerine `WRIST_UP = 0,20·s`, `ELBOW_DOWN = 0,30·s` oldu. Alarm vermiş bölüm için `FIRED_GRACE_S = 3 sn` kopma affı eklendi (aynı olay iki kez alarm vermişti). Yanlış alarma etkisi kabul ölçümünde (kamera başına ≥ 1 saat normal hareket) ölçülecek; şimdilik doğruluk iddiası yok.

**Diğer değişiklikler**
- **Olay resmi her zaman saklanır** (bu belgenin "Olay resmi bilgisayarda 7 gün saklanır" kararıyla uyumlu): `sendImage` yalnızca Telegram'a fotoğraf gidip gitmeyeceğini belirler.
- **İzleme sağlığı.** Oturum durumunda `safety` alanı: `{active, lastAlarmAt, model, modelError, detector, detectorError, processingError, lastOkAt, healthy, reason, unhealthyFor}`. Kart "Nöbette" yazısını yalnızca kamera gerçekten izlenirken gösterir (canlı, iki model hazır, işleme hatası yok, son 10 sn'de kare işlendi); aksi halde "Uyarı" ve neden. 60 sn'den uzun süre izlenmeyen güvenlik kamerası için alarm şeridinde sarı uyarı.
- **Yeniden başlatma.** Güvenlik oturumları `<data>/live/watch.json`'a yazılır ve analiz sunucusu yeniden başlayınca kendiliğinden yeniden izlemeye alınır; açılışta önceki çalışmadan "devam ediyor" kalmış alarmlar kapatılır. Analiz sunucusunun Windows oturumu açılınca kendiliğinden başlaması bu kapsamda yoktur.
- **Kişi tanıma modeli** poz modeliyle aynı düzende yüklenir: ortak zaman aşımlı indirme yardımcısı, arka planda yükleme, 60 sn yeniden deneme; hata metinleri Türkçe.
- **Telegram hataları.** Kalıcı hatalar (400, 401, 403, 404) alarmı hemen `failed` yapar ve Türkçe ileti verir; ağ hataları, zaman aşımı, 429 ve 5xx yeniden denenir (ağ yokken bir tur ilk ağ hatasında durur). Son gönderim hatası (`lastError`) Bildirimler sayfasında görünür. Kayıtlı anahtar sayfadan silinebilir.
- **Dosya adları.** Alarm günlüğü `alarms.json`, Telegram kuyruğu `outbox.json` (önceki taslaktaki `.jsonl` yazımı terk edildi).
- **Ölçüm aracı.** `tools/eval_pose.py --manifest`: birden çok kayıt ve kamera; yakalama toplanır, yanlış alarm kamera başına sınanır; etiketlerde isteğe bağlı `end`; aynı olayın içindeki ikinci alarm "tekrar" olarak ayrı sayılır.
