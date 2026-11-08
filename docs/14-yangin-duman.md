# 14 — Yangın / duman erken uyarısı

> **Erken uyarıdır; yangın algılama ve alarm sisteminin yerine geçmez.** Sertifikalı (EN 54 vb.) bir yangın algılama
> sistemi değildir; mevcut duman/ısı dedektörlerinin ve alarm panelinin yanında, kameradan erken haber vermek içindir.

Kamera görüntüsünde alev ve dumanı görüp mevcut güvenlik alarmı yolundan (panel alarmı, olay resmi, 8 sn önce + 4 sn
sonra olay kaydı, Telegram, Alarmlar sayfası) haber verir. Yalnızca bilgisayardaki analiz sunucusunda çalışır; iPhone
profili okur ve korur ama analiz etmez. Görüntü bilgisayardan çıkmaz; Telegram'a resim yalnızca kamerada "Alarm resmini
gönder" açıksa gider.

İlgili belgeler: karar katmanı `03-algorithm.md` §4.12; profil ve video işi sözleşmesi `02-contracts.md` (`countMode:
"fire"`, `fire` nesnesi, `preset: fire`); panel ve API `13-web-platform.md` "Yangın / duman"; durum ve ölçüm listesi
`12-durum.md` §5m; tasarım `docs/superpowers/specs/2026-11-08-yangin-duman-design.md`; eğitim araçları
`tools/fire_train/README.md`.

## 1. Durum: model henüz yok

Yazılım hazırdır, **model dosyası (`fire_smoke_v1.onnx`) dağıtılmıyor.** Model, kabul hedefleri (§6) gerçek veriyle
ölçülüp tutana ve kullanıcı onaylayana kadar yayımlanmaz; indirme adresi boştur. Model yokken:
- canlı oturum açılır ama **sağlıksızdır**: kart "Sorun", neden "Yangın/duman modeli kurulu değil.", ayar panelinde
  "Yangın/duman modeli: kurulu değil"; 60 sn'den uzun sürerse alarm şeridinde "Yangın/duman kamerası izlenmiyor" uyarısı;
- "Video ile test"te iş başarısız olur: "Analiz başarısız: Yangın/duman modeli kurulu değil.".

Sessizce "izleniyor" görünmez.

## 2. Kullanım

- **Canlı:** menüde Analizler → **Yangın / duman** (`/live?tur=yangin`) → "Yeni analiz" → kamera → hazır profil
  **Yangın / duman**. Oturum sayım yapmaz, alarm üretir. Alan ve sayım çizgisi bu modda yoktur; görüntünün tamamı
  izlenir, dışarıda bırakma **hariç bölgelerle** yapılır.
- **Ayarla** (kamera başına kaydedilir):
  - **Yangın** (alev) kuralı: aç/kapa ve süre 2–10 sn (varsayılan 3);
  - **Duman** kuralı: aç/kapa ve süre 5–30 sn (varsayılan 8); ikisi birden kapatılamaz ("En az bir kural açık olmalı.");
  - **Hassasiyet:** Düşük / Normal / Yüksek (varsayılan Normal);
  - **Alarm resmini gönder** (Telegram'a olay resmi; varsayılan kapalı, resim bilgisayarda her zaman saklanır);
  - **Hariç bölgeler:** en çok 8 çokgen; kutusunun merkezi bir bölgenin içinde kalan alev/duman alarm vermez.
- **Alarm:** panelde "Yangın" / "Duman", Telegram'da "🔥 YANGIN" / "💨 DUMAN" ve ikinci satır "Görüntüyü hemen kontrol
  edin.". Aynı kamera ve türde 60 sn içinde ikinci bildirim gitmez (güvenlik alarmıyla aynı tekrar önleme).
- **Yanlış alarm:** alarm penceresinde "Yanlış alarm" denince alarm onaylanır ve görüntüsü zor örnek olarak saklanır (§8).
- **Video ile test:** "Ürün" listesinde **Yangın / duman**; kurallar ve hassasiyet aynı. Komut satırı:
  `python -m bantvision.video VIDEO --preset fire [--fire N | --no-fire] [--smoke N | --no-smoke] [--sensitivity low|normal|high]`.
  Sonuç alarm listesi ve `alarms.csv` (`tur`: Yangın / Duman). Canlıyla aynı çekirdek, video zamanıyla.

## 3. Ayar önerileri

- **Kamera:** alevin ya da dumanın çıkabileceği alanı (raf arası, makine, depo köşesi, park yeri) geniş ve sabit gören
  kamera. Uzaktaki küçük duman 640 piksellik model girişinde kaybolabilir: alan kare yüksekliğinin en az birkaç
  yüzdesini kaplamalıdır (kutunun kısa kenarı kare yüksekliğinin %1,5'inden küçükse hiç sayılmaz).
- **Hariç bölgeler:** ocak, fırın, mangal, kaynak tezgâhı, mum, şömine, buhar/duman çıkan baca veya havalandırma,
  hareketli kırmızı/turuncu tabela ve ışıklar. Bölgeyi kaynağın biraz dışına taşacak kadar büyük çizin; bölgeden
  dışarı taşan alev (kutu merkezi bölge dışında) yine alarm verir.
- **Hassasiyet:** önce Normal. Yanlış alarm çoksa önce hariç bölge, sonra Düşük. Küçük ve soluk alev/duman
  kaçırılıyorsa Yüksek (yanlış alarm artabilir).
- **Süreler:** varsayılanlar (alev 3 sn, duman 8 sn) çoğu yer için uygundur. Duman yavaş gelişir; buharın sık olduğu
  yerde duman süresini uzatmak yanlış alarmı azaltır, alarmı geciktirir.
- **Işık:** gece IR geçişi ve ani ışık değişimi kendi başına alarm doğurmaz (§5), ama sürekli yanıp sönen ışık kaynağı
  varsa o bölge hariç tutulmalıdır.

## 4. Nasıl karar verir (özet)

Her analiz edilen karede model alev ve duman kutuları bulur; hassasiyet eşiğinin altındaki, çok küçük ve merkezi hariç
bölgede kalan kutular atılır. Kalan kutu, yaklaşık 1 sn önceki kareye göre içinde değişim (titreşim, yayılma) varsa oy
verir: sabit bir alev resmi, kırmızı lamba ya da beyaz duvar oy vermez. Kare 8×6 hücreye bölünür; alarm için kural
süresi boyunca aynı bölgede (komşu hücreler dahil) oy veren karelerin en az %60'ı ve en az 3 kare olumlu olmalıdır.
Bölüm başına tek alarm; 10 sn olumlu kare gelmezse bölüm biter. Ayrıntı ve sabitler: `03-algorithm.md` §4.12.

## 5. Sınırlar

- **Analiz hızı:** yangın modunda kamera başına en çok **5 kare/sn** analiz edilir (çok kamerada ekran kartını korumak
  için); aradaki kareler önizlemede ve olay kaydında yer alır ama analiz edilmez. Oturum durumundaki `fps` bu
  **analiz** hızıdır (≤ 5), kameranın kare hızı değildir.
- **Yavaş akış:** alarm için kural süresi içinde en az 3 olumlu kare gerekir. Saniyede 1 kareden yavaş akışta 2 sn'lik
  alev kuralı bu koşulu sağlayamaz (alarm gecikir ya da hiç gelmez); böyle kamerada alev süresi 3 sn ya da üstü olmalı,
  akış en az 1 kare/sn olmalıdır.
- **Ani büyük değişim:** kare genelinde 1 sn içinde piksellerin %40'ından fazlası değişirse (ışık patlaması, IR geçişi,
  kamera sarsıntısı) o kare oy dışı sayılır. Görüntünün %40'ından fazlasını 1 sn içinde kaplayan bir alev ya da duman
  patlaması da bu yüzden o anlarda oy vermez; yayılma yavaşladığında oylama sürer. Eşik (`GLOBAL_CHANGE_MAX`) model
  eğitimi sonrası ölçülüp yeniden değerlendirilecek (`12-durum.md` §5m).
- **Bilinen yanlış alarm kaynakları** (bütün görüntü tabanlı yangın tespitlerinde): buhar, sis, toz, araç farları,
  gün batımı ve güneş yansıması, kaynak ışığı, kırmızı/turuncu hareketli nesneler. Hareket denetimi ve hariç bölgeler
  azaltır, sıfırlamaz.
- **Kapsam:** iç mekân ve yakın dış mekân. Termal kamera, uzak orman dumanı ve iPhone'da analiz kapsam dışıdır.
- **Fiziksel çıkış yok:** bu modül röle, siren ya da ejektör tetiklemez.

## 6. Model kartı — `fire_smoke_v1` (taslak; ölçüm bekliyor)

| Alan | Değer |
|---|---|
| Mimari | YOLOX-S (Megvii, Apache-2.0), COCO ön eğitimli `yolox_s.pth`'den ince ayar |
| Giriş / çıkış | 640×640 BGR, sağ/alt 114 gri dolgu; ham ızgara çıktısı `[1, 8400, 7]` = (cx, cy, w, h, nesnelik, fire, smoke). Kod çözme ve sınıf başına NMS (0,45) uygulamada |
| Sınıflar | 0 `fire` (alev), 1 `smoke` (duman) |
| Çalışma | ONNX Runtime; Windows'ta DirectML (ekran kartı) ya da işlemci; Cihaz ayarlarında "Yangın/duman modeli" satırı |
| Eğitim verisi | D-Fire (yalnız `PublicDataset` ön eki taşımayan görüntüler: yazarların kendi kameraları ve web, CC0 1.0 derlemesi; "hiçbiri" görüntüleri negatif olarak kalır), FireNet (MIT). İsteğe bağlı: kullanıcı izniyle kendi zor örneklerimiz (§8) |
| Değerlendirme verisi | D-Fire test bölümü (görüntü düzeyi mAP50), FIRESENSE videoları (CC BY 4.0; olay düzeyi) |
| Kabul hedefleri (v1) | D-Fire test mAP50 (iki sınıf ortalaması) ≥ 0,60; FIRESENSE pozitif videolarının ≥ %80'inde Normal hassasiyette 15 sn içinde alarm; negatif videolarda Normal hassasiyette 0 yanlış alarm |
| Ölçümler | **Henüz yok.** Eğitim ve ölçüm kullanıcı onayıyla yapılacak; sonuçlar `tools/fire_train/eval_fire.py` raporundan buraya yazılır (ölçüm neyse o) |
| Eşikler | `core/fire_rules.py` `THRESHOLDS` başlangıç değerleridir (Düşük .60/.65, Normal .45/.50, Yüksek .35/.40); ölçümden sonra `eval_fire.py` önerisiyle ayrı commit'te güncellenir |
| Bilinen zayıflıklar | Buhar, sis, araç farı, gün batımı, kaynak ışığı; küçük/uzak erken duman (640 giriş); eğitim verisi iç mekân CCTV'sini (depo, fabrika) az temsil eder; FIRESENSE düşük çözünürlüklü ve filigranlıdır, olay düzeyi ölçüm bugünün kameralarını tam temsil etmez; set dışı genelleme yayın literatüründe düşüktür, sahada ayrıca doğrulanmalıdır |
| Yayımlama | Hedefler tutar ve kullanıcı onaylarsa GitHub sürümüne yüklenir, uygulamaya adres ve SHA-256 yazılır. Tutmazsa ayrıntılı rapor kullanıcıya sunulur, model yayımlanmaz |
| Kullanılmayanlar | Ultralytics kodu, ağırlığı ve eğitim araçları (AGPL) hiçbir aşamada kullanılmaz. TRASSIR yangın modülünün yazılımı ya da modeli alınmaz; yalnızca alarm çıktıları kıyaslanır (§9) |

## 7. Veri ve model atıfları

- **D-Fire** — Gaia, solutions on demand; P. V. A. B. de Venâncio, A. C. Lisboa, A. V. Barbosa, "An automatic fire
  detection system based on deep convolutional neural networks for low-power, resource-constrained devices", Neural
  Computing and Applications, 2022. Derleme CC0 1.0 (https://github.com/gaiasd/DFireDataset). `PublicDataset` ön ekli
  görüntüler üçüncü taraf kamu setlerinden gelir ve özgün sağlayıcılarının koşullarına tabidir; ürün modelinde
  kullanılmaz (`prepare_data.py` varsayılan olarak atar).
- **FireNet** — Moses Olafenwa, 2019, MIT lisansı (https://github.com/OlafenwaMoses/FireNET).
- **FIRESENSE** — FIRESENSE projesi (CERTH ve Bilkent Üniversitesi) yangın ve duman videoları, Zenodo kaydı 836749,
  CC BY 4.0 (https://zenodo.org/records/836749). Yalnızca değerlendirmede kullanılır, dağıtılmaz.
- **YOLOX** — Z. Ge, S. Liu, F. Wang, Z. Li, J. Sun, "YOLOX: Exceeding YOLO Series in 2021", arXiv 2107.08430; Megvii,
  Apache-2.0 (https://github.com/Megvii-BaseDetection/YOLOX). COCO ön eğitimli YOLOX-S ağırlığı aynı depodan.

Eğitim sırasında `prepare_data.py` her görüntünün kaynağını ve lisansını `sources.csv`'ye yazar; yayımlanan her model
sürümü bu listeyle birlikte arşivlenir.

## 8. Zor örnekler: yanlış alarmların eğitime katılması

- Bir yangın/duman alarmı "Yanlış alarm" işaretlenince alarm resmi ve olay kaydı bu bilgisayarda analiz sunucusunun veri
  klasöründe `live/hard-negatives/<alarm kimliği>/` altına kopyalanır: `image.jpg`, `clip.webm` (yazılmışsa) ve
  `meta.json` (`id`, `type`, `camera`, `firedAt`, `sourceId`, `channelId`). İşaret geri alınırsa klasör silinir; en çok
  500 alarm tutulur (en eskiler silinir). Hiçbir yere gönderilmez; panelde ayrı ekranı yoktur.
- **Dikkat:** alarm resmi ve olay kaydı **kutuları çizili** hâlidir. Eğitime doğrudan katılmaz (`prepare_data.py`
  zor örnek klasöründeki `image.jpg`'yi atlar). Eğitim için **ham kare** gerekir:
  1. `meta.json`'daki kaynak, kanal ve `firedAt` ile o anın ham görüntüsü kayıt cihazından alınır (panelde Kayıttan
     izleme; TRASSIR'da dışa aktarma) ya da aynı sahne yeniden kaydedilir.
  2. Alarmın olduğu birkaç saniyeden birkaç kare (aynı sahneden çok sayıda neredeyse aynı kare değil) JPEG olarak bir
     klasöre çıkarılır.
  3. `prepare_data.py --negatives <klasör>` bu kareleri kutusuz (negatif) görüntü olarak eğitim havuzuna katar
     (`sources.csv`'de "Zor örnek").
- Müşteri kamerası görüntüsü **yalnızca müşterinin açık izniyle** eğitime alınır ve elle taşınır; eğitim ortamı dışında
  saklanmaz, model ya da veriyle birlikte dağıtılmaz.
- Zor örneklerle yeni sürüm (v2) ayrı bir iştir: aynı kabul hedefleri ve ölçüm, ayrıca toplanan zor örneklerin
  ayrılmış bir bölümünde yanlış alarm sayısı.

## 9. TRASSIR ile kıyas

TRASSIR'ın yangın modülü yalnızca yan yana doğruluk kıyası için kullanılır: aynı sahneye iki sistemin **yalnızca alarm
çıktıları** (zaman, tür, yanlış alarm) karşılaştırılır; TRASSIR'ın yazılımı, modeli ya da ayarları alınmaz. Prosedür ve
sonuç tablosu `12-durum.md` §5m'dedir.
