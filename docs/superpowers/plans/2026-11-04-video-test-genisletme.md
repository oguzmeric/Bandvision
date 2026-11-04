# Video ile test: güvenlik alarmı (poz), araç ve hayvan sayımı — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add three analyses to "Video ile test" that today run only live or only from the command line:
- **Güvenlik alarmı (poz):** hands up and person lying on the floor.
- **Araç sayımı.**
- **Hayvan sayımı.**

The user can then test with their own recordings every analysis the product sells.

**Why:** the user wants every analysis to be testable with video and does not want half-done work ("mantıken bunlarıda test etmemiz gerekmez mi ? yarım yamalak iş yapma.", 2026-11-04).

**Architecture:**
- **`bantvision.video`:**
  - It gains a `safety` mode built on the same `core.safety.SafetyAnalyzer` the live sessions use, so the same rules and the same code run in both places.
  - It writes an alarm list to `ozet.json`, one JPEG per alarm, and an annotated video with skeletons.
  - Vehicle and animal presets already exist in `video.py` (`PRESETS`). They only need wiring through the contract, the analyzer and the panel.
- **Contract:**
  - `options.preset` gains `vehicle`, `animal` and `safety`.
  - New `options.safety` carries the rules.
  - `result.alarms` holds the alarm list, and `result.files` may contain `alarm-N.jpg`.
- **Panel:**
  - `UploadCard` offers the new presets with the right form.
  - `JobDetail` shows an alarm table; clicking a row seeks the video to that moment.

**Tech stack:** Python 3.11+, FastAPI, OpenCV, numpy, pytest, ruff; Next.js 15, TypeScript, `node --test`, Playwright.

**Spec:** none separate. The user delegated the decisions ("soruları atla, direkt başla" earlier; "yarım yamalak iş yapma" now). The rulings below are the controller's and they are binding.

## Rulings (binding)

**R1. Presets.**
- **Contract:** `options.preset` enum adds `vehicle`, `animal` and `safety`.
- **CLI:** `video.py` `PRESETS` adds `"safety": Profile.jeweler`.
- **Analyzer:**
  - `OptionsIn.preset` adds the three values.
  - `options_to_args` already passes `--preset`.
  - For `safety`, `countMode`, `truth`, `direction`, `line`, `countLine`, `roi`, `roiPolygon`, `bgRange`, `productLength` and `countAnchor` are rejected with `422`. Message: `Güvenlik alarmı videosunda sayım ayarları kullanılmaz.`
  - For non-`safety` presets, `options.safety` is rejected with `422`. Message: `Kural ayarları yalnızca güvenlik alarmı videosunda kullanılır.`
- **vehicle and animal** behave exactly like `people`: two-way detect counting with direction, line and anchor, plus `truth` = entries.

**R2. Safety rules** (`options.safety`).
- **Shape:** `{ "handsUp": {"enabled": bool, "seconds": number}, "lying": {"enabled": bool, "seconds": number} }`. Both keys are optional, and so is the object itself.
- **Defaults** are those of `Profile.jeweler()`: handsUp on, 3 s; lying on, 10 s.
- **Ranges** match the live rules (`live/api.py` `_SAFETY_RULES`): handsUp 3–5 s, lying 5–30 s. Outside the range gives `422`. Both rules disabled gives `422`, message `En az bir kural açık olmalı.`
- **CLI:** `--hands-up SECONDS` / `--no-hands-up` and `--lying SECONDS` / `--no-lying`, validated with the same ranges and Turkish `SystemExit` messages.

**R3. Video safety mode** (`video.py`, new function `count_safety`, alongside `count_detect`).
- **Engine:** build `SafetyAnalyzer(detector=ObjectDetector(), pose=PoseEstimator())`. Both models follow the process default device; Task 2 of the GPU plan gives `--device`.
- **Frame loop:**
  - Process every frame with `ts = frame_index / fps`, i.e. video time.
  - Draw with `overlay.draw_safety`.
  - Honour `--start`/`--end` like `count_detect`.
- **Alarm records:**
  - Each `fired` alarm creates `{kind: "handsUp"|"lying", trackId, startS: round(started, 1), atS: round(ts, 1), endS: null, image}`. Map `hands_up` to `handsUp`.
  - When the matching `ended` episode arrives (same track and kind), set `endS = round(ts, 1)`.
  - At the end of the video, open episodes close with `endS` = video end. Use `SafetyAnalyzer.end_all()`.
- **Images:**
  - Each alarm writes `alarm-<n>.jpg`, n starting at 1: the annotated frame at the moment of firing, 640 px wide, JPEG quality 80.
  - At most 50 images. Alarms after the 50th still go in the list with `image: null`.
  - At most 500 alarms in the list. `count` stays the true total.
- **`ozet.json`:**
  - `count` is the number of alarms, `alarms` is the list, `device` is the detector's `used`, as in Task 2 of the GPU plan.
  - `fps`, `seconds`, `size` and `processingFps` are filled as the other modes do.
- **Progress:** `--progress-json` progress messages are emitted as in `count_detect`, i.e. `{progress, count}`.
- **Outputs:** `sayimlar.csv` is replaced by `alarmlar.csv` (columns `baslangic_sn, alarm_sn, bitis_sn, tur, iz`). `profil.json` is still written.

**R4. Contract** (`contracts/analysis-job.schema.json`, `docs/02-contracts.md`).
- **`options.safety`:** shape as in R2, with min/max per rule.
- **`result.alarms`:** an array, max 500, of `{kind: enum[handsUp, lying], trackId: integer, startS: number ≥0, atS: number ≥0, endS: number|null, image: string matching ^alarm-[0-9]{1,2}\.jpg$ | null}`, `additionalProperties: false`. It is present only for safety jobs.
- **`result.files` items:** `anyOf` [the existing enum + `"alarms.csv"`, `{pattern: "^alarm-[0-9]{1,2}\\.jpg$"}`].
- **Example:** add `contracts/examples/analysis-job-safety-done.json` with two alarms. `tools/validate_contracts.py` must pick it up; check how it discovers examples.

**R5. Analyzer jobs** (`analyzer/jobs.py`).
- `RESULT_FILES` maps `alarmlar.csv` to `alarms.csv`. `alarm-N.jpg` files are moved from `raw` to `out`, keeping their names.
- `PUBLIC_FILES` becomes a check function, `is_public_file(name)`, that accepts the fixed names plus `^alarm-[0-9]{1,2}\.jpg$`. The `GET /jobs/{id}/files/{name}` route serves `image/jpeg` for them.
- `result.alarms` is copied from the summary only when every item is valid in shape; otherwise the job fails with `Sonuç hazırlanamadı: alarm listesi bozuk`. That list is our own output, so a bad shape is a bug.
- `result.count` is the alarm count.

**R6. Panel.**
- **Preset labels:** `PRESET_LABELS` adds `vehicle: "Araç (giriş / çıkış)"`, `animal: "Hayvan (giriş / çıkış)"`, `safety: "Güvenlik alarmı (poz)"`.
- **UploadCard:**
  - vehicle and animal use the people form: two-way, direction, line or geometry, anchor, and "Doğru giriş".
  - safety hides all counting fields: truth, direction, mode, geometry and bgRange. It shows two rule rows, each with a checkbox and a seconds input: `Eller yukarı` (3–5 sn, varsayılan 3) and `Yerde yatan kişi` (5–30 sn, varsayılan 10). Client-side validation uses the same ranges and messages as R2.
  - The help text for safety is: `Videodaki herkese uygulanır; canlıdaki güvenlik kamerasıyla aynı kurallar ve aynı analiz.`
- **JobDetail, safety job:**
  - **Stats:** `Alarm` (count), `İşleme hızı`, `Cihaz`; no Doğruluk or Giriş/Çıkış.
  - **Alarm table:** columns Başlangıç (`mm:ss`), Tür (`Eller yukarı` / `Yerde yatan kişi`), Süre (`endS − startS`, as `N sn`), and Resim (a thumbnail served through the existing job files route).
  - **Row click:** seeks the annotated `<video>` to `startS` and plays it.
  - **Empty list:** shows the text `Bu videoda alarm yok.`
- **Job list:** the kind label shows the preset label for the new presets.
- **Other pages:** check every place that switches on `preset === "people"` for count labels. vehicle and animal get the same two-way display.

**R7. Docs.**
- `docs/13-web-platform.md` "Video ile test" section: the new presets, the rules, the alarm table, and that the same engine as live is used.
- `docs/02-contracts.md`: the schema changes.
- `docs/12-durum.md`: a status line.

## Global constraints
- **Language:** user-visible text in Turkish; identifiers in English; comments match the file, which is Turkish.
- **Python:**
  - Interpreter: `C:/Users/MSI-LAPTOP/bantvision/services/edge/.venv/Scripts/python.exe`, which now has `onnxruntime-directml`. Run it from the worktree's `services/edge` with `PYTHONPATH=<worktree>/services/edge`.
  - Never `pip install` anything.
  - Analyzer API tests use `local_client` from `tests/conftest.py`.
  - `ruff` in CI form: `cd services/edge && <python> -m ruff check . ../../tools`.
- **Dashboard:**
  - Checks: `npm run -s test:unit`, `npx tsc --noEmit`, `npm run -s lint`, `npm run -s build`.
  - Playwright runs with `PYTHON=<that python>`.
  - `node_modules` is a junction; never `npm install`.
- **Never touch ports 8090, 3000 or 3001; those are the user's.** Never kill processes by image name.
- **Contract rule:** schema, docs/02 and every implementation change in the same branch. `tools/validate_contracts.py` must pass.
  - Known local failure: `tools/tests/test_contracts.py::test_schema_rejects_mutation[olay ts …]` fails in this venv on main too (missing format checker). CI passes it.
- **Commits:** Turkish subject, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. No user videos and no model files.
- **Tests and models:**
  - Tests use fake detector and pose models; no model download in tests.
  - A real-model test may exist only behind the existing skip pattern used in `tests/test_pose_model.py`.

## Review focus
1. **Same behaviour as live.** A hands-up episode of exactly the rule seconds fires once, at the same moment the live session would fire. Video time is used, not wall time, so a 30 fps file processed at 5 fps gives the same alarm times.
2. **Episode end pairing.** An alarm that never ends before the video ends gets `endS` = video end, not null.
3. **Mixed-up options are refused.** A counting option on a safety job, or a safety option on a counting job, gets `422` with the Turkish text, not a silent ignore.
4. **Large alarm counts.** Images stop at 50 and the list stops at 500, while `count` stays true. The panel table scrolls rather than freezing.
5. **vehicle and animal end to end.** Upload, then result, then the same Giriş/Çıkış display as people.

---

### Task 1: `bantvision.video` safety mode

**Files:**
- Modify: `services/edge/bantvision/video.py`
- Create: `services/edge/tests/test_video_safety.py`

**Interfaces:**
- Produces:
  - `--preset safety`, `--hands-up S` / `--no-hands-up`, `--lying S` / `--no-lying`;
  - `ozet.json` with `count`, `alarms` and `device`;
  - `alarm-N.jpg`, `alarmlar.csv`, `isaretli.mp4`.

- [ ] **Step 1:** Failing tests. A fake detector returns one person box per frame. A fake pose returns a hands-up pose (wrists above the head, using the same keypoint layout `core/pose_rules.py` expects) for frames in [2 s, 6 s) and a standing pose otherwise. Feed a synthetic 10 s, 10 fps video written with OpenCV to `video.main([...])` in-process, monkeypatching the model constructors. Assert:
  - one handsUp alarm, with `startS` ≈ 2.0 and `atS` ≈ 5.0 (3 s rule), `endS` ≈ 6.x, image `alarm-1.jpg` exists and is a valid JPEG;
  - `--no-hands-up` gives no alarms;
  - `--hands-up 6` exits with a usage error;
  - an alarm still active at the video end gets `endS` = video end;
  - the cap: a fake producing more than 50 alarms writes 50 images and lists the rest with `image: null`; use a small video with very short episodes, and patch the caps as constants for speed if needed;
  - no `sayimlar.csv`, but `alarmlar.csv` exists, with a header line.
- [ ] **Step 2:** Run them and expect failures.
- [ ] **Step 3:** Implement per R2 and R3. Read `core/safety.py`, `core/pose_rules.py`, `overlay.draw_safety` and `live/session.py`'s safety path to use the analyzer exactly as live does.
- [ ] **Step 4:** Focused tests, the existing `test_video*.py`, and ruff. Commit `Video ile test: güvenlik alarmı (poz) modu — canlıdaki analizle aynı kurallar, alarm listesi ve resimleri`.

### Task 2: Contract and analyzer

**Files:**
- Modify: `contracts/analysis-job.schema.json`, `docs/02-contracts.md`
- Create: `contracts/examples/analysis-job-safety-done.json`
- Modify: `services/edge/bantvision/analyzer/app.py` (`OptionsIn`, R1 refusals), `services/edge/bantvision/analyzer/jobs.py` (`options_to_args`, R5)
- Test: the existing analyzer tests (extend) and `tools/tests/test_contracts.py`

- [ ] **Step 1:** Failing tests:
  - `OptionsIn` accepts vehicle, animal and safety with rules;
  - the R1 and R2 refusals, with their exact texts;
  - `options_to_args` produces `--preset safety --hands-up 3 --no-lying` and so on;
  - the worker, with a fake `Popen` writing a safety `ozet.json` plus two alarm JPEGs, gives `result.alarms` and `files` that include `alarm-1.jpg`; the files route serves them as `image/jpeg`; an unknown `alarm-999.jpg` or `../x` name gives 404;
  - a broken alarm list fails the job with the R5 text;
  - the schema validates the new example and the worker's result.
- [ ] **Step 2:** Implement.
- [ ] **Step 3:** Run the focused tests, `tools/tests`, `validate_contracts.py` and ruff. Commit `Video ile test sözleşmesi: araç, hayvan ve güvenlik alarmı; alarm listesi ve resimleri`.

### Task 3: Panel and docs

**Files:**
- Modify: `apps/dashboard/src/lib/types.ts`, `apps/dashboard/src/components/video/UploadCard.tsx`, `apps/dashboard/src/components/video/JobDetail.tsx`, and the job list kind label (grep `PRESET_LABELS`)
- Create: pure helpers in a `.mjs` module with a `.d.mts` and a `.test.mjs`, added to `test:unit`:
  - `safetyOptions(form)` → options or a Turkish error;
  - `formatClock(s)` → `mm:ss`;
  - `alarmRows(result)`.
- Modify: `apps/dashboard/e2e/video-analysis.spec.ts`, using the mocked job routes it already uses: a safety job with alarms (table, thumbnail URL, row click sets `video.currentTime`), an empty alarm list, and a vehicle job showing Giriş/Çıkış. Add an upload-form test: choosing Güvenlik alarmı hides the counting fields, shows the rules, and sends the right `options`; capture the request with `page.route`.
- Modify: `docs/13-web-platform.md`, `docs/12-durum.md`

- [ ] **Step 1:** Write the unit tests and e2e tests, and watch them fail.
- [ ] **Step 2:** Implement per R6, then write the docs per R7.
- [ ] **Step 3:** Run `test:unit`, `tsc`, lint, build, the e2e `video-analysis.spec.ts`, then the full Playwright run once. Commit `Panel: Video ile test'te araç, hayvan ve güvenlik alarmı; alarm tablosu`.

## Final verification (controller)
- **Real models, scratch data dir, port 8097:** run a real analyzer job for safety on a local video, and one for vehicle; check the result in the API.
- **Full suites:** edge, tools and dashboard, then CI green, then merge.
