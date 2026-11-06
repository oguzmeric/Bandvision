# Canlı izleme: sıralı gösterim, klavye kısayolları, sekme sırası — Plan

**Goal:** Bring three viewing features from Ajax PRO Desktop's video wall to the panel's "Canlı izleme" page. None of them needs recorder archive access.
1. **Sıralı gösterim** (camera tour).
2. **Klavye kısayolları.**
3. **Reordering template tabs by drag and drop.**

**Why:** The user asked us to take over Ajax's viewing-side UI features ("ajax systemden görüntüleme tarafında alabileceğimiz özellikler … alalım", 2026-11-06). Archive playback, synced timelines and clip export come later. They need the recorder brands, which the user has not given yet.

**Spec:** none separate. The user delegated ("devam et uygula"). The rulings below are binding.

## Rulings

**R1. Sıralı gösterim (tour)**
- **What it does:** cycles the single-camera view through the current template's filled tiles, in tile order. Empty tiles are skipped.
- **Starting:**
  - The template editor menu (`EditorMenu`) gets a new item, `Sıralı gösterim…`.
  - It opens a small dialog with an interval select: 5, 10, 20, 30 or 60 s, default 10.
  - The dialog has `Başlat` and `İptal` buttons.
- **Running:**
  - The view enters single-camera mode on the first filled tile.
  - It advances every interval and wraps to the start.
- **Overlay:** a small bar in a corner shows:
  - `Sıralı gösterim · <camera name> · <n>/<total>`;
  - a pause/resume button, `Duraklat` / `Sürdür`;
  - a stop button, `Durdur`.
- **Stopping:** Stop, Esc, a template change, or a tab switch end the tour. The grid comes back.
- **Fewer than 2 filled tiles:** the menu item is disabled, with the title `Sırayla göstermek için en az 2 kamera gerekir.`
- **Remembered:** the interval, per browser in a cookie (pattern of `src/lib/nav.ts`). Do not use localStorage: the panel's port can change.
- **Not persisted:** the tour state itself. A reload shows the grid.
- **Out of scope:** a single tile that rotates through several cameras (it would need a template schema change).

**R2. Klavye kısayolları** on the Canlı izleme page.
- **When they are off:** shortcuts are ignored while focus is in an input, select, textarea or contenteditable, or while a dialog or menu is open.
- **The keys:**
  - `F`: on the grid, enlarge the tile under the mouse, or the last-clicked tile, to single-camera view. In single-camera view, return to the grid. This is the same action as double-click.
  - `Esc`: leave single-camera view, or stop the tour.
  - `Space`: during a tour, pause or resume. Otherwise do nothing, and do not scroll the page.
  - `←` / `→`: in single-camera view (tour or not), previous or next filled tile. During a tour this also resets the interval timer.
  - `1`–`9`: switch to the nth template tab.
  - `?`: open or close a small help panel listing the shortcuts in Turkish.
- **Help:** a `Kısayollar` button in the page header also opens the help panel.

**R3. Reordering template tabs.**
- **Drag:** `TemplateTabs` tabs are draggable. Dropping on another tab moves the dragged tab to that position.
- **Keyboard and touch alternative:** the tab context menu (right-click / long-press, existing) gets `Sola taşı` and `Sağa taşı`. They are disabled at the ends.
- **Stored on the server:** the order is shared by every browser and the phone.
  - New analyzer endpoint `PUT /api/v1/live/views/order` with body `{"ids": [...]}`.
  - The body must be exactly the set of saved template ids, with no duplicates and none missing. Otherwise `422` with `Şablon listesi değişmiş; sayfayı yenileyip yeniden deneyin.`
  - It reorders `views.json`, using the existing atomic write and busy handling in `live/views.py`.
  - It returns the new list.
  - Drafts (unsaved templates) are not part of the order. They keep their current placement.
- **Panel side:**
  - It goes through the existing `/api/live/[...path]` proxy.
  - It updates optimistically, and reverts with the error line on failure.
- **Docs:** the template file schema is unchanged; its order is the list order. Document the endpoint in `docs/13-web-platform.md` (the API table and the Çoklu izleme section).

## Global constraints
- **Language:** user-visible text in Turkish; identifiers in English; comments match the file.
- **Python:**
  - Use `C:/Users/MSI-LAPTOP/bantvision/services/edge/.venv/Scripts/python.exe` from the worktree's `services/edge`, with `PYTHONPATH=<worktree>/services/edge`.
  - API tests use `local_client`.
  - Run `ruff` in CI form: `cd services/edge && <python> -m ruff check . ../../tools`.
- **Dashboard:**
  - Run `npm run -s test:unit`, `npx tsc --noEmit`, `npm run -s lint` and `npm run -s build`.
  - Run Playwright with `PYTHON=<python>`.
  - `node_modules` is a junction: never `npm install`.
- **Pure logic in tested `.mjs` modules** (added to `test:unit`):
  - tour stepping (next and previous with wrap, skipping empties);
  - shortcut key mapping, including the focus/dialog guard;
  - tab reorder.
- **e2e:**
  - Shortcuts: F, Esc, arrows, number keys, and `?` help.
  - Tour cycling: use Playwright's `page.clock` to advance time, plus pause and stop.
  - Tab drag reorder, and the menu move, both persisting after a reload.
  - A reorder conflict returns 422.
- **Ports:** never touch ports 3000, 3001, 3300 or 8090. Never kill processes by image name.
- **Commits:** Turkish subject, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
