# 08 — TRASSIR Entegrasyonu (doğrulama bekliyor)

TRASSIR kullanan müşterilerde ek kutu olmadan ya da mevcut sunucu altyapısıyla çalışmak hedeflenir. Aşağıdaki teknik varsayımlar **doğrulanmadı**; planlamadan önce kullanıcıya (TRASSIR deneyimi olan ekip) sorulmalı.

## Seçenekler
| Seçenek | Nasıl | Artı | Eksi |
|---|---|---|---|
| A. Edge, TRASSIR'dan akış alır | Edge servisi kameraya doğrudan ya da TRASSIR sunucusunun yeniden yayınından (varsa) RTSP ile bağlanır | Çekirdek değişmez; en hızlı yol | Ayrı kutu; kamera bağlantı sayısı limiti |
| B. TRASSIR script modülü | Sayım/QC, TRASSIR'ın dahili Python script ortamında çalışır | Ek donanım yok; TRASSIR arayüzünde yaşar | Script ortamında numpy/OpenCV olup olmadığı, CPU payı ve kare erişimi belirsiz |
| C. Olayları TRASSIR'a geri besleme | Edge sonuçları TRASSIR'a olay/alarm olarak yazılır (SDK/HTTP API) | Operatör tek ekrandan görür; NOK anında ilgili kamera kaydına atlama | API yetenekleri doğrulanmalı |

Önerilen sıra: **A + C** (çekirdek aynı kalır, operatör deneyimi TRASSIR içinde), B ancak script ortamı yeterliyse.

## Açık sorular
1. TRASSIR sunucusu kanal başına RTSP yeniden yayını sunuyor mu? URL biçimi ve kimlik doğrulama?
2. Dahili script ortamının Python sürümü; harici paket (numpy, OpenCV) kurulabiliyor mu?
3. Script'ten ham kare (gri/BGR) erişimi var mı, hangi çözünürlük ve fps'te?
4. Dış sistemden TRASSIR'a olay/alarm yazmak için resmi API/SDK hangisi? Olaya görsel eklenebiliyor mu?
5. Olay zaman damgasından ilgili kanal arşivine bağlantı (deep link) üretilebiliyor mu?
6. Lisanslama: modül TRASSIR tarafında ayrı lisans gerektirir mi, dağıtım modeli ne olur?

## Kabul kriteri (taslak)
- TRASSIR'a bağlı bir kamerada edge servisi sayım yapıyor; her NOK, TRASSIR'da ilgili kamera üzerinde olay olarak görünüyor ve tıklayınca kayda gidiyor.
