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
