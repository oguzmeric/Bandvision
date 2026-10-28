# Sade Arayüz ve İzleme Sekmeleri Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The web panel gets a TRASSIR-style shell: a written, grouped left menu, a bottom status strip and plain pages. The İzleme page becomes "Canlı izleme" with template tabs, a "Şablon editörü" menu and N×M grids of up to 128 tiles.

**Architecture:**
- **Contract:** layout ids gain a `"<rows>x<cols>"` form, resolved by the same `layout_by_id` on the analyzer and by a pure TS helper in the panel.
- **Analyzer:** gets in-memory **drafts** (unsaved templates that the existing mosaic/status endpoints can stream), a configurable reader limit (default 128) and a `/system/status` endpoint.
- **Panel:** a new shell (`Sidebar` + `StatusBar`); every page restyled. The watch page is rebuilt around tabs + editor menu, with its pure editing logic in a unit-tested `.mjs` module.

**Tech Stack:** Next.js 15 (App Router, Tailwind), Playwright, node --test; Python 3.11+ FastAPI analyzer, pytest, ruff; JSON Schema contracts.

**Spec:** `docs/superpowers/specs/2026-10-28-sade-arayuz-design.md` (binding). Mockups the user approved: `.superpowers/brainstorm/931-1793177385/content/duzen.html`, `sayfalar.html` (layout reference only; not shipped).

## Global Constraints

- **Language:** user-visible text is Turkish; code identifiers English; comments match the surrounding file (Turkish).
- **Contracts are the single source of truth.** A layout/template format change updates `contracts/`, `docs/02-contracts.md` §8, the Python catalog and the panel in the same branch. The template schema stays version 1 (additive change).
- **N×M id:** `"<rows>x<cols>"`, rows and cols 1–16, rows×cols ≤ 128, equal cells in row-major order, canvas ratio assumes 16:9 tiles (same rule as today). `"4x4"` is valid (same geometry as `"16"`).
- **Editor:** 10 layout buttons in this order — 1, 2×2, 3×3, 4×4, 1+5, 1+7, 4×3, 5×5, 8×8, N×M.
  - Ids: `"1"`, `"4"`, `"9"`, `"16"`, `"6"`, `"8"`, `"12"`, `"5x5"`, `"8x8"`, and the N×M input.
  - Catalog layouts `"2"` and `"3"` keep working in saved templates but have no button.
  - A new template opens as 2×2 (`"4"`).
- **Limits:** a template has at most 128 tiles; the analyzer sub-stream reader limit defaults to 128 (env `BV_WATCH_MAX_SUB`), main stays 2. Over the limit a tile shows "Sınır aşıldı (en çok N kamera)."; saving is never refused for it.
- **Drafts:** unsaved edits live on the analyzer as drafts, are deleted after 10 min without a stream/status request, are never written to disk, and reuse the same camera readers (shared cameras never reconnect).
- **No new npm dependencies.** Python may add `psutil` to the `analyzer` extra.
- **Menu groups and items exactly as the spec's "Menü grupları":**
  - "Yangın ve duman", "Cihaz ayarları", "Lisans" are grey and say "yakında" when clicked.
  - "Kalite kontrol" and "Raporlar" stay "yakında" as today.
- **Tests never connect to real cameras or the network** (existing pytest/Playwright file-source setup).
- **Environment:**
  - Work in worktree `C:/Users/MSI-LAPTOP/bantvision-arayuz`, branch `sade-arayuz` from `main`.
  - Never touch ports 3000/8090 (e2e uses 3100/3101/8091). Kill processes by PID only.
  - Python runs from the main venv with `PYTHONPATH=<worktree>/services/edge`; never `pip install -e` from the worktree. If `psutil` is missing, install it into the main venv with plain `pip install psutil`.
- **Commits:** Turkish messages, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Push the branch after each task and keep GitHub `ci` green.

## Review Focus

1. **Templates saved before this change** (layouts `"2"`, `"3"`, `"6"`…) open, stream and edit unchanged in the new page. Test: `watch-ui` e2e opens a fixture template with layout `"3"` and shows 3 tiles (Task 7).
2. **The analyzer restarts while a draft is open** (draft id now 404). The editor silently recreates the draft from its local state; the grid keeps streaming without an error banner. Test: `templateEdit` unit + `watch-ui` e2e where the draft route returns 404 once (Task 7).
3. **A 128-tile template on a reader limit below 128.** Excess tiles show "Sınır aşıldı…", the page stays responsive, saving succeeds. Test: pytest with `BV_WATCH_MAX_SUB=4` and a 6x8 draft → status has 4 live/connecting and 44 "Sınır aşıldı" (Task 2).
4. **Leaving with unsaved edits** (tab switch, menu click, browser reload) asks "Kaydedilmedi, çıkılsın mı?"; cancelling keeps the edits. Test: `watch-ui` e2e (Task 7).
5. **Phone-width screen** (390 px): the menu collapses behind a button, template tabs scroll horizontally, nothing overflows the page. Test: `shell` e2e at 390×844 (Task 4) and `watch-ui` e2e (Task 7).

---

### Task 1: N×M layout ids in the contract and the analyzer catalog

**Files:**
- Modify: `contracts/view-template.schema.json` (`layout`), `docs/02-contracts.md` §8, `tools/tests/test_contracts.py`, `services/edge/bantvision/live/layouts.py`, `services/edge/bantvision/live/api.py` (`MAX_TILES` users), `services/edge/tests/test_layouts.py`
- Create: `contracts/examples/view-template-nxm.json`, `apps/dashboard/src/lib/layoutGrid.mjs`, `apps/dashboard/src/lib/layoutGrid.d.mts`, `apps/dashboard/src/lib/layoutGrid.test.mjs`
- Modify: `apps/dashboard/package.json` (`test:unit` adds `src/lib/layoutGrid.test.mjs`)

**Interfaces:**
- Produces (Python):
  - `layouts.MAX_TILES = 128`;
  - `layouts.layout_by_id(layout_id: str) -> Layout | None` — catalog ids, or `"<r>x<c>"` → `Layout(id, name=f"{r}×{c}", cols=c, rows=r, cells=row-major 1×1)`;
  - `layouts.parse_grid(layout_id: str) -> tuple[int, int] | None`.
- Produces (TS):
  - `layoutFor(id: string, catalog: ViewLayout[]): ViewLayout | null`
  - `parseGrid(id: string): {rows: number, cols: number} | null`
  - `gridId(rows: number, cols: number): string`
  - `MAX_TILES = 128`

- [ ] **Step 1: Failing tests.** In `services/edge/tests/test_layouts.py`:
  - `test_grid_id_resolves`: `layout_by_id("6x8")` has `rows == 6`, `cols == 8`, 48 cells, cell 9 == `(1, 1, 1, 1)`, name `"6×8"`.
  - `test_grid_4x4_matches_catalog_16`: same `cells`, `cols` and `rows` as `layout_by_id("16")`.
  - `test_grid_rejects`: `"0x5"`, `"17x2"`, `"12x12"` (144), `"6X8"`, `" 6x8"`, `"6x"`, `"x8"`, `"06x8"` → `None`.
  - `test_catalog_ids_unchanged`.

  In `tools/tests/test_contracts.py`: replace the enum-equality test with `test_template_layout_accepts_catalog_and_grid_ids` (each catalog id and `"6x8"` validate; `"17x2"`, `"5"` fail) and keep `test_view_layout_ids_are_the_agreed_set`. The new example `view-template-nxm.json` (layout `"6x8"`, 48 tiles, a few cameras) must validate.

  In `layoutGrid.test.mjs`: the same accept/reject cases for `parseGrid`; `layoutFor("6x8", [])` geometry; `layoutFor("3", catalog)` returns the catalog entry; `gridId(5, 5) === "5x5"`.
- [ ] **Step 2: Run, verify they fail.**
  ```bash
  PYTHONPATH=$PWD/services/edge /c/Users/MSI-LAPTOP/bantvision/services/edge/.venv/Scripts/python -m pytest -q services/edge/tests/test_layouts.py tools/tests/test_contracts.py -k "layout or grid"
  ```
  and `cd apps/dashboard && npm run -s test:unit`.
- [ ] **Step 3: Implement.**
  - Schema `layout`: `{"anyOf": [{"enum": [catalog ids]}, {"type": "string", "pattern": "^([1-9]|1[0-6])x([1-9]|1[0-6])$"}]}`. The 128 product rule is enforced by the analyzer (schema note in §8).
  - `tiles.maxItems` becomes 128.
  - Python `parse_grid` uses a full-match regex plus the product check; `MAX_TILES` users in `api.py` follow automatically.
  - TS mirrors it.
  - `docs/02-contracts.md` §8 documents the N×M form, the 128 limit, that iPhone does not read it, and the new example.
- [ ] **Step 4: Run all three suites → pass.** Also run `ruff check services/edge`.
- [ ] **Step 5: Commit** `İzleme: N×M düzen kimliği (en çok 128 kutu) sözleşmede, analiz sunucusunda ve panelde`.

### Task 2: Drafts and the configurable reader limit on the analyzer

**Files:**
- Create: `services/edge/bantvision/live/drafts.py`, `services/edge/tests/test_drafts.py`
- Modify: `services/edge/bantvision/live/viewer.py` (`MAX_SUB` from env, message), `services/edge/bantvision/live/api.py` (draft routes; `LiveManager` wiring; stream/status accept draft ids), `services/edge/tests/test_live.py`

**Interfaces:**
- Consumes: Task 1 `layout_by_id`, `MAX_TILES`.
- Produces:
  - `DraftStore(clock: Callable[[], float] = time.monotonic, idle_s: float = 600.0)` with:
    - `create(layout: str, tiles: list[dict | None]) -> dict`, where the id is `"draft-" + 12 hex`;
    - `update(draft_id, layout, tiles) -> dict | None`;
    - `get(draft_id) -> dict | None` (touches);
    - `delete(draft_id) -> bool`;
    - `sweep() -> int`.

    Draft dict: `{id, layout, tiles, name: "Taslak", createdAt, updatedAt}`.
  - HTTP routes:
    - `POST /api/v1/live/views/drafts` (201, body `{layout, tiles}`, same tile validation as templates minus name);
    - `PUT /api/v1/live/views/drafts/{id}` (404 when gone);
    - `DELETE /api/v1/live/views/drafts/{id}` (204).
  - `GET /views/{id}/stream` and `/views/{id}/status` resolve `drafts.get(id)` before `views.get(id)`.
  - `viewer.MAX_SUB` is read from `BV_WATCH_MAX_SUB` (int ≥ 1, default 128) at import. The sub limit message is `f"Sınır aşıldı (en çok {MAX_SUB} kamera)."`.

- [ ] **Step 1: Failing tests.**
  - `test_drafts.py` (fake clock):
    - create → get round-trip;
    - update changes layout/tiles and bumps `updatedAt`;
    - unknown layout and tile-count mismatch raise `ValueError` with the Turkish texts `TemplateStore`/`ViewStore` already use;
    - a draft untouched for 600 s is removed by `sweep`, while a `get` at 599 s keeps it alive;
    - drafts are never written under the data dir (assert directory empty).
  - `test_live.py`:
    - `test_draft_stream_and_status_use_draft` (file sources, `limit` query): POST draft → `/views/{draftId}/status` lists its tiles → PUT changes layout → status follows → DELETE → 404.
    - `test_reader_limit_env` (monkeypatch `viewer.MAX_SUB = 4` via reload, or a constructor arg if the implementer prefers): a `"6x8"` draft with 48 distinct file sources → status has exactly 4 non-limit tiles and 44 messages starting "Sınır aşıldı (en çok 4 kamera)".
    - Saving a 48-tile template via `POST /views` succeeds.
- [ ] **Step 2: Run, verify they fail.**
  ```bash
  … pytest -q services/edge/tests/test_drafts.py services/edge/tests/test_live.py -k "draft or limit"
  ```
- [ ] **Step 3: Implement.**
  - `DraftStore` is in-memory with a lock.
  - `LiveManager` owns `drafts`, and its reaper/sweep calls `drafts.sweep()`.
  - `MosaicHub` is constructed with a lookup `lambda vid: drafts.get(vid) or views.get(vid)`.
  - Shared readers come for free (same `ViewHub`).
- [ ] **Step 4: Run** the focused tests, then the full edge suite once and `ruff check`.
- [ ] **Step 5: Commit** `İzleme: kaydedilmemiş şablon taslağı canlı akışla, kamera sınırı ayarlanabilir (varsayılan 128)`.

### Task 3: System status endpoint and panel proxy

**Files:**
- Modify: `services/edge/bantvision/analyzer/app.py`, `services/edge/pyproject.toml` (`psutil>=5.9` in `analyzer`), `services/edge/tests/test_analyzer_app.py` (or the existing app test file)
- Create: `apps/dashboard/src/app/api/system/route.ts`

**Interfaces:**
- Produces:
  - `GET /api/v1/system/status` (auth like other `/api/v1` routes) → `{"cpuPercent": float, "uptimeS": int, "version": str}`. `version` comes from `importlib.metadata.version("bantvision")` or `"?"`. `cpuPercent` is `psutil.cpu_percent(interval=None)`, rounded to 1 decimal.
  - Panel `GET /api/system`:
    - analyzer reachable → `{"analyzer": "up", cpuPercent, uptimeS, analyzerVersion, panelVersion}` (`panelVersion` from `package.json`);
    - analyzer unreachable → `{"analyzer": "down"}` with status 200;
    - session expired → the existing 401 handling of panel API routes.
- [ ] **Step 1: Failing test:** `test_system_status_shape` checks the keys and types, and that it is unauthorized without the token when a token is configured.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** (follow the existing route/proxy pattern in `src/app/api/live/...` and `lib/analyzer.ts`).
- [ ] **Step 4: Run → pass;** `npm run -s lint && npx tsc --noEmit`.
- [ ] **Step 5: Commit** `Sistem durumu: işlemci yükü, çalışma süresi, sürüm (analiz sunucusu + panel vekili)`.

### Task 4: New shell — grouped text menu, status strip, plain page header

**Files:**
- Create: `apps/dashboard/src/lib/nav.ts`, `apps/dashboard/src/components/StatusBar.tsx`, `apps/dashboard/src/app/(panel)/about/page.tsx`, `apps/dashboard/e2e/shell.spec.ts`
- Modify: `apps/dashboard/src/components/Sidebar.tsx` (rewrite), `apps/dashboard/src/app/(panel)/layout.tsx`, `apps/dashboard/src/components/PageHeader.tsx`, `apps/dashboard/src/app/globals.css`

**Interfaces:**
- Consumes: Task 3 `/api/system`.
- Produces:
  - `NAV: NavGroup[]` in `nav.ts`, where `NavGroup = {title: string, items: NavItem[]}` and `NavItem = {label: string, href: string | null, soon?: boolean}`. It holds exactly the spec's groups and items, in order. Analiz hrefs: `/live?tur=urun`, `/live?tur=kisi`, `/live?tur=guvenlik`, `/videos`.
  - `PageHeader({title, text?})` — a plain heading row (no logo, no eyebrow pill). Callers drop `eyebrow`.
  - Plain style classes in `globals.css`: `.pl-section` (titled bordered block), `.pl-row` (label/value form row), `.pl-table`, `.pl-btn`, `.pl-input`. Palette: grey-blue, 1 px borders, no shadows, 2–4 px radius.

- [ ] **Step 1: Failing e2e `shell.spec.ts`:**
  - Every non-soon menu item navigates to its page, with a heading visible.
  - Soon items show "yakında" and do not navigate.
  - The current page's item has `aria-current="page"`.
  - Groups collapse and expand.
  - At 390×844 the menu is hidden behind a "Menü" button, opens over the content and closes on navigation; `document.documentElement.scrollWidth <= 390`.
  - The status strip shows "Analiz sunucusu: çalışıyor" and an "İşlemci %" value. With `/api/system` routed to `{"analyzer":"down"}` it shows "Analiz sunucusu: kapalı" and "—".
  - `/about` shows the panel and analyzer versions.
- [ ] **Step 2: Run** `npx playwright test e2e/shell.spec.ts` → fail.
- [ ] **Step 3: Implement.**
  - Sidebar: 230 px written menu (logo + "BandVision" at top, logout at bottom as today). Group headers are buttons toggling their list, and the collapse state is kept in `localStorage` `bv.nav.collapsed`.
  - Layout grid: `[230px_1fr]` on desktop, single column below `md`.
  - StatusBar polls `/api/system` every 5 s.
  - Ekran kartı slot: "Ekran kartı: —". Lisans is not shown.
- [ ] **Step 4: Run** `shell.spec.ts` and the full Playwright suite. Fix other specs that relied on the old icon sidebar or `PageHeader` eyebrow (selectors only, no behaviour change).
- [ ] **Step 5: Commit** `Panel: yazılı, gruplu sol menü, durum şeridi, Hakkında sayfası`.

### Task 5: Analiz pages as filtered views of Canlı sayım

**Files:**
- Modify: `apps/dashboard/src/app/(panel)/live/page.tsx`, `apps/dashboard/src/components/live/LiveView.tsx`, `apps/dashboard/src/components/live/StartSessionDialog.tsx`, `apps/dashboard/e2e/live.spec.ts`
- Create: `apps/dashboard/src/lib/analysisKind.ts`

**Interfaces:**
- Produces:
  - `type AnalysisKind = "urun" | "kisi" | "guvenlik"`
  - `kindOfMode(mode: CountMode): AnalysisKind` — `blob`/`linescan` → urun, `detect` → kisi, `safety` → guvenlik.
  - `KIND_TITLE: Record<AnalysisKind, string>` = Ürün sayımı / Kişi sayımı / Güvenlik alarmı.
  - `parseKind(q: string | null): AnalysisKind | null`.

- [ ] **Step 1: Failing e2e (live.spec):**
  - `/live?tur=kisi` lists only sessions whose profile `countMode` is `detect`, and the page title is "Kişi sayımı".
  - "Yeni analiz" there opens the start dialog with only person-counting profiles offered.
  - `/live` without `tur` still lists all sessions (old links work).
  - An invalid `tur` behaves like no filter.
  - The menu item "Kişi sayımı" is `aria-current` on `/live?tur=kisi`.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** with the existing session data; no analyzer change.
- [ ] **Step 4: Run** `live.spec.ts`, then the full suite.
- [ ] **Step 5: Commit** `Panel: Ürün sayımı, Kişi sayımı, Güvenlik alarmı menüleri (Canlı sayımın türe süzülmüş hali)`.

### Task 6: Plain restyle of every existing page

**Files:**
- Modify (style only): every page under `apps/dashboard/src/app/(panel)/` and the components they render (`components/live/*`, `components/video/*`, `components/settings/*`, `components/geometry/*`).
- Not `components/watch/*`, which Task 7 rebuilds.
- Create: `apps/dashboard/src/lib/plainStyle.test.mjs`.

**Interfaces:**
- Consumes: Task 4 `.pl-*` classes and `PageHeader({title, text?})`.

- [ ] **Step 1: Failing guard test `plainStyle.test.mjs`** (add to `test:unit`). It scans `src/app/(panel)/**/*.tsx` and `src/components/{live,video,settings,geometry}/**/*.tsx` and fails on any of the old card idioms: `rounded-3xl`, `rounded-2xl`, `shadow-`, `bg-white/70`, `backdrop-blur`. Each hit is reported with file:line.
- [ ] **Step 2: Run** `npm run -s test:unit` → fail, listing the current hits.
- [ ] **Step 3: Restyle.** Replace card wrappers with `.pl-section`, label/value pairs with `.pl-row`, lists with `.pl-table` where tabular, buttons with `.pl-btn`. Keep every control, id, aria label and behaviour (no logic changes).
- [ ] **Step 4: Run** `test:unit`, `lint`, `tsc`, `build`, and the full Playwright suite → all green. Selector fixes only where a test matched removed wrapper text.
- [ ] **Step 5: Commit** `Panel: tüm sayfalar sade görünümde (kartlar yerine düz bölümler, form satırları, tablolar)`.

### Task 7: Canlı izleme — template tabs, Şablon editörü, N×M, live drafts

**Files:**
- Create:
  - `apps/dashboard/src/lib/templateEdit.mjs`, `templateEdit.d.mts`, `templateEdit.test.mjs` (added to `test:unit`);
  - `apps/dashboard/src/components/watch/TemplateTabs.tsx`;
  - `apps/dashboard/src/components/watch/EditorMenu.tsx`;
  - `apps/dashboard/src/components/watch/useDraft.ts`.
- Modify: `apps/dashboard/src/components/watch/WatchView.tsx` (rebuilt), `CameraList.tsx` (right-side list with status dots, draggable), `TileOverlay.tsx` (drop target, tap-select, right-click "Boşalt"), `apps/dashboard/src/app/(panel)/watch/page.tsx` (title "Canlı izleme"), `apps/dashboard/src/lib/views.ts` (draft API types), `e2e/watch-ui.spec.ts`, `e2e/watch.spec.ts`.
- Delete: `ViewEditor.tsx` once its functions live in the new UI.

**Interfaces:**
- Consumes: Task 1 `layoutFor`, `parseGrid`, `gridId`, `MAX_TILES`; Task 2 draft routes (via the existing `api()` helper: `views/drafts`); Task 4 shell.
- Produces (`templateEdit.mjs`, pure):
  - `EDITOR_LAYOUTS` — the 10 button ids in order; the last entry is `"nxm"`.
  - `newDraft(catalog): Draft` with layout `"4"` and 4 null tiles. `Draft = {layout, tiles, name}`.
  - `applyLayout(draft, layoutId, catalog): {draft, dropped}` — reuses `retile`.
  - `assign(draft, index, ref | null): Draft` — a ref already in another tile moves (no duplicates).
  - `history`: `initHistory(draft)`, `push(h, draft)`, `undo(h)`, `redo(h)`, `canUndo(h)`, `canRedo(h)`, with a 50-step cap.
  - `isDirty(h, saved: Draft | null): boolean`.
  - `validateGrid(rows, cols): string | null` — Turkish error, e.g. "En çok 128 kutu (16×9 = 144)." and "Satır ve sütun 1–16 arasında olmalı.".

- [ ] **Step 1: Failing unit tests** in `templateEdit.test.mjs` for every function above:
  - undo/redo order and the cap;
  - `assign` moves a duplicate;
  - `applyLayout("8x8")` keeps the first 4 cameras;
  - `validateGrid(16, 9)` gives the 144 message and `validateGrid(6, 8)` gives null;
  - `isDirty` after undo back to the saved state is false.
- [ ] **Step 2: Failing e2e (`watch-ui.spec.ts`, mocked API as today):**
  - Templates appear as tabs; clicking switches; "+" creates "Yeni şablon" as 2×2; the selected tab is remembered across reload.
  - Right-click on a tab gives Yeniden adlandır / Kopyala / Sil (Sil asks for confirmation).
  - "Şablon editörü" opens the menu with Yeni şablon / Geri al / Yinele / Kaydet / Farklı kaydet… and the 10 layout buttons. N×M with 6 and 8 gives 48 tiles; 16 and 9 shows "En çok 128 kutu…" and nothing changes.
  - Dragging a camera from the right list onto a tile assigns it. Tap-select (tap tile, then camera) works. Right-click on a tile → Boşalt.
  - While editing, the grid image `src` points at `/api/live/views/draft-…/stream`. "Kaydet" PUTs the template, and the stream then points at the template id.
  - With unsaved edits, switching tab and clicking a menu item both ask "Kaydedilmedi, çıkılsın mı?". Cancel keeps the edits; `beforeunload` is registered.
  - Draft route returns 404 once → a new draft is POSTed silently and no error is shown (Review Focus 2).
  - A fixture template with layout `"3"` shows 3 tiles (Review Focus 1).
  - Double-click a tile opens the single camera; double-click closes it.
  - The existing video wall, "Tüm kanallardan şablon" (now "NVR'dan şablon" in the editor menu) and phone landscape still work.
  - At 390 px the tabs scroll horizontally without page overflow (Review Focus 5).
- [ ] **Step 3: Run** `npm run -s test:unit` and `npx playwright test e2e/watch-ui.spec.ts` → fail.
- [ ] **Step 4: Implement.**
  - `useDraft(saved, catalog)` creates or updates the analyzer draft (debounced 300 ms) whenever the edited state differs from the saved template. While a draft exists, the grid streams it; on save or discard it deletes the draft. It recreates the draft on a 404.
  - Keep `TileOverlay` badges, the alarm frame and the alarm window as they are.
  - Unsaved-leave guard: `beforeunload`, plus a confirm before tab switches and before Next `Link` navigations from the shell. Expose `useUnsavedGuard()` and have `Sidebar` links consult it.
- [ ] **Step 5: Run** unit, the whole `watch-ui`/`watch` specs, then the full Playwright suite, `lint`, `tsc`, `build`.
- [ ] **Step 6: Commit** (several focused commits, e.g. logic module; tabs; editor menu + drafts; camera list DnD; e2e).

### Task 8: Real-stack e2e, docs, measurement note

**Files:**
- Modify: `apps/dashboard/e2e/watch.spec.ts` (real analyzer with file sources: create a `"5x5"` draft → stream returns JPEG frames → save → template stream), `docs/13-web-platform.md` (new shell, menu map old→new, Canlı izleme, drafts API, reader limit env, `/system/status`), `docs/12-durum.md` (new section: what shipped, "Ölçüm BEKLİYOR" for 16/32/64 tiles on the office NVR, no performance claims), `apps/dashboard/README.md` (menu overview), spec status line → "uygulandı (ölçüm bekliyor)".

- [ ] **Step 1: Write the real-stack e2e;** run it against the e2e analyzer (8091) → pass.
- [ ] **Step 2: Update the docs** listed above (Turkish; no device models, IPs or secret names).
- [ ] **Step 3: Full verification:**
  - edge `pytest -q` (full) and `ruff check`;
  - `tools` contract tests;
  - dashboard `test:unit`, `lint`, `tsc`, `build`, full Playwright;
  - push, and GitHub `ci` green.
- [ ] **Step 4: Commit** `Belgeler: sade arayüz, Canlı izleme sekmeleri, N×M (ölçüm bekliyor)`.

### Task 9 (controller, with the user): merge and measure

- After the final review: merge to `main`, push, restart the user's panel via the desktop shortcut.
- With the user on the office NVR: 16/32/64-tile templates, analyzer CPU and per-tile fps → `docs/12-durum.md`.
