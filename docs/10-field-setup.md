# 10 — Saha Kurulumu, Kalibrasyon ve Kabul Testi

## 1. Montaj
- Kamera bandın **tam tepesinde**, optik eksen banda dik. Eğik açı ürün boyutunu konuma göre değiştirir (QC ve boy sınıfını bozar).
- Montajı bant şasesine değil **ayrı stand/kola** bağla; titreşim sayımı bozar.
- Ürün kadrajda en az 4–5 kare görünmeli: `kadraj boyu (mm) / bant hızı (mm/sn) × fps ≥ 5`. Örnek: 400 mm kadraj, 1000 mm/sn bant, 25 fps → 10 kare ✔︎.
- iPhone: şarja bağlı, kılıfsız, doğrudan güneş almayan yer. Gece boyu çalışacaksa ısınmaya karşı küçük fan değerlendirilebilir.

## 2. Işık
- Sabit, titreşimsiz (flicker'sız) LED. Tavan floresanları 50 Hz titreşim yapar; kısa pozlamada şerit/parlaklık dalgalanması görülürse LED ekle.
- Yumurta: yandan ya da halka ışık, koyu bant/arka plan en iyi kontrast. Kılcal çatlak için alttan aydınlatma (candling) gerekir; üstten kamera yalnızca belirgin kırıkları görür.
- Torba: geniş yumuşak ışık (difüzör), parlak plastik torbalarda yansımayı azaltmak için ışığı 45°'ye al.

## 3. CCTV kamera ayar listesi (IP / AHD)
| Ayar | Değer | Neden |
|---|---|---|
| Pozlama/obtüratör | Manuel, 1/500–1/1000 sn | Hareket bulanıklığı |
| Kazanç (gain) | Sabit ya da üst sınırlı | Gürültü dalgalanması |
| Gece/gündüz modu | Sürekli **gündüz (renkli)**, IR kapalı | IR geçişi arka planı bozar |
| WDR / BLC / HLC | Kapalı | Parlaklık sıçramaları |
| Akıllı kodek (H.265+, H.264+, dinamik GOP/fps) | Kapalı | Değişken kare zamanlaması izlemeyi bozar |
| Alt akış | 640×360 (ya da 704×576), 25 fps, CBR | Sayım için yeterli, CPU dostu |
| Ana akış | 1080p, 25 fps | NOK görseli ve barkod (`qcSource`) |
| Gürültü azaltma (3D DNR) | Düşük | Yüksek DNR hareketli üründe iz bırakır |
| Odak | Manuel, kilitli | Otomatik odak dolaşması |

## 4. Kalibrasyon prosedürü
1. ROI'yi bandın kullanılan kısmına, sayım çizgisini ROI'nin ortasına yerleştir; akış yönünü seç.
2. **Boş bant öğren** (bant çalışırken, üzerinde ürün yokken). Önerilen eşik otomatik gelir.
3. **Örnek ürün geçir:** 8 ürün tek tek ve aralıklı.
4. Maskeyi kontrol et: ürün tam dolu yeşil, bant boş. Ürün parçalıysa "birleştirme"yi artır; bantta yeşil gürültü varsa eşiği artır.
5. QC açılacaksa: mm/piksel kalibrasyonu (cetvel ya da bilinen ölçülü nesne), sonra 50 sağlam üründe metriklerin dağılımına bakıp eşikleri ayarla (dashboard → hat → metrik histogramı).
6. Kaydet; profil adını ürün + hat olarak ver.

## 5. Sorun giderme
| Belirti | Olası neden | Çözüm |
|---|---|---|
| Fazla sayım | Bant dikişi/leke ürün sanılıyor | Eşik ↑, min. alan oranı ↑, ROI'yi daralt |
| Eksik sayım (seyrek akış) | Kontrast düşük | Işık/arka plan, eşik ↓ |
| Eksik sayım (yoğun akış) | Bitişik ürünler tek leke | "Bitişik ayır" açık, örnek kalibrasyonunu tekrarla; olmuyorsa ML (09) |
| Çift sayım | Ürün parçalı görünüyor | Birleştirme ↑ |
| Uzun süre sonra sayım bozuluyor | Işık değişti | Boş bandı yeniden öğren; arka plan uyum hızı ↑ |
| fps düşük | Isınma / işlemci | İşleme genişliği ↓, alt akış |

## 6. Kabul testi (müşteri teslimi)
- **Sayım:** 3 koşu × en az 500 ürün, elle (ya da PLC/kantar) sayımla karşılaştırma. Rapor: koşu başına hata (%). Hedef müşteriyle önceden yazılı belirlenir (ör. ≤ %0,5).
- **QC:** bilinen 20 hatalı + 480 sağlam ürün karışık. Rapor: yakalanan hatalı oranı, sağlamlarda yanlış NOK oranı.
- **Dayanıklılık:** 8 saat kesintisiz; ağ 10 dk kesilip geri gelince veri kaybı yok.
- Sonuçlar `docs/acceptance/<müşteri>-<tarih>.md` olarak saklanır.
