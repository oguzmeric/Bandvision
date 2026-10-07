# 03 — Algoritma Referansı (bağlayıcı)

Bu doküman Swift (`apps/ios/BantSayac/Vision`) ve Python (`services/edge/bantvision/core`) çekirdeklerinin uyması gereken davranıştır. Python kodu bu dokümanın çalışan karşılığıdır.

Girdi: zaman damgalı tam çözünürlüklü kare. Çıktı: lekeler, izler, sayım olayları, (QC açıksa) muayene sonuçları.

## 1. Ön işleme
1. Kareyi profilin `source.rotation` değerine göre dik konuma döndür (iPhone: donanımda 90°, RTSP: genelde 0°).
2. Gri seviyeye çevir (iPhone: YUV'nin Y düzlemi; RTSP: BGR→GRAY).
3. **Kutu-ortalama ile küçült:** `f = max(1, floor(srcW / max(64, processingWidth)))`, `w = floor(srcW/f)`, `h = floor(srcH/f)`. Her çıktı pikseli f×f bloğun ortalaması. (Python'da `cv2.resize(..., INTER_AREA)` kabul edilir; yuvarlama farkı ±1 gri seviye.)

## 2. Arka plan ve segmentasyon
Durum: `bg` (float32, w×h). Boyut değişirse sıfırlanır; yoksa ilk kareyle başlatılır ve o karede leke dönmez.

0. **ROI maskesi** (w×h, ROI ya da boyut değişince yeniden hesaplanır):
   - **Dikdörtgen:** `x0 = clamp(int(roi.x·w), 0, w−1)`, `y0 = clamp(int(roi.y·h), 0, h−1)`, `x1 = clamp(int((roi.x+roi.width)·w), x0+1, w)`, `y1 = clamp(int((roi.y+roi.height)·h), y0+1, h)`; piksel `(i, j)` içeride ⇔ `x0 ≤ i < x1` ve `y0 ≤ j < y1`.
   - **Çokgen** (`roiPolygon` varsa, 3–12 köşe, normalize): piksel ayrıca **merkezi** `px = (i + 0.5)/w`, `py = (j + 0.5)/h` çokgenin içindeyse içeridedir. İçerisi **çift-tek kuralı** (yatay ışın): `inside = false`; her kenar `(xa, ya) → (xb, yb)` için (köşe `k` ile `k−1`, ilk kenar son köşeden ilk köşeye) `(ya > py) ≠ (yb > py)` ise `xc = (xb − xa) · (py − ya) / (yb − ya) + xa` ve `px < xc` ise `inside = ¬inside`. Çift duyarlıklı kayan nokta, işlem sırası aynen bu (Python ve Swift aynı pikselleri seçer).
   - `roi`, çokgenin sınır kutusudur (uygulamalar çokgen ayarlarken hesaplar: köşeler [0, 1]'e kırpılır, kutu kenarı en az 0,01, sayım çizgisi `[lo + 0.02, max(lo + 0.02, hi − 0.02)]` aralığına çekilir; Python `Profile.set_polygon` = Swift `ProductProfile.setPolygon`); maske her durumda dikdörtgen ∩ çokgen olduğundan tutarsız veride de davranış tanımlıdır. Sayım çizgisi (`linePosition`) bu kutuya göredir.
   - Amaç: eğik bant ya da kenarda insan/makine hareketi varken yalnızca bant alanı sayılır ve boş bant öğrenmesi (§5) yalnızca bu alana bakar.
1. **Eşik:** ROI maskesi içinde `mask = |gray − bg| > diffThreshold` (kesin büyüktür). Dışı 0.
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
Her izin durumu: konum, hız `v`, `hits`, `missed`, `startedBefore`, `countedSoFar`, çarpan geçmişi (son 5), alan geçmişi (son 9), son lekenin kutusu `bbox` ve o lekeden ize düşen çarpan `lastMult`.
`MERGE_MARGIN = 0.05`. **Yuvarlama:** tüm `round` işlemleri en yakın çifte yuvarlar (2,5 → 2; Python `round`, Swift `.rounded(.toNearestOrEven)`).

**Gözlem** (iz bir lekeyle güncellendiğinde, çarpan `m`, alan `a`): `bbox = leke.bbox`, `lastMult = m`, `hits += 1`, `missed = 0`, geçmişlere `m` ve `a` eklenir, ardından §4.4 sayım kuralı.

Her karede, tahmini konum `p̂ = konum + v`:
0. **Birleşik gruplar:** her leke için `p̂`'si lekenin kutusunun içinde (kenarlar `MERGE_MARGIN · kutu boyutu` kadar genişletilmiş) olan izler bulunur. Bir iz birden fazla grup adayı lekenin içindeyse merkezi `p̂`'ye en yakın lekeye ait olur. **≥ 2 izi olan** leke bir gruptur (birbirine değen ayrı ürünler):
   - Üyeler akışta öndeki önce sıralanır (`−s · p̂_eksen` artan).
   - **Demirleme:** `δ = leke.merkez − ortalama(p̂_üyeler)`; her üye için `yeni = p̂ + δ`, `v = 0.6·v + 0.4·(yeni − konum)`, `konum = yeni`. Üyeler lekenin ortasına zıplamaz (yoksa ayrıldıklarında geri gitme kuralı yüzünden kendi ürünlerini bulamazlar); demirlenmezlerse şişmiş hızla lekeden kopup öne kaçarlar.
   - **Çarpan paylaşımı:** `toplam = max(leke.çarpan, n)`; `k`. üyeye `toplam div n + (k < toplam mod n ? 1 : 0)`, alan `leke.alan / n`. Her üye bu değerlerle gözlemlenir.
   - Gruptaki izler ve leke sonraki adımlarda kullanılmış sayılır.
1. **Aday eşleşmeler** (grupta olmayan iz ve lekeler): `s·(leke_eksen − iz_eksen) < −0.03` ise aday değil (geri gitme yok). `d = ‖leke − p̂‖ ≤ maxDistEff` ise aday. Bu adımdan önce her izin `bbox` ve `lastMult` değeri `önceki` olarak saklanır.
2. **Açgözlü atama:** adayları `d`'ye göre artan sırala; iz ve leke kullanılmamışsa eşle.
3. **Eşleşen iz güncellemesi:** `v = 0.6·v + 0.4·(leke − konum)`, `konum = leke`, sonra leke çarpanı ve alanıyla gözlem.
4. **Sayım kuralı** (her gözlemde):
   - Henüz sayılmadıysa (`countedSoFar = 0`): `startedBefore` **ve** `hits ≥ minHits` **ve** `s·(eksen − line) ≥ 0` ise say. `delta = max(1, round(mean(çarpan geçmişi)))`, `countedSoFar = delta`. Olay: `isFirstCrossing = true`, `medianArea = median(alan geçmişi)`.
   - Sayıldıysa: son 3 çarpanın **minimumu** `countedSoFar`'dan büyükse farkı ekle (arkadan gelen ürün lekeye katıldı). `isFirstCrossing = false`.
5. **Bölünme:** 2. adımda eşleşmiş ve `önceki.lastMult ≥ 2` olan izler ebeveyn adayıdır. Hâlâ eşleşmemiş her leke için, merkezi ebeveynin `önceki.bbox`'ının `v` kadar ötelenmiş ve `MERGE_MARGIN` kadar genişletilmiş hâlinin içindeyse, merkezi ebeveynin (güncel) konumuna en yakın ebeveyn seçilir ve leke onun **çocuğu** olur:
   - `keep = min(ebeveyn.countedSoFar, ebeveyn.lastMult)`.
   - Çocuk: konum = leke, `v = ebeveyn.v`, `hits = ebeveyn.hits`, `startedBefore = ebeveyn.startedBefore`, `countedSoFar = min(ebeveyn.countedSoFar − keep, leke.çarpan)`, geçmişler `[leke.çarpan]`, `[leke.alan]`, `bbox = leke.bbox`, `lastMult = leke.çarpan`.
   - Ebeveyn: `countedSoFar = keep`, çarpan geçmişi `[lastMult]`; `önceki` değeri güncellenir (aynı ebeveyn aynı karede ikinci kez bölünmez).
   - Çocuk, 6. adımdaki silmeye girmez ve 7. adımdaki yeni izlerden sonra listeye eklenir. Bölünmeyi tanımadan, çizgiden sonra ayrılan çiftin ikinci ürünü "çizgiden sonra doğdu" diye hiç sayılmazdı.
6. **Eşleşmeyen izler:** `missed += 1`, konum `+= v` (öteleme). `missed > maxMissedEff` ya da konum [−0.1, 1.1] dışına çıktıysa sil.
7. **Yeni izler:** hâlâ eşleşmemiş her leke için iz; `startedBefore = s·(eksen − line) < 0`, `bbox` ve `lastMult` lekeden. **Başlangıç hızı:** 6. adımdan sonra kalan, `hits ≥ 3` ve `missed = 0` olan izlerin `vx` ve `vy` medyanları (yoksa 0). Banttaki her ürün aynı hızla gider; sıfır hızla doğan iz bir sonraki karede geride tahmin edilir ve gruba giremez. Çizgiden sonra doğan iz **asla** sayılmaz (çift sayım koruması).
8. İz kimliği artan tamsayı; ekranda `hex(id)` gösterilir.

**Neden:** Birbirine hafifçe değen yumurtalar kareden kareye bir birleşik (×2) bir ayrık görünür. Bu kurallar olmadan 100 yumurtalık render videoda 110 sayılıyordu (her birleşmede yeni iz doğuyor, izler lekeden kopuyordu). Testler: `test_synthetic.py::flicker_pairs`, `test_rendered.py`.

Silme sınırı (6. adım) varsayılan olarak her iki eksende `[−0.1, 1.1]`; §4.8'de çizgi çerçevesinin sınırları kullanılır.

### 4.8 Açılı sayım çizgisi (`countLine`)
Profilde `countLine = {a, b}` (normalize uçlar) varsa sayım çizgisi bu doğrudur; `direction` ve `linePosition` sayımda kullanılmaz. Eksik ise davranış yukarıdakinin aynısıdır.
- **Akış yönü:** a'dan b'ye yürürken **sağ el** tarafı (görüntü koordinatları, y aşağı). a→b soldan sağa ise akış aşağı; yönü ters çevirmek uçları değiştirmektir.
- **Eş ölçekli koordinat:** `α = w / h` (işleme karesi, §1.3 sonrası). Normalize nokta `(x, y)` → `q = (x·α, y)` (birim: kare yüksekliği; açılar kare olmayan karede de doğru).
- **Çerçeve:** `A = q(a)`, `B = q(b)`, `L = ‖B − A‖` (`L < 1e-6` ise `countLine` yok sayılır), `d = (B − A)/L`, `n = (−d.y, d.x)`. Nokta için `r = q(x, y) − A`, `v = r·d` (çizgi boyunca), `u = r·n` (akış yönünde; çizgi `u = 0`).
- **İzleyiciye verilen leke:** merkez = ağırlık merkezinin (§2.6) `(v, u)`'su; alan ve çarpan aynı. **Kutu doğrudan piksellerden:** bileşenin her pikselinin merkezi `((i + 0.5)/w, (j + 0.5)/h)` çerçeveye çevrilir, `v` ve `u`'nun en küçük/en büyüğü alınır ve her yöne yarım piksel (`0.5/h`, eş ölçekli birimde bir piksel `1/h`) eklenir. (Görüntüdeki eksen hizalı kutunun köşelerini çevirmek kutuyu iki kez şişirir; değip ayrılan çiftlerde birleşik grup kuralını bozar: 45–60°'de 20 yerine 22.) İzleyici `down` yönü (`s = +1`) ve `line = 0` ile çalışır; `maxDistEff` ve `MERGE_MARGIN` aynı (birim artık kare yüksekliği).
- **Silme sınırı:** görüntünün 4 köşesinin `(v, u)`'daki en küçük/en büyük değerleri `± 0.1`.
- **Geri dönüşüm** (ekrandaki iz işaretleri): `q = A + v·d + u·n`, `x = q.x / α`, `y = q.y`. Sayım olayının kutusu (QC kırpıntısı) görüntüdeki **özgün** lekenin kutusudur.
- **Hız (§9):** bant hızı `|v_u|` ile, `span = kare yüksekliği` alınarak hesaplanır.
- Doğru sonsuzdur (ROI maskesi zaten yalnızca alandaki lekeleri bırakır); arayüz yalnızca alan içindeki parçayı çizer.
- **Doğrulama:** `test_angled_line.py` — 30°, 45°, 60°, 135°, 160°'de tek sıra ve arka arkaya bitişik çiftler tam; yatay `countLine` eski "aşağı, 0.5" ile aynı sayar. **Bilinen sınır:** değip ayrılan çiftler (`flicker_pairs`) döndürülmüş sahnede 30°/60°'de 20 yerine 21–24 sayılabiliyor; **düz çizgide de aynı** sapma çıkar (izleyicinin birleşik grup kuralının genel sınırı, §4.0), açılı çizgiden kaynaklanmaz. İyileştirme ayrı iş.

### 4.9 Şerit tarama sayımı (`countMode = "linescan"`)
Tek sıra gelen **hacimli** ürünler (torba, koli, kasa) için. Bitişik ya da üst üste binmiş ürünler tek leke olur ve bant çoğu zaman hiç boş görünmez; §2–§4 burada boş bant öğrenemez, lekeyi ayıramaz. Şerit tarama arka plan kullanmaz: sayım çizgisi çevresinde bandın kare başına kaymasını ölçer ve çizgiden geçen her satırın parlaklığını "geçen mesafe" ekseninde bir sinyale ekler (sanal çizgi-tarama kamerası). Sinyaldeki çukurlar ürün aralarıdır (ek yeri gölgesi, boşluk), iki çukur arası ürün(ler)dir. Açılı çizgi (`countLine`) ile kullanılmaz; düz çizgi (`direction`, `linePosition`). Python başvurusu: `core/linescan.py`.

0. **Hareketli bölge** (alan bandın dışına taşsa da yalnızca bant): ilk kare ve sonraki **hareketli** kareler saklanır; kare hareketli ⇔ `|kare − önceki|` (ROI maskesi dışı 0) haritasında, ROI dikdörtgeninde akışa dik eksendeki her konumun (dikey akışta her sütunun) ROI satırları üzerinden ortalaması en çok olanı ≥ 1,0. 10 hareketli kare birikince piksel başına **alt medyan** fark haritası (10 değerin sıralı 4. indeksi; siyah kare, sahne geçişi etkisiz) alınır; akışa dik her konum için maske içindeki ortalaması hesaplanır ve en büyüğünün ≥ %25'i olan konumlar seçilir. Etkin maske = ROI maskesi ∩ seçili konumlar; aşağıdaki "ROI dikdörtgeni" yerine seçili konumların ilk–son aralığı (akış ekseni ROI ile aynı, kırpılmaz) kullanılır. Saklanan kareler sonra baştan işlenir (öğrenme sırasında geçen ürün kaçmaz; hareketsiz kare kayma 0 verdiğinden atlanması sonucu değiştirmez). Tam sıfırlamada, ROI/çokgen/eksen değişince bölge yeniden seçilir. Neden: ekran kaydında menüler, kenar rayları, yerde duran torbalar ROI'ye girince satır istatistikleri durağan içerikle dolup kayma 0 ölçülüyordu (tam ekran alanda 7 yerine 1).
1. **Profil** (her kare, §1 sonrası küçük gri kare): ROI dikdörtgeni §2.0'daki gibi (`x0..x1`, `y0..y1`; 0. adımdan sonra etkin bölge), maske §2.0 (0. adımdan sonra etkin maske). Akış ekseni boyunca her satır (`down/up`) ya da sütun (`right/left`) için maske içindeki piksellerin sıralı dizisinden `m = n−1` ile **alt çeyrek** `s[m div 4]`, **alt medyan** `s[m div 2]`, **üst çeyrek** `s[(3m) div 4]`; maske içinde pikseli olmayan satır bir öncekinin değerlerini alır (ilki 0). Uzunluk `N = y1 − y0` (ya da `x1 − x0`); `N < 8` ise sayım yok. Dizi akış yönünde sıralanır (`down/right`: artan, `up/left`: ters). Çizgi: `b = floor(linePosition · H + 0.5)` (yatayda `W`); `down/right`: `ℓ = b − lo`, `up/left`: `ℓ = hi − b`; `ℓ = clamp(ℓ, 2, N − 2)`. Bir satır `k ≥ ℓ` ise çizgiyi geçmiştir.
2. **Kayma** (medyan profil, anahtar kareye göre): `win = max(4, N div 8)`, `smax = max(2, N div 6)`, `ka = max(smax, ℓ − win)`, `kb = min(N, ℓ + win)` (`kb − ka < 4` ise belirsiz). `e(s) = ortalama_k∈[ka,kb) (cur[k] − key[k − s])²`, `s = 0..smax`; `s* = argmin` (eşitlikte küçük). `ē = ortalama e`; `(ē − e(s*)) / (ē + 1e−6) < 0.05` ise **belirsiz**. Aksi halde `0 < s* < smax` ise parabol: `a, b, c = e(s*−1), e(s*), e(s*+1)`, `d = a − 2b + c`, `d > 1e−9` ise `s = s* + 0.5(a − c)/d`.
   - Durum: `key` (anahtar profil), `base`, `dist`, `vel`. İlk karede `key = profil`, `base = dist = vel = 0`. Her karede: belirsizse `D = dist + vel`, `key = cur`, `base = D`; değilse `D = base + s`, ve `s ≥ smax/2` ise `key = cur`, `base = D`. `inc = max(0, D − dist)`, `vel = inc`, `dist = max(dist, D)`. (Anahtar kareye göre ölçmek kare kare yuvarlama hatasının birikmesini önler; ekran kayıtlarında tekrarlanan karelerde artış 0'dır.)
3. **Sinyal:** `acc += inc`, `q = floor(acc)`, `acc −= q`, `q = min(q, N − ℓ)`; bu karede geçen `q` satır, önce geçen önce: `j = 0..q−1` için satır `ℓ + q − 1 − j`'nin (alt, üst çeyrek) çifti eklenir. **Başlangıç:** ilk karede çizgiyi zaten geçmiş kısım `k = N−1 … ℓ` eklenir; `start` = bu uzunluk (merkezi `start`'tan önce olan ürün sayılmaz). Profil uzunluğu ya da `ℓ` değişirse her şey baştan (öğrenilmiş boy ve yön korunur).
4. **Açık/koyu kararı:** boy biliniyorsa (`productLength > 0`) sinyal `start + N` uzunluğa ulaşınca; bilinmiyorsa `start + N`'den itibaren her `max(4, N div 2)` örnekte bir **deneme** yapılır ve yalnızca güvenilirse (seçilen boyda ≥ 4 tam parça ve kalan hata ≤ 0,15) kabul edilir, değilse geri alınır; `start + 2N`'de (ya da video sonunda) sonuç ne olursa kabul edilir (sayılar gecikip topluca gelmesin, erken ve yanlış boy da kalıcı olmasın): iki yorum denenir — açık ürün: sinyal = üst çeyrek; koyu ürün: sinyal = `255 − alt çeyrek` (ürün üstündeki etiket/bant satırı "boşluk" gibi göstermesin diye ürün tarafındaki çeyrek). Her yorumda boy (biliniyorsa o, değilse 5. adım) ve **kalan hata** (`mean |ℓ_i/P − max(1, round(ℓ_i/P))|`, 6. adımdaki taramanın ilk/son hariç parça boyları `ℓ_i ≥ 0.3P`, en az 2 parça) hesaplanır; kalan hatası 0,03'ten fazla küçük olan seçilir. Belirsizse kenar/orta oyu: her karede çizgi çevresindeki 5 satırda ROI'nin ortası (%30–%70) ile kenarları (%15'er) alt medyanlarının farkı > 15 ise +1, < −15 ise −1; toplam < 0 ise koyu. **Önce yayılım ipucu:** satır içi yayılım `s = üst − alt çeyrek`; Pearson ilintileri `cn = r(üst, s)`, `ci = r(255 − alt, s)`. `cn > 0,3` ve `ci < 0` ise açık, `ci > 0,3` ve `cn < 0` ise koyu ürün (ürün banttan darsa ürün satırında kenarlarda bant görünür, boş bant satırı düzdür) — kesin; değilse yukarıdaki kalan hata karşılaştırması (bitişik akışta gölgeli ek yerleri de yayılım verir). Düzenli aralıklı ürünlerde ürün ve boşluk aynı düzende olduğundan kalan hata tek başına yanılabiliyordu. Karardan sonra sinyal tek değerlidir.
5. **Ürün boyu öğrenme** (`productLength = 0`): `pmin = max(4, N div 10)`, `pmax = min(N, len div 2)`. Adaylar: (a) öz-ilinti (`x − ortalama` ve yüksek geçiren `x − kayan ortalama(2·max(2, pmin div 2)+1)`; `ac(g) = Σ x_i x_{i+g} / Σ x_i²`; `[pmin, pmax)`'teki yerel tepeler, en güçlüsü ≥ 0,1 ise gücü onun %60'ından az olmayan en kısa gecikme; iki sinyalden güçlüsü), (b) orta seviyenin (`lo + 0.5·(p90 − lo)`, `lo = p05`, kayan ortalama `max(1, pmin div 8)`) üstündeki, uçlara değmeyen ve `≥ pmin` koşuların medyanı (en az 2). Her aday için 6. adım taramasıyla bulunan parça boylarının medyanı da aday olur. Her adayın (yuvarlanmış; `pmin`'den kısası atılır — kıvrım/etiket parçası) kalan hatası hesaplanır; kalan hatası ≤ 0,15 olanların **en büyüğü**, yoksa en küçük kalan hatalı olan seçilir (P/2 de tam sayı oranları verir, büyükten küçüğe bakılır; 2P oranları 0,5 yapar, elenir). Yüzdelikler interpolasyonsuz: sıralı dizide `floor(q·(n−1))`; `round` yarımı çifte yuvarlar (Python `round`, Swift `.toNearestOrEven`).
6. **Ek yeri taraması** (çevrimiçi, `pp = max(4, round(P))`, `r = pp div 50`, `half = max(1, pp div 3)`, `hp = max(1, pp div 2)`; `sm(i)` = `[i−r, i+r]`'nin (sinyal içinde kırpılmış) ortalaması): aday `i` için `i + hp + r` henüz yoksa beklenir. `C = p90 − p02` (pencere `sm[i − 4pp .. i + hp]`), `C ≥ 6`, ürün eşiği `low = p02 + 0.25·C`. `i` bir ek yeridir ⇔ (a) **dar çukur:** `[i−half, i+half]`'te `sm(j) ≥ sm(i)` ve solda (`j < i`) kesin büyük, ve `min(max sm[i−hp..i], max sm[i..i+hp]) − sm(i) ≥ 0.25·C`; ya da (b) **düşen kenar:** `sm(i) ≤ low < sm(i−1)` (aralıklı ürünlerde uzun düz boşlukta çukur derinliği ölçülemez); ve son ek yerinden uzaklık ≥ `half`. Her ölçülen `C > 0`'da `low` güncellenir.
7. **Parça kapanışı** (ek yerinde; önceki `a`, bu `b`): ürün kısmı `[ia, ib)` = `sm > low` olan ve en az `max(2, round(0.15·pp))` uzunluktaki koşuların ilkinin başı / sonuncusunun sonu (yoksa boş bant; eşiğe yakın boş banttaki gürültü kırıntıları ürüne katılmaz). Bekletilen kısa parça varsa ve `ia − a ≤ 0.15P` ve `ib − c.ia ≤ 1.35P` ise **birleşir** (aradaki çukur ürün içi kıvrımdı). Parça kısa (`ib − ia < 0.75P`), sağı bitişik (`b − ib ≤ 0.15P`) ve ek yeri sığsa (`sm(b) > low`) bekletilir. Aksi halde `n = min(maxMultiplicity, floor((ib − ia)/P + 0.5))` ürün; `n = 0` ama parçanın önünde boşluk var (`a` yok ya da `ia − a > 0.15P`, birleşme olmadı) ve `ib − ia ≥ 0.25P` ise `n = 1` (perspektifte uzak, sivri görünen torba); merkezler `ca = max(a, ia − 0.1P)`, `cb = min(b, ib + 0.1P)` arasında eşit aralıklı (`ca + (q + 0.5)(cb − ca)/n`). Merkezi `[start, end)` içindekiler sayılır.
8. **Ön sayım** (numara ürün çizgideyken görünsün): açık parçanın (son ek yerinden beri `sm > low` ilk/son indeksi) uzunluğu `0.5·P`'yi geçince **yalnızca ilk** ürün hemen sayılır (açık parçanın uzunluğu kapanıştakinden uzun ölçülebilir; sonraki ürünler kapanışta); parça kapanınca eksik kalan eklenir, **fazla sayılan geri alınmaz**. Parça `start`'tan önce başladıysa ya da bekletilen kısa parçaya bitişik ve birleşebilir durumdaysa ön sayım yapılmaz. Olay kimliği `parça · 16 + q`.
9. **Video sonu** (`flush`): son karede çizgiye henüz varmamış kısım (`k = ℓ−1 … 0`) eklenir, `end` = eklemeden önceki uzunluk; tarama sona kadar yapılır, son açık parça (sağ ek yeri olmadan, `cb = ib + 0.1P`) ve bekletilen parça kapatılır.
- **Video:** ürün boyu bilinmiyorsa oynatmadan önce hızlı bir ön tarama (videonun ilk ≤ 60 sn'si, iPhone; Python video aracında ilk `--calib-seconds`) boyu öğrenir; sayılar baştan itibaren tek tek gelir. Ön taramayla bulunan boy yalnızca o video için kullanılır, kayıtlı profili değiştirmez.
- **Kalibrasyon:** boş bant öğrenme gerekmez (hemen biter, `diffThreshold` değişmez). Örnek öğrenme = ürün boyu öğrenme: sayım yapılmadan 5. adım (sinyal `start + 2N` olunca; başarısızsa her `N`'de yeniden; video biterse eldeki veriyle); bitince `productLength = P / N`.
- **Doğrulama:** `test_linescan.py` — bitişik, üst üste binmiş, düzensiz aralıklı torbalar; koyu (açık bantta) ve açık (koyu bantta) koliler; ekran kaydı (tekrarlanan kareler, yavaş bant), duran ve hızlanan bant, bant ek yerleri; dört akış yönü, çokgen ROI, çizgi konumu; video aracı uçtan uca. Gerçek bir ekran kaydında (bitişik un torbaları, 16 sn) elle sayılan 7'nin aynısı: tam ekrandan banda sıkı alana 5 alan × 3 çizgi konumu × 2 çözünürlük, 30/30. **Bilinen sınır:** videonun ilk/son karesinde çizgiye yarım binen ürün ±1 sapabilir (merkezi ürün uçlarının gölgesinden tahmin edilir).

### 4.10 Tanıma ile iki yönlü geçiş sayımı (`countMode = "detect"`: kişi, araç, hayvan)
Mağaza girişi, kapı, yol, ağıl gibi **iki yönlü** geçişler için. §2–§4 tek yönlü bant akışı içindir (insanlar durur, geri döner, yan yana geçer, birbirinin önünden geçer). Burada her kare nesne tanıyıcıdan kutular gelir, ayrı bir izleyici kimlikleri korur, çizgiyi `direction` yönünde geçen **giriş**, ters yönde geçen **çıkış** sayılır. Kalibrasyon yok (arka plan, eşik, alan öğrenilmez). Görüntü cihazdan çıkmaz, saklanmaz; yalnızca sayılar. Python başvurusu: `core/people_track.py` (izleyici), `core/detect_count.py` (tanıma, hareket, çizgi).

**Tanıyıcı (platforma göre; izleyici her yerde aynı):** Python/web: YOLOX-S (Apache-2.0, COCO sınıfları) ONNX Runtime ile; ilk kullanımda resmi sürümden indirilir, SHA-256 doğrulanır. iPhone: Apple Vision insan dikdörtgeni (`detectClasses = ["person"]`; araç/hayvan "yakında"). Girdi ROI sınır kutusu + her yanda %5 pay kesitidir (model girdisi sabit boyda olduğundan kesit küçüldükçe kişi büyür). İsteğe bağlı döşeme (`tiles = n`): kesit `n×n`, %30 örtüşen parçalara da bölünüp ayrıca taranır; tüm kutular sınıftan bağımsız NMS (IoU 0,5) ile birleşir. Merkezi ROI maskesi (§2.0) dışında kalan kutu atılır. Güven `≥ low = 0,15` olanlar alınır.

**Hareket desteği yalnızca tepeden kamerada** (`countAnchor = "center"`): tanıyıcı kameranın tam altındaki kişiyi (yalnızca kafa/omuz görünür) çoğu zaman bulamaz, hareket lekesi taşır. Yatık/yandan kamerada (`countAnchor = "bottom"`) tanıyıcı kişiyi zaten bulur; kapı, ekran yazısı, gölge hareketi ise hayalet iz üretir — hareket lekeleri verilmez.

Kutular normalize `(x1, y1, x2, y2)`, merkez `c(b)`; parametreler (`MotParams`): `high = max(detectConfidence, low + 0,05)`, `iou_match = 0,2`, `iou_low = 0,3`, `center_gate = 0,8`, `gate_grow = 0,5`, `gate_max = 1,6`, `motion_gate = 1,0`, `tentative_age = 2`, `vel_window = 10`, `min_hits = max(1, minHits)`, `max_age = max(5, round(fps · 1,0))`, `band = 0,02`, `band_rel = 0,1`, `side_frames = 2`, `contain = 0,85`, `part_area = 0,75`, `group_area = 1,8`, `group_margin = 1,0`, `dup_iou = 0,3`, `motion_life = 1,5`, `unverified_life = 3,0`. Her iz: `box` (tahmin), `last` (son gözlem), `vel = (vx, vy, vx, vy)`, `hits`, `misses`, `confirmed`, `verified`, `side`, aday yan `cand`/`cand_n`, `pending`, `hist` (hız tabanı), `born`, `last_det`. Kayıp izin kapı büyümesi `grow(t) = gate_grow · misses · hypot(vx / en(last), vy / boy(last))` (yürüyen kişinin konum belirsizliği zamanla artar, duranınki artmaz). `g(a, b) = hypot(Δcx / en(last), Δcy / boy(last))` (kişinin kendi boyuna göre elips kapı). Her kare (kare sayacı `f`):

1. **Tahmin:** her iz `box += vel`.
2. **Parça kutu bastırma:** kutular alana göre büyükten küçüğe (eşitlikte giriş sırası); bir kutu, daha önce tutulan bir kutuyla kesişimi kendi alanının `≥ contain`'i **ve** alanı onunkinin `≤ part_area` katıysa atılır, tutulanın güveni `max(ikisi)` olur (aynı kişinin üst gövde/yarım kutusu; yan yana grupta mükerrer izin ana kaynağı). Eş boy üst üste kutu (arkadaki gerçek kişi) atılmaz. Sonraki adımlarda tespitler bu sıradadır.
3. **Eşleştirme (tek tur, açgözlü):** her (iz, tespit) çifti için `ov = max(IoU(box, b), IoU(last, b))`, `dc = min(g(box, b), g(last, b))`; kapı `G = min(gate_max, center_gate + grow(t))`. Aday: yüksek güvenli (`≥ high`) tespit `ov ≥ iou_match` ya da `dc < G`; düşük güvenli yalnızca `ov ≥ iou_low`. Çiftler `(−ov, dc, iz, tespit)` artan sıralanır, iz ve tespit birer kez kullanılır. (İki aşamalı ByteTrack'te önce yalnızca güçlü tespitler eşlendiğinden, silik tespiti olan kişinin izi yanındakinin güçlü tespitine atlıyordu.)
4. **Hareket desteği** (`motion` verilirse): 3'te eşleşmeyen iz, şunlar hariç lekeye talip olur: tanımadan doğmuş onaysız iz (`verified ∧ ¬confirmed` — birleşik/yarım kutudan doğan hayali iz grubun lekesiyle yaşayıp sayılıyordu); doğrulanmış ve `f − last_det > motion_life · max_age`; doğrulanmamış ve `f − born > unverified_life · max_age` (kapı/ekran/gölge hareketiyle süresiz yaşayan hayalet iz başka kişilerin geçişini sayıyordu). Talip `dc = g(box, m) < min(gate_max, motion_gate + grow(t))` ya da tahmini merkezi lekenin içinde olan lekelerden `dc`'si en küçüğü seçer (eşitlikte ilki). Lekenin **sahip sayısı** = talipler + tanıma kutusunun merkezi lekede olan (3'te eşleşmiş) izler. Sahip `> 1` ya da leke alanı `> group_area · alan(last)` ise **grup lekesi**: tahmini merkez lekenin `group_margin ·` (en, boy) kadar genişletilmiş kutusundaysa lekeye kırpılır, değilse eşleşme yok (uzaklaşan iz sürüklenmez — yanından ters yönde geçen grubun lekesi işi bitmiş izi çizgiden geçirip ikinci kez saydırıyordu). Değilse gözlenen merkez lekenin merkezi. Gözlenen kutu = `last` boyunda, bu merkezde.
5. **Güncelleme** (tespit ya da leke ile eşleşen iz): tespitte `score` güncellenir; güven `≥ high` ve iz doğrulanmamışsa `verified = true`, `hist = []`; tespitte `last_det = f`. Tanıma gözleminde ya da doğrulanmamış izde hız güncellenir: `hist` son `vel_window` kare dışındakileri atar, kalan ilk kayıt `(f0, b0)` ise `v = (c(b) − c(b0)) / (f − f0)`; `(f, b)` eklenir (doğrulanmış izin hızı yalnızca tanımadan: lekeye kırpılan konum hızı bozmasın). Sonra `box = last = b`, `hits += 1`, `misses = 0`, 8. Eşleşmeyen iz: `misses += 1`.
6. **Yeni iz:** eşleşmeyen yüksek güvenli tespit → `verified = true`; hiçbir izin kutusuyla kesişmeyen ve hiçbir izin kutusu merkezini içermeyen leke → `verified = false` (bu sırayla, eklenen iz sonraki lekelerin denetimine girer). `born = last_det = f`, `hist = [(f, b)]`, 8. Düşük güvenli tespit iz başlatmaz.
7. **Silme:** `misses > (confirmed ? max_age : tentative_age)`; tahmini merkezi sayım alanının (ROI dikdörtgeni) dışında (kadrajdan çıkan kişinin izi aynı kenardan giren yeni kişiye geçmesin); doğrulanmamış ve doğrulanmış bir izle (silmeden önceki liste) `IoU ≥ dup_iou` ya da merkezi onun kutusunda. `f += 1`.
8. **Gözlem ve geçiş:** çapa noktası `countAnchor`: `center` kutu merkezi, `bottom` alt orta. `s` = çizgiye işaretli uzaklık, giriş yönü pozitif: düz çizgide `sign · (y − linePosition)` (dikey akış) ya da `sign · (x − linePosition)`; `countLine` varsa §4.8 çizgi çerçevesinin `u` ekseni (a→b'nin sağ eli = giriş). Bant `B = max(band, band_rel · boy(box))`; `d = +1` (`s > B`), `−1` (`s < −B`), yoksa 0 (çizgi üstü; durum değişmez). `d ≠ 0`: yan 0 ya da `d = yan` ise `yan = d`, aday sıfırlanır; değilse **yan teyidi**: `cand = d` ise `cand_n += 1` yoksa `cand = d, cand_n = 1`; `cand_n ≥ side_frames` olunca `pending`'e `d` eklenir (`+1` giriş, `−1` çıkış), `yan = d`, aday sıfırlanır. İz `verified` ve `hits ≥ min_hits` olunca onaylanır; onaylı izin `pending`'i sayılır ve boşaltılır (onaydan/doğrulamadan önceki geçiş kaybolmaz, bir kez sayılır).

Sonuç: çizgide sallanan/bekleyen ve kutu kenarı tek karelik zıplayan sayılmaz; girip geri dönen bir giriş + bir çıkış sayılır; yalnızca gözlemler (tespit ya da leke; tahmin değil) yan belirler; kişi olmayan hareket (kapı, gölge, ışık, araba) hiç tanınmadığından sayılmaz.

- **Hareket lekeleri** (`MotionDetector`): kare `160` px genişliğe küçültülür, gri, 5×5 Gauss. İlk karede arka plan = kare (leke yok). Sonra `fg = |g − bg| > 22`, açma 3×3, kapama 5×5; arka plan yalnızca `fg = 0` piksellerde `bg += 0,05 (g − bg)`, ayrıca her yerde `bg += 0,002 (g − bg)`. 8-bağlantılı bileşenlerden alanı `≥ 0,002 · w · h` ve kutu merkezi ROI maskesinde olanlar. (Leke geometrisi platformlar arasında piksel düzeyinde aynı olmak zorunda değildir; eşdeğerlik izleyici düzeyinde sınanır.)
- **Kurulum:** çizgi kişilerin **tamamen geçtiği** yere, yürüme alanının ortasına konur — kapı eşiğine değil (kapıda durup karanlığa giren kişinin ayağı çizgiyi bandın ötesine geçmez, sayılmaz). Tepeden kamerada `center`, yatık kamerada `bottom` (çizgi zemine).
- **Olay:** giriş `count.direction = "in"`, çıkış `"out"`; `total` o yönün toplamı (sözleşme `event.schema.json`). Panel ve rapor: yalnızca **Giriş** ve **Çıkış** (kullanıcı kararı; doluluk/kapasite yok). Giriş yönü kullanıcı tarafından tek dokunuşla çevrilebilir (`direction` tersine; açılı çizgide uçlar yer değiştirir).
- **Doğrulama:**
  - `test_people_track.py`: giriş/çıkış, çizgide sallanma, tek karelik kenar zıplaması, yakındaki büyük kişinin titremesi, geri dönme, çizgiden önce dönme, kayıp ve silik tespitle kimlik, kayıpken duran kişi, uzaktaki yeni kişinin kimliği çalmaması, tek kare yanlış tespit, yan yana grup, karşılıklı geçiş, hızlı hareket, onaydan önceki geçiş; hareket desteği: tanınmayan kişinin girişi/çıkışı, kişi olmayan hareketin sayılmaması, tespit + lekenin tek sayılması, birleşik grup lekesinde iki kişi, geç doğrulama.
  - `test_people_groups.py` (`core/sim_people.py`): 2–3 kişilik yan yana gruplar ve karşılıklı akış; kaçırma, örtüşme (arkadaki gizli), titreme, düşük güven, yarım kutu, birleşik kutu kusurları; 60 tohum × 3 kusur düzeyi, mükerrer sayım 0.
  - Kör bölgeli tepeden kamera simülasyonu: çizginin ±0,12'sinde tanıma yok, yalnız hareket; 120 tohum, 1195 kişi. Normal kusurla %1,4 hata (2 fazla, 15 eksik), ağır kusurla %2,2; hareket desteği olmadan %5,4.
  - Eşdeğerlik: `tools/make_people_fixture.py` → `apps/ios/BantSayacTests/people_parity.json` (7 senaryo); Swift `PeopleTrackerTests` aynı karede aynı iz kimliğiyle aynı olayları üretir. `test_people_fixture.py` dosyanın güncelliğini denetler.
  - Gerçek videolar (elle sayıldı):
    - Tepeden kamera mağaza girişi (46 sn, 3 giriş + 3 çıkış): 3/3. Altı geçişin zamanı da doğru, çizgi 0,50–0,65 ve `center`/`bottom` ile aynı. Hareket desteği olmadan 1/2.
    - Yatık koridor kamerası (78 sn, 9 giriş + 3 çıkış; ikisi kapıya kadar gidip dönen kişi): 9/3, 12 geçişin hepsi doğru, sahte olay 0. Çizgi kapı eşiğindeyken (kurulum hatası) 8/4 ve olaylar yanlıştı.

#### §4.10 eki: personel rengi (isteğe bağlı, kamera/profil başına)

Mağaza personeli belirgin renkte üniforma/yelek giyiyorsa bu renk bir kez öğretilir (`staffColors`, en çok 3 renk, Lab); o renkteki kişilerin geçişi **müşteri** `total` / `total_out` toplamına eklenmez, ayrı **personel geçişi** (`staff_in` / `staff_out`) sayılır. `staffColors` yoksa ya da boşsa kod yolu çalışmaz, davranış bu eke kadar olanla birebir aynıdır. Kutular normalize `(x1, y1, x2, y2)`, `w = x2 − x1`, `h = y2 − y1`. Python başvurusu `core/staff_color.py`; Swift `Vision/StaffColor.swift`; ikisi aşağıdakini birebir uygular.

**Gövde bölgesi:** `x ∈ [x1 + 0,30w, x1 + 0,70w]`; `countAnchor = bottom` (yandan/yatık) için `y ∈ [y1 + 0,15h, y1 + 0,45h]`, `center` (tepeden) için `y ∈ [y1 + 0,30h, y1 + 0,70h]`. Kutu `w·W < 8` ya da `h·H < 16` pikselse oy yok.

**Oy verilen kutular:** o karede **tanımayla gözlenen** her kutu (eşleşen düşük güvenli tespit dahil); tahmin ya da hareket lekesiyle sürdürülen karede oy yok. `others` = aynı karede parça bastırmadan sonra kalan **diğer tüm** tanıma kutuları (düşük güvenliler dahil).

**Örtüşme dışlama:** ızgara noktası `others` kutularından birinin içine düşüyorsa (sınır dahil) atılır — yan yana/üst üste grupta komşunun rengi karışmasın. Kalan nokta `< 36` (ızgaranın %25'i) ise o karede oy yok.

**Örnekleme:** bölgede 12 × 12 ızgara; nokta `(i, j)`: `px = rx0 + (i + 0,5)/12 · rw`, `py = ry0 + (j + 0,5)/12 · rh`; piksel `⌊px · W⌋`, `⌊py · H⌋`, `[0, W−1] × [0, H−1]` aralığına kırpılır. Görüntü sRGB 8 bit. iPhone'da kameranın YUV verisi yalnızca örnek noktalarda RGB'ye çevrilir; matris (BT.709 / BT.601) tampon eki (attachment) bilgisinden seçilir. Eşdeğerlik RGB örneklerinden itibaren tanımlıdır.

**sRGB → CIE Lab (D65):**
- Doğrusallaştırma: `c = v/255`; `c ≤ 0,04045 ? c/12,92 : ((c + 0,055)/1,055)^2,4`.
- `X = 0,4124564 R + 0,3575761 G + 0,1804375 B`, `Y = 0,2126729 R + 0,7151522 G + 0,0721750 B`, `Z = 0,0193339 R + 0,1191920 G + 0,9503041 B`; beyaz nokta `Xn = 0,95047`, `Yn = 1`, `Zn = 1,08883`.
- `f(t) = t > 0,008856 ? ∛t : 7,787 t + 16/116`; `L = 116 f(Y/Yn) − 16`, `a = 500 (f(X/Xn) − f(Y/Yn))`, `b = 200 (f(Y/Yn) − f(Z/Zn))`.

**Eşleşme:** nokta öğretilen renklerden birine `d = √((0,5 ΔL)² + Δa² + Δb²) < 20` uzaklıktaysa ve `L ≥ 8` ise eşleşir (parlaklık yarım ağırlıklı: gölge/ışık farkına dayanıklı; çok karanlık nokta eşleşmez).

**Kare oyu:** kalan noktaların eşleşen oranı `≥ 0,25` → personel oyu. İz başına `votes` (oy verilen kare) ve `staff_votes` birikir. Oy, aynı karenin geçiş gözleminden (adım 8) **önce** işlenir; böylece geçişin gerçekleştiği karenin oyu da karara girer.

**Geçiş kararı:** geçiş onaylanıp sayıldığı anda (bekleyen geçişler dahil) `votes ≥ 3` ve `2 · staff_votes ≥ votes` ise geçiş **personel** (`staff_in` / `staff_out`), değilse müşteri. Karar her geçişte oylar birikmiş haliyle yeniden verilir. Karanlık/belirsiz sahnede noktalar eşleşmez → müşteri sayılır (güvenli yön).

**Öğretme:** (1) tıklanan noktayı içeren en küçük alanlı tanıma kutusunun gövde bölgesi; kutu yoksa tıklanan yer merkezli, kenarı görüntü genişliğinin 0,06'sı olan kare (yükseklik oranlı). (2) 12 × 12 nokta Lab'a çevrilir; `(⌊a/8⌋, ⌊b/8⌋)` kutucuklarından en çok nokta düşen seçilir (eşitlikte ilk görülen). (3) Sonuç = o kutucuktaki noktaların L, a, b **medyanı**. Medyan `L < 8` ise reddedilir (çok karanlık).

**Arayüz uyarısı (sayımı etkilemez):** öğretilen renk akromatik (`C = √(a² + b²) < 15`) ya da koyuysa (`L < 30`, `COMMON_DARK_L`) "Bu renk müşterilerde de sık görülür; müşteri yanlışlıkla düşülebilir." gösterilir.

**Çıktı:** web canlı sayım `staffIn` / `staffOut` ve CSV'de `personel_giris` / `personel_cikis` satırları (giriş/çıkış toplamlarına katılmaz); iPhone ekranda "Personel geçişi: N". Personel geçişi **olay olarak gönderilmez**; iPhone CSV ve webhook değişmez (yalnızca müşteri).

**Sabitler** (`staff_color.py` ↔ `StaffColor.swift`): `GRID = 12`, `MATCH_DIST = 20`, `MIN_FRACTION = 0,25`, `MIN_POINTS = 36`, `DARK_L = 8`, `MIN_VOTES = 3`, `ACHROMATIC_C = 15`, `COMMON_DARK_L = 30`, `TEACH_PATCH = 0,06`, `MAX_COLORS = 3`, `MIN_BOX_PX = (8, 16)`. Oy `people_track.py` (`votes`, `staff_votes`), `detect_count.py`, `pipeline.py`; Swift `PeopleTracker.swift`, `PeopleCounter.swift`, `FrameProcessor.swift`.

**Doğrulama:**
- `test_staff_color.py`: Lab referans değerleri, oy (tam üniforma, gövdenin %30'u yelek, gölge, başka renk, akromatik, örtüşme), öğretme; izleyici/boru hattı testleri (tek başına personel, personel + müşteri yan yana, renk yokken birebir aynı sayılar).
- Eşdeğerlik: `tools/make_staff_fixture.py` → `apps/ios/BantSayacTests/staff_parity.json`; Python `test_staff_fixture.py` ve Swift `StaffColorTests` aynı fikstürü doğrular.
- **Kabul ölçütü: her kamera açısında (tepeden, eğik ~45°, yandan) personel yakalama ≥ %95 ve yanlış hariç tutma ≤ %5.** Ölçüm: `python tools/eval_staff.py VIDEO --profile profil.json --labels VIDEO.staff.json --angle tepeden [--every N]`. Etiket `[{"t": sn, "dir": "in"|"out", "staff": true|false}]`; her etiket aynı yönde ±1,5 sn (sınır dahil) içindeki kullanılmamış en yakın tahmine eşlenir. Yakalama = personel sayılan personel etiketi / tüm personel etiketleri (tahmine eşlenmeyen personel yakalanmamış sayılır); yanlış hariç tutma = personel sayılan müşteri etiketi / tüm müşteri etiketleri (eşlenmeyen müşteri ayrı sayım kaçağıdır); eşlenmeyen tahminler sınıfa göre "fazla" yazılır. Açı başına en az 20 personel + 20 müşteri geçişi (müşterilerin bir kısmı koyu/siyah giyimli, bir kısmı yan yana grupta); azsa araç ölçmez. Profil: web'de kameranın kayıtlı ayarı (`<ANALYZER_DATA_DIR>/live/camera_profiles.json`) ya da `GET /api/v1/live/sessions/{id}` yanıtındaki `profile`. Araç Python/web yolunu onaylar; iPhone yolu aynı videoların uygulamanın video modunda oynatılıp sayaçların okunmasıyla denetlenir (`12-durum.md` "Personel rengi"). Gerçek ölçümler bekliyor (kayıt gerekli; kayıtlar public repoya konmaz). %95'i tutmayan açıda eşikler (`MATCH_DIST`, `MIN_FRACTION`, gövde bölgesi) yalnızca ölçümle ayarlanır ve iki tarafta birlikte değişir.

### 4.11 Poz güvenlik alarmı (`countMode = "safety"`: eller yukarı, yerde yatan kişi)
Kuyumcu gibi mağazalarda **sessiz alarm**: soygun sırasında "eller yukarı" duruşu ve düşme/bayılma sonrası yerde yatan kişi. Sayım yapmaz, olay üretir (alarm günlüğü, panel, Telegram: `13-web-platform.md`). Yalnızca bilgisayardaki analiz sunucusunda (canlı kamera/kayıt cihazı oturumu) çalışır; iPhone `safety` yöntemini profilde tanır ama çalıştırmaz ("Yalnızca bilgisayarda"), bu yüzden bu bölümün **Swift karşılığı yoktur**, referans yalnızca Python'dır. Görüntü bilgisayardan çıkmaz; alarm kişiyi tanımaz, yalnızca duruşa bakar. Python başvurusu: `core/pose.py` (poz), `core/pose_rules.py` (kurallar), `core/safety.py` (çözümleyici). Tasarım belgesi: `docs/superpowers/specs/2026-10-06-poz-guvenlik-design.md`.

**Akış** (her işlenen karede):
1. Kişi tanıma (YOLOX-S, §4.10 ile aynı ortak model) ve izleyici (§4.10 `MotTracker`) **tam karede** çalışır; alan kırpması, sayım çizgisi ve kutu merkezi süzgeci yoktur.
2. **Alan:** profilde alan (ROI / çokgen) varsa kişi yalnızca **konum noktası** alan içindeyse değerlendirilir. Konum noktası güvenlikte **her zaman kutunun alt ortasıdır** (`countAnchor` yok sayılır; tanıma kutuları kareye kırpıldığından, kareye değen kişi dışarıda sayılmasın diye kare içine çekilir). Varsayılan alan tüm görüntü; zemine çizilmiş alanın içindeki kişinin gövde merkezi alanın üstünde kalabileceğinden kutu merkezi kullanılmaz.
3. Poz yalnızca **onaylı ve bu karede tanımayla gözlenen** izlere uygulanır; boş sahnede (tanıma atlandığında) ve tahminle sürdürülen karede poz yoktur.
4. Eklemlerden kare kararı → kare kararlarından bölüm durum makinesi → bölümden alarm.

**Poz modeli:** MoveNet SinglePose Thunder (Google, Apache-2.0, ticari kullanım serbest), ONNX Runtime CPU; kişi kutusu başına çalışır. Google modeli SavedModel olarak yayımlar; `tools/convert_movenet.py` onu bir kez ONNX'e çevirir ve orijinalle karşılaştırır (rastgele, sentetik ve verilirse video kareleri: en büyük çıktı farkı < 0,01, değilse çıkış kodu 1). Çeviri GitHub Actions'ta (`.github/workflows/models.yml`) çalışır; çıktı projenin GitHub sürümü `models-v1`e `movenet_thunder.onnx` olarak yüklenir (kaynak ve lisans notu: `tools/models/MOVENET-NOTICE.md`). Sunucu modeli ilk kullanımda oradan indirir (akış halinde; bağlanma/okuma zaman aşımı ve toplam süre sınırı var), **SHA-256 doğrular** (YOLOX ile aynı düzen, `BANTVISION_MODEL_DIR`), doğrulanamazsa ya da indirme koparsa yarım dosyayı siler. Ağırlıklar depoya girmez.
- **Kırpma:** kişi kutusu `1,25×` genişletilir, kare yapılır (uzun kenar `side`), görüntü dışına taşan kısım **siyahla** doldurulur; `256×256`'ya ölçeklenir (bilineer), RGB, `int32`, girdi biçimi `1×256×256×3`.
- **Çıkış:** `17 × (y, x, güven)`, kare içinde normalize; görüntü pikseline `x = x0 + xn · side`, `y = y0 + yn · side` ile döner (`(x0, y0)` karenin sol üstü).
- **Ortak model ve yükleme:** tüm güvenlik kameraları tek poz modelini kullanır, kareler sırayla işlenir. Model (indirme dahil) **arka planda** yüklenir; oturum güvenliğe geçince ısıtılır, ilk kişi beklenmez. Hazır olana kadar karelerde poz yoktur: görüntü akar, alarm olmaz. Yükleme hatasında Türkçe hata günlüğe yazılır ve 60 sn sonra yeniden denenir. Oturum durumunda `safety.model`: `loading` / `ready` / `error`.

**Eklemler:** COCO-17: 0 burun, 1–2 göz, 3–4 kulak, 5–6 omuz, 7–8 dirsek, 9–10 bilek, 11–12 kalça, 13–14 diz, 15–16 ayak bileği; piksel `(x, y, güven)`, `y` aşağı artar. Eklem **görünür** ⇔ güven `≥ KP_CONF = 0,3`. **Baş:** burun görünürse burun, değilse görünen göz/kulakların (1–4) ortalaması, hiçbiri yoksa baş yok.

**Ölçek `s`:** iki omuz da görünmezse karar yok. İki kalça da görünürse `s = |omuz_orta − kalça_orta|` (gövde boyu); değilse baş varsa `s = 2,5 · |baş − omuz_orta|`; ikisi de yoksa ya da `s = 0` ise karar yok.

**Kare kararı** (`True` / `False` / `None` = yetersiz eklem, karar yok):
- **Eller yukarı** (`hands_up`): dört eklemden (iki omuz, iki bilek) biri görünür değilse ya da `s` tanımsızsa `None`. Her iki taraf (sol: omuz 5, dirsek 7, bilek 9; sağ: 6, 8, 10) için `bilek.y ≤ omuz.y − 0,35 · s` **ve**, dirsek görünürse, `dirsek.y ≤ omuz.y + 0,15 · s` (görünmezse dirsek koşulu aranmaz; kol aşağıda sarkmıyor). Bir taraf tutmazsa `False`; ikisi de tutarsa `True`. Tek el kalkıksa `False`.
- **Yerde yatma** (`lying`): dört eklemden (iki omuz, iki kalça) biri görünür değilse `None` (tezgâh arkasında, kalçası görünmeyen ayaktaki kişi böyle kalır: alarm olmaz). `v = omuz_orta − kalça_orta`, `s = |v|` (`s = 0` ise `None`), `θ = atan2(|v.x|, −v.y)` (0°: omuz kalçanın tam üstünde, 90°: yatay, 180°: omuz kalçanın altında). `True` ⇔ `θ ≥ 60°` **ya da** (baş var ve `baş.y ≥ kalça_orta.y − 0,1 · s`; baş–ayak doğrultusu kameraya dönük yatmayı yakalar). Aksi `False`. Eğilme, çömelme ve oturma `False` olmalıdır (testli).

**Bölüm durum makinesi** (`EpisodeTracker`; iz ve tür başına; zaman = kare zaman damgası):
- `True` kare bir **bölüm** başlatır ya da sürdürür. `False`, `None` ve tanımayla gözlenmeyen kareler bölümü en çok **`grace`** süre sürdürür; son `True`'dan beri `grace`'ten uzun geçerse (ya da zaman geriye giderse) bölüm biter, sonraki `True` yeni bölüm başlatır.
- `grace = max(GRACE_S, 2,5 / fps)`, `GRACE_S = 0,5 sn`; `fps` boru hattının zaman damgalarından ölçtüğü kare hızıdır (son 2 sn). Yavaş akışta (örn. 1 kare/sn) sabit 0,5 sn tolerans bölümü sürekli koparırdı; en az ~2,5 kare aralığı affedilir.
- Bölüm süresi (ilk `True` → son `True`) `≥ T` olunca **alarm**, bölüm başına **bir kez**. Alarmın başlangıcı `startedAt = ts − bölüm süresi`.
- İz silinirse (kişi kayboldu) bölüm biter. Ayar değişince ve Sıfırla'da izler ve bölümler sıfırlanır; kamera bağlantısı koparsa kare gelmez, yeniden bağlanınca ara `grace`'i aştığından eski bölüm biter.
- Bölüm bitince alarmın `endedAt` değeri yazılır; panelde "devam ediyor" kalkar.
- Varsayılan `T` (profil `safety`, sözleşme `02-contracts.md`): eller yukarı **3 sn** (ayar 3–5), yerde yatma **10 sn** (ayar 5–30). Aralıklar API'de denetlenir.

**Tekrar önleme:** aynı kamerada aynı tür için son **kuyruğa alınan** bildirimden itibaren (Telegram yapılandırılmışsa) `COOLDOWN_S = 60 sn` içinde doğan alarmlar günlüğe ve panele yazılır, Telegram'a gitmez (`notify: "suppressed"`). Deneme alarmı tekrar önlemeye tabi değildir ve süreyi başlatmaz.

**Sabitler** (`pose_rules.py`, `safety.py`): `KP_CONF = 0,3`, `GRACE_S = 0,5`, `COOLDOWN_S = 60`; eller yukarı bilek eşiği `0,35 · s`, dirsek payı `0,15 · s`; yerde yatma `θ ≥ 60°`, baş payı `0,1 · s`; baş tabanlı ölçek çarpanı `2,5`; `grace` en az `2,5 / fps`. Hazır profil "Kuyumcu güvenliği": `countMode = "safety"`, `detectClasses = ["person"]`, `detectConfidence = 0,35`, `countAnchor = "bottom"`, `minHits = 3`, `processingWidth = 640`, alan tüm görüntü.

**Çıktı:** `FrameResult.safety` (`SafetyResult`): bu karede gözlenen izler, iz başına eklemler (piksel), etkin bölümler, bu karede doğan alarmlar, biten bölümler. Bindirme (`overlay.py`): iskelet çizgileri; alarm veren iz kırmızı kutu ve etiket ("ELLER YUKARI" / "YERDE"), iz bir kare kaçırılsa da son bilinen kutuda kalır.

**Dosyalar:** `core/pose.py`, `core/pose_model.py` (ad, adres, SHA-256), `core/pose_rules.py`, `core/safety.py`, `core/pipeline.py` (`_process_safety`), `overlay.py` (`draw_safety`); canlı: `live/alarms.py` (alarm günlüğü), `live/notify.py` (Telegram), `live/session.py`, `live/api.py`; `tools/convert_movenet.py`, `tools/eval_pose.py`.

**Doğrulama:**
- `test_pose_rules.py`: ölçek, eller yukarı (iki el baş üstü, teslim, tek el, eksik bilek → `None`, düşük dirsek), yerde yatma (yatay, kameraya doğru, eğilme, çömelme, oturma, kalçasız → `None`), `EpisodeTracker` (eşik, `grace` affı ve uyarlaması, uzun kopma, iz kaybı, bölüm başına tek alarm, geriye giden zaman).
- `test_safety.py`: uçtan uca alarm süresi, 1 kare/sn akışta tek alarm, alan (alt orta nokta, zemin çokgeni), boş sahnede ve gözlenmeyen izde poz çağrısı yok, kalçasız kişide yatma yok, biten ve sıfırlamayla kesilen bölümler, kırmızı kutu.
- `test_pose.py`, `test_pose_model.py`: kırpma, siyah dolgu, geri çevirme, sahte oturumla çıkarım; model indirme (akış, zaman aşımı, SHA-256, yarım dosya silme); `tools/tests/test_convert_movenet.py`.
- `test_alarms.py`, `test_notify.py`, `test_live.py`: alarm günlüğü ve 7 gün temizliği, Telegram (sahte sunucu), kuyruk, tekrar önleme, uç noktalar; panel e2e `apps/dashboard/e2e/safety.spec.ts`, `safety-ui.spec.ts`. `tools/tests/test_eval_pose.py`: eşleme (sınırlar dahil, tür, tek alarm tek etiket) ve etiket/profil girdi doğrulaması.
- **Kabul ölçütü** (gerçek ölçüm; **bekliyor**, kayıtlar kullanıcıdan gelir ve public repoya konmaz): ofis bullet/dome kameralarıyla canlandırma kayıtlarında
  - eller yukarı **≥ 20 olay** (farklı kişiler; önden, yandan, tezgâh arkası) ve yerde yatma **≥ 20 olay** (farklı yönler);
  - **≥ 1 saat normal hareket**;
  - olayların **≥ %95'i** kural süresi + 2 sn içinde alarm verir; normal harekette yanlış alarm **kamera başına 8 saatte ≤ 1**.
- **Ölçüm:** `python tools/eval_pose.py VIDEO --profile PROFİL.json --labels VIDEO.pose.json [--every N]`.
  - Etiket `[{"t": sn, "type": "hands_up"|"lying"}]`, `t` olayın başladığı an. Etiket, aynı türde `t ≤ alarm ≤ t + T + 2 sn` (sınır dahil; `T` profildeki tür süresi) içindeki kullanılmamış en erken alarma eşlenir; her alarm en çok bir etikete. Eşlenmeyen alarmlar (geç gelen, etiketsiz) yanlış alarmdır.
  - Çıkış kodu **0 yalnızca** her tür için yakalama ≥ %95 (her türde ≥ 20 etiket) ve `yanlış alarm / saat · 8 ≤ 1` iken. Video 1 saatten kısaysa yanlış alarm "yetersiz süre" olarak raporlanır ve kapı kalır (1). Girdi hatası (bilinmeyen etiket türü, bozuk etiket/profil dosyası, açılamayan video) 2.
  - Profil güvenlik yöntemi olmalı: web'de kameranın kayıtlı ayarı (`<ANALYZER_DATA_DIR>/live/camera_profiles.json` içindeki kaydın kendisi) ya da `GET /api/v1/live/sessions/{id}` yanıtındaki `profile`.
  - Araç Python/web yolunu ölçer: videoyu her karede (ya da `--every N`) işler, canlıdaki boş sahnede tanıma atlama kullanılmaz, kare hızı zaman damgalarından gelir.
- **Bilinen risk:** MoveNet ağırlıklı olarak fitness/dans/yoga videolarıyla eğitildi; eğik ve uzak güvenlik kamerasında doğruluk yukarıdaki ölçümle sınanır. %95'i ya da yanlış alarm sınırını tutmayan senaryoda eşikler (`KP_CONF`, `0,35`, `0,15`, `60°`, `grace`) yalnızca ölçümle ayarlanır; yetmezse model seçimi yeniden değerlendirilir.

## 5. Kalibrasyon
**Boş bant öğrenme** (`backgroundSeconds = 1.0`, `N = round(fps · 1.0)`, en az 15 kare):
- 0. kare: `bg = gray`. Sonrakiler: `bg += 0.15·(gray − bg)` (koşulsuz).
- `0.4·N`'den itibaren her karede ROI maskesi (§2.0) içindeki piksellerde `|gray − bg|`'nin %99,5 yüzdeliği ölçülür, en büyüğü `m`.
- Bitiş: `th = clamp(int(1.5·m) + 8, 12, 100)`, izler sıfırlanır. `th = 100` (üst sınır) ise öğrenirken bantta ürün ya da hareket vardı: **eşik değiştirilmez**, kullanıcı uyarılır (`background_rejected`). Aksi halde `diffThreshold = th`.
- **Yalnızca arka plan** (`updateThreshold = false`): video baştan oynatılırken otomatik öğrenme arka plan görüntüsünü yeniler ama kaydedilmiş eşiği değiştirmez (kullanıcının "Kaydet" ettiği kalibrasyon sabit kalır). Eskiden ürünle başlayan videoda eşik her seferinde 100'e kaçıyor, sonra hiçbir şey sayılmıyordu.

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

Hem Python hem Swift uygular: fps, kaynağın kare zaman damgalarından (kamerada sunum zamanı, videoda kare zamanı) hesaplanır; zaman geri giderse (kaynak değişti) pencere sıfırlanır. §5 boş bant öğrenme süresi de aynı fps ile `N = max(15, round(F))` karedir. RTSP'de 25 fps, telefon videolarında 30 fps tipiktir.

## 8. Bant çalışıyor/durdu
- Son `idleSeconds` (varsayılan 30, cihaz ayarı) içinde en az bir leke görüldüyse ya da sayım olduysa `running = true`.
- Durum değiştiğinde `state` olayı (`motion` / `no_motion`).

## 9. Ejektör zamanlaması (F5)
- Bant hızı: son 2 sn'de sayılan izlerin eksen hızlarının medyanı (normalize/kare) × eksen boyunca tam çözünürlük piksel sayısı × `mmPerPixel` × `F` → mm/sn.
- `delayMs = distanceMm / hız · 1000 − (şimdi − kare zaman damgası) − latencyCompensationMs`.
- `mmPerPixel` yoksa ya da hız < 10 mm/sn ise ejektör tetiklenmez ve uyarı loglanır.
- Komut I/O köprüsüne "X ms sonra darbe" olarak gider (saat senkronu gerekmez).
