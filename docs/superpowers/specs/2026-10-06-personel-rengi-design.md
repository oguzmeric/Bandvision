# Personel rengi: kişi sayımında personeli giriş/çıkıştan ayırma — tasarım

Tarih: 2026-10-06 · Durum: onaylandı (sohbette), yazılı belge incelemede

## Amaç
Mağazada personelin gün boyu girip çıkması giriş/çıkış sayılarını şişiriyor. Personel belirgin renkte
üniforma ya da yelek giyiyorsa bu renk bir kez öğretilir; o renkteki kişilerin geçişleri **müşteri
giriş/çıkışına eklenmez**, ayrıca "Personel geçişi" olarak gösterilir.

**Kullanıcının söyledikleri:**
- Yöntem: renk öğretme.
- Üniforma rengi şirketten şirkete değişiyor, bu yüzden ayar isteğe bağlı ve kamera başına.
- Personel geçişleri ayrı gösterilsin.

**Başarı ölçütü (kullanıcı, 2026-10-06):** kamera farklı açılardan (tepeden, eğik ~45°, yandan) konumlandırıldığında
her açıda **geçiş başına doğruluk ≥ %95**. Ölçüm iki taraflıdır:
- Personel geçişlerinin en az %95'i personel olarak ayrılır (yakalama).
- Müşteri geçişlerinin en az %95'i müşteri kalır (yanlış hariç tutma ≤ %5).

Ayrıca:
- Öğretilen renkte giyinmiş kişi geçişte personel sayılır.
- Başka renkte giyinmiş kişi normal sayılır.
- Yan yana grupta (personel + müşteri) yalnızca müşteri giriş/çıkışa eklenir.
- Renk öğretilmemişse davranış bugünküyle birebir aynıdır.

**Varsayımlar:**
- Personelin rengi gövdede (gömlek, yelek, tişört) görünür.
- Sahne, renk ayırt edilecek kadar aydınlıktır.

## Kapsam
- **Var:**
  - Python çekirdeği (`core/`): canlı web ve video analizi, profilde renk varsa uygulanır.
  - iPhone (Swift) çekirdeği, eşdeğer davranış.
  - Web canlı sayfasında öğretme ve gösterme.
  - iPhone kişi sayımı ekranında öğretme ve gösterme.
  - Sözleşme (profil şeması), dokümanlar (02, 03 §4.10, 13).
- **Yok (YAGNI):**
  - Video analizi yükleme formunda renk seçimi.
  - Supabase'e personel olayı göndermek.
  - Görünüşle tekil sayım ve yüz tanıma.

## Kullanıcı akışı (web ve iPhone)
1. Kişi sayımında "Ayarla" panelinde **Personel rengi** bölümü bulunur. Renk yoksa "Kapalı — tüm geçişler sayılır" yazar.
2. "Personel rengini öğret" → görüntüde bir personelin üstüne tıklanır/dokunulur → renk örnek kare olarak eklenir. **En fazla 3 renk**; her biri × ile silinir.
3. Öğretilen renk akromatikse (renk doygunluğu `C = √(a² + b²) < 15`; siyah, beyaz, gri, lacivert) örneğin yanında uyarı çıkar: "Bu renk müşterilerde de sık görülür; müşteri yanlışlıkla düşülebilir."
4. Kaydetme: web'de **kamera başına** (`camera_profiles.json`), iPhone'da profil başına.
5. Sayaçlar: Giriş, Çıkış. Altında küçük "Personel geçişi: N" (giriş + çıkış), yalnızca renk öğretilmişse görünür.
   - Görüntüde personel izinin kutusu gri, etiketi "P".
   - Web canlı CSV'sinde (olay başına satır) personel geçişleri `yon = personel_giris` / `personel_cikis` satırlarıyla yer alır; giriş/çıkış toplamlarına katılmaz.
   - iPhone'un dakikalık CSV'si ve webhook'u değişmez: yalnızca müşteri giriş/çıkışı. Personel sayısı ekranda görünür.

## Algoritma (§4.10 eki — Python ve Swift birebir)
Tanımlar normalize koordinatlarda; kutu `(x1, y1, x2, y2)`, `w = x2 − x1`, `h = y2 − y1`.

**Gövde bölgesi:**
- `countAnchor = bottom` (yandan/yatık kamera): `x ∈ [x1 + 0,30w, x1 + 0,70w]`, `y ∈ [y1 + 0,15h, y1 + 0,45h]`.
- `countAnchor = center` (tepeden kamera): `x ∈ [x1 + 0,30w, x1 + 0,70w]`, `y ∈ [y1 + 0,30h, y1 + 0,70h]`.

**Örtüşme dışlama:** ızgara noktası aynı karedeki **başka bir tanıma kutusunun** içine düşüyorsa atılır (yan yana/üst üste
grupta komşunun rengi karışmasın). Kalan nokta sayısı 36'dan (ızgaranın %25'i) azsa o karede oy yok.

**Örnekleme:**
- Bölgede 12 × 12 ızgara; nokta `(i, j)`: `px = rx0 + (i + 0,5)/12 · rw`, `py = ry0 + (j + 0,5)/12 · rh`.
- Piksel `⌊px · W⌋`, `⌊py · H⌋`, `[0, W−1] × [0, H−1]` aralığına kırpılır.
- Görüntü sRGB 8 bit; iPhone'da kameranın YUV verisinden önce RGB'ye çevrilir. Eşdeğerlik RGB örneklerinden itibaren tanımlıdır.

**sRGB → CIE Lab (D65):**
- Doğrusallaştırma: `c = v/255`; `c ≤ 0,04045 ? c/12,92 : ((c + 0,055)/1,055)^2,4`.
- XYZ matrisi:
  - `X = 0,4124564 R + 0,3575761 G + 0,1804375 B`
  - `Y = 0,2126729 R + 0,7151522 G + 0,0721750 B`
  - `Z = 0,0193339 R + 0,1191920 G + 0,9503041 B`
- Beyaz noktaya bölme: `Xn = 0,95047`, `Yn = 1`, `Zn = 1,08883`.
- `f(t) = t > 0,008856 ? ∛t : 7,787 t + 16/116`.
- `L = 116 f(Y) − 16`, `a = 500 (f(X) − f(Y))`, `b = 200 (f(Y) − f(Z))`.

**Eşleşme:**
- Noktanın öğretilen renklerden herhangi birine uzaklığı `d = √((0,5 ΔL)² + Δa² + Δb²) < 20` ise nokta eşleşir. Parlaklık yarım ağırlıklı: gölge/ışık farkına dayanıklı.
- `L < 8` olan (çok karanlık) nokta eşleşmez.

**Kare oyu:**
- Yalnızca bu karede **tanımayla gözlenen** kutu için (tahmin ya da hareket lekesiyle sürdürülen karede oy yok): eşleşen nokta oranı (kalan noktalara göre) `≥ 0,25` → personel oyu.
- İz başına `votes` (oy verilen kare sayısı) ve `staff_votes` birikir.

**Geçiş kararı:**
- Geçiş onaylanıp sayıldığı anda (bekleyen geçişler dahil): `votes ≥ 3` ve `staff_votes ≥ 0,5 · votes` ise geçiş **personel** sayılır (`staff_in` / `staff_out`), değilse müşteri (`total` / `total_out`).
- Bir iz bir kez personel kararı alınca sonraki geçişleri de aynı iz için yeniden değerlendirilir (oylar birikmeye devam eder).

**Öğretme** (eşdeğerlik gerekmez; sonuç veri olarak saklanır, yine de iki tarafta aynı kural):
1. Tıklanan noktayı içeren en küçük alanlı tanıma kutusunun gövde bölgesi alınır.
2. Kutu yoksa tıklanan yer merkezli, kenarı görüntü genişliğinin 0,06'sı olan kare alınır.
3. 12 × 12 nokta Lab'a çevrilir. `(⌊a/8⌋, ⌊b/8⌋)` kutucuklarından en çok nokta düşen seçilir; eşitlikte ilk görülen.
4. Sonuç = o kutucuktaki noktaların L, a, b ayrı ayrı **medyanı** (çift sayıda noktada iki ortanın ortalaması).

## Sözleşme
`contracts/product-profile.schema.json` → isteğe bağlı `staffColors`:
- Dizi, `maxItems: 3`; öğe `{ "L": 0..100, "a": −128..127, "b": −128..127 }`, ek alan yok.
- Yoksa ya da boşsa özellik kapalı; boş dizi yazılmaz (alan atlanır).
- Kırıcı değil: `v1` kalır.
- `docs/02-contracts.md` profil bölümü güncellenir; örnek `examples/profile-people.json` eklenmez (isteğe bağlı alan).
- Olay şeması değişmez: personel geçişi olay olarak gönderilmez.
- Canlı API durumu (`/api/v1/live/sessions`): `staffIn`, `staffOut` eklenir (docs/13).

## Bileşenler
- **Python:**
  - `core/staff_color.py`: `srgb_to_lab`, `torso_region`, `sample_points`, `vote(frame, box, anchor, colors)`, `teach(frame, boxes, point, anchor)`, `is_achromatic`. Saf fonksiyonlar.
  - `core/people_track.py`: `MotTrack.votes`, `staff_votes`; `update(...)` isteğe bağlı `votes_by_det` alır.
  - Sayım sonucu `(girenler, çıkanlar)` yanında personel geçişleri ayrı döner.
  - `core/detect_count.py`: profilde renk varsa gözlenen kutular için oy hesaplar, `DetectResult.staff_in/staff_out`.
  - `core/pipeline.py`: `total_staff_in/out`.
  - `profile.py`: `staffColors` alanı.
  - `overlay.py`: "P" etiketi.
  - `live/session.py` + `api.py`:
    - Durumda `staffIn`/`staffOut`, CSV satırları.
    - `POST /sessions/{id}/staff-color {x, y}` → öğretilen rengi döndürür; profil güncellemesi mevcut `PUT profile` ile (renkler profilde).
- **Swift:**
  - `Vision/StaffColor.swift` aynı fonksiyonlar.
  - `PeopleTracker` oy alanları.
  - `FrameProcessor` örnekleme (YUV → RGB, yalnızca örnek noktalarda).
  - `ProductProfile.staffColors`.
  - Kalibrasyon panelinde bölüm ve dokunarak öğretme.
  - Sayaç altında "Personel geçişi".
- **Web:**
  - `GeometryControls` / canlı sayfa Ayarla panelinde **Personel rengi** bölümü (örnekler, öğret modu, uyarı).
  - `RoiEditor` üstünde tıklama yakalama.
  - Sayaç kartında "Personel geçişi".
  - `lib/live.ts` tipleri.

## Hata ve sınır durumları
- Renk yok → kod yolu çalışmaz (oy hesaplanmaz, işlemci maliyeti sıfır).
- Kutu görüntü kenarında / çok küçükse (`w·W < 8` ya da `h·H < 16` piksel) → oy yok.
- Karanlık sahne → noktalar eşleşmez → geçiş müşteri sayılır (güvenli yön: personel değil).
- Öğretmede tıklanan yer çok karanlıksa (`medyan L < 8`) → reddedilir: "Burası çok karanlık; personelin üstüne tıklayın."
- 4. renk eklenmek istenirse → "En fazla 3 renk" uyarısı.

## Test
- **Python:**
  - Lab çevirisi referans değerlerle (beyaz, siyah, saf kırmızı/yeşil/mavi, orta gri).
  - `vote`:
    - Tam üniforma, gövdenin %30'u yelek, gölgede (L −30), başka renk, akromatik.
  - İzleyici:
    - Sentetik video karelerinde renkli kişi kutuları.
    - Personel tek başına geçer → `staff_in = 1`, `total = 0`.
    - Personel + müşteri yan yana → `total = 1`, `staff_in = 1`.
    - Renk öğretilmemiş → bugünkü sayılar birebir.
  - `teach`: kutu içinden, kutusuz, karanlık ret.
  - API: öğret uç noktası, durumda `staffIn/staffOut`, CSV.
- **Eşdeğerlik:** `tools/make_staff_fixture.py` → `staff_parity.json` (RGB örnekleri → Lab, oy, karar); Python testi ve Swift `StaffColorTests` aynı fikstürü doğrular.
- **Web e2e:** Ayarla → Personel rengi → öğret (test klibinde tıklama) → örnek görünür → sil.
- **Açı doğrulaması (kabul ölçütü, ≥ %95 her açıda):** `tools/eval_staff.py`.
  - Etiketli kayıtlarda geçiş başına personel/müşteri kararını elle etiketle karşılaştırır, açı başına yakalama ve yanlış hariç tutma oranını yazar.
  - **Kayıt protokolü:** 3 açı (tepeden, eğik ~45°, yandan). Her açıda en az 20 personel geçişi (belirgin renkli yelek/tişört; giriş ve çıkış, tek başına ve müşteriyle yan yana) ve en az 20 müşteri geçişi (yelek rengine yakın olmayan ve bir kısmı koyu/siyah giyimli).
  - Etiket dosyası: `<video>.staff.json` = `[{"t": saniye, "dir": "in"|"out", "staff": true|false}]`.
  - Kayıtlar kullanıcının; **public repoya konmaz** (yerelde kalır); sonuçlar docs/12'ye yazılır.
  - %95 tutmayan açıda eşikler (`MATCH_DIST`, `MIN_FRACTION`, gövde bölgesi) yalnızca ölçümle ayarlanır ve iki tarafta birlikte değişir.
- Mevcut kişi sayımı testleri ve iki gerçek video (3/3, 9/3) renk yokken değişmeden geçmeli.

## Gizlilik (KVKK)
Görüntü saklanmaz ve cihazdan çıkmaz. Öğretilen renk yalnızca 3 sayıdır, kişiyi tanımlamaz. Oylar izle birlikte bellekte yaşar, iz bitince silinir.
