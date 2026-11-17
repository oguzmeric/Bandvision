# Alarm penceresi yenileme — tasarım

Tarih: 2026-11-17 · Durum: kullanıcı taslağı onayladı ("tamammdır"), birleşik düzen seçimi bana bırakıldı.

## Amaç ve neden

Kullanıcı panelin alarm ekranını "yangın videolarındaki açılır pencereler gibi daha profesyonel" istiyor. Taslak üzerinde
tek şartı: **açılır pencerede kameranın canlı görüntüsünden kesit olmalı** ("pop up da canlı görüntüden kesit vermemiz
gerek"). Bugün alarm penceresi yalnız olay kaydını (ya da olay resmini) gösteriyor; operatör olayın şu an sürüp
sürmediğini görmek için "Kamerayı aç"a gitmek zorunda.

Başarı: alarm gelince operatör tek bakışta (1) şu an kamerada ne olduğunu (canlı), (2) alarmı neyin tetiklediğini
(alarm anının yakın planı), (3) gerekirse alarm kaydını görür; kritik alarm ekranı kaplar, uyarı işi bölmez.

## Hedefler

1. **Önem düzeyine göre iki sunum** (birleşik düzen, benim kararım):
   - **Kritik** — yangın, duman, eller yukarı, yerde yatan kişi, deneme alarmı: ortada büyük pencere (bugünkü modal
     `<dialog>` yenilenir).
   - **Uyarı** — telefon kullanımı: sağ altta köşe kartı; modal değildir, sayfayı kilitlemez.
2. **Görüntü alanı** (iki sunumda da): varsayılan **Canlı**; "● Canlı | Alarm kaydı" düğmesiyle kayda geçilir.
   - Canlı kaynak sırası: alarmın oturumu hâlâ varsa oturumun işaretli akışı (`/api/live/sessions/{sessionId}/stream`;
     iskelet ve alarm kutusu çizili), yoksa kameranın ham akışı (`/api/live/cameras/stream?source=&channel=&quality=sub`,
     alarmda `sourceId` varsa), ikisi de yoksa canlı yok: görüntü alanı doğrudan "Alarm kaydı"nda açılır ve "Canlı"
     düğmesi devre dışıdır ("Canlı görüntü yok" ipucu).
   - Canlı akış kopar/bağlanamazsa görüntünün üstünde "Canlı görüntü alınamıyor" yazar; "Alarm kaydı" çalışmaya devam eder.
   - **Alarm anı köşe penceresi** (Canlı'dayken): olay resminin (`image.jpg`) alarm kutusuna yakınlaştırılmış hâli ve
     alarm saati ("Alarm anı · 14:30:50 ▶"). Kutu yoksa (eski kayıt, deneme alarmı) resmin tamamı küçük gösterilir;
     resim yoksa köşe penceresi hiç çıkmaz. Kutunun merkezi görüntünün sağ yarısındaysa köşe penceresi sol alta, değilse
     sağ alta yerleşir (canlı görüntüdeki olay yerini kapatmasın). Tıklanınca "Alarm kaydı"na geçer.
   - "Alarm kaydı": bugünkü davranış aynen (video döngüde, "Durum başladı"/"Alarm anı" işaretleri, hazır değilse
     "Kayıt hazırlanıyor…", olmazsa olay resmi ve açıklama).
3. **Renk ve başlık**: tür rengi başlık şeridinde — yangın/duman turuncu, kişi alarmları kırmızı, telefon sarı (koyu
   yazı), deneme alarmı gri-mavi. Başlıkta simge + tür adı + "DEVAM EDİYOR" (sürüyorsa) ya da "Süre: N sn".
4. **Ortadaki pencere** (kritik):
   - Bilgi satırı: Kamera, Saat (tarih-saat), Geçen süre (canlı sayaç: "38 sn önce", "9 dk önce"), Bildirim
     (`NOTIFY_LABELS`).
   - Düğmeler (bugünküler korunur): Gördüm (odak burada), Kamerayı aç, Kayıt cihazında izle (koşulları aynı),
     Yanlış alarm (onay sorar), Küçült (Esc de; asla onay değil).
   - Sağda **açık alarmlar listesi** (yalnız etkin kipte ve birden çok alarm varken): kritikler üstte, sonra uyarılar;
     her grup içinde yeniden eskiye. Her satırda olay resminin küçüğü (canlı değil: tarayıcının aynı adrese eşzamanlı
     bağlantı sınırı yüzünden yalnız gösterilen alarm canlı akar), tür, kamera, geçen süre. Tıklayınca o alarm gösterilir.
     Bugünkü "1 / 3" ve ‹ › gezintisi listeyle değişir; dar ekranda (< 768 px) liste gizlenir, ‹ › geri gelir.
   - Gördüm / Yanlış alarm sonrası sıradaki alarma geçiş kuralı bugünküyle aynıdır (aynı yerdeki sonraki).
5. **Köşe kartı** (uyarı):
   - En yeni uyarı tam kart (başlık, görüntü alanı + düğme + köşe penceresi, kamera, saat · geçen süre, düğmeler:
     Gördüm, Kamerayı aç, Yanlış alarm, ×). İkinci uyarı küçük kart: solda olay resmi küçüğü (canlı değil), yanında
     kamera/saat, aynı düğmeler. Fazlası "+N uyarı daha" (tıklayınca ortadaki pencere listeyle açılır).
   - "×" kartı gizler (küçült); alarm üst çubukta kalır. Onay değildir.
   - Ortadaki pencere açıkken köşe kartları çizilmez (pencere modal; uyarılar listede zaten var).
6. **Yeni alarm gelince**: kritik → ortadaki pencere o alarmda açılır (bugünkü kural: bu sekmede ilk kez görülen
   alarm). Yalnız uyarı → köşe kartı çıkar, pencere açılmaz. Ses tercihi açıksa bip (bugünkü gibi); masaüstü bildirimi ve
   sekme başlığı yanıp sönmesi aynen.
7. **Üst çubuk** (`AlarmBanner` yenilenir): kırmızı şeritler yerine ince sayaç çubuğu — "● N kritik alarm" (kırmızı),
   "N uyarı" (sarı), "Son: <tür> — <kamera>", "Alarmları göster" (ortadaki pencereyi açar). "Gördüm kaydedilemedi"
   iletisi, alarm akışı uyarısı ve "… kamerası izlenmiyor" satırları aynen kalır.
8. **Ekran kenarı**: onaylanmamış kritik alarm varken ekranın kenarında kırmızı çerçeve yanıp söner;
   `prefers-reduced-motion`'da yanıp sönmez, sabit kalır. Uyarıda yok.
9. **Göz atma kipi** (Alarmlar sayfası, yan panel; `mode="browse"`): aynı yeni pencere görünümü, liste yok, görüntü
   alanı "Alarm kaydı"nda açılır (geçmiş alarm), "Canlı" düğmesi yine kullanılabilir. Onay/yanlış alarm durum
   rozetleri bugünkü gibi.

10. **Kişi üstü etiket** (kullanıcı onayı 2026-11-17: "evet uygun, alarm penceresiyle birlikte ekle"; yazı "Kişi",
    çünkü ekrandaki metinler Türkçe): poz güvenlik çiziminde (`overlay.draw_safety`; canlı işaretli akış, alarm
    kaydı ve video analizi aynı çizimi kullanır) iskeletlere ek olarak:
    - Gözlenen her kişi: ince gri kutu ve küçük "Kişi" etiketi. Karede 6'dan çok kişi varken "Kişi" yazısı çıkmaz,
      yalnız ince kutu kalır (kalabalık).
    - Süre doluyor (kural açık, bölüm sürüyor, alarm henüz yok): sarı kalın kutu, etiket "TELEFON 9 / 15 sn" (geçen
      tam saniye / kuralın süresi) ve etiketin altında süre çubuğu. Aynı kişide birden çok kural sayıyorsa dolmaya en
      yakın olanı gösterilir.
    - Alarm verildi: kırmızı, daha kalın kutu, etiket "TELEFON · ALARM 0:21" (bölümün süresi dk:sn). Kişi bu karede
      görünmese de son bilinen kutusu çizilir (bugünkü gibi).
    - Etiket adları: TELEFON, ELLER YUKARI, YERDE. Etiket kutunun üstüne sığmazsa kutunun içine, üst kenara yazılır.

11. **Güvenlik analiz alanları** (kullanıcı isteği 2026-11-17: "analiz yapılması istenen alanda taranabilsin …
    görüntülerde belli bölgelerde analiz yapılmak istenebilir"; "trassirde aynı ekranda 15 farklı bölge seçilip
    alarm aktif edilebiliyor". 2026-10-07'deki "güvenlikte alan kısıtı yok" kararını kullanıcı böylece değiştirdi).
    Benim kararlarım:
    - Profil sözleşmesinde `safety.areas`: en çok **16** alan; her alan `{name, points, rules}`: `name` 1–40 karakter
      (boşluk kırpılır), `points` 3–12 `[x, y]` köşe (0–1), `rules` bu alanda açık kurallar — `handsUp`, `lying`,
      `phone` alt kümesi, boş olamaz. Alan yoksa bütün kare ve bütün açık kurallar (bugünkü davranış).
    - Bir kurala ancak kamerada açıksa (süresi kameranın kural ayarından) ve kişinin **kutu merkezi**, `rules`'unda o
      kural olan bir alanın içindeyse bakılır. Hiçbir alanın içinde olmayan kişi analizde yok sayılır (iskelet, etiket,
      sayaç, alarm yok). Alandan çıkan kişinin bölümü, görünmeyen kişi gibi biter. Kişi birden çok alandaysa kurallar
      birleşir; alarmın alanı, listede ilk gelen ve o kuralı içeren alandır.
    - Alarm kaydına `area` (alanın adı; alan yoksa `null`). Alarm penceresinin bilgi satırında ve köşe kartında
      "Alan: <ad>"; Telegram iletisinde kamera adının yanında.
    - Alanlar canlı işaretli görüntüde, alarm kaydında ve video analizinde ince açık mavi çizgiyle ve ilk köşesinde
      adı ve içindeki kişi sayısıyla çizilir: "Masa 3: 1" (sarı/kırmızı kişi etiketleriyle karışmasın diye mavi). İçinde alarmı süren kişi olan alan kalın kırmızı çizilir (hangi alanda alarm olduğu ekrandan görülür; kullanıcı: "ekranda da hangi alanlarda aktif bölgeler görebiliyorsun").
    - Panelde güvenlik (poz) ve telefon kameralarının "Ayarla" bölümünde "Analiz alanları": görüntü üstünde çokgen
      düzenleyici (yangındaki hariç bölge düzenleyicisi) ve alan listesi (ad kutusu, kural kutucukları, sil). Yeni
      alanın adı "Alan N", kuralları kamerada açık olanlar. Açıklama: "Boş bırakırsanız bütün görüntü izlenir."
    - Yangın/duman bu işin dışında (orada "Hariç bölgeler" var); video işi (`analysis-job`) seçeneklerine alan
      eklenmez. iPhone profili alanları okur ve geri yazar (işlemez), yangındaki gibi.

12. **Profesyonel başlık, emoji yok** (kullanıcı eski pencere için: "çok amatör, logo ve dahası"): alarm arayüzünde
    hiç emoji kullanılmaz; tür başına küçük SVG simge (alev, duman, eller yukarı kişi, yerde yatan kişi, telefon, zil)
    renkli başlıkta beyaz yuvarlak köşeli rozet içinde. Başlık: rozet · tür adı · "<kamera> · <tarih-saat>" · sağda
    durum çipi.
13. **Alarm sesleri** (kullanıcı: "alarm sesi seçmemiz gerek … 10 tane alarm sesi wav dosyası belirleyelim"). Benim
    kararlarım:
    - 10 ses, depodaki bir üretici betikle sentezlenir (lisans sorunu yok, tekrar üretilebilir) ve panelle gelir:
      `apps/dashboard/public/sounds/alarm-01.wav` … `alarm-10.wav` (22 050 Hz, tek kanal, 16 bit, 1–2 sn).
      Adları: Klasik bip, Siren, Hızlı siren, Çan, Uyarı düdüğü, Nabız, Yükselen ton, İkili korna, Sonar, Yumuşak gong.
    - Bildirim ayarlarında (bugünkü "Sesli uyarı" yanında) üç grup için ses seçimi ve "Dinle": Yangın/duman (varsayılan
      Siren), Kişi alarmları — eller yukarı, yerde yatan, deneme (varsayılan Hızlı siren), Telefon kullanımı (varsayılan
      Klasik bip); ses düzeyi kaydırıcısı (varsayılan %80). Ayarlar bu tarayıcıda (bugünkü ses ayarı gibi çerez).
    - Çalma: kritik alarmda ses, pencere açık ve onaylanmamış kritik alarm varken 3 sn arayla tekrar eder; "Gördüm",
      "Küçült" ya da pencerenin kapanması sesi durdurur. Uyarıda (telefon) yeni alarm başına bir kez. "Sesli uyarı"
      kapalıysa hiç çalmaz (bugünkü varsayılan: kapalı).
    - Tarayıcı sesi engellerse (sayfayla hiç etkileşim yok) üst çubukta "Alarm sesi için sayfaya bir kez tıklayın" yazar.

## Sunucu (edge) değişikliği

- Alarm kaydına **`box`** alanı: alarmı tetikleyen kutu, normalize `[x1, y1, x2, y2]` (0–1); `SafetyAlarm.box` ve
  `FireAlarm.box`'tan yazılır. Deneme alarmında ve bu alandan önceki kayıtlarda `null`. Diskteki eski kayıtlar
  okunurken `null` tamamlanır; bozuk değer (`4 sayı değil`, aralık dışı) `null` sayılır.
- `docs/13-web-platform.md` alarm kaydı satırı ve alan listesi güncellenir. (Alarm günlüğü `contracts/` şemasında
  değildir; olay sözleşmesi değişmez.)

## Hedef olmayanlar

- Liste satırlarında ve küçük kartta canlı akış (bağlantı sınırı; yukarıda).
- Başka bir VMS ürününün görünümünü/markasını birebir kopyalamak.
- Ses türleri, sessize alma, alarm yükseltme (escalation), iPhone uygulaması.
- Canlı izleme duvarındaki alarmlı kutu işaretlemesi (zaten var).

## Kısıtlar

- Kullanıcıya görünen metinler Türkçe; yerel `<dialog>` + `showModal()` ortadaki pencerede korunur (başka modalların
  üstünde açılma, odak tuzağı, Esc = Küçült).
- Köşe kartlarının bölgesi `aria-live="assertive"` (yeni uyarı ekran okuyucuda okunur); kart odak çalmaz, sayfa
  kullanılmaya devam eder.
- Panel görüntüsü yalnız yerel ağ üzerinden analiz sunucusundan gelir; yeni harici istek yok.
- Var olan e2e testleri (`safety-ui`, `fire-ui` ve alarm penceresine dokunan diğerleri) yeni davranışa göre
  güncellenir; `data-testid="alarm-modal"`, `alarm-title`, `alarm-video`, `clip-caption`, `alarm-timeline`,
  `alarm-status`, `alarm-state`, `alarm-banner` adları korunur (yeni öğelere yeni adlar).

## Kurucuya bırakılanlar

- Bileşen bölümlemesi (ör. ortak `AlarmMedia`, `AlarmQueue`, `AlarmToast`), renk değerlerinin Tailwind
  belirteçlerine eşlenmesi, yakınlaştırmanın CSS mi tuval mi ile yapılacağı.
- Canlı akışın yeniden bağlanma ayrıntısı (`useStreamKey` yeniden kullanılabilir).
