# Çoklu kamera izleme (şablonlu ızgara) — web tasarımı

Tarih: 2026-10-08 · Durum: uygulandı (ölçüm bekliyor) · Tasarım kullanıcı tarafından bölüm bölüm onaylandı; uygulanan davranış ve tasarımdan ayrılanlar `docs/13-web-platform.md`'de, durum `docs/12-durum.md` §5g'de · Alt proje A (web). Alt proje B (iPhone) ayrı tasarımla gelecek.

## Amaç
Birden fazla kamerayı TRASSIR istemcisindeki gibi tek ekranda, şablonlu bir ızgarada **canlı izlemek**.
- Web panelinde ve telefonun tarayıcısında çalışacak.
- 2, 3, 4'lü düzenler ve katları desteklenecek.
- Kutulara kamera atanan şablonlar kaydedilecek.

**Kullanıcının söyledikleri (2026-10-08):**
- Kameralar, TRASSIR ekran görüntüsündeki gibi topluca izlenebilmeli. Bu hem mobilde hem webde olmalı.
- Şablon oluşturulabilmeli; 4'lü, 2'li, 3'lü ya da onların katları seçilebilmeli.
- "Mobil", hem iPhone uygulaması hem telefondan açılan web paneli demek. Önce web, sonra iPhone yapılacak.
- Telefondan erişim **ofis ağından (Wi-Fi)** olacak. Dışarıdan erişim (VPN/tünel) bu işin dışında, sonra ayrıca ele alınacak.
- Görüntü **sunucuda birleştirilmiş tek akış** olarak taşınacak; WebRTC/go2rtc kullanılmayacak.

**Varsayımlar (kullanıcı tasarım bölümlerinde onayladı):**
- Kutular akıcı canlı görüntü gösterir (fotoğraf yenileme değil). Kutuya çift tıklayınca kamera büyür.
- Izgarada izlemek **analiz başlatmaz**, yalnızca görüntüdür. Kamerada analiz çalışıyorsa rozeti ve alarmı kutuda görünür.

## Başarı ölçütü (kabul)
- Ofis NVR'ında 4'lü ve 9'lu şablon oluşturulup canlı izlenir.
- 16 kamerada saniyede en az 8 kare elde edilir. Aynı anda çalışan sayım oturumlarının kare hızı belirgin düşmez; ölçüm belgeye yazılır.
- Telefon, ofis Wi-Fi'ında şifreyle bağlanıp aynı şablonu izler.
- Kutuya çift tıklayınca/dokununca tek kamera büyür.
- Güvenlik alarmında ilgili kutu kırmızı yanar.
- Testler hiçbir gerçek kameraya ya da ağa bağlanmaz.

## Kapsam
**Var:**
- düzenler ve şablonlar;
- analiz sunucusunda izleme okuyucuları ve birleştirici;
- İzleme sayfası (izleme/düzenleme kipi, tek kamera, video duvarı);
- kutu üstü bilgiler;
- telefondan erişim (yerel ağ, şifre, QR);
- testler ve ölçüm.

**Yok (sonraya):**
- iPhone ekranı (alt proje B);
- dışarıdan erişim;
- şablonlar arası otomatik dolaşım;
- kamera döndürme/yakınlaştırma (PTZ);
- NVR kaydından geriye dönük izleme;
- WebRTC ile yükseltme.

## Düzenler (sözleşme)
Düzen tanımları web ile iPhone'da birebir aynı olacağı için **sözleşmedir**. Kuralın gereği olarak:
- `contracts/view-layouts.json` (veri) ve `contracts/view-template.schema.json` (şablon biçimi) eklenir;
- `docs/02-contracts.md` güncellenir.

Düzen, birim ızgarada hücre listesidir: `{id, name, cols, rows, cells: [[x, y, w, h], …]}`. Hücre sırası kutu sırasıdır. Tuval herhangi bir boyutta olabilir ve hücreler oransal yerleşir.

| id | Ad | cols×rows | Hücreler |
|---|---|---|---|
| `1` | Tek | 1×1 | [0,0,1,1] |
| `2` | 2'li (yan yana) | 2×1 | [0,0,1,1] [1,0,1,1] |
| `3` | 3'lü (1 büyük + 2) | 3×2 | [0,0,2,2] [2,0,1,1] [2,1,1,1] |
| `4` | 4'lü | 2×2 | 2×2 eşit |
| `6` | 6'lı (1 büyük + 5) | 3×3 | [0,0,2,2] [2,0,1,1] [2,1,1,1] [0,2,1,1] [1,2,1,1] [2,2,1,1] |
| `8` | 8'li (1 büyük + 7) | 4×4 | [0,0,3,3] [3,0,1,1] [3,1,1,1] [3,2,1,1] [0,3,1,1] [1,3,1,1] [2,3,1,1] [3,3,1,1] |
| `9` | 9'lu | 3×3 | 3×3 eşit |
| `12` | 12'li | 4×3 | 4×3 eşit |
| `16` | 16'lı | 4×4 | 4×4 eşit |

**Şablon** (`view-template.schema.json`):
- Alanlar: `{id, name, layout, tiles, createdAt, updatedAt}`.
- `tiles` uzunluğu düzenin hücre sayısına eşittir. Her öğe `null` (boş) ya da `{sourceId, channelId}` olur; tek kamerada `channelId` `null`'dır.
- Kamera kimlikleri platforma özgüdür. Web'de analiz sunucusunun kaynak kimliği kullanılır; iPhone kendi kimliklerini kullanacak. Biçim ortaktır.

## Şablonlar
- Analiz sunucusunun veri klasöründe `<data>/live/views.json` dosyasında saklanır. Mevcut atomik JSON yazıcısı kullanılır; kilitli dosya okunamazsa kayıtlar kaybolmaz (alarms/watch ile aynı desen). Aynı panele bağlanan her tarayıcı aynı şablonları görür.
- Doğrulama:
  - ad 1–60 karakter;
  - düzen katalogda olmalı;
  - `tiles` uzunluğu düzenle aynı olmalı;
  - kaynak ve kanal kimlikleri güvenli biçimde olmalı;
  - aynı kamera bir şablonda en fazla bir kez yer alır.

  Bu kurallar bozulursa 422 döner, ileti Türkçe olur.
- **Kayıt cihazı kısayolu:** `POST /views/from-recorder {sourceId}`, NVR'ın kanal listesinden kanal sayısına uyan en küçük düzeni seçer ve kanalları sırayla yerleştirir (ör. 7 kanal → `8`). 16'dan fazla kanal varsa ilk 16 kanal alınır ve kullanıcıya bildirilir.
- Bir kaynak silinince şablonlar bozulmaz; kutu "Kamera silinmiş" gösterir.

## Analiz sunucusu (Python)
### İzleme okuyucusu (`live/viewer.py`, `ViewHub`)
- Anahtar: `(sourceId, channelId, kalite)`. Kalite `sub` (ızgara) ya da `main` (tek kamera "Net görüntü") olur.
- Her anahtar için bir okuyucu iş parçacığı vardır:
  - mevcut `opener`/`camera_url` ve FFmpeg seçenekleriyle akışı açar;
  - son kareyi küçültülmüş hâlde tutar (en çok 960 px genişlik);
  - kopunca artan beklemeyle (1 → 30 sn) yeniden dener; TRASSIR anahtarı her denemede yeniden alınır;
  - durumunu (`connecting` / `live` / `error` + Türkçe neden, fps) tutar.
- **Paylaşım:**
  - Aynı anahtar birden çok şablonda ya da tarayıcıda olsa da tek okuyucu açılır.
  - Kamerada zaten analiz oturumu çalışıyorsa NVR'a ikinci bağlantı açılmaz; oturumun ham karesi kullanılır. İzleme oturumları **asla** başlatmaz, durdurmaz ya da değiştirmez.
- **Yaşam süresi:** Okuyucu 30 sn boyunca kullanılmazsa kapanır.
- **Sınır:** Aynı anda en çok 16 `sub` ve 2 `main` okuyucu açılır. Fazlası için kutu durumu `error: "Sınır aşıldı (en çok 16 kamera)"` olur.

### Birleştirici
- Anahtar `(şablon, w, h)`. Tuval boyutu tarayıcıdan gelir, en çok 1920×1080'e sığdırılır ve 16'nın katına yuvarlanır.
- Saniyede en çok 10 kez, yalnızca en az bir izleyici varken tuval oluşturulur:
  - her hücreye kamera karesi oran korunarak sığdırılır (siyah pay);
  - boş ya da karesiz hücre koyu gri olur;
  - kamera adı, durum ve rozetler tuvale **çizilmez**; bunlar sayfada HTML olarak eklenir.
- JPEG kalitesi 75. Aynı şablon ve boyutu izleyen tarayıcılar aynı kareyi paylaşır.

### Uç noktalar (`/api/v1/live`)
| Yöntem | Yol | Açıklama |
|---|---|---|
| GET | `/view-layouts` | Düzen kataloğu (sözleşme dosyası) |
| GET/POST | `/views` | Şablon listesi / yeni şablon |
| PUT/DELETE | `/views/{id}` | Şablonu güncelle / sil |
| POST | `/views/from-recorder` | NVR'ın kanallarından şablon |
| GET | `/views/{id}/stream?w=&h=` | Birleşik MJPEG (`multipart/x-mixed-replace`); 60 sn yeni kare yoksa biter |
| GET | `/views/{id}/status` | Kutu başına `{state, message, fps, analysis}` |
| GET | `/cameras/stream?source=&channel=&quality=sub\|main` | Tek kamera ham MJPEG (çizim yok) |

`analysis` alanı:
- `null`; ya da
- o kameradaki oturumun özeti:
  - `{mode, sessionId}`;
  - kişi sayımında Giriş/Çıkış;
  - bantta sayılan;
  - güvenlikte `healthy`/`reason` ve onaylanmamış alarm (`alarm: {id, type}`).

## Web paneli
- **İzleme sayfası (`/watch`):** Menüde "Kameralar"dan sonra "İzleme" girişi olur. İlk açılışta son kullanılan şablon gelir; bu bilgi tarayıcıda tutulur.
- **Üst çubuk:**
  - şablon seçici;
  - "Yeni şablon";
  - "Düzenle";
  - "Tüm ekran" (Fullscreen API; menüler gizlenir, video duvarı);
  - "Tüm kanallardan şablon" (kayıt cihazı seçerek).
- **İzleme kipi:**
  - Tek `<img>` birleşik akışı gösterir. Üstüne düzen geometrisine göre konumlanan HTML katmanları gelir.
  - Sol üstte kamera adı. Ortada "Bağlanıyor…" ya da "Bağlantı yok — <neden>" ya da "Kamera silinmiş".
  - Sağ üstte rozet: kişi sayımında "G 12 · Ç 9", bantta "Sayılan 120", güvenlikte yeşil "Nöbette" ya da sarı "Uyarı".
  - Alarmda kırmızı yanıp sönen çerçeve ve tür yazısı ("ELLER YUKARI") çıkar; tıklanınca mevcut alarm penceresi açılır.
  - Durum 1,5 sn'de bir yoklanır. Akış koparsa 2 sn sonra yeniden bağlanılır.
- **Tek kamera:**
  - Çift tıkla (telefonda dokun) açılır; geri ya da Esc ile ızgaraya dönülür.
  - Ham tek kamera akışı kullanılır (`quality=sub`); "Net görüntü" ile `main`'e geçilir.
  - Kutunun üstüne gelince "Tam ekran" ve "Canlı sayıma git" düğmeleri çıkar. Analiz çalışıyorsa oturuma gidilir, çalışmıyorsa başlatma penceresi açılır.
- **Düzenleme kipi:**
  - Sağda kamera listesi: tek kameralar ve NVR kanalları, küçük resim ve adla.
  - Kutuya sürükle-bırak ya da kutuya tıklayıp listeden seç. Kutu boşaltılabilir, kutular sürükleyerek yer değiştirebilir.
  - Düzen değiştirilirse kutular sırasıyla korunur; fazlası boşa düşer ve uyarılır.
  - "Kaydet" ve "Vazgeç". Şablon yeniden adlandırılabilir, kopyalanabilir ve silinebilir (onaylı).
- **Telefon görünümü:**
  - Şablon seçici üstte, ızgara genişliği kaplar. Birleşik akışın boyutu kapsayıcının gerçek boyutundan istenir.
  - Dokununca tek kamera açılır; yan çevirince tam ekran olur.

## Telefondan erişim (ofis ağı)
- **Varsayılan:** Panel yalnızca bu bilgisayardan açılır. Başlatıcı `next dev`/`next start`'ı `-H 127.0.0.1` ile çalıştırır. Bugün Next'in tüm ağ arayüzlerini dinlemesiyle oluşan şifresiz yerel ağ erişimi böylece kapanır.
- **Açma:** Ayarlar → "Telefondan erişim":
  - Önce panel şifresi belirlenir (en az 8 karakter). Şifre yalnızca scrypt özeti olarak panelin yerel dosyasında tutulur (`apps/dashboard/.local/access.json`, git dışı); bir oturum sırrı da aynı dosyada durur.
  - Erişim açıkken panel tüm ağ arayüzlerini dinler ve **herkes için** şifre ister, bu bilgisayar dahil. Uzak adres güvenilir biçimde ayırt edilemediği için yerel istisna yapılmaz.
- **Çalıştırma:** Panel küçük bir başlatıcıyla çalışır (`tools/panel_run.mjs`):
  - erişim dosyasını okur;
  - `-H` adresini ve oturum sırrı ile şifre özetini ortam değişkeni olarak verip Next'i çalıştırır;
  - dosya değişince Next'i yeniden başlatır (yaklaşık 10 sn). Şifre değişince eski oturumlar düşer.
- `DASHBOARD_PASSWORD` ortam değişkeni varsa önceliklidir; bugünkü davranış korunur.
- **Ayarlar sayfası:** Açıkken telefonda açılacak adresi (bilgisayarın yerel IP'leri) ve bir **QR kodu** gösterir. QR için küçük bir npm paketi (`qrcode`, MIT) eklenir.
- **Windows güvenlik duvarı:** İlk açılışta "özel ağ" izni isteyebilir; bunu kullanıcı onaylar. Sayfada bu not yazar.
- **Analiz sunucusu** yalnızca `127.0.0.1`'de kalır. Telefon yalnızca panelle konuşur; kamera şifreleri telefona gitmez.
- **Bilinen sınır:** Yerel ağda bağlantı şifrelenmemiş http'dir. Dışarıdan erişim ayrıca ele alınacak.

## Hata ve sınır durumları
- Kamera ya da NVR kopar: kutuda Türkçe neden görünür ve yeniden denenir. NVR yeni bağlantıyı reddederse ("bağlantı sınırı") bu da Türkçe yazılır.
- Sunucu yeniden başlar: sayfa akışı ve durumu kendiliğinden yeniden açar.
- `views.json` kilitli ya da bozuk: çökme olmaz. Bozuk dosya `.corrupt` olarak kenara alınır; kilitliyse yazma ertelenir ve birleştirilir.
- İzleyici kalmazsa birleştirici durur, okuyucular 30 sn sonra kapanır.

## Performans
- Izgarada her zaman alt akış kullanılır; saniyede en çok 10 tuval oluşturulur.
- Ofis NVR'ıyla 4, 9 ve 16 kamerada işlemci kullanımı ve kare hızı ölçülüp `docs/12-durum.md` ve `docs/13-web-platform.md`'ye yazılır. Ölçülen sayım oturumu kare hızı da yazılır.

## Test
- **Python (ağsız; sahte açıcı ve sentetik kareler):**
  - düzen kataloğu sözleşmeye uyar (hücreler ızgarada, çakışmasız, tam kaplama);
  - birleştirici kareleri doğru hücreye oran korunarak koyar;
  - okuyucu paylaşımı, 30 sn kapanış (enjekte saat), oturum karesinin yeniden kullanımı;
  - 16/2 sınırı;
  - yeniden bağlanma ve durum;
  - şablon doğrulama ve 422'ler;
  - kilitli `views.json`;
  - `from-recorder` seçimi;
  - uç nokta içerik türleri.
- **Uçtan uca (Playwright, dosya kaynakları):**
  - şablon oluşturma, kamera atama;
  - birleşik akışın 200 `multipart/x-mixed-replace` gelmesi;
  - tek kameraya büyütme, şablon silme.
- **Sahte veriyle (`page.route`):**
  - rozetler, alarm çerçevesi ve tıklayınca alarm penceresi;
  - "Bağlantı yok" ve "Kamera silinmiş";
  - 375 px telefon görünümü;
  - düzen değişiminde kutuların korunması.
- **Erişim:**
  - erişim kapalıyken başlatıcı `127.0.0.1` adresini verir;
  - açıkken şifresiz istek reddedilir (sayfa giriş formuna, API 401'e);
  - şifre özeti doğrulanır, düz şifre hiçbir dosyada ya da yanıtta yoktur.
- Sözleşme dosyaları sözleşme testlerine eklenir (`tools/tests/test_contracts.py`).

## Gizlilik (KVKK)
- Izgara **kayıt yapmaz**; yalnızca canlı görüntü gösterir. Görüntü bilgisayardan yalnızca aynı ağdaki, şifreyle giriş yapmış tarayıcıya gider.
- Analiz sunucusu dış ağa açılmaz. Kamera şifreleri yalnızca bilgisayardaki `secrets.json`'da kalır.
