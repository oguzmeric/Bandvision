# Ekran Kartı Desteği ve Cihaz Ayarları Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The analyzer's two neural models can run on the graphics card:
- YOLOX-S, used for people, vehicle and animal detection;
- MoveNet, used for pose (the security alarm).

The user picks the device per use on a new "Cihaz ayarları" page. The analyzer falls back to the CPU on its own whenever the card is missing or fails, and every surface says which device actually ran.

**Why:** PC roadmap item 2 (`docs/superpowers/specs/2026-10-28-sade-arayuz-design.md` "Yol haritası"). Today every model runs on the CPU only (`providers=["CPUExecutionProvider"]` in `core/detector.py` and `core/pose.py`).

**Measured on the user's PC** (2026-11-03; YOLOX-S 640×640, ONNX Runtime 1.24.4 DirectML, scratch venv):

| Device | Detection, per frame | Detection + pose, per frame | Session load |
|---|---|---|---|
| CPU | 81 ms | 85 ms | 0.1 s |
| NVIDIA RTX 4050 Laptop (DXGI index 1) | 10 ms | 13 ms | 2 s |
| Intel UHD (DXGI index 0) | 61 ms | 67 ms | 15 s, first time |

Other findings from the same run:
- **Output accuracy:** max raw output difference against the CPU was 4e-5 on NVIDIA and 0.5 on Intel.
- **DirectML `device_id`** equals the `IDXGIFactory1::EnumAdapters1` index. Index 2 was "Microsoft Basic Render Driver", flagged `DXGI_ADAPTER_FLAG_SOFTWARE`.
- **Invalid `device_id`:** ONNX Runtime prints an "EP Error" and silently falls back to the CPU. `session.get_providers()[0]` then reads `CPUExecutionProvider`.

**Architecture:**
- **Device module.** A new pure-Python module `bantvision/core/devices.py`:
  - enumerates GPUs through DXGI on Windows using ctypes, with no new dependency;
  - resolves a device choice;
  - opens ONNX Runtime sessions with a verified CPU fallback.
- **Model classes.** `ObjectDetector` and `PoseEstimator` take a device choice.
- **Live models.** The shared live models (`SharedDetector`, `SharedPose` in `live/api.py`) load on the chosen device. When the choice changes they hot-swap without a gap.
- **Video jobs.** They pass `--device` to `bantvision.video` and record the device used in `result.device`, a contract change.
- **Status bar.** The analyzer status gains the GPU load, read through Windows PDH counters, so the panel status bar's "Ekran kartı: —" becomes real.
- **Panel page.** `/devices` lists the devices, runs a speed test per device, and saves the choices.
- **Install.** On Windows the analyzer installs `onnxruntime-directml` instead of `onnxruntime`. The launcher swaps the packages safely.

**Tech Stack:**
- Python 3.11+, FastAPI, onnxruntime / onnxruntime-directml, ctypes (DXGI, PDH), pytest, ruff.
- Next.js 15 App Router, TypeScript, `node --test`, Playwright.

**Spec:** none separate. The user skipped the questions ("soruları atla, direkt başla", 2026-11-03), so the controller decided the rulings below under that delegation. They are binding.

## Rulings (binding)

**R1. Engine.**
- **Windows:** ONNX Runtime with the DirectML execution provider (`onnxruntime-directml>=1.24`). One package covers NVIDIA, Intel and AMD with no CUDA install.
- **Other platforms:** CPU `onnxruntime>=1.18`, unchanged. This covers CI (ubuntu) and the Linux edge box.
- **Out of scope:** CUDA, TensorRT, OpenVINO and NPU execution providers.

**R2. Devices and their ids.**
- **CPU:** `{"id": "cpu", "kind": "cpu", "name": "İşlemci"}`.
- **GPU list.** Every DXGI adapter from `EnumAdapters1`, skipping:
  - adapters with `DXGI_ADAPTER_FLAG_SOFTWARE` (value 2);
  - adapters with `VendorId == 0x1414` (Microsoft).
- **GPU id:** `gpu-<vendor:04x>-<device:04x>`. The second and later identical adapters get `-2`, `-3` and so on, in DXGI order. The id survives DXGI index changes, such as after a driver update or a new display. It is resolved to the current DXGI index each time a session opens.
- **GPU fields:** `{"id", "kind": "gpu", "name": <DXGI Description, stripped>, "memoryMb": DedicatedVideoMemory // 2**20, "index": <DXGI index>, "luid": "0x<high:08x>_0x<low:08x>"}`.
- **What the API returns:** `index` and `luid` are internal. The API returns `id`, `kind`, `name` and `memoryMb` only.
- **Non-Windows, or DXGI failure:** the GPU list is empty. A DXGI failure is logged once at warning level.

**R3. Choices.** A choice is `"auto"`, `"cpu"`, or a GPU id. A GPU id that is not present right now is allowed and kept; it falls back as in R5.
- **What `"auto"` resolves to:** the listed GPU with the largest `memoryMb`, lowest DXGI index on ties, when DirectML is available. Otherwise `"cpu"`.
- **On the user's PC** `"auto"` picks the NVIDIA card. Intel is selectable by hand.

**R4. DirectML availability.** `"DmlExecutionProvider" in onnxruntime.get_available_providers()`. When it is missing, every GPU choice runs on the CPU with note N1. When onnxruntime itself does not import, the existing model-load error path stays as it is.

**R5. Opening a session.** `devices.open_session(model_path, configure, choice) -> GuardedSession`. `configure(so)` applies the caller's own session options to a fresh `SessionOptions`; `open_session` builds new options for every attempt, so the caller's settings are never mutated or reused.

Resolve the choice, then:
- **CPU:** `providers=["CPUExecutionProvider"]`. The session options stay exactly as the callers set them today.
- **GPU:** build fresh options with `configure`, then:
  - set `enable_mem_pattern = False` and `execution_mode = ORT_SEQUENTIAL`, as DirectML requires;
  - pass `providers=[("DmlExecutionProvider", {"device_id": index}), "CPUExecutionProvider"]`;
  - verify `session.get_providers()[0] == "DmlExecutionProvider"`. If it is not, or the constructor raises, open a CPU session instead with note N3.

The `used` record and the notes:
- **`used`:** `Used(kind: "cpu"|"gpu", id: str, name: str, note: str | None)`. `id` is `"cpu"` or the GPU id that really runs.
- **Notes.** Turkish, shown to the user verbatim:
  - **N1:** `Ekran kartı desteği kurulu değil (onnxruntime-directml); işlemci kullanılıyor.` On non-Windows: `Ekran kartı desteği yalnız Windows'ta var; işlemci kullanılıyor.`
  - **N2:** `Seçilen ekran kartı bulunamadı; işlemci kullanılıyor.` Used when a GPU id choice is not in the list.
  - **N3:** `Ekran kartında açılamadı (<neden>); işlemci kullanılıyor.`
  - **N4:** `Ekran kartı çalışırken hata verdi (<neden>); işlemci kullanılıyor.`
  - **When notes apply:** `"auto"` that resolves to the CPU because no GPU or no DirectML exists has `note=None`, since the CPU was the expected choice. `"cpu"` has `note=None`. A GPU id choice gets N1 when DirectML is missing.
- **`<neden>`:** the exception's first line, at most 160 characters, with no file paths. The plan does not need a general path scrubber: ONNX Runtime messages here hold no secrets, and `failure_reason` in `core/model_download.py` already exists for the download path. Use the first line, truncated.

**R6. Runtime failure.** `GuardedSession.run(...)` delegates to the inner session.
- On a GPU session, any exception from `run` triggers the fallback: log an error, rebuild once on the CPU with the same model and fresh options from `configure`, set `used` to CPU with note N4, and retry the same call on the CPU.
- A CPU session's exceptions propagate unchanged.
- After a fallback the session stays on the CPU until it is reopened by a saved setting or a restart. It never flips back on its own.
- `GuardedSession` exposes `get_inputs()` and `used`.

**R7. Model classes.**
- **Constructors:** `ObjectDetector(path=None, device: str | None = None)` and `PoseEstimator(path=None, device: str | None = None)`.
- **`device=None`:** use the process default `devices.default_choice()`. It is `"cpu"` unless `devices.set_default_choice(choice)` was called.
- **`.used`:** both classes expose the session's `Used`.
- **Thread settings:** the per-class settings stay as they are today (`intra_op_num_threads`, `allow_spinning=0`).

**R8. Settings.** The file `<data>/devices.json` holds `{"choices": {"detector": c, "pose": c, "video": c}}`.
- **Location:** `<data>` is the same root as `live/` and `alarms`, i.e. `LiveManager`'s `root`.
- **Defaults:** missing file or missing key → `"auto"`.
- **Bad files:** a corrupt file is kept aside (`.bozuk`), following the `views.py` pattern, and defaults apply. A locked or unreadable file means defaults in memory and the file is left untouched; the write is retried on the next save.
- **Writes** are atomic (`jsonfile.py`).
- **What each setting means:**
  - **`detector`:** the live people and vehicle detector. It serves both Kişi sayımı and Güvenlik alarmı person finding.
  - **`pose`:** live pose, for the security alarm.
  - **`video`:** every model inside "Video ile test" jobs.
  - **Ürün sayımı** uses no model and is not listed. The page says so in one line.

**R9. Live hot-swap.** `SharedModel.set_choice(choice)`:
- **New choice differs** from the current one: load a new inner model on the background thread while the old one keeps serving. Swap under `_infer` when ready, then drop the old one.
- **Failed load:** keep the old model, set the existing `error` state text, and leave the stored choice as saved. The next `_start_loading` retry uses the new choice.
- **Never loaded:** only the choice is stored.
- **Idempotent:** the same choice twice is a no-op.

**R10. API** (under the live router, prefix `/api/v1/live`, existing auth; panel proxy `/api/live/[...path]`, unchanged).

**`GET /devices` →**
```json
{"gpuSupport": {"available": true, "reason": null},
 "devices": [{"id": "cpu", "kind": "cpu", "name": "İşlemci"},
             {"id": "gpu-10de-28a1", "kind": "gpu", "name": "NVIDIA GeForce RTX 4050 Laptop GPU", "memoryMb": 5920}],
 "auto": "gpu-10de-28a1",
 "choices": {"detector": "auto", "pose": "auto", "video": "auto"},
 "inUse": {"detector": {"state": "ready", "device": {"id": "gpu-10de-28a1", "kind": "gpu", "name": "..."}, "note": null},
           "pose": {"state": "idle", "device": null, "note": null}}}
```
- **`gpuSupport.reason`** is N1's first clause without "; işlemci kullanılıyor.", or null.
- **`inUse.*.state`** is one of `"idle"` (never loaded), `"loading"`, `"ready"` or `"error"`. The `device` and `note` keys come from the inner model's `used` when ready, else null.

**`PUT /devices`**
- **Body:** `{"choices": {"detector", "pose", "video"}}`, strict, all three required.
- **Values:** each must be `"auto"`, `"cpu"`, or match `^gpu-[0-9a-f]{4}-[0-9a-f]{4}(-[0-9]+)?$`. Anything else gets `422`.
- **Effects:** saves, calls `set_choice` on both shared models with the resolved choice, and returns the GET body.

**`POST /devices/benchmark`**
- **Body:** `{"device": "cpu" | <gpu id>}`.
- **What it times:** a fresh `ObjectDetector(device=...)` runs a fixed frame: `numpy.random.default_rng(0)`, 720×1280×3 uint8. It does 3 warm-up runs, then 20 timed runs.
- **Response:** `{"device": Used-as-json, "msPerFrame": round(mean, 1), "loadS": round(session open seconds, 1)}`.
- **One at a time:** while one runs, the next gets `409` `Başka bir hız testi sürüyor; bitince yeniden deneyin.`.
- **Model download failure:** `502` with the existing model-download Turkish message.
- **Fallback is reported, not hidden:** a GPU that fell back to the CPU returns 200 with its N-note in `device.note`.

**R11. Video jobs.**
- **Worker:** reads `choices["video"]` at job start and passes `--device <choice>` to `bantvision.video`.
- **`bantvision.video`:**
  - new option `--device`, default `"cpu"`, so CLI and tools stay reproducible;
  - calls `devices.set_default_choice(a.device)` before any model is built;
  - writes `"device": {"kind", "name", "note"}` into `ozet.json`, only when a model was actually built (the detect mode or pose). Product counting has no model and no `device` key.
- **`jobs.py`:** copies it to `result.device`.
- **Contract** `contracts/analysis-job.schema.json` `result.properties.device`:
  - shape `{"type": "object", "required": ["kind", "name"], "additionalProperties": false, "properties": {"kind": {"enum": ["cpu", "gpu"]}, "name": {"type": "string"}, "note": {"type": ["string", "null"]}}}`;
  - description: `Modelin çalıştığı cihaz (yalnız model kullanan analizlerde)`.
- Update `docs/02-contracts.md` and the dashboard type.
- **JobDetail** gains `<Stat label="Cihaz" value={kind === "gpu" ? "Ekran kartı" : "İşlemci"} hint={name} />`. The note, when present, shows as one muted line under the stats.

**R12. GPU load.** A new module `bantvision/core/gpu_load.py`, Windows only, reads PDH counters through ctypes.
- **Query:** `\GPU Engine(*)\Utilization Percentage` via `PdhAddEnglishCounterW` and `PdhGetFormattedCounterArrayW` with `PDH_FMT_DOUBLE`.
- **Load for an adapter:** sum the values per instance with the same `luid_0x…_0x…_phys_…_eng_N` (summing over pids), then take the max over engines, capped at 100. This matches the Windows Task Manager.
- **Lifetime:** keep one query open for the process. The first call collects twice, 100 ms apart. Later calls collect once and report the change since the previous call.
- **Unavailable:** any PDH failure gives `None` and a warning logged once.

`/api/v1/system/status` gains `"gpu": {"name": str, "percent": float | null} | null`:
- **Which GPU:** the GPU the live detector currently uses, else the pose GPU, else the `auto` GPU.
- **No GPU** at all: `null`.

The panel:
- **System route:** passes `gpuPercent` and `gpuName` through (`systemStatus.mjs`).
- **StatusBar:**
  - shows `Ekran kartı: %<round>`, with the GPU name in `title`;
  - shows `Ekran kartı: —` when it is null, unknown or not up.

**R13. Panel page.**
- **Nav:** "Cihaz ayarları" (Donanım) gets `href: "/devices"` and is no longer `soon`.
- **Page title:** "Cihaz ayarları".
- **Intro text:** `Kişi ve araç tanıma ile poz modelleri ekran kartında çalışabilir. Ürün sayımı model kullanmaz, işlemcide çalışır.`

**Section "Cihazlar"** is a table with columns Ad, Tür, Bellek, Hız testi.
- **Tür:** İşlemci or Ekran kartı.
- **Bellek:** `<memoryMb> MB` or —.
- **Hız testi:** the button "Hız testi" runs that one device. While it runs, the button reads "Ölçülüyor…" and is disabled, and other test buttons are disabled too.
- **Result:** `<msPerFrame> ms/kare` plus `(<loadS> sn açılış)`. If `device.note` is set, the note shows in the row in the nok colour instead.
- **Errors:** a 409 or other error shows the error text in that row.
- **Banner:** when `gpuSupport.available` is false, a muted line above the table shows `gpuSupport.reason`.

**Section "Kullanım"** has three rows, each with a `<select>`:
- **Rows:** "Kişi ve araç tanıma (canlı)", "Poz — güvenlik alarmı (canlı)", "Video ile test".
- **Options:**
  - `Otomatik (<auto device name>)`;
  - `İşlemci`;
  - one option per GPU;
  - a saved GPU id that is not listed shows as `Bulunamayan ekran kartı (<id>)`.
- **Under each live row:** a muted line `Şu an: <device name>`. It reads `Şu an: yükleniyor…` while loading, `Şu an: kullanılmıyor` when idle, and gives the error text when in error. A `note` shows in the nok colour.
- **Kaydet:** follows the NotifySettings rules:
  - disabled until the settings are read and while unchanged;
  - a read error and the last action's result are separate lines;
  - the page retries reading every 5 s while the read failed (`useRetryWhileFailed`);
  - `{error}`/`detail` text is read via `failure.ts`;
  - `UnsavedGuard` covers unsaved changes.

**R14. Install and launcher.**
- **`pyproject.toml`**, both the `analyzer` and `detect` extras: replace `"onnxruntime>=1.18"` with `"onnxruntime>=1.18; sys_platform != 'win32'"` and `"onnxruntime-directml>=1.24; sys_platform == 'win32'"`.
- **`tools/check_analyzer_deps.py`:**
  - **Markers:** evaluates markers of the form `sys_platform == '<x>'` / `!= '<x>'`. Any other marker, such as `python_version`, counts as true, which is today's behaviour. A requirement whose marker is false is skipped.
  - **New `conflicts()`:** on win32, when the distribution `onnxruntime` is installed alongside a required `onnxruntime-directml`, it reports `onnxruntime (işlemci sürümü) ekran kartı sürümüyle (onnxruntime-directml) aynı klasörü kullanıyor; kaldırılmalı`.
  - **Exit codes:** `0` all good; `1` missing or old; `3` conflict, which takes precedence over 1.
- **`tools/panel_baslat.bat`:**
  - **Update with the analyzer running:** if the check fails (non-zero) and `/healthz` on 8090 answers, it prints `Analiz sunucusu paketleri guncellenecek: "BandVision analiz" penceresini kapatip kisayolu yeniden calistirin.`, skips the install, and continues. Packages cannot be replaced under a running analyzer, because its DLLs are locked.
  - **Exit code 3:** `pip uninstall -y onnxruntime`, then `pip install -q --force-reinstall --no-deps "onnxruntime-directml>=1.24"`, then the usual `pip install -q -e "%EDGE%[analyzer]"`.
  - **Exit code 1:** the usual install. If the venv has `onnxruntime` but not `onnxruntime-directml` (the first update), `check` returns 3 only after DirectML is installed. For that reason the exit-1 path re-runs the check after installing and handles a 3 from it.
  - **ASCII only** in echo lines, as the file does today.

**R15. Docs.**
- **`docs/13-web-platform.md`:** a new section "Cihaz ayarları (ekran kartı)": behaviour, API, notes N1–N4, settings file, hot-swap, status bar, launcher swap.
- **`docs/02-contracts.md`:** `result.device`.
- **`docs/12-durum.md`:** a status line.
- **`apps/dashboard/README.md`:** setup notes for Windows (`onnxruntime-directml`).
- **No device models in docs**, per the project's doc rules. Use "NVIDIA dizüstü ekran kartı" and "Intel tümleşik ekran kartı" instead.

## Global Constraints

- **Language:** user-visible text is Turkish, code identifiers are English, and comments match the surrounding file, which is Turkish.
- **Python:** 3.11+, type hints mandatory, `ruff` clean (line length 110), `pytest` green.
- **Analyzer tests:**
  - use `local_client` from `services/edge/tests/conftest.py` (`base_url="http://127.0.0.1"`); the Host check refuses `testserver`;
  - run with `C:/Users/MSI-LAPTOP/bantvision/services/edge/.venv/Scripts/python.exe -m pytest` from the worktree's `services/edge`, with `PYTHONPATH=<worktree>/services/edge`;
  - **never** `pip install` anything into that venv, and never `pip install -e` from a worktree.
- **No new Python dependency** beyond the R14 marker swap; DXGI and PDH go through ctypes.
- **Windows-only code:**
  - imports and runs only when `sys.platform == "win32"`;
  - its tests use `pytest.mark.skipif(sys.platform != "win32", ...)` for real-hardware checks;
  - everything else is tested with fakes, so CI (ubuntu, CPU onnxruntime) stays green.
- **Dashboard:** Next.js 15 App Router, existing components and styles (`PageHeader`, the form/table patterns of `NotifySettings`/`AccessSettings`). No new npm dependency.
- **Dashboard checks:** `npm run -s lint`, `npx tsc --noEmit`, `npm run -s test:unit`, and Playwright e2e.
- **Before e2e:**
  - run `npm run -s build`;
  - set the env `PYTHON=C:/Users/MSI-LAPTOP/bantvision/services/edge/.venv/Scripts/python.exe`;
  - use ports other than 8090/3000, which are the user's servers. Never touch those.
- **Process kills:** never kill processes by image name.
- **Contract rule (CLAUDE.md):** schema, `docs/02-contracts.md` and every implementation change in the same branch; `tools/validate_contracts.py` and `tools/tests/test_contracts.py` stay green.
- **Commits:**
  - end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - Turkish subject lines like the repo history;
  - no user videos and no secrets.

## Review Focus

1. **GPU disappears or the driver resets mid-session** (TDR, laptop dGPU power-off). Live counting and the security alarm must keep producing results on the CPU, with note N4 visible on the page. They must not stop or crash. Covered by Task 1's `run` fallback test and Task 3's shared-model test with a raising fake.
2. **Choosing Intel live (15 s first load) must not blank the security alarm.** The old model serves until the new one is ready (R9). Covered by Task 3's hot-swap test with a slow fake loader.
3. **Silent CPU fallback by ONNX Runtime** must never be reported as "Ekran kartı". `get_providers()` is verified (R5). Covered by Task 1's test where the fake session reports CPU providers.
4. **A first update on a machine with CPU `onnxruntime`** must end with exactly `onnxruntime-directml` installed and the analyzer starting. Covered by Task 6's `check_analyzer_deps` tests (marker skip, conflict exit 3) plus the manual launcher check in Task 6.
5. **CI and non-Windows** must see one CPU device, `gpuSupport.available == false` with the non-Windows N1 reason, and unchanged results. Covered by Task 1 (no-win32 path) and Task 3's API test.

---

### Task 1: `core/devices.py` — enumeration, choice resolution, guarded sessions

**Files:**
- Create: `services/edge/bantvision/core/devices.py`
- Create: `services/edge/tests/test_devices.py`

**Interfaces:**
- Produces:
  - `Gpu` dataclass `(id: str, name: str, memory_mb: int, index: int, luid: str)`.
  - `Used` dataclass `(kind: str, id: str, name: str, note: str | None)` with `to_json() -> dict` returning `{"id", "kind", "name", "note"}`.
  - `list_gpus() -> list[Gpu]`, cached for 30 s; `refresh=True` bypasses the cache.
  - `dml_available() -> bool`.
  - `gpu_support() -> tuple[bool, str | None]`, the reason as in R10.
  - `auto_choice(gpus=None) -> str`.
  - `resolve(choice: str, gpus=None) -> tuple[Gpu | None, str | None]`: the GPU to use or None for the CPU, plus a note.
  - `open_session(model_path: str | os.PathLike[str], configure: Callable[[SessionOptions], None], choice: str) -> GuardedSession`.
  - `GuardedSession` with `.run(output_names, feeds)`, `.get_inputs()` and `.used`.
  - `default_choice()` and `set_default_choice(choice)`.
  - `CHOICE_RE`.
  - `cpu_used(note=None) -> Used`.
- **Test seams** (parameters, not env vars): `open_session(..., _ort=None, _gpus=None)` accepts a fake `onnxruntime` module and GPU list; `list_gpus` takes `_enum: Callable[[], list[tuple[int, str, int, int, int, int, int, int]]] | None`, yielding raw DXGI rows `(index, description, vendor, device, dedicated_bytes, flags, luid_high, luid_low)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_devices.py`. Use a `FakeOrt` module object:
  - It has `get_available_providers()`, `SessionOptions` (a simple attribute bag with `add_session_config_entry`), `ExecutionMode.ORT_SEQUENTIAL`, and `InferenceSession(path, so, providers=...)`.
  - The fake session records its providers and options, can be told to report CPU providers (simulating the silent fallback) or to raise from `run`, and returns a numpy array from `run`.

  The cases:
  1. **ids:** raw rows Intel (8086/9a49), NVIDIA (10de/28a1), Basic Render (1414/008c, flags 2) and a second identical NVIDIA give the ids `gpu-8086-9a49`, `gpu-10de-28a1`, `gpu-10de-28a1-2`. The software/Microsoft row is dropped. `memory_mb` and `luid` are formatted as in R2.
  2. **auto:** `auto_choice` picks the largest memory, lowest index on ties. It is `"cpu"` when there are no GPUs or `dml_available()` is false.
  3. **resolve:** covers `"cpu"`, `"auto"`, a present id, a missing id (N2), and an id with DirectML missing (N1). For `"auto"` with no GPU the note is None.
  4. **CPU session:** `open_session` with `"cpu"` passes `providers=["CPUExecutionProvider"]` and leaves `enable_mem_pattern`/`execution_mode` unset.
  5. **GPU session:** `open_session` with a GPU passes `[("DmlExecutionProvider", {"device_id": idx}), "CPUExecutionProvider"]`, `enable_mem_pattern False` and `ORT_SEQUENTIAL`. `configure` is applied to the fresh options (assert the thread setting arrives). `used.kind == "gpu"`.
  6. **Silent fallback:** the fake reports `["CPUExecutionProvider"]` after asking for DML, so the result is a CPU session with N3 whose reason reads `DirectML etkinleşmedi`.
  7. **Constructor raises** `RuntimeError("D3D12 device removed\nstack…")`: the result is a CPU session with note `Ekran kartında açılamadı (D3D12 device removed); işlemci kullanılıyor.`
  8. **`run` raises on GPU:** the session rebuilds on the CPU, `used` gets N4, the same feeds are retried, and the CPU result is returned. A second `run` uses the CPU directly; the GPU is not retried.
  9. **`run` raises on CPU:** the exception propagates.
  10. **default choice:** `default_choice()` is `"cpu"` initially; `set_default_choice("auto")` changes it. Restore it in teardown.
  11. **`CHOICE_RE`** accepts `auto`, `cpu`, `gpu-10de-28a1` and `gpu-10de-28a1-2`, and rejects `GPU-10DE-28A1`, `gpu-1-2` and `gpu-10de-28a1-x`.
  12. **Real hardware** (win32 only, skipif): `list_gpus(refresh=True)` returns a list. Each id matches `CHOICE_RE`, and no item has vendor Microsoft.

- [ ] **Step 2:** Run `pytest tests/test_devices.py -q` and expect failures, because the module does not exist yet.

- [ ] **Step 3: Implement** `devices.py`.
  - **DXGI enumeration** via ctypes. `CreateDXGIFactory1` takes IID `770aae78-f26f-4dba-a829-253c83d1b387`. The vtable slots are:
    - `IDXGIFactory1::EnumAdapters1` = 12;
    - `IDXGIAdapter1::GetDesc1` = 10;
    - `Release` = 2 on every COM object, including the factory, in `finally`.
  - **`DXGI_ADAPTER_DESC1` layout:** `WCHAR Description[128]; UINT VendorId, DeviceId, SubSysId, Revision; SIZE_T DedicatedVideoMemory, DedicatedSystemMemory, SharedSystemMemory; LUID AdapterLuid {DWORD LowPart; LONG HighPart}; UINT Flags`.
  - **Exceptions:** wrap any exception into an empty list, logged once.
  - **Note texts:** exactly the R5 texts.
  - **`<neden>`:** the first line, stripped, truncated to 160 characters.
  - **Logging:** each fallback is logged at error level with the full exception.
  - **Lazy imports:** `onnxruntime` is imported inside the functions, as the existing modules do.

- [ ] **Step 4:** Run the tests and ruff; expect them to pass.

- [ ] **Step 5: Commit:** `Cihazlar: ekran kartı listesi (DXGI), seçim çözümü ve işlemciye düşen ONNX oturumu`.

### Task 2: Models use devices; video jobs record the device (contract)

**Files:**
- Modify: `services/edge/bantvision/core/detector.py` (`ObjectDetector.__init__`, `used`)
- Modify: `services/edge/bantvision/core/pose.py` (`PoseEstimator.__init__`, `used`)
- Modify: `services/edge/bantvision/video.py` (`--device`, `set_default_choice`, `ozet.json` `device`)
- Modify: `services/edge/bantvision/analyzer/jobs.py` (`--device` arg from a `device_choice: Callable[[], str]` given to the `Worker`; `result.device`)
- Modify: `services/edge/bantvision/analyzer/app.py` (pass `device_choice` into the `Worker`, reading the R8 settings; in this task use a module function reading `devices.json` through the store from Task 3; if Task 3's store does not exist yet, use a `lambda: "auto"` placeholder wired in Task 3)
- Modify: `contracts/analysis-job.schema.json`, `contracts/examples/*` (add `device` to one done-job example if one exists), `docs/02-contracts.md`
- Modify: `apps/dashboard/src/lib/types.ts`, `apps/dashboard/src/components/video/JobDetail.tsx`
- Test: `services/edge/tests/test_devices_models.py` (new), the existing job tests (extend), `tools/tests/test_contracts.py` (passes)

**Interfaces:**
- Consumes: Task 1's `open_session`, `Used`, `default_choice` and `set_default_choice`.
- Produces:
  - `ObjectDetector(path=None, device=None).used` and `PoseEstimator(path=None, device=None).used`;
  - `bantvision.video --device {auto,cpu,gpu-…}`;
  - `ozet.json` `device`;
  - job `result.device`;
  - `Worker(..., device_choice: Callable[[], str] = lambda: "cpu")`.

- [ ] **Step 1: Failing tests.**
  - **Model classes:** monkeypatch `devices.open_session` to record its `choice` and return a fake guarded session. Then:
    - `ObjectDetector(path=<dummy>, device="auto")` passes `"auto"`;
    - `device=None` passes `devices.default_choice()`;
    - `.used` is the fake's `used`;
    - the same for `PoseEstimator`.
  - **Video CLI:** the existing tests that run `bantvision.video` on synthetic product videos assert that `ozet.json` has no `device` key, because no model ran. A detect-mode test with a monkeypatched detector, in-process via `video.main([...])` if the existing tests do that, asserts that `device` is present.
  - **Jobs:** extend the existing `FakeChildren`-style or real-run job test so that `--device auto` appears in the analysis command when `device_choice` returns `"auto"`, and so that a summary containing `device` lands in `result.device`. The schema validates (`jsonschema`).

- [ ] **Step 2:** Run the tests and expect failures.
- [ ] **Step 3:** Implement. The DirectML-specific session settings live only in `devices.open_session`; the model classes pass a `configure` callback with their current thread and spinning settings.
- [ ] **Step 4:** Dashboard. Add `device?: { kind: "cpu" | "gpu"; name: string; note?: string | null }` to the result type. JobDetail adds the "Cihaz" stat per R11 and the note line. Run `npx tsc --noEmit` and lint.
- [ ] **Step 5:** Run the full edge pytest, ruff, `tools` tests, `tsc` and lint. Commit: `Video ile test: analiz modeli seçilen cihazda çalışır, sonuçta kullanılan cihaz (sözleşme: result.device)`.

### Task 3: Settings store, shared-model hot-swap and the devices API

**Files:**
- Create: `services/edge/bantvision/live/devices_store.py` (`DeviceSettings`)
- Modify: `services/edge/bantvision/live/api.py` (`SharedModel`: choice, `set_choice`, `inner_used`, `ever_started`; loaders take a choice; `LiveManager` owns `DeviceSettings` and applies the choices at construction; routes `GET`/`PUT /devices` and `POST /devices/benchmark`)
- Modify: `services/edge/bantvision/analyzer/app.py` (the `Worker`'s `device_choice` reads `live.device_settings.choices()["video"]`)
- Create: `services/edge/tests/test_devices_api.py`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces:
  - `DeviceSettings(root).choices() -> dict[str, str]` and `.save(choices) -> dict[str, str]`;
  - the `SharedModel` API: `set_choice(choice: str)` and `status() -> {"state", "device", "note"}`;
  - the R10 JSON shapes.

- [ ] **Step 1: Failing tests.**
  1. **Store:** missing file gives the defaults; it round-trips; a corrupt file is moved aside to `devices.json.bozuk` with defaults applied; an unknown key is ignored; a locked read (monkeypatch the open to raise `PermissionError`) gives defaults and leaves the file untouched.
  2. **SharedModel hot-swap.** The fake loader takes `choice` and returns an object with `.used` and `.detect`.
     - **Slow swap:** the second loader blocks on an `Event`. During the swap `detect` keeps returning the OLD model's results. After the event is set and the swap completes, it returns the new model's results. `status()` reflects the new device.
     - **Failed swap:** the loader raises. The old model keeps serving, and `state == "error"` with the text.
     - **Never loaded:** `set_choice` only stores the choice and `status()["state"] == "idle"`.
     - **Same choice:** a no-op, so the loader is not called again.
  3. **Runtime fallback through the shared model:** with an inner whose `used` changes to a CPU note after a raise (simulated), `status()` shows the note.
  4. **API** (`local_client`, a `tmp_path` data dir, monkeypatched `devices.list_gpus`/`dml_available` and the loaders):
     - **GET:** the R10 shape.
     - **PUT:** a valid body saves and calls `set_choice` on both models with the resolved choice. A bad value gets 422, and a missing key gets 422.
     - **Benchmark:** with a fake detector it returns `msPerFrame` and `loadS`. A concurrent second call gets 409: use a blocking fake plus a thread. A model download error gets 502.
     - **Non-win32 path** (monkeypatch `sys.platform` within `devices`, or an empty `list_gpus` and `dml_available` False): one CPU device, `gpuSupport.available false`, and `auto == "cpu"`.
- [ ] **Step 2:** Run the tests and expect failures.
- [ ] **Step 3: Implement.**
  - The shared model resolves `"auto"` at load time through `devices.open_session`, so `auto` follows the hardware.
  - `LiveManager.__init__` reads `DeviceSettings` and calls `set_choice` on `detector` and `pose` before anything warms.
  - The benchmark lock is a non-blocking `threading.Lock().acquire(blocking=False)`.
- [ ] **Step 4:** Run the full edge pytest and ruff. Commit: `Cihaz ayarları: seçimler devices.json'da, canlı modeller boşluk olmadan yeni cihaza geçer, /devices ve hız testi`.

### Task 4: GPU load in the status and the status bar

**Files:**
- Create: `services/edge/bantvision/core/gpu_load.py`
- Modify: `services/edge/bantvision/analyzer/app.py` (`system_status` gains `gpu`)
- Modify: `apps/dashboard/src/lib/systemStatus.mjs` (+ `.d.mts`), `apps/dashboard/src/lib/systemStatus.test.mjs`, `apps/dashboard/src/lib/system.ts`, `apps/dashboard/src/app/api/system/route.ts`, `apps/dashboard/src/components/StatusBar.tsx`
- Test: `services/edge/tests/test_gpu_load.py`, the system status test (extend), `systemStatus.test.mjs`, `e2e/system.spec.ts` (extend: the CI analyzer has no GPU, so it shows `Ekran kartı: —`)

**Interfaces:**
- Produces:
  - `gpu_load.aggregate(samples: Iterable[tuple[str, float]], luid: str) -> float | None`, a pure function of the instance names and values;
  - a `GpuLoad` class with `.percent(luid) -> float | None` (PDH; returns None off Windows);
  - the status JSON `gpu`;
  - `SystemInfo` up-variant fields `gpuPercent: number | null` and `gpuName: string | null`.

- [ ] **Step 1: Failing tests.**
  - **`aggregate`:** two pids on the same engine are summed; the max is taken over engines; another LUID is ignored; the result is capped at 100; no matching instance gives None. Use instance names in the real format, `pid_11064_luid_0x00000000_0x000132d5_phys_0_eng_0_engtype_3d`, built with a test LUID.
  - **Status:** `system_status` with a monkeypatched GPU picker and `GpuLoad` returns `gpu: {name, percent}`, and `null` without a GPU.
  - **Panel unit test:** `analyzerSummary` passes `gpu` through, and an old analyzer without `gpu` gives null fields.
  - **StatusBar:** reads `%12` with the name in `title`; `—` when null.
  - **Real hardware** (win32 skipif): `GpuLoad().percent(<luid of the first listed GPU>)`, called twice, returns a float between 0 and 100 or None, with no exception.
- [ ] **Step 2:** Run the tests and expect failures.
- [ ] **Step 3:** Implement. Use PDH via `ctypes.windll.pdh`; `PDH_MORE_DATA = 0x800007D2` for the two-call array size pattern. Free buffers are Python-owned.
- [ ] **Step 4:** Run the edge tests, ruff, `test:unit`, `tsc`, lint, then build and the e2e `system.spec.ts`. Commit: `Durum şeridi: ekran kartı yükü (Windows sayaçları)`.

### Task 5: The "Cihaz ayarları" page

**Files:**
- Modify: `apps/dashboard/src/lib/nav.ts` (`/devices`)
- Create: `apps/dashboard/src/app/(panel)/devices/page.tsx`, `apps/dashboard/src/components/devices/DeviceSettings.tsx`, `apps/dashboard/src/lib/devices.ts` (types + fetchers via the existing `live.ts` `api()` helper)
- Create: `apps/dashboard/src/lib/deviceOptions.mjs` (+ `.d.mts`, + `deviceOptions.test.mjs`, added to `test:unit`). Pure functions:
  - `choiceOptions(devices, auto, saved) -> {value, label}[]`;
  - `inUseText(status) -> {text, warn}`;
  - `benchText(result) -> {text, warn}`.
- Create: `apps/dashboard/e2e/devices.spec.ts`
- Modify: `apps/dashboard/e2e/shell.spec.ts` if it asserts "Cihaz ayarları" is a "yakında" item.

**Interfaces:**
- Consumes: Task 3's API through `/api/live/devices`.

- [ ] **Step 1: Failing unit tests** for `deviceOptions.mjs`:
  - **The auto label** `Otomatik (NVIDIA …)`, and `Otomatik (İşlemci)` when `auto == "cpu"`.
  - **Missing saved GPU:** a saved GPU id that is not in `devices` adds `Bulunamayan ekran kartı (<id>)`.
  - **`inUseText`** for idle, loading, ready with a GPU, ready with a note (`warn: true`), and error.
  - **`benchText`** formats `12.3 ms/kare (2.0 sn açılış)`; a note means `warn` and the note text.
- [ ] **Step 2: e2e `devices.spec.ts`.**
  - **Against the real test analyzer** (CPU only in CI; on the dev PC without DirectML in the venv it is CPU only too):
    - the page opens from the menu;
    - the CPU row is shown;
    - "Hız testi" on the CPU shows `ms/kare`;
    - changing "Video ile test" to "İşlemci" enables Kaydet; saving shows the result line; a reload keeps the value.
  - **GPU rendering** uses `page.route("**/api/live/devices", …)` with a fixture of two GPUs, one with a note, plus `inUse` with N4. The test asserts:
    - the options list;
    - the `Şu an:` lines;
    - the note in the warning colour class;
    - "Bulunamayan ekran kartı" for a saved missing id.
  - **Read failure:** a route returning 502 shows the error line, Kaydet is disabled, and the page recovers once the route is restored (`useRetryWhileFailed`).
- [ ] **Step 3:** Implement the page per R13, following `NotifySettings.tsx` for the read, save, retry and error lines, and `UnsavedGuard`.
- [ ] **Step 4:** Run `test:unit`, `tsc`, lint, build, then e2e `devices.spec.ts`, `shell.spec.ts` and `system.spec.ts`. Commit: `Panel: Cihaz ayarları sayfası (cihazlar, hız testi, kullanım seçimi)`.

### Task 6: Install swap, launcher and docs

**Files:**
- Modify: `services/edge/pyproject.toml` (R14 markers in `analyzer` and `detect`)
- Modify: `tools/check_analyzer_deps.py`, `tools/tests/test_check_analyzer_deps.py`
- Modify: `tools/panel_baslat.bat`
- Modify: `docs/13-web-platform.md`, `docs/02-contracts.md` (if Task 2 left anything out), `docs/12-durum.md`, `apps/dashboard/README.md`

- [ ] **Step 1: Failing tests** in `test_check_analyzer_deps.py`:
  - **Markers:** `sys_platform == 'win32'` and `!= 'win32'` are honoured for a given platform. `requirements(p, platform="linux")` vs `"win32"` takes the new keyword argument `platform: str = sys.platform`. A `python_version` marker stays included.
  - **Conflict:** `conflicts(reqs, installed={"onnxruntime": "1.30.0", "onnxruntime-directml": "1.24.4"}, platform="win32")` returns the R14 text. Without `onnxruntime` installed, or on linux, it returns nothing.
  - **Exit codes:** `main` returns 3 on a conflict even when something is also missing, 1 when only something is missing, and 0 otherwise. Extend the existing `test_main_exit_code` style with injected fakes.
  - **Real `pyproject.toml`:** on linux it yields `onnxruntime` and not `onnxruntime-directml`; on win32 the reverse.
- [ ] **Step 2:** Implement. The marker evaluator handles only `sys_platform` with `==` and `!=` and single or double quotes. Anything else is True.
- [ ] **Step 3:** Update `.bat` per R14. Verify it manually in a scratch copy, without touching the real venv: run `tools/panel_baslat.bat` logic pieces is not possible safely, so review the batch file by reading. The controller does the real-machine install check after the merge, with the user.
- [ ] **Step 4:** Docs per R15.
- [ ] **Step 5:** Run the `tools` tests, ruff and edge pytest. Commit: `Kurulum: Windows'ta onnxruntime-directml (işlemci sürümüyle çakışma başlatıcıda çözülür), belgeler`.

## Final verification (controller, after the final review)

- **Run on the real hardware** from the worktree, in the scratch DirectML venv (PYTHONPATH), on a free port, never 8090:
  - `GET /api/v1/live/devices` lists the CPU, NVIDIA and Intel;
  - a benchmark on each device, recording ms/kare;
  - a video job in detect mode (`--mode detect --classes people` on any local video), checking `result.device.kind == "gpu"` with `auto`;
  - setting a missing GPU id, checking N2;
  - the GPU load in `/api/v1/system/status`.
- **Full suites:** edge pytest, `tools` pytest, dashboard unit, `tsc`, lint, build, and the full Playwright run.
- **Merge** only after CI is green: `gh run watch --exit-status && git merge`.
