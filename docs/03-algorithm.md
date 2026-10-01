# 03 — Algoritma Referansı (bağlayıcı)

Bu doküman Swift (`apps/ios/BantSayac/Vision`) ve Python (`services/edge/bantvision/core`) çekirdeklerinin uyması gereken davranıştır. Python kodu bu dokümanın çalışan karşılığıdır.

Girdi: zaman damgalı tam çözünürlüklü kare. Çıktı: lekeler, izler, sayım olayları, (QC açıksa) muayene sonuçları.

## 1. Ön işleme
1. Kareyi profilin `source.rotation` değerine göre dik konuma döndür (iPhone: donanımda 90°, RTSP: genelde 0°).
2. Gri seviyeye çevir (iPhone: YUV'nin Y düzlemi; RTSP: BGR→GRAY).
3. **Kutu-ortalama ile küçült:** `f = max(1, floor(srcW / max(64, processingWidth)))`, `w = floor(srcW/f)`, `h = floor(srcH/f)`. Her çıktı pikseli f×f bloğun ortalaması. (Python'da `cv2.resize(..., INTER_AREA)` kabul edilir; yuvarlama farkı ±1 gri seviye.)

## 2. Arka plan ve segmentasyon
Durum: `bg` (float32, w×h). Boyut değişirse sıfırlanır; yoksa ilk kareyle başlatılır ve o karede leke dönmez.

1. **Eşik:** ROI içinde `mask = |gray − bg| > diffThreshold` (kesin büyüktür). ROI dışı 0.
2. **Açma:** 3×3 erozyon, ardından 3×3 genişleme. Görüntü kenarında yalnızca görüntü içindeki komşular dikkate alınır.
3. **Kapama:** `closeIterations` kez (3×3 genişleme → 3×3 erozyon).
4. **Seçici arka plan güncellemesi:** her piksel için `bg += r · (gray − bg)`; `r = rateEff` (mask=0) ya da `rateEff · 0.002` (mask=1). `rateEff` §7'ye göre.
   - Ürün altındaki katsayı çok küçük olmalı. Yoğun akışta bir piksel zamanın `c` kadarında üründür; arka planın ürüne doğru denge kayması ≈ `k · c/(1−c) · kontrast` (`k` = ürün altı katsayısı). Eski değer `k = 0.05` ile %76 dolulukta (c/(1−c) ≈ 3,2, kontrast 130) kayma ≈ 20 gri seviyeydi; eşiği aşıp ürün arası boşlukları ön plana çeviriyor, şerit tek lekeye dönüşüp sayım duruyordu. `k = 0.002` ile %95 dolulukta bile kayma < 5. Tamamen 0 yapılmaz: banda kalıcı bırakılan bir nesne çok uzun sürede (60 fps'te ~7 dk) arka plana karışabilsin.
5. **Bağlı bileşenler:** 8-komşuluk. Her bileşen için: piksel sayısı, ağırlık merkezi, sınırlayıcı kutu.
6. **Normalizasyon:** `cx = meanX / w`, `cy = meanY / h`, `area = pixels / (w·h)`, kutu da w/h'ye bölünür.

## 3. Filtre ve çarpan
- `minArea = expectedArea · minAreaFactor` (expectedArea > 0 ise), yoksa `minAreaAbs`. `area < minArea` olan lekeler atılır.
- `splitTouching` ve `expectedArea > 0` ise: `ratio = area / expectedArea`; `ratio < 1.5 → 1`, aksi halde `clamp(round(ratio), 1, maxMultiplicity)`.
- Örnek kalibrasyonu sırasında `expectedArea` 0 kabul edilir (çarpan hep 1, filtre `minAreaAbs`).

## 4. İzleme
Akış ekseni: `down/up → y`, `right/left → x`. İşaret `s = +1 (down/right)`, `−1 (up/left)`. Çizgi: `linePosition`.

Her karede:
1. **Aday eşleşmeler:** her (iz, leke) için tahmini konum `p̂ = (x+vx, y+vy)`. `s·(leke_eksen − iz_eksen) < −0.03` ise aday değil (geri gitme yok). `d = ‖leke − p̂‖ ≤ maxDistEff` ise aday.
2. **Açgözlü atama:** adayları `d`'ye göre artan sırala; iz ve leke kullanılmamışsa eşle.
3. **Eşleşen iz güncellemesi:** `v = 0.6·v + 0.4·(leke − konum)`, `konum = leke`, `hits += 1`, `missed = 0`. Çarpan geçmişi son 5, alan geçmişi son 9 değer.
4. **Sayım kuralı:**
   - Henüz sayılmadıysa (`countedSoFar = 0`): `startedBefore` **ve** `hits ≥ minHits` **ve** `s·(eksen − line) ≥ 0` ise say. `delta = max(1, round(mean(çarpan geçmişi)))`, `countedSoFar = delta`. Olay: `isFirstCrossing = true`, `medianArea = median(alan geçmişi)`.
   - Sayıldıysa: son 3 çarpanın **minimumu** `countedSoFar`'dan büyükse farkı ekle (arkadan gelen ürün lekeye katıldı). `isFirstCrossing = false`.
5. **Eşleşmeyen izler:** `missed += 1`, konum `+= v` (öteleme). `missed > maxMissedEff` ya da konum [−0.1, 1.1] dışına çıktıysa sil.
6. **Yeni izler:** eşleşmeyen her leke için iz; `startedBefore = s·(eksen − line) < 0`. Çizgiden sonra doğan iz **asla** sayılmaz (çift sayım koruması).
7. İz kimliği artan tamsayı; ekranda `hex(id)` gösterilir.

## 5. Kalibrasyon
**Boş bant öğrenme** (`backgroundSeconds = 1.0`, `N = round(fps · 1.0)`, en az 15 kare):
- 0. kare: `bg = gray`. Sonrakiler: `bg += 0.15·(gray − bg)` (koşulsuz).
- `0.4·N`'den itibaren her karede ROI içinde `|gray − bg|`'nin %99,5 yüzdeliği ölçülür, en büyüğü `m`.
- Bitiş: `diffThreshold = clamp(int(1.5·m) + 8, 12, 100)`, izler sıfırlanır.

**Örnek ürün öğrenme** (hedef 8): ilk kez sayılan (`isFirstCrossing`) her izin `medianArea`'sı toplanır; hedefe ulaşınca `expectedArea = median(toplanan)`.

## 6. Kalite kontrol (F4)
### 6.1 Ne zaman, hangi görüntüde
- Yalnızca `isFirstCrossing` olaylarında, `delta = 1` ise. Çarpanı > 1 olan lekeler muayene edilmez (bitişik ürünlerin ayrı ayrı muayenesi ML aşamasına kalır).
- Geometri, küçültülmüş görüntüdeki leke piksellerinden hesaplanır (bileşen etiketi korunur).
- Leke/barkod/metin, **tam çözünürlüklü** kareden kırpılır: çekirdek son 3 tam kareyi halka tamponda tutar; leke kutusu %10 dolgu ile tam çözünürlüğe ölçeklenir.
- Barkod/metin asenkron çalışır; 500 ms içinde sonuç gelmezse "okunamadı" sayılır.

### 6.2 Geometri
- `areaRatio = area / expectedArea` → `< areaMinFactor`: `area_low`; `> areaMaxFactor`: `area_high`.
- `aspect`: leke piksellerinin kovaryans matrisinin özdeğerleri λ1 ≥ λ2; `aspect = sqrt(λ1/λ2)`. `[aspectMin, aspectMax]` dışı: `aspect_out`.
- `solidity = piksel sayısı / dışbükey zarf alanı`; zarf, leke piksellerinin **dört köşesi** (x,y),(x+1,y),(x,y+1),(x+1,y+1) üzerinden hesaplanır, böylece değer ≤ 1 olur (Python: `cv2.convexHull` + `cv2.contourArea`; Swift: monotone chain + shoelace). `< solidityMin`: `solidity_low` (kırık, ezik, yırtık torba). Sağlam elips için tipik değer ~0,97.
- Eksen uzunlukları (eşdeğer elips, tam eksen): `L = 4·sqrt(λ)` işleme pikseli → `· f` tam çözünürlük pikseli → `· mmPerPixel` mm.
- **Boy sınıfı:** küçük eksen (mm) için `sizeClasses` sırayla taranır, `minorMm ≤ maxMm` olan ilk sınıf. Ağırlık değil çap tahminidir; tartının yerini tutmaz.

### 6.3 Leke / kir
- Tam çözünürlüklü kırpıntıda ürün maskesi: küçültülmüş maskenin en yakın komşu büyütmesi, ardından `f + 0.03·küçükEksen_tamPiksel` piksel yarıçaplı erozyon; kırpıntı sınırı dışı 0 kabul edilir (büyütmeden kalan karışık kenar blokları ve gölgeler dışlanır).
- `ref = median(maske içi gri değerler)`. Leke pikseli: `gray < ref − darkDelta`.
- `spotRatio = leke pikselleri / maske pikselleri`; `> maxSpotAreaRatio`: `spots`.
- Varsayım: açık renkli üründe koyu leke. Koyu ürün/açık leke için ileride `polarity` alanı eklenir.

### 6.4 Barkod ve metin
- iOS: `VNDetectBarcodesRequest` (sembolojiler profilden), `VNRecognizeTextRequest` (`.fast`, `tr-TR`, `en-US`).
- Edge: `zxing-cpp` (barkod), metin için isteğe bağlı `rapidocr-onnxruntime`.
- `required` ve okunamadı → `barcode_missing` / `text_missing`. `pattern` (regex) eşleşmedi → `*_mismatch`.

### 6.5 Karar
`reasons` boşsa `ok`, değilse `nok`. Tüm ölçümler `metrics` içinde gönderilir (eşik ayarı için). `saveNokImages` açıksa NOK kırpıntısı JPEG (kalite 80, uzun kenar ≤ 640 px) kaydedilir.

## 7. Kare hızından bağımsızlık
Profil parametreleri `referenceFps` (varsayılan 60) için tanımlıdır. Gerçek fps `F` (son 2 sn ortalaması) ile:
- `k = referenceFps / F`
- `maxDistEff = min(0.5, maxMatchDistance · k)`
- `rateEff = 1 − (1 − backgroundRate)^k`
- `maxMissedEff = max(2, round(6 / k))`
- `minHits` değişmez (en az 1).

Not: iOS v1 kodu bu ölçeklemeyi yapmıyor (60 fps varsayıyor). F2 ile birlikte iOS'a da eklenmeli; ayrıca RTSP'de 25 fps tipiktir.

## 8. Bant çalışıyor/durdu
- Son `idleSeconds` (varsayılan 30, cihaz ayarı) içinde en az bir leke görüldüyse ya da sayım olduysa `running = true`.
- Durum değiştiğinde `state` olayı (`motion` / `no_motion`).

## 9. Ejektör zamanlaması (F5)
- Bant hızı: son 2 sn'de sayılan izlerin eksen hızlarının medyanı (normalize/kare) × eksen boyunca tam çözünürlük piksel sayısı × `mmPerPixel` × `F` → mm/sn.
- `delayMs = distanceMm / hız · 1000 − (şimdi − kare zaman damgası) − latencyCompensationMs`.
- `mmPerPixel` yoksa ya da hız < 10 mm/sn ise ejektör tetiklenmez ve uyarı loglanır.
- Komut I/O köprüsüne "X ms sonra darbe" olarak gider (saat senkronu gerekmez).
