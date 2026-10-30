# Analiz Sunucusu Sertleştirme (Host denetimi + yanlış anahtar iletisi) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close two analyzer access gaps that predate the sade-arayüz branch, and a third one found while planning.
- **DNS rebinding.** With no `ANALYZER_TOKEN`, the analyzer accepts any `Host`. After this plan it answers only to loopback names.
- **Misleading errors.** Three failures currently read as "Oturum süresi doldu" and offer a "Giriş yap" link that cannot help:
  - the panel and the analyzer have different access keys;
  - the analyzer refuses the panel's address;
  - a camera or recorder password is wrong.

  After this plan, each failure gets its own accurate message.

**Architecture:**
- **Analyzer (Python/FastAPI):**
  - A pure ASGI middleware checks `Host` whenever no token is configured.
  - The analyzer's own access check becomes the only source of `401`, and the Host check the only source of `403`. Recorder credential failures become `502` with the same message.
- **Panel (Next.js):**
  - The server-side proxy helper `passThrough` turns an analyzer `401`/`403` into a `502` with a machine-readable `code`.
  - The client error type carries that `code`.
  - The watch, single-camera and alarm surfaces show the matching text, not the session-expiry flow.
  - Codes and texts live in one pure `.mjs` module shared by server and client.

**Tech Stack:**
- Python 3.11+, FastAPI/Starlette, pytest, ruff.
- Next.js 15 App Router, `node --test`, Playwright.

**Spec:** none separate. The requirements and rulings below are binding, decided by the controller under the user's delegation ("sen öner", "top sende").

## Rulings (binding)

**R1.** No token configured: every HTTP and WebSocket request is Host-checked, including `/healthz`, `/docs`, `/redoc` and `/openapi.json`.
- **Accepted names**, case-insensitive, any port or none:
  - `localhost`
  - `127.0.0.1`
  - `[::1]`
- **Refused:**
  - every other name, including `testserver`, `127.0.0.1.evil.example` and `localhost.`;
  - a missing `Host`;
  - a malformed `Host`: empty, bad port, unclosed bracket, unbracketed IPv6.
- **HTTP refusal:** `403`, JSON `{"detail": "Bu adres kabul edilmiyor: erişim anahtarı (ANALYZER_TOKEN) tanımlı değilken analiz sunucusuna yalnızca bu bilgisayardan (localhost, 127.0.0.1) bağlanılabilir."}`.
- **WebSocket refusal:** the connection is closed before accept, with code 1008.
- **Why `/healthz` too:** the launcher and Playwright probe `http://127.0.0.1:<port>/healthz`, so they still pass. A rebinding page cannot even fingerprint the analyzer, and one rule is simpler to reason about.
- **Cost if wrong:** a tool that probes `/healthz` under another name gets `403`.

**R2.** Token configured: no Host check, exactly as today. The token guards every route except `/healthz`, and the docs pages stay off.

**R3.** `python -m bantvision.analyzer --host H` refuses to start when both hold:
- `H` is not loopback (`127.0.0.1`, `localhost`, `::1`);
- the effective token is empty. Read it from the same place `create_app()` reads it; check `Settings` in `analyzer/jobs.py`.

When refused:
- exit code `2`;
- stderr gets the Turkish message `Erişim anahtarı (ANALYZER_TOKEN) olmadan analiz sunucusu yalnızca bu bilgisayarda (127.0.0.1) açılabilir; ağa açmak için ANALYZER_TOKEN tanımlayın.`;
- `uvicorn.run` is never called.

Why: under R1 every LAN request would get `403`. This mirrors the panel rule "şifresiz yerel ağ ASLA açılmaz" (`accessCore.mjs`).

**R4.** A recorder or camera credential rejection (`RecorderError` kind `unauthorized`, `live/api.py` `_err`) returns `502`, not `401`.
- The message stays `Kullanıcı adı ya da şifre hatalı.`
- `502` matches every other recorder error.
- After R1 and R4, the analyzer's only `401` is its own token check, and its only `403` is the Host check.

**R5.** The panel's `passThrough` (`apps/dashboard/src/lib/analyzer.ts`) is used by `/api/live/[...path]` and `/api/jobs/**`. On an upstream analyzer `401` or `403` it:
- does not forward the status;
- returns `502` with JSON `{detail, code}`;
- discards the upstream body (cancel it);
- logs once a minute through `logRateLimited`, with message `analiz sunucusu panelin isteğini reddetti (HTTP <status>)`.

| Upstream | `code` | `detail` (verbatim) |
|---|---|---|
| 401 | `analyzer_key` | `Analiz sunucusu erişim anahtarı uyuşmuyor — panelde ve analiz sunucusunda aynı ANALYZER_TOKEN ayarlanmalı.` |
| 403 | `analyzer_host` | `Analiz sunucusu panelin bağlandığı adresi reddetti — erişim anahtarı yokken ANALYZER_URL 127.0.0.1 ya da localhost olmalı.` |

The panel's own `401` (middleware, session expired) is untouched.

**R6.** Codes, texts and classification live in a new pure module `apps/dashboard/src/lib/analyzerRefusal.mjs`, used by both server and client. It is added to `test:unit`.
- `ApiError` (`src/lib/live.ts`) gains `readonly code: string | null`, read from the body's `code` when it is a string.
- `Problem` (`src/lib/views.ts`) becomes `"auth" | "down" | "key" | "host"`. `problemOf` gives:
  - `401` → `"auth"`;
  - code `analyzer_key` → `"key"`;
  - code `analyzer_host` → `"host"`;
  - otherwise `"down"`.

**R7.** UI for `"key"` and `"host"`:
- `ConnectionProblem` shows the R5 text. It has no "Giriş yap" link and no "yeniden deneniyor".
- `AlarmCenter` uses `problemOf` instead of its own copy. `AlarmBanner` shows `Alarmlar alınamıyor — <R5 text>`, with no login link.
- Polling continues as for `"down"`, so the page recovers on its own once the key is fixed.
- `useDraft` keeps retrying silently on these `502`s, as it does today for 5xx. Its `authLost` stop, which halts draft writes until reload, must fire only for the panel's own `401`. Today a key mismatch also arrives as `401` and stops drafts for good; after R5 it arrives as `502` and is retried. Update the comments, and assert it in the Task 2 e2e: on the key-mismatch panel, draft writes keep retrying.
- The `"auth"` flow (text, link, keep-unsaved attribute) stays byte-for-byte unchanged.

**R8.** e2e real stack adds two `webServer` entries:
- analyzer #2 on port `8092`:
  - `ANALYZER_TOKEN=e2e-dogru-anahtar` (a test value, not a secret);
  - its own data dir `bv-e2e-<pid>-key`;
  - `ANALYZER_ALLOW_FILE_SOURCES` not needed;
- panel #3 on port `3102`:
  - passwordless loopback: `DASHBOARD_PASSWORD=""`, no hash/secret;
  - its own access/state files under the e2e temp dir;
  - `ANALYZER_URL=http://127.0.0.1:8092`, `ANALYZER_TOKEN=e2e-yanlis-anahtar`.

Ports 3000/8090 are never touched.

**R9.** Test fixtures:
- `services/edge/tests/conftest.py` gains `local_client(app, **kw) -> TestClient`, which creates the client with `base_url="http://127.0.0.1"`.
- Every existing `TestClient(` in `services/edge/tests` switches to it.
- Production code has no allowance for `testserver`.
- A test proves that the default TestClient host (`testserver`) gets `403` in no-token mode.

## Global Constraints

- User-visible text is Turkish and verbatim from the rulings. Code identifiers are English. Comments match the surrounding file (Turkish).
- No new npm or Python dependencies.
- **Environment:**
  - Work in worktree `C:/Users/MSI-LAPTOP/bantvision-sertlestirme`, branch `analiz-sertlestirme` from `main`.
  - Python runs from the main venv with `PYTHONPATH=<worktree>/services/edge`. Never run `pip install -e` from the worktree.
  - `apps/dashboard/node_modules` is a junction to the main checkout's copy. Never delete through it.
  - Never touch ports 3000/8090; e2e uses 3100/3101/3102/8091/8092. Kill processes by PID only, never by image name.
- Docs contain no device models, IPs other than loopback, paths or secret values.
- **Commits:** Turkish messages, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Push after each task. GitHub `ci` must be green.
- **Every behaviour change:**
  - comes with a test that fails before the change (record RED) and passes after (GREEN);
  - is followed by the full suites, all pristine (no warnings): edge `pytest -q`, `ruff check`; dashboard `npm run -s test:unit`, `lint`, `npx tsc --noEmit`, `npm run -s build`, and the full Playwright suite.

## Review Focus

1. **Panel session expiry still works exactly as before.** The existing e2e must stay green unedited:
   - `watch-ui.spec.ts` `AUTH` cases;
   - `safety-ui.spec.ts` "Oturum süresi doldu — alarmları görmek için yeniden giriş yapın.".
2. **Streaming survives the middleware.**
   - MJPEG `/views/*/stream` and alarm clip `Range` requests still stream through the new ASGI middleware. Use no `BaseHTTPMiddleware`.
   - Test: an existing stream test passes through `local_client`.
   - Test: one new test streams with `Host: localhost:8090`.
3. **IPv6 and port forms.** `[::1]:8090`, `LOCALHOST`, `127.0.0.1:65535` pass. `[::1`, `::1`, `localhost:99999x`, `a:b:c` get `403`. These are pytest cases in Task 1.
4. **Order of checks.** In no-token mode, a CORS preflight (`OPTIONS` with `Origin`) under a bad Host gets `403`, not a CORS `200`, so the Host middleware is outermost. pytest case in Task 1.
5. **Recovery.** A tile or page in the `"key"` state returns to normal once the analyzer answers again: mocked e2e in Task 2, flipping the route from `502 analyzer_key` to OK.

---

### Task 1: Analyzer — Host check, launch guard, recorder 401 → 502

**Files:**
- Create:
  - `services/edge/bantvision/analyzer/hostcheck.py`
  - `services/edge/tests/test_hostcheck.py`
- Modify:
  - `services/edge/bantvision/analyzer/app.py`, in `create_app` near the CORS middleware;
  - `services/edge/bantvision/analyzer/__main__.py`;
  - `services/edge/bantvision/live/api.py`, `_err` (~line 281);
  - `services/edge/tests/conftest.py`: add `local_client`, or create the file if absent;
  - every `TestClient(` site under `services/edge/tests/`:
    - `test_analyzer.py`, `test_drafts.py`, `test_live.py`, `test_viewer.py`, `test_views.py`;
    - check with `rg -n "TestClient\(" services/edge/tests`;
  - `docs/13-web-platform.md`: the "Güvenlik" line (~41) and the analyzer run notes.

**Interfaces:**
- Produces:
  - `host_name(header: str | None) -> str | None`, which mirrors `apps/dashboard/src/lib/hostCheck.mjs` `hostName` exactly: lower-case, port dropped, IPv6 without brackets, `None` when invalid;
  - `is_loopback_host(header: str | None) -> bool`;
  - `LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})`;
  - `class LoopbackHostMiddleware`, pure ASGI: `__init__(self, app: ASGIApp)` and `async __call__(scope, receive, send)`;
  - `HOST_REFUSED: str`, the R1 text.

- [ ] **Step 1: Write the failing tests** in `tests/test_hostcheck.py`.

  **(a) Parser table**, a port of every case in `apps/dashboard/src/lib/hostCheck.test.mjs`. Read it and mirror it. Add the Review Focus 3 cases.

  **(b) No-token app** via `local_client` and explicit `headers={"host": ...}`:
  - `GET /healthz` with each accepted form → 200: `localhost`, `localhost:8090`, `127.0.0.1:8090`, `[::1]:8090`, `LOCALHOST`;
  - with each refused form → 403 and `detail == HOST_REFUSED`: `testserver`, `evil.example`, `127.0.0.1.evil.example`, `localhost.`, `[::1`, `::1`, `a:b:c`, `localhost:99999x`;
  - same for `GET /api/v1/system/status` and `GET /openapi.json`;
  - plain `TestClient(app)` with the default `testserver` host → 403 (R9).

  **(c) Missing Host.** Build a raw ASGI scope with no `host` header and call the middleware directly → 403.

  **(d) CORS preflight** (Review Focus 4). Use `Settings(cors_origins=["http://localhost:3000"])`, no token, `OPTIONS /api/v1/live/sources` with `Origin` and `Access-Control-Request-Method`, `Host: evil.example` → 403.

  **(e) WebSocket.** Build the app, then add a test-only route with `app.add_api_websocket_route("/ws-test", handler)`. `client.websocket_connect("/ws-test", headers={"host": "evil.example"})` raises `WebSocketDisconnect` with code 1008. With `localhost` it connects.

  **(f) Token mode** (R2): `Settings(token="gizli")`, `Host: evil.example`:
  - `/healthz` → 200;
  - `/api/v1/system/status` without a token → 401, and with `Authorization: Bearer gizli` → 200.

  **(g) Streaming** (Review Focus 2). Pick the existing MJPEG/stream test that uses fakes. Add a variant with `Host: localhost:8090` that reads the first multipart chunk.

  **(h) Launch guard** (R3), with `monkeypatch` on `sys.argv`, env, and `uvicorn.run` → a recorder:
  - `--host 0.0.0.0` and no token → `SystemExit(2)`, the stderr text, `uvicorn.run` not called;
  - `--host 0.0.0.0` with `ANALYZER_TOKEN=x` → `uvicorn.run` is called;
  - default host → called;
  - `--host ::1` → called.

  **(i) Recorder `401` → `502`** (R4). Use `test_live.py`'s fake-recorder app (`_app_with_fakes`). Make the recorder raise `RecorderError.unauthorized()` for channels, then for `view_from_recorder` → 502 and `detail == "Kullanıcı adı ya da şifre hatalı."`.

- [ ] **Step 2: Run them and record RED.**
  `PYTHONPATH=<worktree>/services/edge <main venv python> -m pytest -q tests/test_hostcheck.py`. All new behaviour tests should fail.

- [ ] **Step 3: Implement.**
  - **`hostcheck.py`:** parser, constants, middleware.
    - For `http` and `websocket` scopes, read the `host` header from `scope["headers"]`.
    - Refuse with a 403 `JSONResponse(...)(scope, receive, send)` for http. For websocket, send `{"type": "websocket.close", "code": 1008}` after receiving `websocket.connect`.
    - Pass `lifespan` through untouched.
  - **`app.py`:** when `not settings.token`, call `app.add_middleware(LoopbackHostMiddleware)` AFTER the CORS `add_middleware`, so it is outermost. Add a comment on why.
  - **`__main__.py`:** apply R3 before `create_app`/`uvicorn.run`, using the same token source as `Settings`.
  - **`live/api.py` `_err`:** always 502 (R4). Update the docstring/comment.
  - **`conftest.py`:** `local_client`. Switch every `TestClient(` site to it. Keep the two explicit default-host tests from Step 1(b) and 1(e) on raw `TestClient`.

- [ ] **Step 4: Run the full edge suite and ruff and record GREEN.** Pristine: no new warnings.

- [ ] **Step 5: Docs.** docs/13 "Güvenlik" gets:
  - R1, including `/healthz` and the docs pages: no token → only loopback names; any other name → 403 with the message;
  - R2;
  - R3;
  - R4 (recorder password errors are 502).

  Keep the existing sentences that are still true.

- [ ] **Step 6: Commit.** Message: `Analiz sunucusu: anahtarsız kipte yalnızca bu bilgisayarın adları (Host denetimi, DNS yeniden bağlama); anahtarsız ağa açılmaz; kayıt cihazı şifre hatası 502`. Push. CI green.

### Task 2: Panel — refusal mapping, accurate messages, real-stack e2e

**Files:**
- Create:
  - `apps/dashboard/src/lib/analyzerRefusal.mjs`
  - `apps/dashboard/src/lib/analyzerRefusal.test.mjs`
  - `apps/dashboard/e2e/analyzer-key.spec.ts`
- Modify:
  - `apps/dashboard/package.json` (`test:unit` list);
  - `apps/dashboard/src/lib/analyzer.ts` (`passThrough`);
  - `apps/dashboard/src/lib/live.ts` (`ApiError`, `api()`);
  - `apps/dashboard/src/lib/views.ts` (`Problem`, `problemOf`);
  - `apps/dashboard/src/components/watch/ConnectionProblem.tsx`;
  - `apps/dashboard/src/components/live/AlarmCenter.tsx`;
  - `apps/dashboard/src/components/live/AlarmBanner.tsx`;
  - `apps/dashboard/src/components/watch/useDraft.ts` (comment only);
  - `apps/dashboard/playwright.config.ts` (R8);
  - `apps/dashboard/e2e/watch-ui.spec.ts` (mocked key/host cases + recovery);
  - `docs/13-web-platform.md`: Güvenlik, plus the panel proxy notes.

  Check every consumer of `ApiError.status === 401`:
  ```
  rg -n "status === 401|=== 401" apps/dashboard/src
  ```
  Also check how `/videos` shows job errors. It must show the R5 detail text.

**Interfaces:**
- Consumes the Task 1 analyzer statuses: own `401` (token), own `403` (Host), recorder errors `502`.
- Produces in `analyzerRefusal.mjs`:
  - `export const ANALYZER_REFUSALS = { analyzer_key: "<R5 401 text>", analyzer_host: "<R5 403 text>" }`;
  - `export function refusalFor(status)` → `{ code, detail } | null`: 401 → key, 403 → host, else null;
  - `export function problemFrom(status, code)` → `"auth" | "key" | "host" | "down"`. Its `"auth"` case means the PANEL's own 401: status 401 with no refusal code.

- [ ] **Step 1: Write the failing tests.**
  - **(a) `analyzerRefusal.test.mjs`:**
    - `refusalFor` for 401/403/404/500/502;
    - `problemFrom`: `(401, null)` → auth; `(502, "analyzer_key")` → key; `(502, "analyzer_host")` → host; `(502, null)` → down; `(503, null)` → down; `(401, "analyzer_key")` → key; an unknown code → down;
    - the texts equal R5 verbatim.

    Add the file to `test:unit`.
  - **(b) `analyzer-key.spec.ts`**, real stack on `http://127.0.0.1:3102` (R8):
    - `GET /api/live/views` → 502, JSON `code === "analyzer_key"`, `detail` = the R5 text;
    - `GET /api/jobs` → same;
    - `/watch` shows the R5 key text. There is no "Giriş yap" link and no "Oturum süresi doldu" anywhere on the page;
    - the alarm banner warning reads `Alarmlar alınamıyor — <key text>` after the warning threshold. Use `page.clock` if the threshold is time-based;
    - the status bar shows the analyzer's auth state. Read `StatusBar.tsx` for the exact text.
  - **(c) `watch-ui.spec.ts`, mocked** (existing `mock` helpers):
    - `**/api/live/**` → `502 {detail: <host text>, code: "analyzer_host"}`: the watch status line shows the host text, with no login link;
    - flip the route to the normal fixtures: the problem line disappears (Review Focus 5);
    - same for SingleCamera (double-click a tile) with `analyzer_key`.

- [ ] **Step 2: Run and record RED.**
  - `npm run -s test:unit`
  - `npx playwright test e2e/analyzer-key.spec.ts e2e/watch-ui.spec.ts -g "anahtar|adres"`

- [ ] **Step 3: Implement R5–R7.**
  - **`passThrough`:**
    - on 401/403, `await res.body?.cancel()` or equivalent;
    - `logRateLimited(new Error(\`HTTP ${status}\`), "analiz sunucusu panelin isteğini reddetti")`;
    - `Response.json({detail, code}, {status: 502})`.

    It may become `async`. If so, update every caller (`return await passThrough(...)` inside the existing `try`).
  - **`ApiError`:** `constructor(message, status, code: string | null = null)`. `api()` passes `typeof body?.code === "string" ? body.code : null`.
  - **`problemOf`:** delegates to `problemFrom`.
  - **`ConnectionProblem`, `AlarmCenter`, `AlarmBanner`:** per R7. Import the texts from `analyzerRefusal.mjs`; no duplicated strings.
  - **`useDraft`:** comment only.

- [ ] **Step 4: Run the full verification and record GREEN:** `test:unit`, `lint`, `tsc`, `build`, FULL Playwright. The existing session-expiry e2e stays unedited and green (Review Focus 1).

- [ ] **Step 5: Docs.** docs/13 "Güvenlik":
  - the proxy maps analyzer 401/403 → 502 + `code`;
  - what the pages show;
  - the panel's own 401 is unchanged.

  Also update the `/system/status` "auth" note if its wording claims 401/403 means only a wrong token: 403 now also means a refused Host.

- [ ] **Step 6: Commit.** Message: `Panel: analiz sunucusu anahtar/adres reddi oturum süresi gibi görünmez (502 + kod, doğru ileti, giriş bağlantısı yok)`. Push. CI green.
