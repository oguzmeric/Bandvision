# Sade arayüz ve izleme sekmeleri (web paneli) — tasarım

Tarih: 2026-10-28 · Durum: taslak (kullanıcı incelemesi bekliyor) · Bilgisayar tarafı yol haritasının 1. projesi.

## Yol haritası (kullanıcıyla kararlaştırılan sıra)
1. **Sade arayüz ve izleme sekmeleri** (bu belge)
2. Ekran kartı desteği ve Cihaz ayarları sayfası
3. Lisanslama ve demo
4. Exe kurulumu (Windows)
5. Yangın ve duman analizi

Her proje kendi tasarım belgesi, planı ve incelemesiyle ilerler. iPhone tarafındaki yarım kalan "iPhone izleme" dalı (`iphone-izleme`) bekletiliyor. Öncelik bilgisayar.

## Amaç ve neden
Kullanıcı, web panelinin TRASSIR'ın ayar ekranı gibi sade olmasını istiyor:
- solda yazılı, gruplu bir menü;
- sağda süssüz, form ve tablo gibi sayfalar.

Bugünkü panelde yalnız simgelerden oluşan dar bir yan çubuk var; sayfalar büyük, bol boşluklu kartlardan oluşuyor. Kullanıcı neyin nerede olduğunu tek bakışta görmek istiyor.

İzleme tarafında TRASSIR'daki gibi şunlar gerekiyor:
- şablonlar üstte yan yana sekmeler;
- hızlı bir "Şablon editörü" menüsü;
- N×M ile 128 kutuya kadar büyüyen ızgara.

**Başarı:**
- Kullanıcı paneli açınca her özelliği soldaki yazılı menüde bulur.
- İzleme'de şablonlar arasında sekmeyle geçer.
- Yeni bir şablonu editör menüsünden birkaç tıkla kurar.

## Hedefler
- **Yeni kabuk (tüm sayfalar).**
  - Solda yazılı, gruplu, açılır-kapanır menü; ekranın altında durum şeridi.
  - Mevcut sayfalar bu kabuğa taşınır ve sade görünüme çevrilir: düz başlık, form satırları, tablolar, az boşluk, gölgesiz kenarlıklar.
  - Mevcut işlevler korunur.
- **Menü grupları** (kullanıcı onayladı, taslak `duzen.html`):
  - **İzleme:** Canlı izleme, Alarmlar.
  - **Analizler:** Ürün sayımı, Kişi sayımı, Güvenlik alarmı (poz), Yangın ve duman (gri, "yakında"), Kalite kontrol, Video ile test, Raporlar.
  - **Donanım:** Kameralar ve kayıt cihazları, Cihaz ayarları (proje 2 gelene dek gri).
  - **Sistem:** Bildirimler (Telegram), Telefondan erişim, Lisans (proje 3 gelene dek gri), Hakkında.
- **Durum şeridi** (en alt):
  - analiz sunucusu çalışıyor mu;
  - işlemci yükü;
  - ekran kartı yükü (proje 2 gelene dek "—");
  - lisans durumu (proje 3 gelene dek gösterilmez).
- **Canlı izleme sayfası:**
  - **Sekmeler:** Üstte şablonlar yan yana sekmeler; sonda "+" (yeni şablon). Sekmeye sağ tıklayınca Yeniden adlandır / Kopyala / Sil (silmede onay). Seçili sekme hatırlanır.
  - **Şablon editörü** düğmesi bir menü açar: Yeni şablon, Geri al, Yinele, Kaydet, Farklı kaydet…
  - **Düzenler:** 10 hazır düğme: 1, 2×2, 3×3, 4×4, 1+5, 1+7, 4×3, 5×5, 8×8 ve N×M. N×M satır × sütun girer; toplam en çok 128 kutu.
  - **Kamera listesi:** Sağda yazılı liste. Cihaz adının altında kanallar; yeşil nokta canlı, turuncu sorunlu.
  - **Kamera atama:** Listeden kutuya sürükle-bırak; ya da kutuyu seç, sonra kameraya tıkla. Kutuya sağ tıklayınca "Boşalt". Dokunmatikte sürükleme yok, dokun-seç çalışır.
  - **Tek kamera:** Kutuya çift tıkla → büyür; tekrar çift tıkla → ızgaraya döner.
  - **Kutu üstü bilgiler korunur:** ad, durum metni, sayaç rozeti, alarmda kırmızı çerçeve, tıklayınca alarm penceresi.
  - **Telefon tarayıcısı:** Sekmeler ve şablonlar aynı; dar ekranda menü bir düğmenin arkasına katlanır, sekmeler yatay kaydırılır.

## Hedef dışı (bu projede yok)
- Ekran kartı ile görüntü çözme veya analiz (proje 2).
- Lisans denetimi ve "lisans sınırı" kutuları (proje 3).
- Exe kurulumu (proje 4). Yangın ve duman (proje 5).
- Şablonların web ile iPhone arasında eşitlenmesi.
- PTZ, kayıttan izleme, şablonlar arası otomatik dolaşım.
- Çoklu monitörde ayrı pencereler.

## İstenmeyenler (çalışsa bile başarısız sayılır)
- Bir özelliğin yeni menüde bulunamaması ya da işlevin kaybolması.
- Sade görünümün yalnızca birkaç sayfaya uygulanıp eski kart görünümüyle karışık kalması.
- Sekme değiştirince ortak kameraların kopup yeniden bağlanması.

## Kısıtlar
- **Sözleşme.**
  - Düzenler `contracts/view-layouts.json`'dadır. N×M için sözleşme genişler (`docs/02-contracts.md` §8 ve şema aynı değişiklikte).
  - Öneri: düzen kimliği ya katalogdaki sabit kimliklerden biridir ya da `"<satır>x<sütun>"` biçiminde eşit ızgaradır (ör. `"6x8"`), toplam ≤ 128. Mevcut şablonlar geçerli kalır, yani kırıcı değişiklik değildir ve sürüm 1 kalır.
  - Python kataloğu ve testleri, sözleşme testleri aynı değişiklikte güncellenir.
  - iPhone şablonları eşitlenmediği için iPhone bu biçimi okumak zorunda değildir. iPhone dalı birleşirken bilinmeyen düzenli bir şablon zaten kenara ayrılıyor.
- **Hazır düzenler.** 10 düğmeden 1, 2×2, 3×3, 4×4, 1+5, 1+7 ve 4×3 katalogda karşılığı olanlar (1, 4, 9, 16, 6, 8, 12). 5×5 ve 8×8, N×M biçimiyle (`"5x5"`, `"8x8"`) üretilir. Katalogdaki 2 ve 3'lü düzenler editörde ayrı düğme olarak görünmez, ama mevcut şablonlarda çalışmaya devam eder.
- **Analiz sunucusu sınırları.**
  - Bugünkü kamera okuyucu sınırı (16 alt + 2 ana akış) 128 kutuya izin verecek şekilde yapılandırılabilir olur. Varsayılan üst sınır 128 alt akış.
  - Birleştirilmiş akış tuvali en çok 1920×1080 kalır; 128 kutuda kutular küçük olur.
  - Akıcılık donanıma bağlıdır. Ekran kartı ile çözme gelene dek (proje 2) büyük şablonlarda kare hızı düşük olabilir. Gerçek sınır ofis NVR'ında ölçülür ve belgeye yazılır; başarım iddiası yapılmaz.
- **Analize dokunmama.** İzleme analiz başlatmaz. Kamerada sayım oturumu varsa onun karesi kullanılır (bugünkü davranış).
- **Dil ve yığın.** Kullanıcıya görünen metin Türkçe. Dashboard: Next.js 15 (App Router). Mevcut erişim ve şifre düzeni (telefondan erişim, yerel ağ şifresi) aynen korunur.
- **Testler gerçek kameraya ya da ağa bağlanmaz** (mevcut Playwright ve pytest düzeni).

## Kullanıcının kararları
- TRASSIR tarzı yazılı, gruplu sol menü ve düz sayfalar. Menü grupları taslaktaki gibi (onaylandı).
- Şablonlar üstte yan yana sekmeler.
- Şablon editörü menüsü (Yeni, Geri al, Yinele, Kaydet, Farklı kaydet, düzenler, N×M).
- Bir şablonda en çok 128 kutu.
- Üç düz sayfa taslağı (Şablon editörü, Lisans, Cihaz ayarları) onaylandı. Lisans ve Cihaz ayarları sayfaları kendi projelerinde yapılır.
- Ekran kartı kurulu bilgisayarda kendiliğinden tanınır (proje 2).

## Benim kararlarım (kullanıcı onaylamadı, gerekirse değişir)
- "Analizler" altındaki Ürün sayımı, Kişi sayımı ve Güvenlik alarmı bugünkü tek "Canlı sayım" sayfasının o türe süzülmüş halleridir; ayrı sayfa yazılmaz.
- "Kameralar ve kayıt cihazları" bugünkü Kameralar sayfasıdır. "Telefondan erişim" bugünkü Ayarlar sayfasının ilgili bölümüdür. "Hakkında" sürüm bilgisini gösteren yeni küçük bir sayfadır.
- Yeni şablon varsayılan olarak 2×2 açılır.
- Geri al ve Yinele yalnızca açık düzenleme oturumunda çalışır (sayfa yenilenince geçmiş silinir).
- "Kaydet" tıklanana dek değişiklik sunucuya yazılmaz. Kaydedilmemiş değişiklikle sekme değiştirilince "Kaydedilmedi, çıkılsın mı?" sorulur.
- Görsel dil: TRASSIR'a yakın gri-mavi tonlar, sistem yazı tipi, ince kenarlıklar. Koyu tema bu projede yok.
- **Analiz süzmesi.** Ürün sayımı / Kişi sayımı / Güvenlik alarmı aynı sayfanın (`/live`) `?tur=urun|kisi|guvenlik` ile süzülmüş halidir. Süzme oturumun profil yöntemine göre yapılır:
  - ürün: `blob` ve `linescan`;
  - kişi: `detect`;
  - güvenlik: `safety`.
  Süzülmüş sayfadan yeni oturum başlatılınca profil seçici o türün profilleriyle açılır. Süzmesiz `/live` adresi çalışmaya devam eder (eski bağlantılar kırılmaz) ama menüde ayrı öğesi yoktur; üç süzme birlikte tüm oturumları kapsar.
- **Eski sayfalar.**
  - Canlı izleme bugünkü `/watch` sayfasının yerini alır; adres aynı kalır. Eski düzenleyicinin işlevleri (tüm kanallardan şablon, video duvarı, tek kamera, telefon yatay görünümü) yeni sayfada korunur.
  - Alarmlar bugünkü `/alarms` sayfasıdır.
  - Kutudaki alarm penceresi bugünkü bileşendir.
- **N×M kimlik biçimi.** `"<satır>x<sütun>"`, örneğin `"6x8"` = 6 satır, 8 sütun, eşit hücreler. Satır ve sütun 1–16 arasında, toplam ≤ 128. Tuval oranı bugünkü kural gibi kutuları 16:9 kabul eder. `"4x4"` geçerlidir ve `"16"` ile aynı geometridedir. Editördeki 4×4 düğmesi katalogdaki `"16"`yı, 5×5 ve 8×8 düğmeleri `"5x5"`/`"8x8"`i kullanır. Editör "Satır × Sütun" diye gösterir.
- **Kaydedilmemiş taslak da canlı görünür.** Editörde yapılan değişiklik, analiz sunucusunda geçici (kaydedilmeyen, 10 dk boşta silinen) bir izleme taslağı olarak açılır ve ızgara bu taslağın birleşik akışını gösterir. Böylece TRASSIR'daki gibi düzenlerken görüntü akar. "Kaydet" taslağı şablona yazar. Ortak kameralar aynı okuyucuyu kullandığı için taslak ile şablon arasında geçişte kopmaz.
- **128 kutu ve okuyucu sınırı.**
  - Alt akış okuyucu sınırı analiz sunucusunun ayar dosyasında (ortam değişkeni ile de ezilebilir) yapılandırılabilir; varsayılan 128 alt + 2 ana. Arayüzde ayar ekranı yok.
  - Sınırın üstündeki kutular bugünkü gibi "Sınır aşıldı" gösterir; şablon kaydı reddedilmez.
  - Proje 3'te lisans bu sayıyı ayrıca kısıtlar.
- **Seçili sekme** her tarayıcıda ayrı hatırlanır (bugünkü gibi tarayıcı deposu).
- **Durum şeridi.**
  - Analiz sunucusuna yeni bir durum uç noktası eklenir: işlemci yükü ve çalışma süresi. Gerekirse `psutil` bağımlılığı eklenir.
  - Analiz sunucusu kapalıysa şerit "Analiz sunucusu: kapalı" yazar ve diğer alanlar "—" olur.
  - Oturum düşmüşse bugünkü giriş yönlendirmesi geçerlidir.
- **Hakkında** sayfası panel sürümünü (`package.json`), analiz sunucusu sürümünü ve git kısa özetini gösterir.

## Uygulayana bırakılanlar
- Bileşen yapısı, durum yönetimi, sürükle-bırak kütüphanesi (harici bağımlılık eklemeden, HTML5 sürükle-bırak tercih).
- Sayfaların tek tek sade görünüme çevrilme sırası.
- Tablo ve form ayrıntıları.

## Kabul
- **Menü:**
  - Tüm mevcut sayfalar yeni menüden açılır.
  - Gri öğeler tıklanınca "yakında" der.
  - Telefonda menü katlanır.
- **Görünüm:** Hiçbir sayfada eski kart düzeni kalmaz.
- **Sekmeler:** Canlı izlemede şablonlar sekme olarak görünür. Ekle, yeniden adlandır, kopyala, sil ve seçili sekmeyi hatırla çalışır.
- **Şablon editörü:**
  - 10 düzen düğmesi çalışır.
  - N×M ile 6×8 = 48 kutuluk şablon kurulur.
  - 129 kutu reddedilir (Türkçe ileti).
  - Geri al, Yinele, Kaydet ve Farklı kaydet çalışır.
- **Kamera atama:** Sürükle-bırak ve dokun-seç ile kamera atanır. Çift tıkla tek kamera açılıp kapanır.
- **Sözleşme ve sunucu:** Sözleşme, Python ve dashboard testleri N×M kimliklerini kapsar. Mevcut şablonlar bozulmadan açılır.
- **Testler:** Playwright uçtan uca testleri yeni menü ve sekmelerle güncellenir ve geçer.
- **Ölçüm (kullanıcıyla):** Ofis NVR'ında 16, 32 ve 64 kutuluk şablonda işlemci yükü ve kutu başına kare hızı ölçülüp `docs/12-durum.md`'ye yazılır.
