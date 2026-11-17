# Alarm penceresi yenileme — uygulama planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Alarm penceresini önem düzeyine göre ikiye ayırmak (kritik: ortada büyük pencere; telefon uyarısı: köşe kartı) ve
ikisinde de canlı görüntü + alarm anının yakın planı + alarm kaydı göstermek.

**Architecture:** Edge alarm kaydına tetikleyen kutu (`box`) eklenir. Panelde saf mantık `src/lib/alarmPopup.mjs`'te
(düğüm testleriyle), görünüm üç bileşende: ortak `AlarmMedia` (canlı/kayıt/köşe penceresi), yenilenen `AlarmViewer`
(ortadaki pencere + liste), yeni `AlarmToast` (köşe kartları). `AlarmCenter` hangi alarmın nerede görüneceğine karar
verir; `AlarmBanner` ince sayaç çubuğu olur.

**Tech Stack:** Python 3.11 / FastAPI (edge), Next.js 15 + React 19 + Tailwind 4 (panel), `node --test`, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-17-alarm-penceresi-design.md`

## Global Constraints

- Kullanıcıya görünen metinler Türkçe; kod tanımlayıcıları İngilizce. Yeni bağımlılık yok.
- Korunan test adları: `alarm-modal`, `alarm-title`, `alarm-time`, `alarm-video`, `clip-caption`, `alarm-timeline`,
  `alarm-status`, `alarm-state`, `alarm-counter` (dar ekranda ‹ › ile), `alarm-banner`, `alarm-feed-warning`, `watch-warning`.
- Ortadaki pencere yerel `<dialog>` + `showModal()` olarak kalır; Esc = Küçült, asla onay değil; odak "Gördüm"de.
- Türler: kritik = `fire`, `smoke`, `hands_up`, `lying`, `test`; uyarı = `phone`.
- Renkler: yangın/duman `#e2531f` (yeni belirteç `--color-fire-600`), kişi alarmları `nok-600` (#d93a4a), telefon
  `#d89a1e` üstünde koyu yazı `#2b1d00` (yeni `--color-alert-warn` / `--color-alert-warn-ink`), deneme `#4a5f7d`
  (yeni `--color-alert-test`).
- Yalnız gösterilen alarm canlı akar; liste satırları ve küçük kart olay resmi küçüğü kullanır.
- Edge testleri: worktree'nin `services/edge` klasöründen ana venv'in python'u ile `PYTHONPATH=.` (venv'e kurulum yok).
- Portlar: 3000 ve 8090'a dokunulmaz; Playwright'ın ortak portları (3100, 3101, 3102, 3118, 8091, 8092, 8098) boş mu
  bakılır, dolu süreç öldürülmez.
- Kullanıcı videoları ve dosya adları commit'e ve dokümana girmez.
- Commit sonu: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Oturumu ve kaynağı olmayan alarm (Bildirimler sayfasındaki deneme alarmı: `sessionId: null`, `sourceId: null`):
   pencere "Alarm kaydı"nda açılmalı, "Canlı" devre dışı, kırık `<img>` yok. → Task 3 testi.
2. Canlı akış hata verir (404/kopma): "Canlı görüntü alınamıyor" yazmalı, "Alarm kaydı"na geçiş çalışmalı. → Task 3 testi.
3. `box` alanı olmayan eski kayıt ve resmi olmayan alarm: köşe penceresi resmin tamamını gösterir / hiç çıkmaz. → Task 2 ve 3 testleri.
4. Pencere küçültülmüşken yalnız uyarı gelir → köşe kartı çıkar, pencere açılmaz; kart açıkken kritik gelir → pencere
   açılır, kartlar gizlenir. → Task 4 testi.
5. Köşe kartında "Gördüm" kaydedilemez → kartta hata iletisi, alarm kalır. → Task 4 testi.

---

### Task 1: Edge — alarm kaydında `box`

**Files:**
- Modify: `services/edge/bantvision/live/alarms.py` (`_DEFAULTS`, `_record`, `add`)
- Modify: `services/edge/bantvision/live/api.py` (`_register` içindeki `self.alarms.add(...)` çağrısı)
- Modify: `docs/13-web-platform.md` (alarm kaydı satırı ~205 ve alan listesi ~219)
- Test: `services/edge/tests/test_alarms.py`, `services/edge/tests/test_live.py` ya da `test_live_fire.py` (hangisi
  `on_alarm` ile kayıt üretiyorsa)

**Interfaces:**
- Produces: alarm kaydında `"box": [x1, y1, x2, y2] | None` (normalize float, 4 basamağa yuvarlanmış);
  `AlarmLog.add(..., box: Sequence[float] | None = None)`.

- [ ] **Step 1: Failing tests** — `test_alarm_record_keeps_trigger_box`: `add(..., box=(0.1, 0.2, 0.3, 0.4))` →
  `get(id)["box"] == [0.1, 0.2, 0.3, 0.4]`; `box` verilmeyince `None`. `test_old_alarm_record_without_box_reads_none`:
  diske `box`'sız kayıt yazılır, yeniden açılınca `box is None`. `test_invalid_box_is_none`: `[0.5, 0.5, 0.4, 0.6]`
  (x2 ≤ x1), `[0, 0, 1]`, `[-0.1, 0, 0.5, 0.5]`, `["a", 0, 1, 1]` diskten okununca `None`.
  `on_alarm` yolu: sahte `SafetyAlarm`/`FireAlarm` (`box=(0.25, 0.25, 0.5, 0.75)`) ile doğan kaydın `box`'ı aynı değer.
- [ ] **Step 2:** `PYTHONPATH=. <ana venv python> -m pytest tests/test_alarms.py -q` → yeni testler FAIL.
- [ ] **Step 3:** `add`'e `box` parametresi; `_record` doğrular (4 sonlu sayı, 0 ≤ x1 < x2 ≤ 1, 0 ≤ y1 < y2 ≤ 1, değilse
  `None`); `_register` `box=getattr(a, "box", None)` geçer. Deneme alarmı (`api.py` ~1740) `box` vermez.
- [ ] **Step 4:** Edge'in tüm testleri: `PYTHONPATH=. <ana venv python> -m pytest -q` → PASS; `ruff check .` temiz.
- [ ] **Step 5:** Docs satırlarına `box` (alarmı tetikleyen kutu, normalize `[x1, y1, x2, y2]`; deneme alarmında ve eski
  kayıtlarda `null`). Commit: "Alarm kaydında tetikleyen kutu (box)".

### Task 2: Panel — saf mantık `alarmPopup.mjs`

**Files:**
- Create: `apps/dashboard/src/lib/alarmPopup.mjs`, `alarmPopup.d.mts`, `alarmPopup.test.mjs`
- Modify: `apps/dashboard/package.json` (`test:unit` listesine `src/lib/alarmPopup.test.mjs`)
- Modify: `apps/dashboard/src/lib/live.ts` (`Alarm` arayüzüne `box?: [number, number, number, number] | null`)

**Interfaces (Produces):**
- `alarmSeverity(type: string): "critical" | "warning"` — `phone` → `"warning"`, diğer her şey `"critical"`.
- `sortAlarms<T extends {type: string; firedAt: number}>(list: T[]): T[]` — yeni dizi; önce kritikler, grup içinde
  `firedAt` büyükten küçüğe; eşitlikte giriş sırası korunur.
- `liveStreamUrl(a: {sessionId: string|null; sourceId?: string|null; channelId?: string|null}, liveSessionIds: ReadonlySet<string>): string | null`
  — oturum `liveSessionIds`'te ise `/api/live/sessions/${encodeURIComponent(id)}/stream`; değilse `sourceId` varsa
  `/api/live/cameras/stream?source=<sourceId>&quality=sub` (+ `&channel=<channelId>` varsa; `URLSearchParams` sırası:
  source, channel, quality); yoksa `null`.
- `insetCrop(box: unknown): {scale: number; left: number; top: number} | null` — geçersiz/yoksa `null`.
  `bw = x2−x1`, `bh = y2−y1`, `scale = clamp(1 / (1.6 · max(bw, bh)), 1, 4)`, `left = clamp((0.5 − cx·scale)·100, (1−scale)·100, 0)`,
  `top` aynı biçimde `cy` ile (yüzde; görüntü `width/height = scale·100%`, `left/top` bu yüzdeler).
  Kayan nokta gürültüsüne karşı sonuç yuvarlanır: `scale` 3 basamak, `left`/`top` 2 basamak (`-0` → `0`).
- `insetSide(box: unknown): "left" | "right"` — geçerli kutunun merkezi `cx > 0.5` → `"left"`, değilse `"right"`.
- `agoText(seconds: number): string` — negatif 0 sayılır; `< 60` → `"N sn önce"`, `< 3600` → `"N dk önce"`
  (aşağı yuvarlanmış), değilse `"N sa önce"`.

- [ ] **Step 1: Failing tests** (`alarmPopup.test.mjs`, `node:test` + `assert/strict`):
  - `alarmSeverity("phone") === "warning"`; `fire`, `smoke`, `hands_up`, `lying`, `test` → `"critical"`.
  - `sortAlarms` girdisi `[phone@300, fire@100, lying@200, phone@400]` → `[lying@200, fire@100, phone@400, phone@300]`;
    girdi dizisi değişmez.
  - `liveStreamUrl({sessionId:"s1", sourceId:"r1", channelId:"c2"}, new Set(["s1"])) === "/api/live/sessions/s1/stream"`;
    aynı alarm boş kümeyle → `"/api/live/cameras/stream?source=r1&channel=c2&quality=sub"`; `{sessionId:"s1"}` boş
    kümeyle ve kaynaksız → `null`; `{sessionId:null, sourceId:null}` → `null`.
  - `insetCrop([0.4,0.4,0.6,0.6])` → `{scale:3.125, left:-106.25, top:-106.25}`;
    `insetCrop([0.9,0.1,1.0,0.2])` → `{scale:4, left:-300, top:-10}`;
    `insetCrop([0,0,1,1])` → `{scale:1, left:0, top:0}`;
    `insetCrop(null)`, `insetCrop([0.5,0.5,0.4,0.6])`, `insetCrop([0,0,1])`, `insetCrop(["a",0,1,1])` → `null`.
  - `insetSide([0.6,0,0.9,0.5]) === "left"`, `insetSide([0.1,0,0.3,0.5]) === "right"`, `insetSide(null) === "right"`.
  - `agoText(-5) === "0 sn önce"`, `agoText(38) === "38 sn önce"`, `agoText(60) === "1 dk önce"`,
    `agoText(599) === "9 dk önce"`, `agoText(7200) === "2 sa önce"`.
- [ ] **Step 2:** `cd apps/dashboard && node --test src/lib/alarmPopup.test.mjs` → FAIL (modül yok).
- [ ] **Step 3:** Uygula; `.d.mts` tipleri yukarıdaki imzalar.
- [ ] **Step 4:** `npm run test:unit` ve `npm run typecheck` → PASS.
- [ ] **Step 5:** Commit: "Alarm penceresi için saf yardımcılar".

### Task 3: Ortadaki pencere — `AlarmMedia` + yenilenen `AlarmViewer`

**Files:**
- Create: `apps/dashboard/src/components/live/AlarmMedia.tsx`
- Modify: `apps/dashboard/src/components/live/AlarmViewer.tsx`, `apps/dashboard/src/app/globals.css` (renk belirteçleri)
- Modify: `apps/dashboard/src/components/live/AlarmCenter.tsx` (yalnız: `alarms`'ı `sortAlarms` ile sıralamak ve
  `AlarmViewer`'a `liveSessionIds` geçmek)
- Modify: `apps/dashboard/src/components/live/SafetyPanel.tsx` ve Alarmlar sayfası (`AlarmsView.tsx`) — `browse` kipinde
  yeni prop'lar
- Test: `apps/dashboard/e2e/alarm-popup.spec.ts` (yeni), `safety-ui.spec.ts` / `fire-ui.spec.ts` (gerekirse güncelle)
- Docs: `docs/13-web-platform.md` "Alarm penceresi" maddesi (~237–242)

**Interfaces:**
- Consumes: Task 2'nin tümü; `Alarm.box`.
- Produces:
  - `AlarmMedia` props: `{ alarm: Alarm; liveUrl: string | null; initial: "live" | "clip"; size: "large" | "compact" }`;
    görüntü alanını, "● Canlı | Alarm kaydı" düğmelerini (`data-testid="media-live"` / `"media-clip"`,
    `aria-pressed`), canlı `<img data-testid="alarm-live">`, köşe penceresini (`<button data-testid="alarm-inset">`,
    `data-side="left|right"`) ve hata yazısını (`data-testid="live-error"`, metin "Canlı görüntü alınamıyor") çizer.
    "Alarm kaydı" içeriği bugünkü `AlarmViewer` video/resim/`clip-caption`/`alarm-timeline` mantığının buraya taşınmış
    hâlidir. `liveUrl === null` → başlangıç "clip", "Canlı" düğmesi `disabled` ve `title="Canlı görüntü yok"`.
    Canlı akışa yeniden bağlanma için `useStreamKey` (`components/watch/useStreamKey.ts`) kullanılır.
  - `AlarmViewer` yeni prop: `liveSessionIds: ReadonlySet<string>` (zorunlu). Etkin kipte ve `alarms.length > 1` iken
    sağda liste `<ul data-testid="alarm-queue">`, her satır `<button data-testid="queue-item" aria-current>`.
  - `alarmSeverity` sonucuna göre başlık rengi sınıfı ve kök öğede `data-severity="critical|warning"`,
    `data-kind=<type>`.

- [ ] **Step 1: Failing e2e** (`alarm-popup.spec.ts`; alarmlar `page.route(/\/api\/live\/alarms\?active=1$/)`,
  oturumlar `**/api/live/sessions`, akış `**/api/live/sessions/abc123/stream*` GIF ile — `safety-ui.spec.ts`'teki
  `fakeSession`/`GIF` kalıbı):
  - `critical alarm opens centre window on live view with alarm-moment inset`: `fire` alarmı, oturum canlı,
    `box: [0.6,0.5,0.8,0.9]`, `image: true` → `alarm-modal` görünür, `media-live` `aria-pressed=true`, `alarm-live`
    `src` `/api/live/sessions/abc123/stream` içerir, `alarm-inset` `data-side="left"`; inset'e tıklayınca `media-clip`
    basılı ve `alarm-video` (ya da `clip-caption`) görünür.
  - `alarm without live source opens on clip and disables live`: `test` türü, `sessionId: null`, `sourceId: null` →
    `media-clip` basılı, `media-live` disabled, sayfada `alarm-live` yok.
  - `broken live stream shows error and clip still works`: akış rotası 404 → `live-error` görünür; `media-clip`
    tıklanınca kayıt alanı görünür.
  - `old record without box shows whole image; no image no inset`: `box` alanı yok + `image: true` → `alarm-inset`
    görünür; `image: false` → `alarm-inset` yok.
  - `queue lists critical first and selects on click`: `phone` (firedAt en yeni), `fire` (lying'den yeni), `lying` →
    `queue-item` sırası fire/lying/phone; ikinciye tıklayınca `alarm-title` "YERDE YATAN KİŞİ".
- [ ] **Step 2:** Port kontrolünden sonra `npm run build` ve `PYTHON=<ana venv python> npx playwright test e2e/alarm-popup.spec.ts` → FAIL.
- [ ] **Step 3:** `AlarmMedia`'yı yaz, `AlarmViewer`'ı yenile (başlık rengi, bilgi satırı Kamera/Saat/Geçen süre
  (`agoText`, saniyede bir)/Bildirim, liste, dar ekranda ‹ ›), `browse` kipinde `initial="clip"`, etkin kipte
  `liveUrl ? "live" : "clip"`. `AlarmCenter` `sortAlarms` uygular ve `liveSessionIds`'i `sessions`'tan üretir.
- [ ] **Step 4:** `alarm-popup.spec.ts`, `safety-ui.spec.ts`, `fire-ui.spec.ts`, `watch-ui.spec.ts`, `shell.spec.ts`
  → PASS; `npm run lint`, `npm run typecheck`, `npm run test:unit` temiz.
- [ ] **Step 5:** Docs güncellemesi; commit: "Alarm penceresi: canlı görüntü, alarm anı yakın planı ve alarm listesi".

### Task 4: Köşe kartları, yönlendirme, ince çubuk ve ekran kenarı

**Files:**
- Create: `apps/dashboard/src/components/live/AlarmToast.tsx`
- Modify: `apps/dashboard/src/components/live/AlarmCenter.tsx`, `AlarmBanner.tsx`
- Test: `apps/dashboard/e2e/alarm-popup.spec.ts` (ekle), `safety-ui.spec.ts` (şerit beklentileri değiştiyse)
- Docs: `docs/13-web-platform.md` (alarm şeridi ve pencere maddeleri)

**Interfaces:**
- Consumes: Task 2 (`alarmSeverity`, `agoText`, `liveStreamUrl`), Task 3 (`AlarmMedia` with `size="compact"`; `AlarmIcon({ type, className })` SVG simgeleri — emoji yok).
- Produces:
  - `AlarmToast` props: `{ warnings: Alarm[]; liveSessionIds: ReadonlySet<string>; onAck: (a: Alarm) => Promise<boolean>;
    onFalseAlarm: (a: Alarm) => Promise<boolean>; onHide: (id: string) => void; onOpenAll: (id: string) => void }`.
    Kök `<section data-testid="alarm-toasts" aria-live="assertive">`; kart `data-testid="alarm-toast"` (ilk tam,
    ikinci `data-compact="true"`), "+N uyarı daha" `data-testid="toast-more"`, kart hatası `data-testid="toast-error"`
    ("Gördüm kaydedilemedi; alarm açık kalıyor. Tekrar deneyin.").
  - `AlarmCenter`: `hidden: Set<string>` (× ile gizlenen uyarılar, oturumluk); yeni alarm kuralı: taze alarmlar
    arasında kritik varsa pencere en yeni taze kritikte açılır, yoksa açılmaz. Köşe kartları yalnız pencere kapalıyken
    çizilir; gizlenmemiş uyarılar gösterilir. Kritik onaylanmamış alarm varken `<div data-testid="alarm-edge">`
    (sabit, tıklanamaz, `motion-safe:animate-…`).
  - `AlarmBanner`: sayaç çubuğu — `data-testid="alarm-count-critical"` ("N kritik alarm"),
    `data-testid="alarm-count-warning"` ("N uyarı"), "Son: <ALARM_LABELS> — <kamera>", düğme "Alarmları göster"
    (`open(alarms[0].id)`). Akış uyarısı, izlenmeyen kamera satırları ve "Gördüm kaydedilemedi" aynen.
- [ ] **Step 1: Failing e2e:**
  - `phone alarm shows corner card without modal`: yalnız `phone` → `alarm-toast` görünür, `alarm-modal` yok,
    `alarm-count-warning` "1 uyarı"; karttaki "Gördüm" ack isteği atar ve kart kaybolur.
  - `critical arrives while card shown opens window and hides cards`: önce `phone`, sonra listeye `smoke` eklenir →
    `alarm-modal` görünür, `alarm-toasts` içinde kart yok; "Küçült" → kart geri gelir, `alarm-edge` görünür.
  - `minimized window plus new warning shows card only`: `fire` açılır, Küçült, sonra `phone` gelir → `alarm-modal`
    kapalı kalır, `alarm-toast` görünür.
  - `card hide keeps alarm in bar`: × → kart gizlenir, `alarm-count-warning` hâlâ "1 uyarı"; "Alarmları göster" →
    `alarm-modal` açılır.
  - `ack failure on card shows error`: ack rotası 500 → `toast-error` görünür, kart kalır.
  - `three warnings show two cards and more`: 3 `phone` → 2 `alarm-toast` (ikincisi `data-compact="true"`),
    `toast-more` "+1 uyarı daha"; tıklayınca `alarm-modal`.
- [ ] **Step 2:** build + bu spec → FAIL.
- [ ] **Step 3:** Uygula.
- [ ] **Step 4:** Bütün panel e2e (`npx playwright test`), `lint`, `typecheck`, `test:unit` → PASS.
- [ ] **Step 5:** Docs; commit: "Telefon uyarısı köşe kartında; ince alarm çubuğu ve ekran kenarı".

### Task 5: Kişi üstü etiket (poz güvenlik çizimi)

**Files:**
- Modify: `services/edge/bantvision/overlay.py` (`draw_safety` ve yeni saf yardımcı)
- Test: `services/edge/tests/test_overlay_safety.py` (yeni)
- Docs: `docs/03-algorithm.md` ve `docs/13-web-platform.md`'de poz güvenlik canlı görüntü/olay kaydı çizimini anlatan
  yerler ("iskelet ve alarmlı kırmızı kutu" geçen cümleler)

**Interfaces:**
- Consumes: `SafetyResult` (`tracks`, `active: (iz, tür, süre sn, alarm verdi mi)`, `boxes`, `poses`), `Profile.safety`
  (`handsUp` / `lying` / `phone`: `SafetyRule(enabled, seconds)`).
- Produces: `SafetyTag` (dataclass: `box: tuple[float, float, float, float]` normalize, `state: "person" | "counting" | "alarm"`,
  `text: str`, `progress: float | None`) ve `safety_tags(profile: Profile, r: SafetyResult) -> list[SafetyTag]`
  (çizim sırası: önce `person`, sonra `counting`, en son `alarm`); `draw_safety` bunları çizer.
  Renkler (BGR): person `(170, 170, 170)` 1 px, counting `(30, 190, 245)` kalın, alarm `RED` daha kalın; etiket zemini
  kutu rengi, yazı counting/person'da koyu `(20, 20, 20)`, alarmda beyaz.

- [ ] **Step 1: Failing tests** (`safety_tags` üzerinde; çizim için yalnız duman testi):
  - `test_observed_person_gets_person_tag`: tek iz, `active` boş → `[SafetyTag(box, "person", "Kişi", None)]`.
  - `test_more_than_six_people_drop_person_text`: 7 iz → 7 `person` etiketi, hepsinin `text == ""`.
  - `test_counting_phone_shows_seconds_and_progress`: telefon kuralı açık 15 sn, `active=[(1, "phone", 9.7, False)]` →
    iz 1 için `SafetyTag(box, "counting", "TELEFON 9 / 15 sn", 9.7/15)` (yuvarlama `progress` için yok; `person`
    etiketi o iz için çıkmaz).
  - `test_counting_picks_rule_closest_to_firing`: aynı izde `hands_up` 1.0/3 ve `phone` 12/15 → yalnız telefon etiketi.
  - `test_fired_alarm_shows_duration`: `active=[(1, "phone", 81.2, True)]` → `"TELEFON · ALARM 1:21"`, state `alarm`,
    `progress None`; iz bu karede gözlenmese de `r.boxes[1]` ile etiket var.
  - `test_disabled_rule_not_counted`: kural kapalıyken `active`'te sayan bölüm → `counting` yok, yalnız `person`.
  - `test_labels_are_turkish`: `hands_up` → "ELLER YUKARI", `lying` → "YERDE"; süre `3.0` → "3 sn" (ondalık yok).
  - `test_draw_safety_smoke`: 640×360 siyah kare, sayan + alarmlı iz → çizim hata vermez, kutu kenarındaki piksel
    rengi beklenen BGR.
- [ ] **Step 2:** `PYTHONPATH=. <ana venv python> -m pytest tests/test_overlay_safety.py -q` → FAIL.
- [ ] **Step 3:** `safety_tags` + `draw_safety` (etiket kutunun üstüne sığmazsa içine; süre çubuğu yalnız counting'de).
  İskelet çizimi aynen kalır. `test_clips.py`'deki `draw_safety` beklentileri değişirse güncelle.
- [ ] **Step 4:** Edge'in tüm testleri ve `ruff check .` → PASS.
- [ ] **Step 5:** Docs; commit: "Poz güvenlik çiziminde kişi üstü etiket: Kişi, süre doluyor, alarm".

### Task 6: Güvenlik analiz alanları — sözleşme, edge, iPhone

**Files:**
- Modify: `contracts/product-profile.schema.json` (`safety.areas`), `docs/02-contracts.md` (`safety` satırı: "alan
  kısıtı yoktur" cümlesi değişir)
- Modify: `services/edge/bantvision/core/profile.py` (`SafetyArea`, `SafetyConfig.areas`, okuma/doğrulama/yazma),
  `services/edge/bantvision/core/safety.py` (alan süzgeci, kural başına), `services/edge/bantvision/overlay.py`
  (alanların çizimi), `services/edge/bantvision/live/alarms.py` + `live/api.py` (alarm kaydında `area`; Telegram metni)
- Modify: `apps/ios/BantSayac/Core/ProductProfile.swift` (`SafetyConfig.areas`, `decodeIfPresent ?? []`),
  `apps/ios/BantSayacTests/` (yangındaki `FireProfileTests` kalıbıyla gidiş-dönüş testi)
- Test: `services/edge/tests/test_safety.py`, `test_overlay_safety.py`, `test_alarms.py`, profil/sözleşme testleri
- Docs: `docs/03-algorithm.md` poz güvenlik bölümü, `docs/13-web-platform.md` (güvenlik bölümü, alarm kaydı alanları)

**Interfaces:**
- Consumes: Task 5 (`safety_tags`, `draw_safety`), Task 1 (`AlarmLog.add`).
- Produces:
  - `SafetyArea` dataclass `{name: str, points: list[tuple[float, float]], rules: list[str]}`;
    `SafetyConfig.areas: list[SafetyArea]` (varsayılan `[]`); JSON `"areas": [{"name", "points": [[x, y], …], "rules": [...]}]`,
    boşsa yazılmaz. Sınırlar: en çok 16 alan, ad 1–40 karakter (kırpılmış), 3–12 köşe 0–1 aralığında, `rules`
    boş olmayan ve yalnız `handsUp`/`lying`/`phone`; aykırısı profil okunurken hata (canlı API `422`, mevcut kalıp).
  - `area_rules(box, areas) -> tuple[set[str], dict[str, str]] | None` — alan yoksa `None` (her şey serbest); varsa
    (kutu merkezinin içinde olduğu alanların kural birleşimi, kural → ilk eşleşen alan adı). Kural adları sözleşmedeki
    (`handsUp`, `lying`, `phone`); `SafetyAlarm.kind` eşlemesi (`hands_up` ↔ `handsUp`) tek yerde.
  - `SafetyAlarm.area: str | None`; alarm kaydında `"area": str | None` (`AlarmLog.add(..., area=None)`, eski kayıtta
    `None`).

- [ ] **Step 1: Failing tests:** profil gidiş-dönüşü (alanlar korunur; boşsa JSON'da yok); geçersiz alanlar reddedilir
  (2 köşe, 13 köşe, 1.2 koordinat, 17 alan, boş ad, 41 karakter ad, boş `rules`, bilinmeyen kural); `area_rules`
  (merkez içeride/dışarıda/iki alanın kesişiminde, alan yok → `None`); güvenlik analizinde: alan dışındaki kişi süre
  biriktirmez ve alarm üretmez; `rules: ["phone"]` olan alandaki kişi telefon alarmı üretir ama eller yukarı
  üretmez; alarmın `area`'sı doğru ad; alarm kaydı `area` saklar ve eski kayıtta `None`; Telegram metni alan adını
  içerir; `safety_tags`/`draw_safety` alan dışındaki kişiye etiket/iskelet çizmez, alanı mavi çizer ve etiketi "<ad>: <alan içindeki kişi sayısı>" (ör. "Masa 3: 1"; kişinin kutu merkezi alanın içindeyse sayılır). İçinde alarmı süren (state alarm) kişi olan alan kalın kırmızı çizilir — test: `test_area_with_active_alarm_drawn_red`.
- [ ] **Step 2:** testler FAIL.
- [ ] **Step 3:** Uygula. Süzgeç iz eşlemeden sonra, kurallardan önce: hiçbir alanda olmayan iz `SafetyResult.tracks`/
  `poses`'a girmez; alandaki iz için yalnız izinli kurallar işletilir (izinli olmayan kuralın bölümü biter).
- [ ] **Step 4:** Edge'in tüm testleri, `ruff`; sözleşme şemasını doğrulayan test(ler) PASS. Swift bu bilgisayarda
  derlenemez: kalıbı birebir izle ve raporda belirt.
- [ ] **Step 5:** Docs; commit: "Güvenlik analiz alanları: alan başına kurallar, alarmda alan adı".

### Task 7: Panelde "Analiz alanları" ve alarmda alan adı

**Files:**
- Modify: `apps/dashboard/src/components/live/LiveView.tsx` (güvenlik taslağında `ZonesEditor` + alan listesi), panelin
  profil tipleri (`safety` bloğu), güvenlik ayar paneli (kuralların düzenlendiği yer), `src/lib/live.ts`
  (`Alarm.area?: string | null`), `AlarmViewer.tsx` bilgi satırı ve `AlarmToast.tsx` ("Alan: <ad>", yalnız `area` varken)
- Test: `apps/dashboard/e2e/safety-ui.spec.ts`, `alarm-popup.spec.ts` (ekle)
- Docs: `docs/13-web-platform.md`

**Interfaces:**
- Consumes: Task 6 (`safety.areas` JSON, `Alarm.area`), `ZonesEditor` (`{src, aspect, zones, onChange, editable}`;
  çokgenler `number[][][]`), Task 3/4 bileşenleri.
- Produces: güvenlik kamerasında "Ayarla" açıkken görüntü üstünde çokgen düzenleyici ve "Analiz alanları" listesi
  (`data-testid="safety-area"` satırlar: ad kutusu, `handsUp`/`lying`/`phone` kutucukları — yalnız kamerada açık
  kurallar seçilebilir —, "Sil"); en çok 16 alan (16'da "Alan ekle" devre dışı); yeni alan "Alan N" ve açık
  kurallarla; açıklama "Boş bırakırsanız bütün görüntü izlenir."; değişiklik `PUT sessions/{id}/profile` ile.

- [ ] **Step 1: Failing e2e:** güvenlik oturumunda Ayarla → "Analiz alanları"; çokgen eklenince profil isteğinde
  `safety.areas[0]` = `{name: "Alan 1", points: […], rules: [açık kurallar]}`; ad değiştirilip bir kural kaldırılınca
  istek güncel; 16 alanda ekleme kapalı; kaydedilmiş alanlı profil açılınca alanlar listede; `/live?tur=telefon`
  oturumunda da aynı; `area: "Masa 3"` olan alarmda pencerede ve köşe kartında "Alan: Masa 3", `area: null`'da satır yok.
- [ ] **Step 2:** build + spec → FAIL.
- [ ] **Step 3:** Uygula (yangındaki hariç bölge akışının kalıbı).
- [ ] **Step 4:** panel e2e (`safety-ui`, `phone-menu`, `fire-ui`, `alarm-popup`), `lint`, `typecheck`, `test:unit` → PASS.
- [ ] **Step 5:** Docs; commit: "Panelde güvenlik analiz alanları ve alarmda alan adı".

### Task 8: Alarm sesleri (10 ses, tür grubuna göre seçim)

**Files:**
- Create: `tools/make_alarm_sounds.py` (numpy + `wave`; deterministik), `apps/dashboard/public/sounds/alarm-01.wav` …
  `alarm-10.wav` (betiğin çıktısı, commit edilir), `apps/dashboard/src/lib/alarmSounds.mjs` + `.d.mts` + `.test.mjs`
- Modify: `apps/dashboard/src/lib/attention.ts` (ses seçimi/düzeyi çerezleri), `components/live/AttentionSettings.tsx`
  (seçim, Dinle, düzey), `components/live/AlarmCenter.tsx` (çalma kuralları), `components/live/AlarmBanner.tsx`
  (engellendi uyarısı), `package.json` (`test:unit`)
- Test: `services/edge/tests/test_alarm_sounds.py` ya da `tools` testi (betik 10 geçerli WAV üretir, aynı girdiyle aynı
  baytlar), `alarmSounds.test.mjs`, `apps/dashboard/e2e/alarm-popup.spec.ts` (ekle)
- Docs: `docs/13-web-platform.md` (Bildirimler / dikkat çekme maddesi)

**Interfaces:**
- Consumes: Task 2 (`alarmSeverity`), Task 4 (pencere açık/küçük durumu `AlarmCenter`'da).
- Produces:
  - `SOUNDS: ReadonlyArray<{id: string; name: string; file: string}>` — 10 kayıt, `id` `"alarm-01"`…`"alarm-10"`, adlar
    spec'teki sırayla, `file` `/sounds/alarm-NN.wav`.
  - `soundGroup(type: string): "fire" | "person" | "phone"` — `fire`/`smoke` → fire, `phone` → phone, diğerleri person.
  - `DEFAULT_SOUND: Record<"fire"|"person"|"phone", string>` = `{fire: "alarm-02", person: "alarm-03", phone: "alarm-01"}`;
    `DEFAULT_VOLUME = 0.8`.
  - `attention.ts`: `readSound(group) -> string` (geçersiz/eksik → varsayılan), `writeSound(group, id)`,
    `readVolume() -> number` (0–1, geçersiz → 0.8), `writeVolume(v)`; `playAlarmSound(id, volume) -> Promise<boolean>`
    (`HTMLAudioElement`; engellenirse `false`).
- [ ] **Step 1: Failing tests:** betik: 10 dosya, her biri RIFF/WAVE, 22050 Hz, mono, 16 bit, 1.0–2.0 sn, iki çalıştırma
  aynı baytlar; `soundGroup` eşlemesi; `SOUNDS` 10 benzersiz id/ad; e2e: ayarlarda üç seçim ve "Dinle" (ses isteği
  `/sounds/alarm-02.wav` gider), seçim değişince çerez güncellenir; "Sesli uyarı" açıkken kritik alarm gelince
  seçilen grubun dosyası istenir ve 3 sn sonra yeniden istenir, "Gördüm" sonrası istenmez; telefon uyarısında tek
  istek; ses kapalıyken hiç istek yok; `play()` reddedilince (`page.addInitScript` ile `HTMLMediaElement.prototype.play`
  reddeden sahte) üst çubukta "Alarm sesi için sayfaya bir kez tıklayın".
- [ ] **Step 2:** testler FAIL.
- [ ] **Step 3:** Uygula; WAV'ları betikle üret ve commit et.
- [ ] **Step 4:** panel e2e tamamı, `lint`, `typecheck`, `test:unit`; betik testi PASS.
- [ ] **Step 5:** Docs; commit: "Alarm sesleri: 10 ses, tür grubuna göre seçim, kritik alarmda tekrar".

