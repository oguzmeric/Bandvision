# iPhone çoklu kamera izleme (cihaz listesi + şablonlu ızgara) — tasarım

Tarih: 2026-10-11 · Durum: uygulandı (ölçüm bekliyor; docs/12-durum.md §5h) · Çoklu izlemenin alt proje B'si (iPhone). Alt proje A (web) `2026-10-08-coklu-izleme-design.md`'de; düzen ve şablon sözleşmesi oradan gelir.

## Amaç
iPhone uygulamasında kameraları NVR duvarı gibi tek ekranda, şablonlu bir ızgarada **canlı izlemek**.
- Görüntü telefona doğrudan NVR'dan ve kameralardan gelir. Ofisteki bilgisayar gerekmez.
- Uygulamaya birden çok kayıt cihazı ve IP kamera eklenebilir.

**Kullanıcının kararları (2026-10-11):**
- Kaynak: telefon görüntüyü **doğrudan NVR'dan ve kameralardan** alır. Ofis paneli üzerinden alma seçilmedi.
- Uygulamaya **birden çok NVR ve IP kamera** eklenebilir.
- Sayım da kamerasını **aynı ortak listeden** seçer.
- Kutuların **hepsi akıcı canlı** görüntü gösterir. Fotoğraf yenileme kullanılmaz.
- Tasarım bölümleri 1–4 tek tek onaylandı.

**Varsayımlar (kullanıcı onayladı):**
- Şablonlar telefonda saklanır, web'dekilerle eşitlenmez. Düzenler ortak sözleşmeden gelir.
- Izgarada izlemek sayım başlatmaz.
- Görüntü telefondan hiçbir yere gönderilmez ("Cihaz üzerinde işleme" kuralı).

## Başarı ölçütü (kabul)
- Kullanıcının iPhone'unda ofis NVR'ından 4'lü ve 9'lu şablon kurulur ve canlı izlenir.
- 16'lı şablonda şunlar ölçülür ve `docs/12-durum.md`'ye yazılır:
  - kutu başına kare hızı;
  - 10 dakikalık izlemede ısınma ve pil tüketimi;
  - sayım çalışırken sayım kare hızına etki.
- Sayılan kamera ızgarada da açıkken NVR'a ikinci bağlantı açılmaz.
- Güncellemeden önce kayıtlı olan kamera ya da NVR, şifresiyle birlikte listeye taşınır. Sayım aynı kamerayla sürer.
- Kutuya dokununca tek kamera net akışla açılır. "Bu kamerayı say" sayımı o kameraya geçirir.
- Testler hiçbir gerçek kameraya ya da dış ağa bağlanmaz. Arayüz testi CI'daki yerel sahte NVR ve RTSP sunucusunu kullanır.

## Kapsam
**Var:**
- Cihazlar listesi ve eski ayarın taşınması;
- sayım kaynağının listeden seçilmesi;
- İzleme sekmesi: şablonlar, düzenleyici, "NVR'dan şablon", ızgara, tek kamera, yan çevirme;
- görüntü dağıtıcısı;
- testler, ölçüm, belgeler, TestFlight.

**Yok (sonraya):**
- web ile şablon eşitleme;
- ofis paneli üzerinden izleme (telefonun tarayıcısı bunu zaten yapıyor);
- dışarıdan erişim (VPN/tünel);
- PTZ;
- NVR kaydından geriye dönük izleme;
- şablonlar arası otomatik dolaşım;
- birden çok kamerada aynı anda sayım;
- ızgarada güvenlik (poz) alarmı. Poz analizi telefonda çalışmaz.

## 1. Cihazlar
**Veri.** Cihaz `NetworkDevice` olarak tutulur:
- `id`: UUID, küçük harf;
- `name`: 1–40 karakter. Benzersizdir; çakışmada sonuna " (2)" eklenir.
- `kind`: `camera` ya da `recorder`;
- bugünkü `NetworkCameraConfig`'in alanları: kamera tarafında marka, adres, port, kanal, alt akış, kullanıcı, tam RTSP adresi; kayıt cihazı tarafında marka, adres, HTTP ve RTSP portları, kullanıcı.
- Kayıt cihazında tek kanal seçimi (`recorderChannel`) artık cihazda tutulmaz.

Liste uygulamanın Application Support klasöründe atomik yazılan bir JSON dosyasındadır. Bozuk dosya kenara ayrılır (`devices.corrupt-<zaman>.json`), kullanıcıya Türkçe ileti gösterilir ve uygulama çökmez.

**Kanal önbelleği.** Kayıt cihazının kanal listesi (ad, numara, alt akış var mı) cihaz başına saklanır. Böylece kutu adları ve seçici çevrimdışıyken de görünür. Liste her "Kanalları yenile"de ve cihaz kaydedilince güncellenir.

**Kamera kimliği.** Bir kamera `{sourceId, channelId}` ile tanınır. Bu, sözleşmedeki şablon kutusu biçiminin aynısıdır:
- `sourceId`: cihaz kimliği;
- `channelId`: kayıt cihazında `RecorderChannel.id` (TRASSIR GUID'i ya da kanal numarası), doğrudan kamerada `null`.

**Şifreler.** Anahtar zincirinde cihaz başına `device.<id>` hesabıyla saklanır:
- `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` (yedekle taşınmaz);
- API'ye, günlüğe ya da ekrana çıkmaz;
- cihaz silinince şifresi de silinir.

**Ayarlar → Cihazlar.**
- Liste; "Ekle" ile "Kamera" ya da "Kayıt cihazı" eklenir.
- Ekleme ve düzenleme formu bugünkü `NetworkCameraForm`'dan türetilir. Kayıt cihazında kanal *seçilmez*, kanallar yalnızca listelenir ve test edilir.
- "Bağlantıyı test et" bugünkü sınama yolunu kullanır.
- Silme onayla yapılır. O cihazı kullanan şablon kutuları "Kamera silinmiş" gösterir. Sayım o cihazdaysa sayım durur ve kaynak seçimi boşalır.

**Sayım kaynağı.**
- Canlı sekmesinde kaynak "iPhone kamerası" ya da listeden bir kameradır.
- Seçici kameraları cihaz adının altında gruplar. Kayıt cihazında kanallar ad ve küçük resimle gelir; küçük resim bugünkü `snapshot` ile alınır.
- Seçim `bs.countCamera` (`{sourceId, channelId}`) olarak saklanır. `bs.source` (phone/network) bugünkü gibi kalır.
- Kurulum sihirbazındaki ağ kamerası adımı da bir cihaz ekler ve onu seçer.
- Sayım için henüz kamera seçilmemişse, kaydedilen cihazın formunda seçilen kamera sayım kamerası olur (sihirbazda her zaman).

**Geçiş (ilk açılışta bir kez).** `bs.netcam` doluysa:
- ondan bir cihaz kurulur. Ad, türe göre "Kamera 1" ya da "NVR 1" olur.
- eski anahtar zinciri hesabının (`camera` ya da `recorder`) şifresi `device.<id>`'ye kopyalanır.
- kayıtlı `recorderChannel` varsa `bs.countCamera`'ya yazılır.
- Eski anahtarlar bir sürüm boyunca silinmez; geri dönüş güvenliği için tutulur.
- Geçiş iki kez çalışmaz. `bs.devicesMigrated` bayrağı bunu engeller.

## 2. İzleme sekmesi
**Yer.** Alt çubuktaki sıra: Canlı · **İzleme** · Genel bakış · Öğret · Ayarlar. Simge `square.grid.2x2`.

**Şablonlar.**
- Üstte şablon seçici, "Yeni şablon" ve "Düzenle". Son açılan şablon hatırlanır.
- Biçim sözleşmedeki `view-template.schema.json` ile aynıdır: `{id, name, layout, tiles, createdAt, updatedAt}`; `tiles[i]` ya `null` ya da `{sourceId, channelId}`.
- Dosya Application Support'ta atomik yazılan `views.json`'dur. Bozuk dosya kenara ayrılır ve ileti gösterilir.
- **Kurallar:**
  - ad 1–60 karakter; çakışmada " (2)" eklenir;
  - düzen katalogda olmalı;
  - `tiles` uzunluğu düzenin hücre sayısına eşit olmalı;
  - aynı kamera bir şablonda en fazla bir kez yer alır.
- **Düzenleyici:**
  - ad girilir ve 9 düzenden biri seçilir (simgeli ızgara);
  - boş kutuya dokununca kamera seçici açılır (sayım seçicisiyle aynı bileşen);
  - dolu kutuya basılı tutunca "Değiştir" ve "Boşalt" çıkar;
  - düzen değişince kutular sırasıyla yeni düzene taşınır, sığmayanlar düşer ve bu söylenir;
  - silme onayla yapılır.
- **NVR'dan şablon:**
  - bir kayıt cihazı seçilir;
  - kanal sayısına uyan en küçük düzen (`smallest_for(n)` ile aynı kural) kurulur ve kanallar sırayla yerleştirilir;
  - 16'dan fazla kanalda ilk 16'sı alınır ve "N kanaldan 16'sı eklendi" denir;
  - ad cihaz adıdır, çakışırsa " (2)" eklenir.

**Izgara.**
- Kutular düzenin hücrelerine oransal yerleşir; aralarında 2 pt boşluk vardır. Görüntü kutuya en-boy oranı korunarak sığdırılır.
- Kutunun sol altında kamera adı yazar. Ortada Türkçe durum metni çıkar (bkz. "Hata durumları").
- Sayılan kameranın kutusunda sayaç rozeti görünür: kişi sayımında Giriş/Çıkış, ürünlerde toplam.
- **Boş durum.** Cihaz yoksa "Önce Ayarlar → Cihazlar'dan kamera ya da NVR ekle" yazar ve Ayarlar'a giden düğme bulunur. Şablon yoksa "Yeni şablon" ve "NVR'dan şablon" düğmeleri çıkar.

**Yan çevirme.**
- Uygulama bugün yalnızca dikey çalışır. Info.plist yatay yönleri de açar.
- Uygulama yönü yalnızca İzleme sekmesi (ızgara ya da tek kamera) görünürken serbest bırakır, diğer sekmelerde dikeye kilitler.
- Yatayda ızgara tam ekran olur; çubuklar ve şablon seçici gizlenir.

**Tek kamera.**
- Kutuya dokununca o kamera tam ekran ve ana akışla açılır.
- Ana akışın ilk karesi gelene kadar alt akışın son karesi kesintisiz gösterilir.
- Düğmeler:
  - "Kapat";
  - "Bu kamerayı say": kaynağı bu kamera yapar ve Canlı sekmesine geçer. Başka bir kamerada sayım sürüyorsa "Sayım <ad> kamerasına geçsin mi?" diye onay ister.
- Doğrudan kamerada ana akış markanın ana akış yoludur. Tam RTSP adresi girilen kamerada alt ve ana ayrımı yoktur; aynı adres kullanılır.

**Teşhis.** Şablon adına uzun basınca küçük bir satır açılır: kutu başına kare/sn, açık bağlantı sayısı ve ısı durumu. Ölçüm için gereklidir; normal kullanımda görünmez.

## 3. Görüntü motoru
**Okuyucu.** `CameraReader` her kamera ve nitelik (alt/ana) için bir bağlantı açar:
- bugünkü `NetworkCameraSource` (RTSP + `H26xDecoder`, VideoToolbox) kullanılır;
- kareler `CVPixelBuffer` olarak gelir;
- kutu, kareyi hazır görüntü örneği olarak bir `AVSampleBufferDisplayLayer`'a verir. Piksel kopyası yapılmaz.

**Dağıtıcı (`CameraHub`).** Web'deki `ViewHub` ile aynı fikirdir:
- Anahtar `(sourceId, channelId, nitelik)`'tir. Her anahtar için tek okuyucu açılır ve aboneler (kutular) aynı kareyi paylaşır.
- **Sayımla paylaşım:**
  - Sayım bir ağ kamerasındaysa hub o kamerayı sayımın kaynağından besler. Kutu sayımın karesini gösterir; nitelik ne olursa olsun ikinci bağlantı açılmaz.
  - Sayım bundan etkilenmez: kareler sayım kapısından (`FrameGate`) önce kopyasız paylaşılır, sayımın kare akışı değişmez.
  - Sayım kaynağı kopup yeniden bağlanırken kutu "Bağlanıyor…" ve son kareyi gösterir, kendi okuyucusunu açmaz.
- **Kayıt cihazı oturumu.** Her cihaz için tek bir `RecorderClient` kullanılır. TRASSIR'da tek oturum (sid) açılır; kanal başına yalnızca görüntü jetonu alınır. Hikvision ve Dahua'da adres doğrudan kurulur.
- **Sınırlar.**
  - Aynı anda en çok 16 alt akış ve 1 ana akış açık olur. Sayımın kendi bağlantısı bu sayıya girmez.
  - Sınır dolunca abonesi kalmamış (boşta bekleyen) aynı nitelikteki en eski okuyucu hemen çıkarılır; şablon geçişinde "Sınır aşıldı" görünmez. Çıkarılacak okuyucu yoksa kutuda "Sınır aşıldı" yazar.

**Yaşam döngüsü.**
- Okuyucular yalnızca İzleme sekmesi ekrandayken ve uygulama öndeyken açıktır.
- Sekme değişince **5 sn** beklenir, sonra okuyucular kapanır. Kısa gidip gelmelerde yeniden bağlanılmaz.
- Ekran kilitlenince ya da uygulama arka plana gidince okuyucular hemen kapanır: iOS uygulamayı askıya aldığı için bekleme sayacı işlemez. Denetim Merkezi gibi kısa kesintilerde (uygulama etkin değil ama ön planda) akışlar sürer.
- Tek kamera açıkken görünmeyen kutuların okuyucuları da 5 sn sonra kapanır. Izgaraya dönünce son kareler hemen görünür ve okuyucular yeniden açılır.
- Şablon değişince iki şablonda da olan kameraların okuyucuları kesilmez.
- Sayım bu kuraldan bağımsızdır; bugünkü gibi sekme değişse de sürer.

**Yeniden bağlanma.**
- Bekleme 1, 2, 4… sn diye büyür, en çok 30 sn olur. İlk kare gelince sıfırlanır (mevcut `NetworkCameraSource` davranışı).
- Kimlik hatasında yeniden denenmez. Kutuda "Şifre hatalı" yazar; kutuya dokununca ya da cihaz düzenlenince yeniden denenir.

**Isınma.** `ProcessInfo.thermalState` `.serious` ya da üstü olunca ekranın üstünde "Telefon ısındı, daha küçük bir şablon önerilir" uyarısı çıkar. Akışlar kendiliğinden kesilmez.

## Hata durumları (kutu metni)
| Durum | Metin |
|---|---|
| bağlanıyor / yeniden bağlanıyor | Bağlanıyor… (son kare görünür kalır) |
| ağ hatası, zaman aşımı | Bağlantı yok |
| 401/kimlik hatası | Şifre hatalı |
| NVR bağlantıyı reddetti (453/503, oturum sınırı) | NVR bağlantı sınırına ulaştı |
| hub sınırı dolu | Sınır aşıldı |
| cihaz silinmiş | Kamera silinmiş |
| kanal NVR'da artık yok | Kanal bulunamadı |
| desteklenmeyen kodek | Görüntü biçimi desteklenmiyor |

## 4. Sözleşme, test, ölçüm, yayın
**Sözleşme.**
- `contracts/view-layouts.json` uygulamaya kopya olarak değil, `project.yml` kaynak yoluyla **doğrudan** paket kaynağı olarak eklenir. Uygulama düzenleri açılışta bu dosyadan okur.
- Şablonlar `view-template.schema.json` biçimindedir.
- Sözleşme değişmez. `docs/02-contracts.md` §8'e "iPhone da bu dosyayı paketten okur; kimlikler cihaz kimliğidir" notu eklenir.
- Cihaz listesi telefona özgü bir ayardır, sözleşmeye girmez.

**Birim testler (BantSayacTests, ağsız):**
- **Düzenler:** paketteki sözleşme dosyası okunur; 9 düzenin hücre konumları ve `smallestFor(n)` (web'deki `smallest_for` ile aynı: 1→1, 2→2, 3→3, 5→6, 7→8, 10→12, 13→16, 20→16) sınanır.
- **Şablon deposu:**
  - ekleme, değiştirme, silme;
  - ad kırpma ve çakışma eki;
  - tekrar eden kameranın reddi;
  - yanlış uzunluğun reddi;
  - bozuk dosyanın kenara ayrılması;
  - `contracts/examples/view-template-4.json`'ın okunması.
- **Cihaz deposu ve geçiş:**
  - eski kamera ayarı → "Kamera 1" + şifre + sayım seçimi;
  - eski NVR ayarı → "NVR 1" + kanal seçimi;
  - geçişin ikinci kez çalışmaması;
  - silmede şifrenin de silinmesi.
- **CameraHub (sahte açıcı + elle ilerletilen saat):**
  - anahtar başına tek okuyucu;
  - sayım kaynağından besleme ve ikinci bağlantının açılmaması;
  - 5 sn kapanış payı;
  - geri çekilme ve sıfırlanma;
  - kimlik hatasında yeniden denenmemesi;
  - 16+1 sınırı ve boştaki okuyucunun çıkarılması;
  - şablon geçişinde ortak kameraların kesilmemesi;
  - silinmiş cihaz ve bulunamayan kanal.
- **NVR'dan şablon:** 4, 9 ve 20 kanal → doğru düzen ve "16'sı eklendi".

**Arayüz testi (CI simülatörü, mevcut MediaMTX + `tools/mock_nvr.py`):**
- Yeni test: Ayarlar → Cihazlar'dan sahte Hikvision NVR eklenir → "NVR'dan şablon" → kutularda kare sayacı artar (kutunun erişilebilirlik değeri) → kutuya dokununca tek kamera açılır → "Bu kamerayı say" → Canlı sekmesinde o kamera sayılır.
- Mevcut kayıt cihazı testleri (TRASSIR, Hikvision, Dahua) yeni "cihaz ekle → kanal seç" akışına uyarlanır. Ağ kamerası sayım testi (referans sayı) aynı kalır.

**Ölçüm (kullanıcıyla, ofis NVR'ı).** Teşhis satırıyla şunlara bakılır:
- 4, 9 ve 16'lı şablonlarda kutu başına kare/sn;
- 10 dakikada ısı durumu ve pil yüzdesi düşüşü;
- sayım çalışırken sayımın kare hızı.

Sonuçlar `docs/12-durum.md`'ye yazılır.

**Yayın ve belgeler.**
- Ayrı dalda, görev görev ve incelemeyle uygulanır. Swift kodu bu bilgisayarda derlenmez; her adım GitHub Actions'ta (ios, ios-uitest) derlenir ve test edilir.
- Bitince TestFlight derlemesi gönderilir ve kullanıcıya haber verilir.
- Güncellenecek belgeler:
  - `docs/04-ios-app.md`: Cihazlar, İzleme;
  - `docs/10-field-setup.md`: cihaz ekleme;
  - `docs/02-contracts.md` §8 notu;
  - `docs/12-durum.md`;
  - `apps/ios/README.md`.

## Riskler
- **NVR eşzamanlı bağlantı sınırı.** Bazı cihazlar (lisans ya da çıkış bant genişliği) 16 alt akışa izin vermeyebilir. Kutuda "NVR bağlantı sınırına ulaştı" görünür. Ölçümde gerçek sınır belgeye yazılır.
- **Isınma ve pil.** 16 canlı akış donanım çözücüde kâğıt üstünde rahattır, ama sürekli kullanımda ısınma ölçülmeden bilinemez. Uyarı var, otomatik kısma yok.
- **Derleme.** Swift yalnızca CI'da derlenir. Görevler küçük tutulur ve her görev CI'da yeşil olmadan sonrakine geçilmez.
- **Geçiş.** Anahtar zinciri kopyası başarısız olursa cihaz şifresiz kurulur ve kutuda "Şifre hatalı" görünür. Eski hesaplar silinmediği için veri kaybolmaz.
