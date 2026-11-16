# Telefon kullanımı alarmı — uygulama planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Güvenlik alarmı moduna üçüncü kural olarak "telefon kullanımı" alarmı (kişi kırpıntısında COCO telefon araması + el/baş yakınlığı + 5 sn'lik dilimlerle kanıt penceresi), canlı kamera, video ile test, panel, iOS taşıma ve ölçüm aracıyla uçtan uca.

**Architecture:** Yeni `core/phone_rules.py` kırpıntı aramasını, isabet kararını ve `PhoneEvidence` bölüm izleyicisini taşır; `SafetyAnalyzer` onu poz sonrası çağırır ve çıktıyı mevcut `fired/ended/active` biçimine (`(iz, "phone")`) katar, böylece canlı alarm/klip/bildirim yolu türden bağımsız kalır. Sözleşmeye eklemeli `safety.phone` alanı ve `"phone"` alarm türü girer (şema sürümü v1 kalır).

**Tech Stack:** Python 3.11+ (numpy, OpenCV, ONNX Runtime, FastAPI, pytest, ruff), Next.js 15 / TypeScript (node --test, Playwright), Swift 5 (XCTest).

**Spec:** `docs/superpowers/specs/2026-11-16-telefon-alarmi-design.md`

## Global Constraints
- Kural varsayılanı **kapalı**, süre **60 sn**, aralık **10–600 sn** (çekirdek, canlı API, video işi, CLI, panel, şema hep aynı).
- Alarm türü adı: canlı `type = "phone"`, video işi `alarms[].kind = "phone"`. Metinler: başlık "TELEFON KULLANIMI", etiket "Telefon kullanımı", görüntü etiketi "TELEFON", Telegram `🚨 TELEFON KULLANIMI`.
- Sabitler (başlangıç, `core/phone_rules.py`): `PHONE_CONF = 0.25`, `PHONE_NEAR = 0.6`, `PHONE_PAD = 0.2`, `PHONE_FPS = 2.0`, `PHONE_SLOT_S = 5.0`, `PHONE_SLOT_RATIO = 0.6`, `PHONE_END_S = 15.0`.
- COCO sınıfı `"cell phone": 67` `CLASS_IDS`'e eklenir; profil `detectClasses` enumuna ve `GROUPS`'a **eklenmez**.
- Telefon kuralı kapalıyken güvenlik çözümleyicisinin davranışı ve model çağrı sayısı bugünküyle birebir aynı.
- Şema sürümü `bantvision.profile.v1` / `bantvision.analysis-job.v1` kalır (eklemeli alan).
- Kullanıcıya görünen metinler Türkçe; kod tanımlayıcıları İngilizce. Ultralytics kodu/ağırlığı yok. Görüntü cihazdan çıkmaz. Kullanıcı videoları repoya girmez.
- Port 3000 ve 8090'a dokunulmaz; Playwright portları (3100, 3101, 3102, 3118, 8091, 8092, 8098) boş mu bakılır, süreç öldürülmez.
- Commit sonu: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus
1. Kayıtlı eski güvenlik profili (`phone` alanı yok: Python JSON, panel, iOS) → telefon kapalı, hata yok; `phone` varsa yeniden kaydetmede korunur. (Task 1, 4, 5 testleri)
2. Yalnız telefon kuralı açık (eller yukarı ve yerde yatma kapalı) → poz çalışır, alarm doğar; video CLI/iş "En az bir kural açık olmalı" demez. (Task 1, 3)
3. İz kaybı ya da isabetsiz `PHONE_END_S` → bölüm biter ve `ended` bildirilir (alarm kaydı açık kalmaz); `reset()`/`end_all()` alarmlı telefon bölümünü de bildirir. (Task 1)
4. Kişi kutusu kare kenarında (kırpıntı kenara taşar) ya da boş kırpıntı → kırpma sınırlanır, boşsa arama atlanır, çökme yok. (Task 1)
5. `/alarms?type=phone` filtresi ve alarm sayfası türü tanır; bekleme süresi (kamera+tür) telefon için de işler. (Task 2, 4)

---

### Task 1: Çekirdek — profil alanı, telefon kuralları, güvenlik çözümleyicisine katma

**Files:**
- Modify: `services/edge/bantvision/core/profile.py` (SafetyConfig, from_dict)
- Modify: `services/edge/bantvision/core/detector.py` (`CLASS_IDS`)
- Create: `services/edge/bantvision/core/phone_rules.py`
- Modify: `services/edge/bantvision/core/safety.py`
- Modify: `services/edge/bantvision/overlay.py` (`_SAFETY_LABELS`)
- Modify: `services/edge/tests/fakes_safety.py` (FakeDetector'a `cls="person"`; yeni `FakePhoneDetector`, `phone_kp()`)
- Create: `services/edge/tests/test_phone_rules.py`
- Modify: `services/edge/tests/test_safety.py`, `services/edge/tests/test_profile_contract.py`

**Interfaces:**
- Produces:
  - `SafetyConfig.phone: SafetyRule = SafetyRule(False, 60.0)`; `from_dict` eksikse varsayılan; `to_dict` `asdict` ile yazar.
  - `phone_rules.find_phones(detector, bgr: np.ndarray, box_px: tuple[float,float,float,float]) -> list[tuple[float,float,float,float,float]]` — kişi kutusu `PHONE_PAD` payla kareye sınırlanarak kırpılır, `detector.detect(crop, ["cell phone"], conf=PHONE_CONF)` sonucundan yalnız `cls == "cell phone"` olanlar, **tam kare piksel** `(x1, y1, x2, y2, skor)`; boş kırpıntı → `[]`.
  - `phone_rules.phone_hit(phones, kp: np.ndarray) -> bool | None` — `pose_rules.scale(kp)` yoksa ya da hiçbir bilek/baş görünmüyorsa None; bir telefon merkezi görünen bilek ya da `pose_rules.head(kp)`'ye `PHONE_NEAR · ölçek` uzaklık içindeyse True; aksi False.
  - `phone_rules.PhoneEvidence` — `observe(track_id: int, ts: float) -> None`, `update(track_id: int, ts: float, hit: bool | None, seconds: float) -> bool` (bu çağrıda alarm doğduysa True, bölüm başına bir kez), `sweep(ts: float, alive: set[int]) -> list[tuple[tuple[int, str], bool]]`, `close_all() -> list[tuple[tuple[int, str], bool]]`, `active() -> list[tuple[int, str, float, bool]]`. Anahtar türü daima `"phone"`.
  - `SafetyAlarm.kind` artık `"hands_up" | "lying" | "phone"`.

- [ ] **Step 1: Kural testlerini yaz** (`test_phone_rules.py`)
  - `test_find_phones_crops_with_pad_and_maps_to_frame_pixels`: 400×300 kare, kişi kutusu (100, 50, 200, 250); sahte dedektör kırpıntıya göre (10, 20, 30, 40, 0.5, "cell phone") ve bir "person" döner → sonuç `[(100-20+10, 50-40+20, 100-20+30, 50-40+40, 0.5)]` (pay %20: 20 px, 40 px); dedektöre giden kırpıntı şekli `(280, 140, 3)`; çağrıdaki sınıf listesi `["cell phone"]` ve `conf == PHONE_CONF`.
  - `test_find_phones_clamps_box_at_frame_edge_and_skips_empty_crop`: kutu (-50, -50, 30, 30) → kırpıntı (0,0)'dan başlar; kutu tamamen dışarıda (500, 500, 600, 600) → `[]` ve dedektör çağrılmaz.
  - `test_phone_hit_near_wrist_or_head`: `phone_kp()` (omuz/kalça ile ölçek 160 px) için bilekten 0,5·ölçek uzaktaki telefon → True; 0,7·ölçek → False; başın yanında → True; telefon yok → False; omuzlar görünmez → None.
  - `test_evidence_fires_when_enough_slots_have_hits`: 60 sn kural; iz 0–60 sn gözlenir (her 0,5 sn `observe`), isabetler her dilimde (5 sn'de bir) → alarm `ts == 60` civarında tam bir kez True; `active()` süresi ilk isabetten beri.
  - `test_evidence_does_not_fire_below_slot_ratio`: isabet 12 dilimin 7'sinde (oran 0,58) → alarm yok; 8'inde (0,67) → alarm.
  - `test_evidence_needs_track_observed_for_whole_window`: isabetler her dilimde ama iz yalnız son 40 sn gözlenmiş → 60 sn kuralında alarm yok (gözlem 60 sn'ye ulaşınca doğar).
  - `test_evidence_ends_after_end_s_without_hits_and_on_track_loss`: son isabetten `PHONE_END_S` + 0,1 sn sonra `sweep` → `[((id, "phone"), fired)]`; alarmsız bölüm iz `alive` dışında kalınca hemen biter; alarmlı bölüm iz kaybında `PHONE_END_S` dolunca biter.
  - `test_evidence_hit_none_is_not_a_miss`: `hit=None` çağrıları bölümü uzatmaz ve isabet sayılmaz, bitirmez de (yalnız süre bitirir).
  - `test_close_all_reports_fired_and_unfired`.

- [ ] **Step 2: Çalıştır, başarısız olduğunu gör**
  Run: `cd services/edge && pytest -q tests/test_phone_rules.py` → FAIL (modül yok).

- [ ] **Step 3: `core/phone_rules.py`'yi yaz**; `CLASS_IDS`'e `"cell phone": 67`; `SafetyConfig.phone` + `from_dict` (eksik → `SafetyRule(False, 60.0)`).
  Kanıt penceresi kuralı (imzanın belirlemediği algoritma):
  ```text
  observe: iz gözlem sürekliliği; son gözlemden > PHONE_END_S geçmişse gözlem başlangıcı = ts.
  update(hit=True): bölüm yoksa başlat (start = ts); hits'e ts ekle; last_hit = ts.
  her update'te (bölüm varsa, alarm verilmemişse): ts − gözlem_başlangıcı ≥ seconds ise
      n = ceil(seconds / PHONE_SLOT_S); dilim i = [ts − seconds + i·SLOT, …); en az bir isabeti olan dilim sayısı / n
      ≥ PHONE_SLOT_RATIO → fired = True, True döndür.
  hits yalnız son `seconds` için tutulur.
  sweep: (iz alive değil ve fired değil) ya da ts − last_hit > PHONE_END_S ya da ts < last_hit → bitti.
  ```

- [ ] **Step 4: `SafetyAnalyzer`'a kat** (`core/safety.py`)
  - Kurallar listesine telefon eklenmez (o liste kare kararı fonksiyonları içindir); bunun yerine `sf.phone.enabled` ise poz döngüsü çalışır (üç kural da kapalıyken poz hiç çalışmaz — korunur).
  - İz başına: `observe`; son aramadan ≥ `1/PHONE_FPS` geçtiyse `find_phones(self.dc.detector, bgr, kutu_px)` → `phone_hit` → `update(...)`; True ise `SafetyAlarm("phone", t.id, box, ts − süre, ts)`.
  - `ended`: mevcut sweep çıktısı + `PhoneEvidence.sweep(ts, alive)`; `active`: iki izleyicinin birleşimi; `reset()` ve `end_all()` telefon bölümlerini de kapatır/bildirir. Son arama zamanları `reset`'te temizlenir.
  - `overlay._SAFETY_LABELS["phone"] = "TELEFON"`.

- [ ] **Step 5: Çözümleyici ve profil testleri** (`test_safety.py`, `test_profile_contract.py`)
  - `test_phone_rule_off_by_default_never_searches_crops`: varsayılan profil; `FakePhoneDetector` çağrı listesinde `["cell phone"]` hiç yok; mevcut testlerdeki model çağrı sayıları değişmez.
  - `test_phone_only_rule_fires_phone_alarm`: handsUp/lying kapalı, phone açık 10 sn; kişi + bileğin yanında telefon her karede; 10 kare/sn 12 sn → tam bir `fired` `kind == "phone"`; poz çağrılmış.
  - `test_phone_search_rate_limited_to_phone_fps`: 10 kare/sn 5 sn → telefon araması 10 ± 1 kez.
  - `test_reset_and_end_all_report_fired_phone_episode`.
  - `test_profile_safety_phone_roundtrip_and_default`: `phone` yoksa `enabled False, 60`; `{"phone": {"enabled": true, "seconds": 120}}` gidip gelir.
  Run: `cd services/edge && pytest -q tests/test_phone_rules.py tests/test_safety.py tests/test_profile_contract.py` → PASS; `ruff check . ../../tools` → temiz.

- [ ] **Step 6: Commit** — `git commit -m "Telefon alarmı: çekirdek kurallar (kırpıntıda telefon, el/baş yakınlığı, dilimli kanıt penceresi)"`

### Task 2: Sözleşme ve canlı API

**Files:**
- Modify: `contracts/product-profile.schema.json` (`safety.phone`, açıklama "Yoksa varsayılanlar: eller yukarı ve yerde yatma açık (3, 10 sn), telefon kapalı (60 sn), resim kapalı.")
- Modify: `contracts/analysis-job.schema.json` (`options.safety.phone` 10–600; `alarms.kind` enumuna `"phone"`)
- Modify: `contracts/examples/analysis-job-safety-done.json` (bir `phone` alarmı içeren örnek) ve gerekiyorsa profil örneği
- Modify: `docs/02-contracts.md` (§1 `safety` satırı, §7 `options`/`alarms.kind`)
- Modify: `services/edge/bantvision/live/api.py` (`_SAFETY_RULES["phone"] = ("Telefon kullanımı", 10.0, 600.0)`, `_TITLES["phone"] = "🚨 TELEFON KULLANIMI"`, `_MODE_OF["phone"] = "safety"`, `/alarms` `Literal`'e `"phone"`)
- Modify: `services/edge/bantvision/live/alarms.py` (belge satırı türler)
- Test: `tools/tests/test_contracts.py`, `services/edge/tests/test_live.py`

**Interfaces:**
- Consumes: Task 1 `SafetyConfig.phone`, `SafetyAlarm.kind == "phone"`.
- Produces: canlı alarm kaydı `type == "phone"`; `GET /alarms?type=phone`.

- [ ] **Step 1: Testler**
  - `test_contracts.py`: şema `safety.phone` 10 ve 600'ü kabul eder, 9 ve 601'i reddeder; `alarms.kind == "phone"` geçerli; mevcut örnek doğrulamaları geçer.
  - `test_live.py`: `test_safety_phone_range_validated_in_turkish` (PUT profil `phone.seconds = 5` → 422, metin "Telefon kullanımı süresi 10–600 sn arasında bir sayı olmalı."); `test_phone_alarm_reaches_store_with_title_and_type_filter` (sahte sink akışıyla `phone` alarmı → kayıt `type == "phone"`, Telegram metni `🚨 TELEFON KULLANIMI — ` ile başlar, `GET /alarms?type=phone` yalnız onu döner); `test_phone_alarm_cooldown_per_camera_and_kind` (60 sn içinde ikinci `phone` → notify "suppressed", aynı anda `hands_up` etkilenmez).
- [ ] **Step 2:** Çalıştır → FAIL. **Step 3:** Şema, doküman, api.py değişiklikleri. **Step 4:** `cd services/edge && pytest -q tests/test_live.py -k "phone or safety"` ve `pytest -q ../../tools/tests/test_contracts.py` → PASS.
- [ ] **Step 5: Commit** — "Telefon alarmı: sözleşme (safety.phone, kind phone) ve canlı API".

### Task 3: Video ile test (analiz sunucusu + CLI)

**Files:**
- Modify: `services/edge/bantvision/analyzer/app.py` (`PhoneIn(SafetyRuleIn)`: `title, low, high = "Telefon kullanımı", 10.0, 600.0`; `SafetyIn.phone: PhoneIn | None = None`)
- Modify: `services/edge/bantvision/analyzer/jobs.py` (`ALARM_KINDS["safety"] = ("handsUp", "lying", "phone")`; `options_to_args` güvenlik kuralları listesine `("phone", "phone")`)
- Modify: `services/edge/bantvision/video.py` (`SAFETY_KINDS["phone"] = "phone"`, `SAFETY_LABELS_TR["phone"] = "Telefon kullanımı"`, `SAFETY_RANGES["phone"] = ("Telefon kullanımı", 10.0, 600.0)`, `--phone SANİYE` / `--no-phone`, `apply_safety_options` üç kural ve "En az bir kural açık olmalı." üç kuralı sayar, `MODE_TR["safety"]` "güvenlik alarmı (poz: eller yukarı, yerde yatan kişi, telefon kullanımı)", özet satırı açık kuralları listeler)
- Test: `services/edge/tests/test_analyzer.py`, `services/edge/tests/test_video_safety.py`

- [ ] **Step 1: Testler**
  - `test_analyzer.py`: `options.safety.phone = {"enabled": true, "seconds": 90}` → `--phone 90`; `{"enabled": false}` → `--no-phone`; `seconds: 5` → 422 Türkçe "Telefon kullanımı süresi 10–600 sn arasında bir sayı olmalı."; sonuçta `kind: "phone"` alarmı geçerli sayılır (`checked_alarms`).
  - `test_video_safety.py`: `--no-hands-up --no-lying --phone 10` kabul edilir (hata yok); `--no-hands-up --no-lying` (telefon varsayılan kapalı) → "En az bir kural açık olmalı."; sahte dedektör/pozla telefon alarmı `alarmlar.csv`'de `Telefon kullanımı`, `ozet.json` alarm `kind == "phone"`.
- [ ] **Step 2:** FAIL. **Step 3:** Uygula. **Step 4:** `pytest -q tests/test_analyzer.py tests/test_video_safety.py` → PASS.
- [ ] **Step 5: Commit** — "Telefon alarmı: video ile test (seçenek, CLI bayrakları, alarm listesi)".

### Task 4: Panel (canlı ayarlar, alarm sayfası, video yükleme)

**Files:**
- Modify: `apps/dashboard/src/lib/live.ts` (`SafetyConfig.phone?: {enabled: boolean; seconds: number}`; `AlarmType` + `"phone"`; `ALARM_TITLES.phone = "TELEFON KULLANIMI"`; `ALARM_LABELS.phone = "Telefon kullanımı"`)
- Modify: `apps/dashboard/src/components/live/SafetyPanel.tsx` (`SAFETY_DEFAULTS.phone = {enabled: false, seconds: 60}`; `SafetySettings` üçüncü satır "Telefon kullanımı", aralık 10–600 adım 10; `value.phone` yoksa varsayılan; satır altında yardım metni: "Kişinin elinde ya da yüzünün yanında telefon/tablet görülürse. Telefonla kulakta konuşma bu sürümde yakalanmaz. Kişi görüntüde yeterince büyük olmalı. Çalışanları bilgilendirin (KVKK).")
- Modify: `apps/dashboard/src/lib/safetyAlarms.mjs` + `.d.mts` (`SAFETY_RULES.phone = {title: "Telefon kullanımı", min: 10, max: 600, def: 60}`; `ALARM_LABELS.phone`; `defaultSafetyForm().phone = {enabled: false, seconds: "60"}`)
- Modify: `apps/dashboard/src/lib/types.ts` (`AlarmKind` + `"phone"`, `JobOptions.safety.phone`)
- Modify: `apps/dashboard/src/components/video/UploadCard.tsx` (güvenlik kural satırları `SAFETY_RULES`'tan geliyorsa otomatik; değilse üçüncü satır)
- Test: `apps/dashboard/src/lib/safetyAlarms.test.mjs`, `apps/dashboard/e2e/safety-ui.spec.ts`, `apps/dashboard/e2e/video-analysis.spec.ts`

- [ ] **Step 1: Testler**
  - `safetyAlarms.test.mjs`: varsayılan formda `phone` kapalı ve `safetyOptions` çıktısı `phone: {enabled: false}`; yalnız telefon açık (60) → `{preset: "safety", safety: {handsUp: {enabled:false}, lying: {enabled:false}, phone: {enabled:true, seconds:60}}}`; `"5"` → "Telefon kullanımı süresi 10–600 sn arasında bir sayı olmalı."; `alarmCounts`/`alarmRows` `phone` türünü "Telefon kullanımı" yazar.
  - `safety-ui.spec.ts`: güvenlik kamerasının Ayarla panelinde "Telefon kullanımı" kutusu kapalı gelir; açıp süreyi değiştirince kaydedilen profil `safety.phone = {enabled: true, seconds: N}`; `phone` alanı olmayan kayıtlı profil açılınca kapalı/60 görünür ve kaydetme hatası yok; alarm sayfası tür filtresinde "Telefon kullanımı" var.
  - `video-analysis.spec.ts`: güvenlik ön ayarında telefon satırı görünür, açılınca gönderilen `options.safety.phone` doğru; sonuç tablosunda `phone` alarmı "Telefon kullanımı".
- [ ] **Step 2:** FAIL. **Step 3:** Uygula. **Step 4:** `npm run lint`, `npm test` (node unit), `npx playwright test e2e/safety-ui.spec.ts e2e/video-analysis.spec.ts` (`PYTHON=<edge venv python>`; portlar boş mu bak) → PASS.
- [ ] **Step 5: Commit** — "Telefon alarmı: panel ayarı, alarm türü ve video yükleme formu".

### Task 5: iOS — alanı taşıma

**Files:**
- Modify: `apps/ios/BantSayac/Core/ProductProfile.swift` (`SafetyConfig.phone: Rule = SafetyConfig.defaultPhone`, `defaultPhone = Rule(enabled: false, seconds: 60)`, `CodingKeys` + `phone`, `init(from:)` `decodeIfPresent ?? defaultPhone`; eşlenik başlatıcı `phone` vermeden çalışmaya devam eder)
- Test: `apps/ios/BantSayacTests/SafetyProfileTests.swift`

- [ ] **Step 1: Testler** — `testPhoneMissingDecodesAsOffSixty`; `testPhoneRoundTrips` (`{"phone":{"enabled":true,"seconds":120}}` çöz → kodla → aynı JSON alanı); mevcut testler değişmeden geçer.
- [ ] **Step 2–4:** Uygula; bu makinede Xcode yok → doğrulama CI `ios.yml` (macOS) koşusunda; yerelde yalnız Swift sözdizimi gözle ve mevcut test kalıbıyla tutarlılık.
- [ ] **Step 5: Commit** — "Telefon alarmı: iOS profil alanını taşır".

### Task 6: Ölçüm aracı ve belgeler

**Files:**
- Modify: `tools/eval_pose.py` (`KINDS = ("hands_up", "lying", "phone")`, `NAMES["phone"] = "Telefon kullanımı"`, etiket biçimi metni, tür başına sayaçlar `KINDS`'ten türetilir, süre tablosu `phone` dahil)
- Modify: `tools/tests/test_eval_pose.py`
- Modify: `docs/03-algorithm.md` (§4.11'e "Telefon kullanımı" alt bölümü: kırpıntı araması, isabet, dilimli kanıt penceresi, sabitler, ofis fizibilite ölçümü, sınırlar: kulakta konuşma, uzak kamera)
- Modify: `docs/13-web-platform.md` (Güvenlik alarmı ve Video ile test: üçüncü kural, aralık, varsayılan kapalı, KVKK notu)
- Modify: `docs/12-durum.md` (yeni madde: telefon alarmı yazılımı; doğruluk ölçümü kullanıcı kayıtlarıyla bekliyor)

- [ ] **Step 1: Test** — `test_eval_pose.py`: `"type": "phone"` etiketi kabul edilir, telefon alarmı aynı türde yakalanmış sayılır; bilinmeyen tür hâlâ girdi hatası (çıkış 2).
- [ ] **Step 2–4:** Uygula; `pytest -q tools/tests/test_eval_pose.py` (edge ortamıyla) → PASS; belgelerde yol/IP/cihaz modeli yok.
- [ ] **Step 5: Commit** — "Telefon alarmı: ölçüm aracı ve belgeler".

### Son doğrulama (tüm dal)
- `cd services/edge && pytest -q` (tam), `ruff check . ../../tools`, `pytest -q ../../tools/tests` ; panel `npm run lint && npm test && npx playwright test` (tam e2e); iOS CI.
- Kullanıcının iki ofis kaydıyla duman testi (kayıtlar repoya girmez): `video.py --preset safety --no-hands-up --no-lying --phone 10` ile `tel 2` (24 sn telefon elde) ve `tel 1` (kulakta konuşma, 15 sn) işlenir; sonuç kullanıcıya raporlanır (kabul kapısı değil — kapı, ek kayıtlarla `eval_pose` ölçümüdür). `tel 1` için alarm beklenmez (belgelenmiş sınır).
