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
- Ofiste: **TRASSIR NeuroStation 64 kanal**, yazılım `Trassir-4.7.4.2-1268296-NeuroStation-64-Release`, 8 kamera bağlı.
- Piyasada kayıt cihazları çoğunlukla TRASSIR, Dahua, Hikvision; 4/8/16/32/64/128 kanal.

## iPhone'dan TRASSIR (uygulandı: `04-ios-app.md` §1g)
Telefon, TRASSIR SDK'sı üzerinden kanal listesini ve kısa ömürlü jetonla RTSP akışını alır (seçenek A'nın telefondaki karşılığı).
Kaynak: resmi SDK dokümanı — [Getting video and audio streams](https://storage.trassir.com/manual/en/sdk-examples-video.html),
[SDK ayarı](https://storage.trassir.com/manual/en/setup-sdk-setup.html), [Oturum](https://storage.trassir.com/manual/en/sdk-examples-id.html),
[Kanal listesi](https://storage.trassir.com/manual/en/sdk-examples-channels.html).

## Açık sorular
1. ~~TRASSIR sunucusu kanal başına RTSP yeniden yayını sunuyor mu? URL biçimi ve kimlik doğrulama?~~
   **Dokümana göre evet** (gerçek cihazda henüz doğrulanmadı): SDK açıkken (Ayarlar → Web sunucusu (SDK), port 8080, SDK şifresi dolu)
   `https://sunucu:8080/login?username=&password=` → `sid` (15 dk) → `/channels?sid=` → `/get_video?channel=<guid>&container=rtsp&stream=main|sub&sid=`
   → `token` (~10 sn, istek geldikçe yaşar; `http://sunucu:555/<token>?ping`) → `rtsp://sunucu:555/<token>`. Video komutları kullanıcı oturumuyla
   (SDK şifresiyle değil) çalışır; kullanıcının ilgili kanallarda izleme yetkisi olmalı. Doğrulanacak: hata kodlarının metni, açık RTSP bağlantısının
   jeton süresi dolunca sürüp sürmediği, `container=jpeg` anlık görüntünün 555'ten nasıl alındığı, sertifika ve TLS sürümü.
2. Dahili script ortamının Python sürümü; harici paket (numpy, OpenCV) kurulabiliyor mu?
3. Script'ten ham kare (gri/BGR) erişimi var mı, hangi çözünürlük ve fps'te?
4. Dış sistemden TRASSIR'a olay/alarm yazmak için resmi API/SDK hangisi? Olaya görsel eklenebiliyor mu?
5. Olay zaman damgasından ilgili kanal arşivine bağlantı (deep link) üretilebiliyor mu?
6. Lisanslama: modül TRASSIR tarafında ayrı lisans gerektirir mi, dağıtım modeli ne olur?

## Kabul kriteri (taslak)
- TRASSIR'a bağlı bir kamerada edge servisi sayım yapıyor; her NOK, TRASSIR'da ilgili kamera üzerinde olay olarak görünüyor ve tıklayınca kayda gidiyor.
