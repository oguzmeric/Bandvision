# 13 — Web platformu: canlı izleme ve video analizi

Kullanıcı isteği (2026-10-02): telefonda yaptığımız canlı analiz ve galeriden çalıştırdığımız video analizi **web'den** de görülebilmeli ve yapılabilmeli.
`06-backend-dashboard.md` (F3) planının üzerine kurulur; o dokümandaki şema/ingest/OEE geçerlidir.

## Kararlar (kullanıcı, 2026-10-02)
| Konu | Karar |
|---|---|
| Canlı görünüm | **Sayılar + işaretli anlık kare.** Sayaç, grafik, OK/NOK, NOK fotoğrafları ve birkaç saniyede bir güncellenen işaretli anlık kare; anlık kare **hat bazında açılıp kapatılır** (varsayılan kapalı — "görüntü cihazdan çıkmaz" ilkesi). Kesintisiz video akışı yok. |
| Barındırma | **Şimdilik yayın yok** (kullanıcı, 2026-10-04): demolar yerel bilgisayarda; yayın müşteri netleşince. Öneri: panel Vercel, analiz sunucusu küçük bir sunucuda (uzun işler, büyük yükleme, kalıcı disk Vercel'e uymaz). |
| Erişim | **Tek şifre** (`DASHBOARD_PASSWORD`): tanımlıysa tüm sayfalar ve API giriş ister; girişsiz istekte aynı adreste giriş formu (yeniden yazma), API 401. Kullanıcı hesapları W4'te. |
| Yüklenen video saklama | **7 gün** sonra video ve işaretli video otomatik silinir; analiz özeti kalır. |

## Mimari
```
iPhone / edge ──olaylar (+isteğe bağlı anlık kare)──► Supabase (ingest, Postgres, Storage, Realtime)
                                                              │
Tarayıcı ◄──── Next.js paneli (apps/dashboard) ◄──────────────┘
   │  video yükle                     ▲ iş durumu, sonuç dosyaları
   └────────► Analiz sunucusu (services/edge, bantvision.analyzer, FastAPI) ─ Python referans çekirdeği
```
- **Analiz sunucusu**, telefondaki ve masaüstündeki ile **aynı Python referans çekirdeğini** kullanır (`bantvision.video`): otomatik kalibrasyon, sayım, işaretli video, özet, CSV. Tarayıcı oynatabilsin diye işaretli video **H.264 (yuv420p, faststart)** olarak üretilir.
- İşler tek tek işlenir (CPU yoğun), kuyruk diskte kalıcıdır; sunucu yeniden başlarsa yarım kalan iş "başarısız: sunucu yeniden başladı" olur, kullanıcı yeniden başlatır.
- Saklama: `ANALYZER_RETENTION_DAYS` (varsayılan 7); süresi dolan işin dosyaları silinir, iş kaydı `expired` olarak özetiyle kalır.

## Sözleşmeler
- **Analiz işi:** `contracts/analysis-job.schema.json` (`bantvision.analysis-job.v1`), `02-contracts.md` §7.
- **Anlık kare (canlı):** W3'te `event.schema.json`'a eklenecek; önce sözleşme, sonra uygulamalar.

## Analiz sunucusu API (v1)
| Yöntem | Yol | Açıklama |
|---|---|---|
| `POST` | `/api/v1/jobs` | `multipart/form-data`: `file` (video), `options` (JSON, isteğe bağlı: `preset`, `countMode`, `productLength`, `truth`, `direction`, `roi`, `roiPolygon`, `line`, `countLine`, `bgRange`). `202` + iş |
| `GET` | `/api/v1/jobs` | Son işler (yeniden eskiye) |
| `GET` | `/api/v1/jobs/{id}` | İş: durum, ilerleme, sonuç |
| `GET` | `/api/v1/jobs/{id}/files/{ad}` | `annotated.mp4`, `counts.csv`, `profile.json`, `background.png` |
| `DELETE` | `/api/v1/jobs/{id}` | İşi ve dosyalarını sil (sürüyorsa iptal) |
| `GET` | `/healthz` | Sağlık |

Güvenlik: `ANALYZER_TOKEN` tanımlıysa `Authorization: Bearer <token>` zorunlu (panelin sunucu tarafı çağırır; tarayıcıya verilmez). Yükleme sınırı `ANALYZER_MAX_UPLOAD_MB` (varsayılan 2048), video olmayan dosya reddedilir. CORS: `ANALYZER_CORS_ORIGINS`.

## Canlı sayım: kamera ve kayıt cihazı (panel, `bantvision/live`)
Kullanıcı isteği (2026-10-05): telefondaki ağ kamerası / NVR eklentileri ve canlı sayım web'de de olsun; ofis NVR'ından görüntü alınıp yerelde test edilebilsin.
- **Nerede çalışır:** analiz sunucusu kameralarla **aynı ağdaki bilgisayarda** (ofis ağı ya da VPN). Görüntü yalnızca orada işlenir; panel işaretli akışı (MJPEG) aynı bilgisayardan alır. Telefondaki ile aynı Python referans çekirdeği (bant üstü ürün, şerit tarama, kişi sayımı §4.10).
- **Panel:** **Kameralar** (kayıt cihazı: TRASSIR / Hikvision / Dahua; IP kamera: marka şablonu ya da özel RTSP; kameralar küçük resimle, arama) → **Canlı sayımı başlat** (ne sayılacak: profil seç ya da hazır profilden ekle) → **Canlı sayım** (işaretli akış, sayaç ya da Giriş/Çıkış, Başlat/Durdur/Sıfırla, giriş yönünü çevir, CSV; **Kalibre/Ayarla**: ham kare üstünde alan ve çizgi düzenleyici, boş bandı / ürün boyunu öğren, `Kaydet` profili de saklar).
- **Kalıcı ayarlar** (`<ANALYZER_DATA_DIR>/live/`): `sources.json` (şifresiz), `secrets.json` (kamera şifreleri ve Telegram bot anahtarı; POSIX'te 0600), `profiles.json` (sözleşme `product-profile`; ilk açılışta telefondaki hazır profillerle) — **kameraya başlangıç şablonu**; `camera_profiles.json`: **kamera başına** kaydedilen ayar (`kaynak|kanal|profil` → profil). Canlı sayfada "Kaydet" yalnızca o kamerayı değiştirir (her kameranın sahnesi farklı; 2026-10-06'da bir kameranın alanı diğerine geçiyordu). Kaynak ya da profil silinince kamera ayarları da silinir. **Hiçbir API yanıtı şifre döndürmez** (`hasPassword` yalnızca var/yok); düzenlemede şifre boş bırakılırsa kayıtlı şifre korunur.
- **Oturumlar** bellekte (sunucu yeniden başlarsa kapanır). Okuyucu iş parçacığı her zaman en son kareyi tutar (RTSP TCP, kopunca artan beklemeyle yeniden bağlanır, TRASSIR jetonu her bağlanışta yenilenir); işleyici en son kareyi sayar, işaretli kare en çok 12/sn. Aynı kamera ikinci kez açılırsa eski oturum kapanır; kaynak silinince oturumları da kapanır.
- **Birden çok kamera** aynı anda sayılır (kullanıcı, 2026-10-06): canlı sayfada her kameranın kartı (Giriş/Çıkış ya da adet), Kameralar'da sayılan kamera "Sayılıyor". Kişi tanıma modeli **tek ve ortak** (kareler sırayla); boş sahnede (alanda hareket ve iz yok) tanıma atlanır, en geç saniyede bir yine çalışır → işlemci kişinin olduğu kameraya kalır. Bu atlama yalnızca canlıdadır; video analizi ve iPhone her karede tanır.
- **Alt / ana akış** oturum başına seçilir (başlatırken ve canlı sayfada). Değiştirince aynı oturum yeni akışa bağlanır; **sayaçlar sıfırlanmaz** (kare boyu değişirse bant sayımı arka planı yeniden öğrenir). Tam RTSP adresli kaynakta seçim yok.
- **RTSP zaman aşımı:** FFmpeg 5+ `stimeout`'u yok sayar; `timeout` kullanılır (kapalı kamerada açılış 30 sn → ~5 sn). Küçük resimde aynı anda en çok 2 RTSP açılışı; alınamayan kamera 1 dk yeniden denenmez.
- **Windows:** sunucu kendini güç kısmasından (verimlilik modu / EcoQoS) çıkarır (`live/power.py`); arka planda tanıma kare başına 65 ms'den ~350 ms'ye çıkıp canlı sayım 13'ten 2–3 kare/sn'ye düşüyordu. Sistem ayarı değişmez.
- **Test:** `ANALYZER_ALLOW_FILE_SOURCES=1` iken "Özel RTSP" adresine yerel video dosyası yazılabilir (başa sararak "kamera" gibi oynar). Yalnızca test/e2e içindir; bayraksız sunucu dosya okumaz.

| Yöntem | Yol (`/api/v1/live`) | Açıklama |
|---|---|---|
| `GET` | `/catalog` | Sayım türleri ve hazır profiller (telefondaki katalog) |
| `GET` `POST` | `/profiles` | Profiller; `POST {"preset": "people", "name"?}` ya da tam profil |
| `PUT` `DELETE` | `/profiles/{id}` | Profili güncelle / sil (son profil silinmez: `409`) |
| `GET` `POST` | `/sources` | Kaynaklar; `POST` kamera (`kind: camera`, `brand`, `host`, `port`, `channel`, `substream`, `customUrl`) ya da kayıt cihazı (`kind: recorder`, `recorderBrand`, `host`, `httpPort`, `rtspPort`) + `username`, `password` |
| `PUT` `DELETE` | `/sources/{id}` | Düzenle (`password: null` → korunur) / sil (şifre ve oturumlar da) |
| `GET` | `/sources/{id}/channels?refresh=` | Kayıt cihazındaki kameralar (önbellekli) |
| `GET` | `/sources/{id}/snapshot?channel=` | Küçük resim (JPEG) |
| `GET` `POST` | `/sessions` | Canlı oturumlar; `POST {sourceId, channelId?, profileId, substream?}` (aynı kamera yeniden açılırsa eskisi kapanır) |
| `GET` `DELETE` | `/sessions/{id}` | Durum (durum, fps, sayılar, `staffIn`/`staffOut`, kalibrasyon, profil; güvenlik oturumunda `safety: {active, lastAlarmAt, model}`) / kapat |
| `POST` | `/sessions/{id}/actions` | `{"action": "start" \| "stop" \| "reset" \| "learnBackground" \| "learnSample" \| "cancelCalibration"}` |
| `PUT` | `/sessions/{id}/stream` | `{"substream": true \| false}`: alt/ana akış; sayaçlar korunur |
| `PUT` | `/sessions/{id}/profile?save=` | Alan, çizgi, yön, yöntem; `save=true` **bu kamera için** kaydeder (şablon değişmez) |
| `POST` | `/sessions/{id}/staff-color` | `{x, y}` (0–1): tıklanan kişinin gövde rengi `{L, a, b, achromatic}`; `422` çok karanlık ("Burası çok karanlık; personelin üstüne tıklayın.") ya da koordinat aralık dışı, `503` kare yok. Profile eklemek `PUT profile` ile (`staffColors`, en çok 3; fazlası `422`) |
| `GET` | `/sessions/{id}/stream` | İşaretli MJPEG akışı |
| `GET` | `/sessions/{id}/frame.jpg` | Ham kare (alan düzenleyici için) |
| `GET` | `/sessions/{id}/counts.csv` | Sayım kaydı; personel geçişleri `personel_giris` / `personel_cikis` satırlarıdır (giriş/çıkış toplamlarına katılmaz) |
| `GET` | `/alarms?active=&since=&sessionId=` | Güvenlik alarmları (yeniden eskiye, en çok 50): `active=1` yalnızca onaylanmamışlar, `since` (epoch sn) o andan sonrakiler, `sessionId` yalnızca o kameranın alarmları. Kayıt: `{id, sessionId, camera, type: "hands_up" \| "lying" \| "test", startedAt, firedAt, endedAt, acked, notify: "disabled" \| "queued" \| "sent" \| "failed" \| "suppressed", image}` |
| `POST` | `/alarms/{id}/ack` | "Gördüm": alarm onaylanır (`404` yoksa) |
| `GET` | `/alarms/{id}/image.jpg` | Olay resmi (resim gönderimi açıkken var, 7 gün); yoksa `404` |
| `POST` | `/alarms/test` | `{sessionId?}`: deneme alarmı (`type: "test"`); kayıt, panel şeridi ve (yapılandırılmışsa) Telegram; tekrar önlemeye tabi değil |
| `GET` | `/notify` | `{enabled, chatId, hasToken}`; bot anahtarı hiçbir yanıtta dönmez |
| `PUT` | `/notify` | `{enabled, chatId, token?}`: `token` `null` → kayıtlı anahtar korunur, `""` → silinir; biçimi geçersiz anahtar `422` (Türkçe ileti, anahtar yankılanmaz) |
| `POST` | `/notify/test` | Telegram deneme mesajı gönderir; hata (anahtar ya da sohbet kimliği yanlış, ağ yok) `422`, Türkçe ve anahtarsız |

**Güvenlik alarmı ve Bildirimler** (isteğe bağlı, kamera başına; algoritma `03-algorithm.md` §4.11): **Canlı sayımı başlat**ta **Güvenlik** kategorisi, hazır profil **Kuyumcu güvenliği** (`countMode: "safety"`). Kamera eller yukarı ve yerde yatan kişiyi izler, sayım yapmaz; yalnızca bilgisayarda çalışır (iPhone profili tanır ama çalıştırmaz, "Yalnızca bilgisayarda" der). **Ayarla** panelinde kamera başına kurallar (eller yukarı 3–5 sn, yerde yatan kişi 5–30 sn; aç/kapa ve süre), alan ve "Olay resmini Telegram'a gönder" (varsayılan kapalı) kaydedilir. Canlı sayfada iskeletli akış, yan panelde "İzleniyor", süren durumlar ve son 10 alarm (saat, tür, küçük resim, bildirim durumu) görünür.
- **Poz modeli** arka planda yüklenir: `safety.model` `loading` / `ready` / `error`. Hazır olana kadar ya da indirilemezse görüntü akar, alarm olmaz; panel durumu gösterir, hata sonrası 60 sn'de yeniden denenir.
- **Alarm şeridi** her panel sayfasında 2 sn'de bir onaylanmamış alarmları çeker (kırmızı şerit: tür, kamera, saat; "Kamerayı aç", "Gördüm"; ses yok). Üst üste 3 istek başarısız olursa (≈ 6 sn) şeritte sarı uyarı satırı çıkar: "Oturum süresi doldu …" (yeniden giriş bağlantısıyla) ya da "Alarmlar alınamıyor …" (analiz sunucusuna ulaşılamıyor); Telegram kapalıyken şerit çoğu zaman tek alarm kanalıdır, kopma sessiz kalmamalı.
- **Bildirimler** sayfası (kenar çubuğu): Telegram kurulumu. Bot anahtarı (parola alanı; kayıtlıysa "Anahtar kayıtlı"), sohbet/grup kimliği, "Bildirimler açık", **Deneme mesajı gönder**, **Deneme alarmı**; BotFather ile bot oluşturma ve sohbet kimliğini bulma adımları sayfada Türkçe yazılıdır.
- **Telegram anahtarı** yalnızca `secrets.json`'da (`telegram`) durur; biçimi `rakam:[A-Za-z0-9_-]+` olmalıdır. Ayar `notify.json` (`{enabled, chatId}`). Hiçbir API yanıtında yoktur (`hasToken`), hata iletilerinde ve günlükte (`httpx` dahil) maskelidir. Doğrulama (`422`) yanıtları gönderilen değeri geri yankılamaz: `detail` listesinde yalnızca `type`, `loc`, `msg` kalır (uygulama geneli; yanlış biçimli anahtar ya da şifre yanıtta dönmesin).
- **Mesaj:** `ELLER YUKARI — <kamera adı> · gg.aa.yyyy ss:dd:ss` (başında alarm simgesi; yerde yatma için `YERDE YATAN KİŞİ`, deneme için `DENEME ALARMI`). `sendMessage`; olay resmi açıksa `sendPhoto`.
- **Olay resmi** yalnızca kamerada "Olay resmini Telegram'a gönder" açıksa üretilir: o karenin işaretli (iskeletli) görüntüsü Telegram'a gider ve bilgisayarda `alarm-images/` altında **7 gün** saklanır (`image.jpg`, panelde küçük resim); resim ve alarm kaydı 7 günü geçince saatlik temizlikte silinir. Kapalıyken (varsayılan) yalnızca kamera adı ve saat gider, resim saklanmaz. Görüntü bilgisayardan başka yere çıkmaz.
- **Tekrar önleme:** aynı kamerada aynı tür için son gönderilen bildirimden sonra **60 sn** içinde doğan alarm günlüğe ve panele yazılır, Telegram'a gitmez (`suppressed`); deneme alarmı bu kurala tabi değildir.
- **Çevrimdışı kuyruk:** bildirimler `outbox.json`'da sıralanır (`queued`); gönderilemezse bekleme 5 sn'den 5 dk'ya artarak yeniden denenir, 24 saat sonra `failed` olur; kuyruk sunucu yeniden başlayınca korunur. Bildirimler kapalıyken (ya da anahtar/sohbet kimliği yokken) hiçbir şey gönderilmez; kayıtlar bildirimler açılana ya da süre dolana kadar bekler. İnternet yokken panel alarmı yine görünür.

**Personel rengi** (isteğe bağlı, kamera başına; algoritma `03-algorithm.md` §4.10 eki): **Ayarla** panelinde "Personel rengi" bölümünden öğretilir (ham karede kişiye tıkla, en çok 3 renk). Renk öğretilmişse sayaç kartında "Personel geçişi" (`staffIn` + `staffOut`) görünür; personel geçişi olay olarak gönderilmez. Renk akromatik/koyuysa arayüz uyarı gösterir (sayımı etkilemez).

Panel bu API'ye `/api/live/...` vekili üzerinden gider (sunucu tarafı; `ANALYZER_TOKEN` tarayıcıya verilmez). Testler: `services/edge/tests/test_live.py`, `test_recorders.py`, `test_alarms.py`, `test_notify.py`; tarayıcıda `apps/dashboard/e2e/live.spec.ts`, `safety.spec.ts`, `safety-ui.spec.ts`.
Yerelde çalıştırma: `tools/panel_baslat.bat` (analiz sunucusu + panel, **Kameralar** sayfasını açar).

## Fazlar
| Faz | İçerik | Kabul |
|---|---|---|
| **W1** | Analiz sunucusu (FastAPI) + sözleşme + testler; Dockerfile | Test klibi yüklenir → sayım Python referansıyla aynı, işaretli H.264 video, CSV; 7 gün kuralı test edilir |
| **W2** ✅ | `apps/dashboard` (Next.js 15): **Video analizi** sayfası — yükle, ilerleme, işaretli video oynatıcı, sayım/doğruluk, CSV indir, geçmiş. Çalıştırma: `apps/dashboard/README.md` | Tarayıcıda uçtan uca (Playwright, CI `dashboard` işi) |
| **W3** | Canlı: Supabase yerel (Docker), ingest, iPhone olay gönderimi (outbox), hat başına isteğe bağlı anlık kare; panelde **Hatlar** ve hat sayfası (Realtime) | iPhone'dan sayım panelde ≤ 5 sn'de görünür; anlık kare kapalıyken hiç görüntü gitmez |
| **W4** | NOK galerisi, raporlar, barındırma (karar sonrası), giriş/organizasyon | `06` kabul kriterleri |
