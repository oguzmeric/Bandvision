# 08 — TRASSIR Entegrasyonu (doğrulama bekliyor)

TRASSIR kullanan müşterilerde ek kutu olmadan ya da mevcut sunucu altyapısıyla çalışmak hedeflenir. Aşağıdaki teknik varsayımlar **doğrulanmadı**; planlamadan önce kullanıcıya (TRASSIR deneyimi olan ekip) sorulmalı.

## Seçenekler
| Seçenek | Nasıl | Artı | Eksi |
|---|---|---|---|
| A. Edge, TRASSIR'dan akış alır | Edge servisi kameraya doğrudan ya da TRASSIR sunucusunun yeniden yayınından (varsa) RTSP ile bağlanır | Çekirdek değişmez; en hızlı yol | Ayrı kutu; kamera bağlantı sayısı limiti |
| B. TRASSIR script modülü | Sayım/QC, TRASSIR'ın dahili Python script ortamında çalışır | Ek donanım yok; TRASSIR arayüzünde yaşar | Script ortamında numpy/OpenCV olup olmadığı, CPU payı ve kare erişimi belirsiz |
| C. Olayları TRASSIR'a geri besleme | Edge sonuçları TRASSIR'a olay/alarm olarak yazılır (SDK/HTTP API) | Operatör tek ekrandan görür; NOK anında ilgili kamera kaydına atlama | API yetenekleri doğrulanmalı |

Önerilen sıra: **A + C** (çekirdek aynı kalır, operatör deneyimi TRASSIR içinde), B ancak script ortamı yeterliyse.

## Saha bilgisi (kullanıcı, 2026-10-02)
- Hedef: TRASSIR kayıt cihazları (yazılım 4.x); sahada TRASSIR, Dahua ve Hikvision yaygın; 4/8/16/32/64/128 kanal.

## iPhone'dan TRASSIR (uygulandı: `04-ios-app.md` §1g)
Telefon, TRASSIR SDK'sı üzerinden kanal listesini ve kısa ömürlü jetonla RTSP akışını alır (seçenek A'nın telefondaki karşılığı).
Kaynak: resmi SDK dokümanı — [Getting video and audio streams](https://storage.trassir.com/manual/en/sdk-examples-video.html),
[SDK ayarı](https://storage.trassir.com/manual/en/setup-sdk-setup.html), [Oturum](https://storage.trassir.com/manual/en/sdk-examples-id.html),
[Kanal listesi](https://storage.trassir.com/manual/en/sdk-examples-channels.html).

## Açık sorular
1. ~~TRASSIR sunucusu kanal başına RTSP yeniden yayını sunuyor mu? URL biçimi ve kimlik doğrulama?~~
   **Evet — gerçek bir TRASSIR (4.x) kayıt cihazında doğrulandı (2026-10-02, derleme 13):** SDK girişi, kanal listesi, jetonlu RTSP
   ile canlı yayın çalıştı; alt akış 704×576 (D1) H.264. Not: D1 görüntüde pikseller kare değildir (görüntü yatayda basık görünür);
   sayımı etkilemez, ölçüme dayalı QC'de (F4/A2: boy, en-boy) piksel en-boy oranı hesaba katılmalı. Henüz gözlenmedi: uzun süreli
   yayında jetonun canlı kalması (`?ping`), küçük görüntülerin `container=jpeg` ile gelip gelmediği. Ayrıntılar: SDK açıkken (Ayarlar → Web sunucusu (SDK), port 8080, SDK şifresi dolu)
   `https://sunucu:8080/login?username=&password=` → `sid` (15 dk) → `/channels?sid=` → `/get_video?channel=<guid>&container=rtsp&stream=main|sub&sid=`
   → `token` (~10 sn, istek geldikçe yaşar; `http://sunucu:555/<token>?ping`) → `rtsp://sunucu:555/<token>`. Video komutları kullanıcı oturumuyla
   (SDK şifresiyle değil) çalışır; kullanıcının ilgili kanallarda izleme yetkisi olmalı. Doğrulanacak: hata kodlarının metni, açık RTSP bağlantısının
   jeton süresi dolunca sürüp sürmediği, `container=jpeg` anlık görüntünün 555'ten nasıl alındığı, sertifika ve TLS sürümü.
2. Dahili script ortamının Python sürümü; harici paket (numpy, OpenCV) kurulabiliyor mu?
3. Script'ten ham kare (gri/BGR) erişimi var mı, hangi çözünürlük ve fps'te?
4. Dış sistemden TRASSIR'a olay/alarm yazmak için resmi API/SDK hangisi? Olaya görsel eklenebiliyor mu?
5. ~~Olay zaman damgasından ilgili kanal arşivine bağlantı (deep link) üretilebiliyor mu?~~
   **Panel tarafında yanıtlandı (2026-11-08, kayıttan izleme paketi):** TRASSIR istemcisine bağlantı yerine BandVision panelinin kendi
   arşiv oynatıcısı kullanılır: `/archive?source=<kaynak>&channel=<kanal>&t=<epoch sn>`. Alarm penceresindeki "Kayıt cihazında izle" bu
   bağlantıyı alarm anından 10 sn önceye açar (`13-web-platform.md` "Kayıttan izleme"). TRASSIR'ın kendi istemcisinde olaya bağlantı
   (seçenek C) ayrı konu olarak açık kalır (soru 4 ile birlikte).
6. Lisanslama: modül TRASSIR tarafında ayrı lisans gerektirir mi, dağıtım modeli ne olur?

## Kayıttan izleme: arşiv SDK uçları (2026-11-08)
Panelin "Kayıttan izleme" sayfası (`13-web-platform.md` "Kayıttan izleme") TRASSIR arşivini SDK üzerinden oynatır. Uçlar resmi SDK
belgesinden alındı; sahte NVR'da (testler) çalışıyor, **ofis NVR'ında doğrulama BEKLİYOR**. Tüm istekler canlıdaki gibi kullanıcı
oturumunun `sid`'iyle gider; oturum hatasında bir kez yeniden giriş yapılır. Zaman biçimi bu bilgisayarın yerel saatidir (cihazın aynı
saat diliminde olduğu varsayılır).

| İş | Uç | Not |
|---|---|---|
| Arşiv jetonu | `/get_video?channel=<guid>&container=rtsp&stream=archive_main\|archive_sub&sid=` | Canlıdaki `token` gibi; akış `rtsp://sunucu:555/<token>`, açıkken `?ping` ile canlı tutulur |
| Oynat | `/archive_command?command=play&start=YYYYMMDDTHHMMSS&stop=…&speed=<1\|2\|4\|8\|16>&token=&sid=` | Hız cihazda (atlar); duraklat, sürdür, sar ve hız değişimi = `stop` + yeni jetonla yeni `play` |
| Durdur | `/archive_command?command=stop&token=&sid=` | Tek istek, yinelenmez (ölü jeton paylaşılan oturumu bozmasın) |
| Takvim | `/archive_status?type=calendar&sid=` | `play` ile açılan jetonun yanıtı; `calendar` listesindeki `YYYY-MM-DD` dizgileri. Yanıt **jetonsuz** (oturumun tüm arşiv oynatmalarını döndürebilir): öğe `token` taşıyorsa bizimkine süzülür, çağrılar kaynak başına sıralanır |
| Çizelge | `/archive_status?type=timeline&sid=` | Gün başından gün sonuna `play` → `archive_status` (boşsa 0,5 sn arayla en çok 3 deneme) → `stop`. Yanıt `[{token, day_start: "YYYY-MM-DD", timeline: [{begin, end}]}]`, `begin`/`end` `day_start` gününün gece yarısından saniye; `day_start` istenen gün değilse boş liste + günlük uyarısı |
| Dışa aktarma | `POST /jit-export-create-task?sid=` `{resource_guid, start_ts, end_ts (µs), is_hardware: 0, prefer_substream: 0}` → `task_id`; `GET /jit-export-download?sid=&task_id=` | Cihaz hazırlarken MP4 dışı yanıt verirse 1 sn arayla en çok 20 deneme; dosya panelden tarayıcıya akıtılır, diske yazılmaz; en çok 30 dk, aynı anda tek görev |

**Ofis NVR'ında doğrulanacaklar** (salt okunur; sonuçlar `12-durum.md` §5l'ye):
- `archive_status` takvim ve çizelge yanıtının gerçek biçimi (alan adları, `day_start` davranışı: istenen günü mü yoksa oynatma konumunun gününü mü verir, gün sınırında ne olur), boş yanıt süresi.
- `play` sonrası ilk karenin gelme süresi; sarmada "3 sn içinde o andan sürer" hedefi.
- `speed` (2, 4, 8, 16) gerçekten cihazda atlıyor mu; konum hesabının (okunan kare / kare hızı × hız) cihazla uyumu.
- `stop` sonrası jetonun ve RTSP bağlantısının kapanması; duraklamada jetonun ölmesi ve sürdürmede yeni jetonla açılış.
- Arşiv jetonunun ömrü (`?ping` ile canlı kalıyor mu).
- `archive_status`'ün jetonsuz olması: aynı oturumda iki oynatma varken yanıt kimin? (`token` alanı geliyor mu).
- `jit-export` akışı: görevin hazırlanma süresi, hazır değilken yanıt, 2 dakikalık aralığın `.mp4` olarak inmesi, dosya adı/biçimi.

## Kabul kriteri (taslak)
- TRASSIR'a bağlı bir kamerada edge servisi sayım yapıyor; her NOK, TRASSIR'da ilgili kamera üzerinde olay olarak görünüyor ve tıklayınca kayda gidiyor.
