# 12 — Durum Özeti (2026-10-01)

Bu oturumda yapılan her şeyin toplu dökümü: ne bitti, nasıl doğrulandı, neler açık, sırada ne var.
Repo: `github.com/oguzmeric/Bandvision` (özel). Ayrıntılar ilgili dokümanlarda; burası giriş noktası.

## 1. Altyapı

| Konu | Durum |
|---|---|
| Repo | Zip'ten kalıcı klasöre (`C:\Users\MSI-LAPTOP\bantvision`) taşındı, git + GitHub (özel) |
| CI `ci` | Her push'ta: edge çekirdek testleri + ruff, sözleşme doğrulaması |
| CI `ios` | Her iOS değişikliğinde macOS'ta Xcode 26 ile imzasız Release derleme + **sıkı concurrency denetimi (uyarı = hata)** |
| CI `testflight` | Elle tetiklenir (Actions → testflight → Run workflow): arşiv, otomatik imzalama, App Store Connect'e yükleme |
| Apple | Bundle ID `com.oguzmeric.bantsayac`, App Store Connect kaydı "Bant Sayaç", Internal Testing grubu |
| Secret'lar | `APPLE_TEAM_ID`, `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_P8` (GitHub Actions secret; değerler repoda yok) |

TestFlight kurulumunda çözülen sorunlar: .p8 anahtarı tarayıcı formunda CRLF'e dönüşüyordu (workflow artık her yapıştırma biçimini normalize ediyor), `ASC_KEY_ID` başka anahtarındı (401; teşhis adımı eklendi), Apple iOS 26 SDK şartı (Xcode 26.3 seçiliyor).

## 2. TestFlight derlemeleri

| Derleme | İçerik |
|---|---|
| 6 | İlk yükleme: uygulama derleniyor, açılıyor; ikon |
| 7 | Yoğun akışta arka plan kayması düzeltmesi |
| 8 | Bitişik ürünlerde birleşme/bölünme izleme, Swift yuvarlaması Python ile aynı |
| **9** | **Video modu** (Fotoğraflar/Dosyalar'dan video sayımı) + §7 fps ölçeklemesi |

## 3. Yol haritası (F0) ve sözleşmeler

- **F0.1 iOS derleme:** ✅ Xcode 16.4 ve 26.3'te hatasız; sıkı concurrency 9 uyarı → 0. Kabul kriterleri (gerçek iPhone'da ROI, kalibrasyon akışı, ≥ 45 fps) **kullanıcı testi bekliyor**.
- **F0.2 Swift testleri:** ⏳ yapılmadı. Swift çekirdeği Python'a satır satır uyarlandı ve derleniyor, ama Swift'te otomatik test yok.
- **F0.3 Sözleşme doğrulaması:** ✅ `tools/validate_contracts.py`; eski CI `uuid`/`date-time` formatlarını hiç denetlemiyordu. 8 örnek, 23 olumsuz test (bozulmuş örnek doğru kuraldan reddediliyor mu), Python `Profile` ↔ şema gidiş-dönüş testi.
- **Genel kabul ölçütü eklendi** (`01-roadmap.md`): her ürün profili için sayım doğruluğu **≥ %98, hedef %99**; ölçüm sahadan ≥ 3 video × ≥ 200 ürün, `--truth` ile.

## 4. Sayım algoritmasında bulunan ve düzeltilen hatalar

Hepsi `03-algorithm.md`'de (bağlayıcı referans), Python'da ve Swift'te birlikte değişti; her biri için eski kodda kırmızı olan regresyon testi var.

| # | Hata | Etki (önce → sonra) | Bölüm |
|---|---|---|---|
| 1 | Ürün altındaki arka plan güncellemesi çok hızlıydı (0,05): yoğun akışta arka plan ürüne kayıyor, şerit tek lekeye dönüşüyordu | %76 dolulukta 60 üründen **26** → **60** (≤ %95 doluluğa kadar %100) | §2.4 |
| 2 | Birbirine değen ürünler kareden kareye bir ×2 bir ayrık görünüyor; her birleşmede yeni iz doğuyor, izler lekeden kopuyordu | 100 yumurtalık render videoda **110** → **100**; 4 farklı videoda **400/400** | §4.0, §4.5, §4.7 |
| 3 | Swift `.rounded()` 2,5'i 3'e, Python `round` 2'ye yuvarlıyordu | iPhone ile referans aynı durumda farklı sayıyordu → aynı | §4 |
| 4 | Swift her kaynağı 60 fps varsayıyordu (§7 ölçekleme yoktu) | 30 fps videoda/yavaş telefonda eşleştirme ve arka plan hızı yanlıştı → Python ile aynı | §5, §7 |

Doğrulama durumu: sentetik senaryolar (tek sıra, üç şerit, arka arkaya/yan yana bitişik, titreşen çiftler) **60/30/25 fps'te %100**; render videolar %100. Swift tarafı yalnızca derleme + kod incelemesiyle doğrulandı (bkz. F0.2).

## 5. Video ile test araçları

| Araç | Kullanım |
|---|---|
| `python -m bantvision.video video.mp4 --truth N` | Masaüstünde videodan sayım: otomatik kalibrasyon (arka plan, eşik, yön, tek ürün alanı), işaretli MP4, `ozet.json` (hata %), sözleşmeye uygun `profil.json`, `sayimlar.csv`. Yoğun bantta `--bg-range`, ayrı kalibrasyon videosu için `--profile`. |
| `python tools/make_test_video.py` | Sayısı bilinen test bandı videoları: `1_kalibrasyon.mp4` (boş bant + 8 yumurta), `2_test_100_yumurta.mp4` (%70 tek, %20 arka arkaya, %10 yan yana bitişik), `manifest.json`. Ekranda oynatıp telefonla çekmek ya da video moduna yüklemek için. |
| iPhone video modu (derleme 9) | Üst çubuk → film simgesi → video seç; boş bantla başlıyorsa arka planı ilk 1 sn'den öğrenir; sonunda "Doğru adet" → doğruluk %. Video sayımı canlı kayda karışmaz. |

Gerçek video denemesi: Pexels'ten 4 video indirildi (`data/videos/`, repoda değil). Hiçbiri sayım düzeneğine uygun değildi (eğik/yükleme ucundan bakış, hareketli kamera, kurgu). Ama video aracının eşik tahmininde bir zayıflığı ortaya çıkardılar (eşik 82–100 → 12, ardışık kare farkıyla).

Test sayısı: Python 30 test (çekirdek, video aracı, render), sözleşme 38 test; hepsi CI'da yeşil.

## 6. Araştırma ve tasarım notları

- **Enao Vision** (iPhone ile kalite kontrol, rakip): `11-market-notes-enao.md`. Saha ipuçları (montaj, yumurta için yandan ışık, ≥ 10 px kuralı, gölge modu), fiyatlar, ürün fikirleri.
- **"Örnekle öğret" (Teach)**: `09-ml-roadmap.md` §4b. Apple Vision `VNGenerateImageFeaturePrint` ile eğitimsiz iyi/kötü sınıflandırma; arayüz Enao'daki Teach/Overview düzenine benzer.
- **Kamera markaları** (Dahua, Hikvision, Axis, Pelco, TRASSIR, Vivotek, Karel, Milesight, Mobotix): `10-field-setup.md` §3b. Birincil yol ONVIF ile akış adresini otomatik almak; marka bazında tipik RTSP adresleri, akıllı kodek adları, uygunluk ön testi.

## 7. Açık konular

- **Telefonda doğrulama bekleniyor:** derleme 9 ile test videoları (kalibrasyon + 100 yumurta) — uygulama kaç sayıyor? F0.1 kabul kriterleri (fps ≥ 45).
- **Swift otomatik testleri yok (F0.2):** Python ile aynı sentetik senaryoları Swift'te koşturan test hedefi gerekli.
- **Gerçek saha videosu yok:** %98–99 hedefi ancak gerçek hattan, sabit kamerayla çekilmiş videolarla kanıtlanabilir.
- Swift `ProductProfile` hâlâ sözleşmenin alt kümesi (`source`, `qc`, `scale`, `io` yok; F1.1).
- Yerel ortam notu: Windows'ta Python venv `%TEMP%\claude\venv-bv` altında; repoda `.venv` yok. `pip install -e ".[dev]"` ile kurulabilir.

## 8. Sırada

1. Derleme 9'un telefonda denenmesi ve sonuca göre düzeltme.
2. **Overview + Teach + kalite kontrol** (Enao görselindeki gibi: ürün kartları, Pass/Fail, güven %, iyi/kötü işaretleme). Python'daki ölçüme dayalı QC'nin (boy, en-boy, kırık/ezik, leke, boy sınıfı) iPhone'a aktarılması (F4) ve örnekle öğretme (F7.0).
3. **Edge kutusu (F2):** RTSP/ONVIF kamera kaynağı, yeniden bağlanma, outbox, tarayıcıda önizleme, Docker. Gerçek bir kamerayla (IP + marka) geliştirmek en sağlıklısı.
4. F0.2 Swift testleri, F1.1 sözleşme v1 + outbox, F1.2 ekranda iz kimlikleri.
