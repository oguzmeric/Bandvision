# Yangın / duman algılama — plan (2026-11-08)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Görevler `### Task N` başlıklarıyla.

**Goal:** Canlı kamerada ve "Video ile test"te `fire` analiz türü: alev → "Yangın", duman → "Duman" alarmı; mevcut güvenlik
alarmı yolu (kayıt, klip, Telegram, panel) üzerinden. Model eğitimi araçları ayrı görevde. **Spec:**
`docs/superpowers/specs/2026-11-08-yangin-duman-design.md` (bağlayıcı).

**Architecture:** `core/fire_model.py` (YOLOX-S iki sınıf, ONNX) → `core/fire_rules.py` (eşik, hariç bölge, hareket, ızgara oyu,
bölüm) → `core/fire.py` (`FireAnalyzer`). Canlıda `LiveSession` `countMode == "fire"` için `_setup_fire()`; alarm sink
(`LiveManager.on_safety`/`_register`) moddan bağımsızlaşır. Video ile test `video.py` `fire` hazır ayarı. Panel `yangin` türü.
Eğitim araçları `tools/fire_train/`.

**Tech:** Python 3.11+, FastAPI, OpenCV, numpy, onnxruntime (mevcut); Next.js 15, Playwright (mevcut). Uygulamaya yeni bağımlılık
yok. Eğitim betikleri PyTorch/YOLOX'u yalnız ayrı eğitim ortamında kullanır; uygulama ve testleri bunları içe aktarmaz.

## Global constraints
- Kullanıcıya görünen metin Türkçe; tanımlayıcılar İngilizce. Tip ipuçları zorunlu; `ruff`, `pytest`, `tsc`, unit, e2e yeşil.
- Görüntü cihazdan çıkmaz; zor örnekler yalnız yerel veri klasöründe. Telegram'a resim yalnız `fire.sendImage` açıksa.
- Model dosyası depoya girmez (`*.onnx` yok sayılıyor); testler gerçek model indirmez (`conftest._no_model_download`).
- Belgelerde cihaz modeli, loopback dışı IP, dosya yolu, sır adı yok.
- Paylaşılan Playwright portları (3100, 3101, 3102, 3118, 8091, 8092, 8098) koşmadan önce boş olmalı; hiçbir süreç öldürülmez.
  8090 ve 3000 portlarına dokunulmaz.
- Worktree'den ana sanal ortama `pip install` yapılmaz. Ultralytics kodu/ağırlığı hiçbir yerde kullanılmaz.
- Commit iletileri Türkçe, sonunda `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Rulings (bağlayıcı)
R1. **Tür yazımı:** canlı kayıt `type` ve video sözleşmesi `kind` için aynı dizgeler: `"fire"`, `"smoke"`. `countMode` değeri
    `"fire"`; hazır ayar anahtarı `"fire"`; panel analiz türü `"yangin"`; katalog kategorisi `{"id": "fire", "title": "Yangın /
    duman", "subtitle": "Alev ve duman için erken uyarı", "presets": [{"key": "fire", "name": "Yangın / duman"}]}` (iOS
    `ProductCatalog.swift` ile aynı).
R2. **FireConfig** (`core/profile.py`): `fire: SafetyRule(True, 3.0)`, `smoke: SafetyRule(True, 8.0)`, `sensitivity: str =
    "normal"` (`"low"|"normal"|"high"`), `ignoreZones: list[list[tuple[float, float]]] = []`, `sendImage: bool = False`.
    Aralıklar: fire 2–10 sn, smoke 5–30 sn; en çok 8 bölge, bölge başına 3–12 nokta, koordinat 0–1. `{}` geçerli. İki kural
    kapalıysa canlı doğrulama `422` "En az bir kural açık olmalı.". `Profile.fire_watch()` → ad "Yangın / duman",
    `countMode="fire"`, `processingWidth=640`, `fire=FireConfig()`. `to_dict` `fire` bloğunu yalnız `countMode=="fire"` iken yazar.
R3. **Model:** dosya `fire_smoke_v1.onnx`; `FIRE_MODEL_URL: str | None = None`, `FIRE_MODEL_SHA256: str | None = None`. Dosya
    yoksa ve URL `None` ise `FireModelMissing("Yangın/duman modeli kurulu değil.")`; URL varsa `download_verified` (etiket
    "Yangın/duman modeli"). Sınıflar `("fire", "smoke")`, giriş 640. YOLOX ızgara çözme + letterbox + sınıf başına NMS
    `core/detector.py`'den ortak bir yardımcıya taşınır (`core/yolox.py`: `letterbox(bgr, size) -> (tensor, r)`,
    `decode(out, r, w, h, class_ids, conf, iou) -> list[(x1,y1,x2,y2,score,cls_index)]`); `ObjectDetector.detect` aynı sonucu
    vermeye devam eder (mevcut testler + yeni eşdeğerlik testi). `FireDetector.detect(bgr, conf: dict[str, float]) ->
    list[Detection]` (sınıf başına eşik; NMS eşiği 0,45). Cihaz seçimi anahtarı `"fire"` (`devices_store`, varsayılan "auto").
R4. **Karar sabitleri** (`core/fire_rules.py`): `THRESHOLDS = {"low": {"fire": .60, "smoke": .65}, "normal": {"fire": .45,
    "smoke": .50}, "high": {"fire": .35, "smoke": .40}}`; `MIN_SIDE = 0.015` (kutunun kısa kenarı / kare yüksekliği);
    `MOTION_W = 160`; `MOTION_LAG_S = 1.0`; `MOTION_PIX = 8` (gri fark); `MOTION_MIN = 0.02` (kutu içinde değişen piksel oranı);
    `GLOBAL_CHANGE_MAX = 0.40` (kare genelinde değişen oran; üstündeyse kare oy dışı); `GRID = (8, 6)` (sütun, satır);
    `RATIO = 0.6`; `MIN_HITS = 3`; `END_S = 10.0`; `MAX_FPS = 5.0`. Hareket karşılaştırması `MOTION_LAG_S` kadar önceki ya da
    ondan eski en yakın kareyle; geçmişte yoksa en eski kareyle; hiç yoksa (ilk kare) kutu oy vermez.
R5. **Oy ve bölüm:** kare başına sınıf başına `8×6` bool ızgara (kutunun kapladığı hücreler). Hücre puanı = son `seconds`
    saniyedeki oy veren karelerde, hücrenin ya da 8-komşusunun işaretli olduğu karelerin oranı ve sayısı. Bölüm sınıfın ilk
    olumlu karesinde başlar; alarm: `ts − started ≥ seconds` ve bir hücrede oran ≥ `RATIO` ve sayı ≥ `MIN_HITS`. Bölüm
    başına tek alarm. Son olumlu kareden `END_S` sonra bölüm biter (`ended`, alarm verdiyse `True`). "Oy dışı" kare (ışık
    patlaması) pencerede sayılmaz. Kural kapalı sınıf hiç işlenmez. `FireAlarm(kind, track_id, box, started, ts)`;
    `track_id` = `0` (fire) / `1` (smoke) — alarm sink'in `(oturum, iz, tür)` anahtarı aynen çalışır. Alarm kutusu: tetikleyen
    hücreye değen son karedeki kutuların birleşimi (normalize).
R6. **FireResult:** `detections: list[tuple[str, Box, float, bool]]` (tür, normalize kutu, skor, hareket geçti mi),
    `active: list[tuple[int, str, float, bool]]` (iz, tür, süre, alarm verdi mi — safety ile aynı biçim), `fired`, `ended`,
    `boxes: dict[int, Box]` (alarm vermiş açık bölümlerin kutusu). `FireAnalyzer(detector=None)`: `process(frame, ts,
    profile) -> FireResult`, `reset()`, `end_all()` — `SafetyAnalyzer` ile aynı sözleşme (reset sonrası alarmlı bölümler
    bir sonraki `process`'te `ended`). Analiz hızı sınırı oturumda uygulanır (R7), analizörde değil.
R7. **Canlı:** `LiveSession` `_setup_fire()` paylaşılan `SharedFire` (api.py, `SharedPose` deseni; ad "Yangın/duman modeli")
    ile `FireAnalyzer` + `ClipBuffer` kurar; `countMode=="fire"` iken kareler arası en az `1 / MAX_FPS` sn (fazlası işlenmez ama
    önizleme ve klip ön kaydı sürer). Pipeline dispatch `FrameResult.fire`. Alarm sink: `on_safety` → `on_alarm` (eski ad
    takma ad olarak kalabilir), `in_safety` → `countMode in ("safety", "fire")`, `send_image` ilgili bloğun `sendImage`'ı.
    `_TITLES["fire"] = "🔥 YANGIN"`, `_TITLES["smoke"] = "💨 DUMAN"`; yangın/duman metnine ikinci satır "Görüntüyü hemen kontrol
    edin.". `GET /alarms` Literal'ına `fire`, `smoke`. `watch.json` yangın oturumlarını da tutar (safety ile aynı koşul).
    Durum: `snapshot_status()["fire"] = {active, lastAlarmAt, model, healthy, reason, unhealthyFor}`; model yoksa
    `healthy=False`, `reason="Yangın/duman modeli kurulu değil."`. Karo rozeti `_analysis()` safety ile aynı biçim, `mode:"fire"`.
R8. **Klip çizimi:** `ClipOverlay` iki türü taşır: `kind: str = "safety"` alanı ve yangın için `fire_boxes:
    tuple[tuple[str, np.ndarray, bool], ...]` (tür, normalize kutu, alarmlı mı). `from_fire(r, shape, profile)` sınıf yöntemi.
    `ClipWriter` `kind=="fire"` ise `overlay.draw_fire` ile çizer: yangın turuncu (BGR `(0,140,255)`) "YANGIN", duman gri
    `(200,200,200)` "DUMAN", alarmlı kutu kalın (3 px) diğerleri 1 px. `empty` yangın için `not fire_boxes`.
R9. **Zor örnek:** `POST /alarms/{id}/false-alarm` bir `fire`/`smoke` alarmında `true` yapılınca `<data>/live/hard-negatives/<id>/`
    altına `image.jpg` ve (varsa, yazılmışsa) `clip.webm` kopyalanır, `meta.json` `{id, type, camera, firedAt, sourceId,
    channelId}` yazılır; geri alınınca (false) klasör silinir. Klip sonradan yazılırsa (`clipPending`) yazıldığında kopyalanır.
    Kopyalama hatası alarm işlemini bozmaz (uyarı günlüğü). Klasör en çok 500 alarm; aşınca en eskiler silinir.
R10. **Video ile test:** `--preset fire`, seçenekler `options.fire = {fire: {enabled, seconds}, smoke: {enabled, seconds},
    sensitivity}`; CLI `--fire N | --no-fire`, `--smoke N | --no-smoke`, `--sensitivity low|normal|high`. Sonuç `alarms[]`
    `{kind, trackId, startS, atS, endS, image}` (kind `fire|smoke`), `alarmlar.csv` aynı sütunlar, `tur` değeri "Yangın"/"Duman".
    Sayım seçenekleriyle karışık istek 422 (mesajlar safety ile aynı kalıp: "Yangın/duman analizi sayım seçenekleriyle
    birlikte kullanılamaz.", "Yangın/duman kuralları yalnız yangın/duman analizinde geçerlidir."). Model yoksa iş `failed`,
    mesaj "Yangın/duman modeli kurulu değil.".
R11. **Panel:** `AnalysisKind` += `"yangin"` (başlık "Yangın / duman", kategori `"fire"`), menü Analizler altında
    `/live?tur=yangin`. Etiketler: `ALARM_TITLES`/`ALARM_LABELS` `fire: "Yangın"`, `smoke: "Duman"`; `/alarms` sayfası sayaçları
    tür listesinden. `FireSettings`: kurallar, hassasiyet (`Düşük`/`Normal`/`Yüksek`), "Alarm resmini gönder", "Hariç
    bölgeler" (en çok 8 çokgen; mevcut `RoiEditor`'dan çoklu çokgen bileşeni), model satırı ("Yangın/duman modeli: hazır /
    yükleniyor / kurulu değil"), sabit uyarı "Erken uyarıdır; yangın algılama ve alarm sisteminin yerine geçmez.". Video ile
    test: hazır ayar "Yangın / duman", kural alanları, hassasiyet. Cihaz ayarları satırı `fire` "Yangın/duman modeli".
R12. **iOS:** `CountMode.fire` (başlık "Yangın / duman (yalnızca bilgisayar)"), `FireConfig: Codable` (safety `init(from:)`
    toleransı aynen; `ignoreZones` `[[[Double]]]` olarak; yalnız okunur/korunur), `ProductProfile.fire: FireConfig?`, katalog
    kategorisi R1, test `FireProfileTests.swift` (gidiş-dönüş, `{}` varsayılanları). Xcode derlemesi bu ortamda yok; mevcut
    safety deseninin birebir uyarlaması.

## Review Focus (spec'in ima ettiği, testle sabitlenen durumlar)
1. Sabit bir alev resmi/kırmızı lamba (dedektör her karede yüksek skor, kutu içi değişim yok) → hiç alarm yok.
2. Kamera ışık patlaması/IR geçişi (kare geneli %40+ değişim) → o kareler sayılmaz, tek başına alarm doğurmaz.
3. 1 kare/sn akış ve 25 kare/sn dosya → aynı sahnede alarm zamanı kural süresinden erken değil, `seconds + 1/fps`'ten geç değil.
4. Hariç bölge içindeki ocak/kaynak alevi → alarm yok; bölge dışına taşan alev → alarm.
5. Model dosyası yok → canlı oturum açılır ama sağlıksız ve nedenli; video işi `failed` ve Türkçe mesaj; panel "kurulu değil".

### Task 1: Sözleşmeler, profil, katalog, iOS
**Files:** `core/profile.py`, `live/store.py` (CATALOG, `make_preset`), `contracts/product-profile.schema.json`,
`contracts/analysis-job.schema.json`, `contracts/examples/analysis-job-fire-done.json` (yeni), `docs/02-contracts.md`,
`apps/ios/BantSayac/Core/ProductProfile.swift`, `apps/ios/BantSayac/Core/ProductCatalog.swift`,
`apps/ios/BantSayacTests/FireProfileTests.swift`; testler `tests/test_profile_contract.py`, `tests/test_fire_profile.py` (yeni).
- R1, R2, R12 uygulanır. `Profile.from_dict` `fire` bloğunu ayrıştırır (bozuk/eksik alan varsayılan; aralık dışı sayılar
  kırpılmaz, canlı doğrulama reddeder — safety ile aynı davranış).
- Şemada `fire` nesnesi: `fire`/`smoke` (`enabled` bool, `seconds` number), `sensitivity` enum, `ignoreZones` (dizi, ≤ 8;
  her öğe 3–12 noktalı `[x,y]` dizisi, 0–1), `sendImage`. `analysis-job` `preset` enum'a `fire`, `options.fire`, `alarms[].kind`
  enum'a `fire`, `smoke`; `if preset==fire then alarms allowed` kuralı safety kuralının yanına; `countMode` enum'una
  `fire` eklenmez (video `--mode` dışı).
- `tools/validate_contracts.py` örnekleri doğrular (yeni örnek dahil).
- Testler: gidiş-dönüş, `{}` varsayılanları, `to_dict` başka modda `fire` yazmaz, şema doğrulaması (geçerli/geçersiz bölge),
  katalog ve `make_preset("fire")`.

### Task 2: Ortak YOLOX çözme ve yangın modeli
**Files:** `core/yolox.py` (yeni), `core/detector.py`, `core/fire_model.py` (yeni), `live/devices_store.py`, testler
`tests/test_yolox.py`, `tests/test_fire_model.py` (yeni), mevcut `tests/test_devices_models.py`.
- R3. `detector.py` davranışı değişmez: eşdeğerlik testi rastgele ama tohumlu ham çıktıyla eski ve yeni yolu karşılaştırır
  (eski kodu testte sabit bir referans işlev olarak kopyalayarak).
- `FireDetector(path=None, device=None)`: `devices.open_session`; `used`, `broken` özellikleri `ObjectDetector` gibi.
  `fire_model_path()`, `ensure_fire_model()`. Testler sahte oturumla (onnxruntime oturumu yerine `run` döndüren nesne):
  sınıf başına eşik, iki sınıfın ayrı NMS'i, letterbox geri ölçek, model yok → `FireModelMissing`, URL varsa indirme yolu
  (`download_verified` monkeypatch).
- `devices_store` seçimlerine `"fire"`; Cihaz ayarları API'si yeni anahtarı döndürür/kaydeder (mevcut testler genişletilir).

### Task 3: Karar katmanı ve FireAnalyzer
**Files:** `core/fire_rules.py`, `core/fire.py` (yeni), `core/pipeline.py` (`FrameResult.fire`, dispatch), testler
`tests/fakes_fire.py`, `tests/test_fire_rules.py`, `tests/test_fire.py` (yeni).
- R4, R5, R6. Hariç bölge testi nokta-çokgen (`cv2.pointPolygonTest`, normalize koordinat × kare boyutu).
- Sahte dedektör: kare zamanına göre kutu listesi döndüren betik (`FakeFireDetector(script)`); sentetik kareler: düz gri
  zemin + kutu içinde her kare değişen gürültü (hareketli) ya da sabit desen (durağan).
- Review Focus 1–4 burada testle sabitlenir; ayrıca: kural kapalı sınıf, bölüm başına tek alarm, `END_S` sonrası bitiş ve
  yeniden başlama, iki sınıf aynı anda, reset → sonraki process'te `ended`, `end_all`, rastgele dağılmış tek kare kutular
  (komşu olmayan hücreler) → alarm yok, yavaş kayan duman kutusu (komşu hücreler) → alarm.

### Task 4: Canlı oturum, alarm yolu, durum, izleme listesi
**Files:** `live/session.py`, `live/api.py` (`SharedFire`, `on_alarm`, `_TITLES`, `/alarms` Literal, doğrulama `_check_fire`,
`_profile_from`, `_analysis`, watch koşulları, cihaz seçimi), `analyzer/app.py` (yaşam döngüsünde `SharedFire`), testler
`tests/test_live_fire.py` (yeni), `tests/test_live.py` (ad değişikliği gerekiyorsa).
- R7. `safety_health` deseni yangın için `fire_health` (tek model). Model yoksa oturum `running` ama `fire.healthy=False` ve
  neden; model sonradan yüklenirse (paylaşılan model `ready`) analiz kendiliğinden başlar (safety'deki model yeniden deneme
  deseni). Review Focus 5 (canlı kısmı) burada.
- Testler: alarm kayda + bildirim kuyruğuna + klip yakalamaya ulaşır (sahte dedektör), başlık ve ikinci satır, soğuma,
  `sendImage` bayrağı, mod değişiminde açık alarm kapanır, `MAX_FPS` atlama, durum bloğu, watch geri yükleme, doğrulama 422'leri.

### Task 5: Klip çizimi ve zor örnekler
**Files:** `live/clips.py`, `overlay.py` (`draw_fire`), `live/alarms.py` (zor örnek kopyası), `live/api.py` (false-alarm ucu),
testler `tests/test_clips.py`, `tests/test_alarms.py`, `tests/test_hard_negatives.py` (yeni).
- R8, R9. Eşleme kuralı (`OVERLAY_MAX_AGE_S`) yangın için de geçerli; mevcut safety klip testleri değişmeden geçer.
- Testler: yangın kutusu klipte çizilir (piksel rengi kontrolü), boş sonuç eski kutuyu siler, zor örnek kopyası/geri alma/
  sonradan yazılan klip/500 sınırı/kopya hatası.

### Task 6: Video ile test
**Files:** `video.py`, `analyzer/jobs.py`, `analyzer/app.py` (`OptionsIn`, `FireIn`, karışık seçenek), testler
`tests/test_video_fire.py` (yeni), `tests/test_analyzer.py`.
- R10. `count_fire()` `count_safety()` kalıbında; `MAX_ALARM_IMAGES` ve CSV biçimi aynı. `jobs.ALARM_KINDS` → tür kümesi
  `{"handsUp","lying","fire","smoke"}` hazır ayara göre doğrulanır.
- Testler: sahte dedektörle sonuç/CSV/resimler, seçeneklerin CLI'ye çevrilmesi, 422'ler, model yok → failed + mesaj, sözleşme
  doğrulaması (`analysis-job.schema.json`).

### Task 7: Panel
**Files:** `apps/dashboard/src/lib/{types.ts,live.ts,analysisKind.ts,nav.ts,views.ts,safetyAlarms.mjs(+.d.mts)}`,
`components/live/{FireSettings.tsx (yeni),SafetyPanel.tsx,LiveView.tsx,StartSessionDialog.tsx,AlarmCenter.tsx,AlarmsView.tsx,
AlarmViewer.tsx,CamerasView.tsx}`, `components/watch/TileOverlay.tsx`, `components/geometry/ZonesEditor.tsx` (yeni),
`components/video/{UploadCard.tsx,JobDetail.tsx}`, `components/devices/DeviceSettings.tsx`; testler
`e2e/fire-ui.spec.ts` (yeni, sahte rotalar), `src/lib/*.test.mjs`, mevcut e2e'ler.
- R11. Alarm merkezi ve afiş yangın oturumlarını da dinler (`countMode in safety|fire`).
- e2e: yangın oturumu ayar paneli (kural/hassasiyet/bölge çizimi → PUT gövdesi), model "kurulu değil" satırı, alarm listesi
  etiketleri ve sayaçları, video ön ayarı seçenek gövdesi, cihaz ayarı satırı, uyarı metni görünür.

### Task 8: Eğitim araçları, model kartı, belgeler
**Files:** `tools/fire_train/{README.md,prepare_data.py,eval_fire.py,export.py,exps/fire_yolox_s.py}`,
`tools/tests/test_fire_train.py` (yeni; PyTorch gerektirmez), `docs/14-yangin-duman.md` (yeni: kullanım, ayar önerileri, sınırlar,
model kartı, veri atıfları, zor örneklerin eğitime katılması), `docs/13-web-platform.md` (bölüm + bağlantı), `docs/12-durum.md`
(§ yangın/duman: durum ve TRASSIR kıyas prosedürü), `docs/03-algorithm.md` (karar katmanı özeti).
- `prepare_data.py`: D-Fire YOLO txt (sınıf 0 smoke, 1 fire — D-Fire düzeni; bizim düzene çevrilir: 0 fire, 1 smoke) →
  COCO json; `--include-public` yoksa `PublicDataset` ön ekli dosyalar atılır ve sayısı raporlanır; FireNet VOC xml → COCO;
  bölümleme D-Fire'ın kendi train/test ayrımını korur, eğitimden %10 doğrulama (tohumlu); `sources.csv` (dosya, kaynak, lisans).
- `eval_fire.py`: (a) COCO mAP50 sınıf başına (pycocotools varsa, yoksa basit 11 nokta AP uygulaması — testte bu kullanılır);
  (b) olay düzeyi: video listesi (pozitif/negatif) gerçek `FireAnalyzer` ile oynatılır, hassasiyet başına pozitif alarm oranı,
  ilk alarm süresi, negatif yanlış alarm sayısı; (c) eşik kalibrasyonu önerisi; Türkçe Markdown tablo çıktısı.
- `export.py`: YOLOX `tools/export_onnx.py` sarmalayıcı (opset 11, decode yok), onnxruntime ile çıktı biçimi denetimi
  (`[1, 8400, 7]`), SHA-256 yazdırır.
- Testler: küçük sahte D-Fire ağacıyla sınıf eşlemesi ve `PublicDataset` filtresi, VOC dönüşümü, AP hesabı (elle hesaplanmış
  örnek), olay düzeyi toplama (sahte analizör sonuçlarıyla).
- Araç testleri `test_eval_pose.py` kalıbında: modül `importlib` ile yüklenir, numpy/OpenCV isteyen testler
  `needs_edge` ile işaretlenir; `ci.yml` edge-core işindeki araç testleri satırına `test_fire_train.py` eklenir.
- iOS değişikliği `ios.yml` (macOS derlemesi) ile push'ta doğrulanır; dal push'tan sonra bu iş de yeşil olmalı.
- Not: gerçek indirme/eğitim/değerlendirme bu görevin parçası değildir (kullanıcı onayına bağlı ayrı adım).
