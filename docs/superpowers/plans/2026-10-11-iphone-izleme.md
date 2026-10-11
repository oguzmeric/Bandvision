# iPhone Multi-Camera Watch (device list + template grid) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The iPhone app gets a device list (several NVRs and IP cameras) and a new **İzleme** tab.
- The İzleme tab shows template grids (layouts 1/2/3/4/6/8/9/12/16) with live video taken directly from the NVR/cameras.
- Counting picks its camera from the same list.

**Architecture:**
- **`DeviceStore`** replaces the single `NetworkCameraConfig` setting. The old setting is migrated once.
- **`TemplateStore`** keeps templates in the contract format.
- **`CameraHub`** opens one RTSP reader per camera and quality, and fans frames out to tiles. Limits: 16 sub + 1 main. Idle readers close after 5 s. The counted camera is fed from the counting stream.
- **Display:** tiles show frames through `AVSampleBufferDisplayLayer` with no pixel copy.
- **Structure:** all control logic is `@MainActor`. Frames travel through lock-protected fan-out objects.

**Tech Stack:** Swift 5 language mode, SwiftUI, iOS 17+, VideoToolbox / AVFoundation / CoreMedia, XCTest, XcodeGen. No external dependencies.

**Spec:** `docs/superpowers/specs/2026-10-11-iphone-izleme-design.md` (binding). Layout/template contract: `docs/02-contracts.md` §8, `contracts/view-layouts.json`, `contracts/view-template.schema.json`.

## Global Constraints

- iOS: Swift 5 language mode, SwiftUI, iOS 17+, no external dependencies.
- User-visible text is **Turkish**. Code identifiers are English. Comments may be Turkish or English; match the surrounding file (this codebase comments in Turkish).
- **No Xcode on this machine.** Swift is compiled only on GitHub Actions.
  - Every task ends with a push to branch `iphone-izleme` and a green `ios` workflow run.
  - The `ios` workflow runs an unsigned Release build, then a strict-concurrency build (`SWIFT_STRICT_CONCURRENCY=complete`, **zero warnings allowed**), then `BantSayacTests` on a simulator.
  - Concurrency rules:
    - Control logic is `@MainActor`.
    - Cross-thread classes are `final class …: @unchecked Sendable` with an `NSLock`.
    - Closures that cross threads are `@Sendable`.
    - Use `UncheckedSendable` (defined in `Vision/FrameProcessor.swift`) to carry a `CVPixelBuffer` or `CMSampleBuffer` into a dispatch closure.
- **Waiting for CI.** Run this in the background (Bash `run_in_background: true`; foreground `sleep` is blocked):
  ```bash
  cd /c/Users/MSI-LAPTOP/bantvision-iphone && SHA=$(git rev-parse HEAD) && git push -q -u origin iphone-izleme && \
  for i in $(seq 1 60); do RUN=$(gh run list --repo oguzmeric/Bandvision --workflow ios --branch iphone-izleme --json databaseId,headSha -q ".[] | select(.headSha==\"$SHA\") | .databaseId" | head -n1); [ -n "$RUN" ] && break; sleep 10; done; \
  gh run watch "$RUN" --repo oguzmeric/Bandvision --exit-status > /dev/null; echo "exit=$? run=$RUN"; \
  gh run view "$RUN" --repo oguzmeric/Bandvision --log-failed | tail -n 150
  ```
- **UI test workflow.** `ios-uitest` (MediaMTX + `tools/mock_nvr.py`) is dispatched manually in Tasks 3 and 7:
  ```bash
  gh workflow run ios-uitest.yml --repo oguzmeric/Bandvision --ref iphone-izleme
  ```
  Then wait for the newest `ios-uitest` run on the branch, using the same loop with `--workflow ios-uitest`, without the `headSha` filter, after a 20 s delay.
- Worktree: `C:/Users/MSI-LAPTOP/bantvision-iphone`, branch `iphone-izleme` from `main`. Work only there.
  - Never kill processes by image name.
  - Never touch ports 3000/8090.
  - Never run `pip install -e` from the worktree.
- Tests never connect to real cameras or the network. UI tests use only the CI MediaMTX and `tools/mock_nvr.py`.
- Images never leave the phone. Passwords live only in the Keychain (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`) and never appear in logs, UI or files.
- Layout data comes **only** from `contracts/view-layouts.json`. It is bundled through `project.yml` with no copy and no Swift table of cells.
- Commits: several focused commits per task, Turkish messages, ending with the trailer line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Docs must not contain device models, real IPs or secret names. Fake IPs in tests are fine.

## Review Focus

1. **Keychain unavailable.** Unsigned simulator; write fails with -34018.
   - A saved device must still connect in this session.
   - A Turkish warning must be shown.
   - Migration must not lose the legacy password: the legacy accounts are kept.
   - Pinned by `DeviceStoreTests.testKeychainFailureKeepsSessionPasswordAndWarns` and `testMigrationFromLegacyCamera` (Task 2).
2. **Device edited or deleted while its cameras are on screen.**
   - Tiles reopen with the new settings, or show "Kamera silinmiş", without a crash or a dangling connection.
   - Counting on a deleted device stops and the selection clears.
   - Pinned by `CameraHubTests.testDeviceResetReopensWithNewSettings` (Task 4) and `WatchModelTests.testDeletedDeviceTileShowsDeleted` (Task 5).
3. **Switching between two 16-camera templates, or leaving and returning to the tab at the limit.**
   - Common cameras are never reconnected.
   - New tiles never show "Sınır aşıldı" while idle readers could be evicted.
   - Pinned by `CameraHubTests.testTemplateSwitchReusesCommonAndEvictsIdle` (Task 4) and `WatchModelTests.testSwitchingTemplatesKeepsCommonCameras` (Task 5).
4. **The counted camera is also in the grid.**
   - No second NVR connection is opened.
   - Changing the counted camera hands the old one back to its own reader.
   - Pinned by `CameraHubTests.testCountedCameraUsesCountingStream`, `testCountingTakesOverOpenReader` and `testCountingStopsThenTileOpensOwnConnection` (Task 4).
5. **Old or corrupt data on disk** (build-12 `bs.netcam`, damaged `devices.json` / `views.json`).
   - The file is quarantined, never overwritten.
   - The legacy setting migrates exactly once.
   - Pinned by `TemplateStoreTests.testCorruptFileIsQuarantined` (Task 1), `DeviceStoreTests.testCorruptFileIsQuarantined` and `testMigrationRunsOnce` (Task 2).

## Rulings made while planning (spec wording updated in the same commit as this plan)

- **R1 — eviction.** A reader with **no subscribers** is evicted immediately when a new reader needs room. The spec said "3 sn'den uzun süredir kullanılmayan". Subscriptions are explicit on iOS, so an unsubscribed reader is unused. This removes the 3 s "Sınır aşıldı" seen on the web.
- **R2 — backgrounding.** When the app goes to the **background**, idle readers close at once. iOS suspends the app, so a 5 s timer cannot run. Tab switches and the single-camera view still use the 5 s grace. `.inactive` (Control Center) keeps streams.
- **R3 — backoff reset.** The existing `NetworkCameraSource` behaviour is kept: the reconnect delay resets on the first decoded frame.
- **R4 — new device becomes the counted camera.** A device saved while no counting camera is chosen becomes the counted camera, using the camera selected in its form. In the onboarding wizard this happens always.
- **R5 — single-camera view.** It is an overlay inside the İzleme tab, not a `fullScreenCover`, so the tab stays "visible" and no grace logic misfires.

## File structure

| File | Task | Responsibility |
|---|---|---|
| `apps/ios/project.yml` | 1, 6 | bundle `contracts/view-layouts.json` (app) and `contracts/examples/view-template-4.json` (tests); landscape orientations |
| `BantSayac/Core/StoreSupport.swift` | 1 | `AppFiles.directory`, `JSONFile` (atomic write, quarantine), `UniqueName` |
| `BantSayac/Core/ViewLayouts.swift` | 1 | `ViewLayout`, `ViewLayouts.catalog/layout/smallestFor`, rects |
| `BantSayac/Core/ViewTemplates.swift` | 1 | `CameraRef`, `ViewTemplate`, `TemplateError`, `TemplateStore` |
| `BantSayac/Core/Devices.swift` | 2 | `TileQuality`, `NetworkDevice`, `CredentialStore`, `KeychainCredentials`, `CameraLookup`, `DeviceStore` (+ migration) |
| `BantSayac/Core/NetworkCamera.swift` | 3 | remove `CameraCredentialStore` |
| `BantSayac/Camera/NetworkStreamPlan.swift` | 3 | optional shared `RecorderClient` |
| `BantSayac/UI/CountingViewModel.swift` | 3, 4 | counting uses `DeviceStore` + `countCamera`; owns `CameraHub`; feeds it |
| `BantSayac/UI/NetworkCameraForm.swift` | 3 | settings section, counted-camera picker, device form |
| `BantSayac/UI/DeviceListView.swift` | 3 | Ayarlar → Cihazlar |
| `BantSayac/UI/CameraPickerView.swift` | 3 | camera chooser grouped by device (counting + template tiles) |
| `BantSayac/UI/OnboardingView.swift` | 3 | wizard uses device form + counted camera |
| `BantSayac/Camera/CameraHub.swift` | 4 | `TileStatus`, `StreamProblem`, `HubKey`, protocols, `HubFanout`, `ExternalFeed`, `CameraHub` |
| `BantSayac/Camera/HubStreams.swift` | 4 | `NetworkHubStream`, `DeviceStore.hubOpen` |
| `BantSayac/Camera/NetworkCameraSource.swift` | 4 | `onProblem` callback |
| `BantSayac/UI/Watch/TileRendering.swift` | 5 | `SampleBuffers`, `TileSink`, `TileVideoView` |
| `BantSayac/UI/Watch/WatchModel.swift` | 5 | `TemplateDraft`, `TileModel`, `WatchModel` |
| `BantSayac/UI/Watch/WatchView.swift` | 6 | İzleme tab: header, grid, tiles, empty states, banners |
| `BantSayac/UI/Watch/TemplateEditor.swift` | 6 | template editor sheet |
| `BantSayac/UI/Watch/SingleCameraView.swift` | 6 | full-screen single camera overlay |
| `BantSayac/App/OrientationLock.swift`, `App/BantSayacApp.swift` | 6 | landscape only on İzleme |
| `BantSayac/UI/RootView.swift` | 6 | fifth tab, tab selection |
| `BantSayacTests/ViewLayoutsTests.swift`, `TemplateStoreTests.swift` | 1 | |
| `BantSayacTests/DeviceStoreTests.swift` | 2 | includes `MemoryCredentials` |
| `BantSayacTests/CameraHubTests.swift` | 4 | includes `FakeStream`, `FakeSubscriber` |
| `BantSayacTests/WatchModelTests.swift` | 5 | |
| `BantSayacUITests/BantSayacUITests.swift` | 3, 7 | recorder flows via Cihazlar; grid test |
| docs (`02`, `04`, `10`, `12`, `apps/ios/README.md`, spec status) | 7 | |

---

### Task 1: Layouts, template store, shared file helpers

**Files:**
- Create: `apps/ios/BantSayac/Core/StoreSupport.swift`
- Create: `apps/ios/BantSayac/Core/ViewLayouts.swift`
- Create: `apps/ios/BantSayac/Core/ViewTemplates.swift`
- Modify: `apps/ios/project.yml` (targets `BantSayac.sources`, `BantSayacTests.sources`)
- Test: `apps/ios/BantSayacTests/ViewLayoutsTests.swift`, `apps/ios/BantSayacTests/TemplateStoreTests.swift`

**Interfaces:**
- Consumes: `RecorderChannel` (`Core/Recorder.swift`), `contracts/view-layouts.json`, `contracts/examples/view-template-4.json`.
- Produces:
  - `AppFiles.directory: URL`
  - `JSONFile(url:)`, with `load<T>(_:) -> JSONFile.LoadResult<T>` (`.missing / .loaded(T) / .corrupt(movedTo: String?)`) and `save<T>(_:) throws`
  - `UniqueName.make(_ base: String, limit: Int, taken: Set<String>) -> String`
  - `ViewLayout` (`id, name, cols, rows, cells, tileCount, aspectRatio, rects(in:gap:)`)
  - `ViewLayouts.catalog`, `ViewLayouts.maxTiles`, `layout(_:)`, `smallestFor(_:)`
  - `CameraRef(sourceId:channelId:)`, `ViewTemplate`, `TemplateError`
  - `@MainActor TemplateStore(directory:now:)` with `templates`, `problem`, `create`, `update`, `delete`, `template(_:)`, `createFromRecorder`, `static retile`, and `removeAll()` (DEBUG/UITEST)

- [ ] **Step 0: Worktree.** Create the worktree and check out the branch:
  ```bash
  cd /c/Users/MSI-LAPTOP/bantvision && git worktree add -b iphone-izleme ../bantvision-iphone main
  ```

- [ ] **Step 1: Bundle the contract files.** In `apps/ios/project.yml`, replace `sources: [BantSayac]` under target `BantSayac` with:

```yaml
    sources:
      - BantSayac
      # Düzen kataloğu sözleşmeden doğrudan (kopya yok): docs/02-contracts.md §8
      - path: ../../contracts/view-layouts.json
        buildPhase: resources
```

Then replace `sources: [BantSayacTests]` under target `BantSayacTests` with:

```yaml
    sources:
      - BantSayacTests
      # Sözleşme örneği: iPhone şablon biçimini okuyabiliyor mu
      - path: ../../contracts/examples/view-template-4.json
        buildPhase: resources
```

- [ ] **Step 2: Write the failing tests.** Create `apps/ios/BantSayacTests/ViewLayoutsTests.swift`:

```swift
import XCTest
@testable import BantSayac

/// Düzen kataloğu doğrudan sözleşme dosyasından (contracts/view-layouts.json) okunur.
final class ViewLayoutsTests: XCTestCase {
    func testCatalogComesFromContract() {
        XCTAssertEqual(ViewLayouts.catalog.map(\.id), ["1", "2", "3", "4", "6", "8", "9", "12", "16"])
        for layout in ViewLayouts.catalog {
            XCTAssertEqual(layout.tileCount, Int(layout.id), "düzen \(layout.id)")
        }
    }

    /// web'deki `smallest_for` (services/edge/bantvision/live/layouts.py) ile aynı
    func testSmallestForMatchesWeb() {
        let cases: [(Int, String)] = [(0, "1"), (1, "1"), (2, "2"), (3, "3"), (4, "4"), (5, "6"), (7, "8"),
                                      (9, "9"), (10, "12"), (13, "16"), (20, "16")]
        for (n, id) in cases {
            XCTAssertEqual(ViewLayouts.smallestFor(n)?.id, id, "n=\(n)")
        }
    }

    func testRectsAreProportional() throws {
        let three = try XCTUnwrap(ViewLayouts.layout("3"))
        XCTAssertEqual(three.rects(in: CGSize(width: 300, height: 200), gap: 0),
                       [CGRect(x: 0, y: 0, width: 200, height: 200),
                        CGRect(x: 200, y: 0, width: 100, height: 100),
                        CGRect(x: 200, y: 100, width: 100, height: 100)])
        let four = try XCTUnwrap(ViewLayouts.layout("4"))
        XCTAssertEqual(four.rects(in: CGSize(width: 100, height: 100), gap: 2)[3],
                       CGRect(x: 51, y: 51, width: 48, height: 48))
    }

    func testAspectRatioAssumesSixteenByNineTiles() throws {
        XCTAssertEqual(try XCTUnwrap(ViewLayouts.layout("4")).aspectRatio, 16.0 / 9.0, accuracy: 0.0001)
        XCTAssertEqual(try XCTUnwrap(ViewLayouts.layout("3")).aspectRatio, 48.0 / 18.0, accuracy: 0.0001)
    }
}
```

Create `apps/ios/BantSayacTests/TemplateStoreTests.swift`:

```swift
import XCTest
@testable import BantSayac

/// Şablon deposu: sözleşme biçimi, ad kuralları, doğrulama, bozuk dosya (ağsız).
@MainActor
final class TemplateStoreTests: XCTestCase {
    private let a = CameraRef(sourceId: "nvr", channelId: "1")
    private let b = CameraRef(sourceId: "nvr", channelId: "2")
    private let cam = CameraRef(sourceId: "cam", channelId: nil)

    private func tempDir() -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("bs-templates-\(UUID().uuidString)", isDirectory: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }

    func testCreatePersistsAndReloads() throws {
        let dir = tempDir()
        let store = TemplateStore(directory: dir, now: { 100 })
        let t = try store.create(name: "  Giriş katı  ", layout: "4", tiles: [a, nil, cam, nil])
        XCTAssertEqual(t.name, "Giriş katı")
        XCTAssertEqual(t.id.count, 32)
        XCTAssertEqual(t.createdAt, 100)
        XCTAssertEqual(TemplateStore(directory: dir).templates, [t])
    }

    func testNameRules() throws {
        let store = TemplateStore(directory: tempDir())
        let long = String(repeating: "ş", count: 70)
        XCTAssertEqual(try store.create(name: long, layout: "1", tiles: [nil]).name.count, 60)
        XCTAssertEqual(try store.create(name: "Kapı", layout: "1", tiles: [nil]).name, "Kapı")
        XCTAssertEqual(try store.create(name: "Kapı", layout: "1", tiles: [nil]).name, "Kapı (2)")
        XCTAssertEqual(try store.create(name: "Kapı", layout: "1", tiles: [nil]).name, "Kapı (3)")
        let second = try store.create(name: long, layout: "1", tiles: [nil]).name
        XCTAssertEqual(second.count, 60)
        XCTAssertTrue(second.hasSuffix(" (2)"))
        XCTAssertThrowsError(try store.create(name: "   ", layout: "1", tiles: [nil])) {
            XCTAssertEqual($0 as? TemplateError, .emptyName)
        }
    }

    func testRejectsBadShapes() {
        let store = TemplateStore(directory: tempDir())
        XCTAssertThrowsError(try store.create(name: "x", layout: "5", tiles: [nil])) {
            XCTAssertEqual($0 as? TemplateError, .unknownLayout)
        }
        XCTAssertThrowsError(try store.create(name: "x", layout: "4", tiles: [a])) {
            XCTAssertEqual($0 as? TemplateError, .tileCount)
        }
        XCTAssertThrowsError(try store.create(name: "x", layout: "2", tiles: [a, a])) {
            XCTAssertEqual($0 as? TemplateError, .duplicateCamera)
        }
        XCTAssertTrue(store.templates.isEmpty)
    }

    func testUpdateKeepsCreatedAtAndRenamesUniquely() throws {
        var clock = 10.0
        let store = TemplateStore(directory: tempDir(), now: { clock })
        let one = try store.create(name: "Bir", layout: "2", tiles: [a, nil])
        _ = try store.create(name: "İki", layout: "1", tiles: [nil])
        clock = 20
        var edited = one
        edited.name = "İki"
        edited.tiles = [a, b]
        edited.createdAt = 0
        let saved = try store.update(edited)
        XCTAssertEqual(saved.name, "İki (2)")
        XCTAssertEqual(saved.createdAt, 10)
        XCTAssertEqual(saved.updatedAt, 20)
        XCTAssertEqual(store.template(one.id)?.tiles, [a, b])
    }

    func testDelete() throws {
        let store = TemplateStore(directory: tempDir())
        let t = try store.create(name: "Sil", layout: "1", tiles: [nil])
        try store.delete(t.id)
        XCTAssertNil(store.template(t.id))
    }

    func testCorruptFileIsQuarantined() throws {
        let dir = tempDir()
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try Data("{bozuk".utf8).write(to: dir.appendingPathComponent("views.json"))
        let store = TemplateStore(directory: dir)
        XCTAssertTrue(store.templates.isEmpty)
        XCTAssertNotNil(store.problem)
        let names = try FileManager.default.contentsOfDirectory(atPath: dir.path)
        XCTAssertTrue(names.contains { $0.hasPrefix("views.corrupt-") }, "bozuk dosya kenara alınmalı: \(names)")
        XCTAssertNoThrow(try store.create(name: "Yeni", layout: "1", tiles: [nil]))
        XCTAssertNil(store.problem)
    }

    func testRetileKeepsOrderAndCountsDropped() throws {
        let one = try XCTUnwrap(ViewLayouts.layout("1"))
        let nine = try XCTUnwrap(ViewLayouts.layout("9"))
        let r = TemplateStore.retile([a, nil, b, cam], to: one)
        XCTAssertEqual(r.tiles, [a])
        XCTAssertEqual(r.dropped, 2)
        let grown = TemplateStore.retile([a, nil, b, cam], to: nine)
        XCTAssertEqual(Array(grown.tiles.prefix(3)), [a, b, cam])
        XCTAssertEqual(grown.tiles.count, 9)
        XCTAssertEqual(grown.dropped, 0)
    }

    func testCreateFromRecorder() throws {
        let store = TemplateStore(directory: tempDir())
        let five = (1...5).map { RecorderChannel(id: String($0), name: "K\($0)", number: $0, hasSubstream: true) }
        let t = try store.createFromRecorder(name: "Ofis NVR", deviceId: "nvr", channels: five)
        XCTAssertEqual(t.layout, "6")
        XCTAssertEqual(t.tiles.compactMap { $0?.channelId }, ["1", "2", "3", "4", "5"])
        XCTAssertNil(t.tiles[5])
        let twenty = (1...20).map { RecorderChannel(id: String($0), name: "", number: $0, hasSubstream: true) }
        let big = try store.createFromRecorder(name: "Ofis NVR", deviceId: "nvr", channels: twenty)
        XCTAssertEqual(big.layout, "16")
        XCTAssertEqual(big.tiles.compactMap { $0 }.count, 16)
        XCTAssertEqual(big.name, "Ofis NVR (2)")
    }

    func testContractExampleDecodesAndEncodesNullChannel() throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "view-template-4", withExtension: "json"))
        let t = try JSONDecoder().decode(ViewTemplate.self, from: Data(contentsOf: url))
        XCTAssertEqual(t.layout, "4")
        XCTAssertEqual(t.tiles[2], CameraRef(sourceId: "src-cam", channelId: nil))
        XCTAssertNil(t.tiles[3])
        let json = String(decoding: try JSONEncoder().encode(t), as: UTF8.self)
        XCTAssertTrue(json.contains("\"channelId\":null"), json)
    }
}
```

- [ ] **Step 3: Implement `StoreSupport.swift`.** Create `apps/ios/BantSayac/Core/StoreSupport.swift`:

```swift
import Foundation

/// Uygulamanın kendi veri klasörü: Application Support/BantSayac (kullanıcı dosyalarında görünmez).
enum AppFiles {
    static var directory: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("BantSayac", isDirectory: true)
    }
}

/// Atomik yazılan JSON dosyası. Okunamayan (bozuk) dosya kenara alınır; üzerine yazılıp veri sessizce kaybolmaz.
struct JSONFile: Sendable {
    let url: URL

    enum LoadResult<T> {
        case missing
        case loaded(T)
        /// Bozuk dosya kenara alındı (yeni adı); nil: kenara alınamadı, dosyaya yazılmamalı
        case corrupt(movedTo: String?)
    }

    func load<T: Decodable>(_ type: T.Type) -> LoadResult<T> {
        guard FileManager.default.fileExists(atPath: url.path) else { return .missing }
        do {
            return .loaded(try JSONDecoder().decode(T.self, from: Data(contentsOf: url)))
        } catch {
            let base = url.deletingPathExtension().lastPathComponent
            let target = url.deletingLastPathComponent()
                .appendingPathComponent("\(base).corrupt-\(Int(Date().timeIntervalSince1970)).json")
            do {
                try FileManager.default.moveItem(at: url, to: target)
                return .corrupt(movedTo: target.lastPathComponent)
            } catch {
                return .corrupt(movedTo: nil)
            }
        }
    }

    func save<T: Encodable>(_ value: T) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        try encoder.encode(value).write(to: url, options: .atomic)
    }
}

/// Benzersiz ad: `base` (en çok `limit` karakter) başka kayıtta varsa " (2)", " (3)" … eklenir; toplam `limit`i aşmaz.
enum UniqueName {
    static func make(_ base: String, limit: Int, taken: Set<String>) -> String {
        let trimmed = String(base.prefix(limit))
        guard taken.contains(trimmed) else { return trimmed }
        var n = 2
        while true {
            let suffix = " (\(n))"
            let candidate = String(trimmed.prefix(max(0, limit - suffix.count))) + suffix
            if !taken.contains(candidate) { return candidate }
            n += 1
        }
    }
}
```

- [ ] **Step 4: Implement `ViewLayouts.swift`.** Create `apps/ios/BantSayac/Core/ViewLayouts.swift`:

```swift
import Foundation
import CoreGraphics

/// Çoklu izleme düzeni (contracts/view-layouts.json, docs/02-contracts.md §8). Hücre `[x, y, w, h]` birim ızgarada;
/// hücre sırası kutu sırasıdır.
struct ViewLayout: Codable, Identifiable, Equatable, Sendable {
    let id: String
    let name: String
    let cols: Int
    let rows: Int
    let cells: [[Int]]

    var tileCount: Int { cells.count }

    /// Kutuları 16:9 kabul eden tuval oranı (genişlik / yükseklik)
    var aspectRatio: CGFloat { CGFloat(cols * 16) / CGFloat(rows * 9) }

    /// Kutu dikdörtgenleri: hücreler `size` tuvaline oranlanır, kutular arasında `gap` boşluk kalır.
    func rects(in size: CGSize, gap: CGFloat = 2) -> [CGRect] {
        guard cols > 0, rows > 0 else { return [] }
        let cw = size.width / CGFloat(cols), ch = size.height / CGFloat(rows)
        return cells.map { c in
            CGRect(x: CGFloat(c[0]) * cw, y: CGFloat(c[1]) * ch, width: CGFloat(c[2]) * cw, height: CGFloat(c[3]) * ch)
                .insetBy(dx: gap / 2, dy: gap / 2)
        }
    }
}

enum ViewLayouts {
    static let maxTiles = 16

    /// Uygulama paketindeki sözleşme dosyası (project.yml: contracts/view-layouts.json, kopya değil)
    static let catalog: [ViewLayout] = load(from: .main)

    private struct Catalog: Decodable {
        let version: Int
        let layouts: [ViewLayout]
    }

    static func load(from bundle: Bundle) -> [ViewLayout] {
        guard let url = bundle.url(forResource: "view-layouts", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let catalog = try? JSONDecoder().decode(Catalog.self, from: data),
              catalog.version == 1 else { return [] }
        return catalog.layouts.filter { layout in layout.cells.allSatisfy { $0.count == 4 } }
    }

    static func layout(_ id: String) -> ViewLayout? { catalog.first { $0.id == id } }

    /// `n` kameranın sığdığı en küçük düzen; 16'dan fazlası için 16'lı (web'deki `smallest_for` ile aynı).
    static func smallestFor(_ n: Int) -> ViewLayout? {
        catalog.first { $0.tileCount >= n } ?? catalog.last
    }
}
```

- [ ] **Step 5: Implement `ViewTemplates.swift`.** Create `apps/ios/BantSayac/Core/ViewTemplates.swift`:

```swift
import Foundation

/// Bir kamera: sözleşmedeki şablon kutusu `{sourceId, channelId}`. iPhone'da `sourceId` cihaz kimliği,
/// `channelId` kayıt cihazının kanal kimliği (doğrudan kamerada nil).
struct CameraRef: Codable, Hashable, Sendable {
    var sourceId: String
    var channelId: String?

    init(sourceId: String, channelId: String?) {
        self.sourceId = sourceId
        self.channelId = channelId
    }

    private enum CodingKeys: String, CodingKey { case sourceId, channelId }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        sourceId = try c.decode(String.self, forKey: .sourceId)
        channelId = try c.decodeIfPresent(String.self, forKey: .channelId)
    }

    /// Sözleşme `channelId`'yi her zaman yazar (kanalsız kamerada null)
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(sourceId, forKey: .sourceId)
        try c.encode(channelId, forKey: .channelId)
    }
}

/// Çoklu izleme şablonu (contracts/view-template.schema.json)
struct ViewTemplate: Codable, Identifiable, Equatable, Sendable {
    var id: String
    var name: String
    var layout: String
    var tiles: [CameraRef?]
    var createdAt: Double
    var updatedAt: Double
}

enum TemplateError: LocalizedError, Equatable {
    case emptyName, unknownLayout, tileCount, duplicateCamera, notFound, readOnly

    var errorDescription: String? {
        switch self {
        case .emptyName: return "Şablon adı boş olamaz."
        case .unknownLayout: return "Bilinmeyen düzen."
        case .tileCount: return "Kutu sayısı düzenle uyuşmuyor."
        case .duplicateCamera: return "Aynı kamera bir şablonda yalnızca bir kez yer alabilir."
        case .notFound: return "Şablon bulunamadı."
        case .readOnly: return "Şablon dosyası okunamadığı için değişiklik kaydedilmiyor."
        }
    }
}

/// Şablonlar telefonda (`views.json`, atomik); web ile eşitlenmez. Kurallar: ad 1–60 karakter (çakışmada " (2)"),
/// düzen katalogda, kutu sayısı düzenle aynı, aynı kamera en fazla bir kez.
@MainActor
final class TemplateStore: ObservableObject {
    static let nameLimit = 60

    @Published private(set) var templates: [ViewTemplate] = []
    /// Dosya bozuktu ya da yazılamadı: İzleme ekranında gösterilir
    @Published private(set) var problem: String?

    private struct Stored: Codable {
        var version = 1
        var templates: [ViewTemplate]
    }

    private let file: JSONFile
    private let now: () -> Double
    /// Bozuk dosya kenara alınamadı: üzerine yazılmaz
    private var readOnly = false

    init(directory: URL = AppFiles.directory, now: @escaping () -> Double = { Date().timeIntervalSince1970 }) {
        file = JSONFile(url: directory.appendingPathComponent("views.json"))
        self.now = now
        switch file.load(Stored.self) {
        case .missing:
            break
        case .loaded(let stored):
            templates = stored.templates.filter { t in
                ViewLayouts.layout(t.layout).map { $0.tileCount == t.tiles.count } ?? false
            }
        case .corrupt(let moved):
            if let moved {
                problem = "Şablon dosyası okunamadı; kenara alındı (\(moved)). Şablonları yeniden oluştur."
            } else {
                readOnly = true
                problem = "Şablon dosyası okunamadı; değişiklikler kaydedilmeyecek."
            }
        }
    }

    func template(_ id: String?) -> ViewTemplate? {
        guard let id else { return nil }
        return templates.first { $0.id == id }
    }

    @discardableResult
    func create(name: String, layout: String, tiles: [CameraRef?]) throws -> ViewTemplate {
        let t = now()
        var template = ViewTemplate(id: Self.newID(), name: "", layout: layout, tiles: tiles, createdAt: t, updatedAt: t)
        template.name = try uniqueName(name, excluding: template.id)
        try validate(template)
        try commit(templates + [template])
        return template
    }

    @discardableResult
    func update(_ template: ViewTemplate) throws -> ViewTemplate {
        guard let i = templates.firstIndex(where: { $0.id == template.id }) else { throw TemplateError.notFound }
        var t = template
        t.name = try uniqueName(template.name, excluding: t.id)
        t.createdAt = templates[i].createdAt
        t.updatedAt = now()
        try validate(t)
        var list = templates
        list[i] = t
        try commit(list)
        return t
    }

    func delete(_ id: String) throws {
        try commit(templates.filter { $0.id != id })
    }

    /// Kayıt cihazının kanallarından şablon: kanal sayısına uyan en küçük düzen, en fazla 16 kanal (sırayla).
    @discardableResult
    func createFromRecorder(name: String, deviceId: String, channels: [RecorderChannel]) throws -> ViewTemplate {
        guard let layout = ViewLayouts.smallestFor(channels.count) else { throw TemplateError.unknownLayout }
        let refs: [CameraRef?] = channels.prefix(layout.tileCount).map { CameraRef(sourceId: deviceId, channelId: $0.id) }
        return try create(name: name, layout: layout.id,
                          tiles: refs + Array(repeating: nil, count: layout.tileCount - refs.count))
    }

    /// Düzen değişince kameralar sırasıyla yeni kutulara taşınır; sığmayanların sayısı döner.
    static func retile(_ tiles: [CameraRef?], to layout: ViewLayout) -> (tiles: [CameraRef?], dropped: Int) {
        let cameras = tiles.compactMap { $0 }
        let kept: [CameraRef?] = cameras.prefix(layout.tileCount).map { $0 }
        return (kept + Array(repeating: nil, count: layout.tileCount - kept.count), cameras.count - kept.count)
    }

    #if DEBUG || UITEST
    /// UI testi: her test boş şablonla başlar
    func removeAll() {
        do { try commit([]) } catch { problem = error.localizedDescription }
    }
    #endif

    // MARK: - İç

    static func newID() -> String { UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased() }

    private func uniqueName(_ raw: String, excluding id: String) throws -> String {
        let base = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !base.isEmpty else { throw TemplateError.emptyName }
        return UniqueName.make(base, limit: Self.nameLimit, taken: Set(templates.filter { $0.id != id }.map(\.name)))
    }

    private func validate(_ t: ViewTemplate) throws {
        guard let layout = ViewLayouts.layout(t.layout) else { throw TemplateError.unknownLayout }
        guard t.tiles.count == layout.tileCount else { throw TemplateError.tileCount }
        let cameras = t.tiles.compactMap { $0 }
        guard Set(cameras).count == cameras.count else { throw TemplateError.duplicateCamera }
    }

    private func commit(_ list: [ViewTemplate]) throws {
        guard !readOnly else { throw TemplateError.readOnly }
        do {
            try file.save(Stored(templates: list))
        } catch {
            problem = "Şablonlar kaydedilemedi: \(error.localizedDescription)"
            throw error
        }
        templates = list
        problem = nil
    }
}
```

- [ ] **Step 6: Commit and run CI.** Commit with the message `iPhone izleme: düzen kataloğu sözleşmeden, şablon deposu`, then run the CI wait command from Global Constraints. Expected: `exit=0`, with all 4 `ViewLayoutsTests` and all 9 `TemplateStoreTests` passing in the unit-test step log. On failure, read the `--log-failed` tail, fix, commit, and re-run.

---

### Task 2: Device store and migration of the old single-camera setting

**Files:**
- Create: `apps/ios/BantSayac/Core/Devices.swift`
- Test: `apps/ios/BantSayacTests/DeviceStoreTests.swift`

**Interfaces:**
- Consumes:
  - `NetworkCameraConfig`, `NetworkDeviceKind`, `RecorderChannel`, `RecorderClient`, `NetworkStreamPlan.recorderClient(_:password:)`
  - `JSONFile`, `UniqueName`, `AppFiles`, `CameraRef` (Task 1)
- Produces:
  - `enum TileQuality: String, Sendable { case sub, main }`
  - `struct NetworkDevice` (`id`, `name`, `config`, `kind`, `summary`, `static newID()`)
  - `protocol CredentialStore`, `struct KeychainCredentials: CredentialStore`
  - `enum CameraLookup { case ok(NetworkCameraConfig), deleted, channelMissing }`
  - `@MainActor final class DeviceStore`:
    - state: `devices`, `channels`, `problem`
    - methods: `device(_:)`, `password(for:)`, `save(_:password:) -> (device:, warning:)`, `setChannels(_:for:)`, `delete(_:)`, `lookup(_:substream:)`, `title(for:)`, `summary(for:)`, `recorderClient(for:)`, `migrateLegacy(defaults:) -> CameraRef?`
    - statics: `account(_:)`, `migratedKey`
    - `removeAll()` (DEBUG/UITEST)

- [ ] **Step 1: Write the failing tests.** Create `apps/ios/BantSayacTests/DeviceStoreTests.swift`:

```swift
import XCTest
import Security
@testable import BantSayac

/// Bellekte şifre deposu (Keychain yerine). `failWrites`: imzasız simülatördeki gibi yazma hatası.
final class MemoryCredentials: CredentialStore, @unchecked Sendable {
    private let lock = NSLock()
    private var values: [String: String] = [:]
    var failWrites = false

    func password(account: String) -> String {
        lock.lock(); defer { lock.unlock() }
        return values[account] ?? ""
    }

    func setPassword(_ password: String, account: String) -> OSStatus {
        lock.lock(); defer { lock.unlock() }
        if failWrites { return errSecMissingEntitlement }
        values[account] = password.isEmpty ? nil : password
        return errSecSuccess
    }
}

/// Cihaz listesi, şifreler, kanal önbelleği ve eski tek kamera ayarının taşınması (ağsız).
@MainActor
final class DeviceStoreTests: XCTestCase {
    private func tempDir() -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("bs-devices-\(UUID().uuidString)", isDirectory: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }

    private func tempDefaults() -> UserDefaults {
        let name = "bs-devices-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: name)!
        addTeardownBlock { UserDefaults().removePersistentDomain(forName: name) }
        return defaults
    }

    private func cameraConfig() -> NetworkCameraConfig {
        var c = NetworkCameraConfig()
        c.host = "10.0.0.64"
        return c
    }

    private func recorderConfig(_ brand: RecorderBrand = .hikvision) -> NetworkCameraConfig {
        var c = NetworkCameraConfig()
        c.kind = .recorder
        c.recorderBrand = brand
        c.recorderHost = "10.0.0.5"
        return c
    }

    private let ch1 = RecorderChannel(id: "1", name: "Bant 1", number: 1, hasSubstream: true)
    private let ch2 = RecorderChannel(id: "2", name: "", number: 2, hasSubstream: true)

    func testSaveNamesPersistsAndReloads() {
        let dir = tempDir()
        let creds = MemoryCredentials()
        let store = DeviceStore(directory: dir, credentials: creds)
        XCTAssertEqual(store.save(NetworkDevice(id: "a", name: "  ", config: cameraConfig()), password: "").device.name,
                       "Kamera 1")
        XCTAssertEqual(store.save(NetworkDevice(id: "b", name: "", config: cameraConfig()), password: "").device.name,
                       "Kamera 2")
        XCTAssertEqual(store.save(NetworkDevice(id: "c", name: "", config: recorderConfig()), password: "").device.name,
                       "NVR 1")
        XCTAssertEqual(store.save(NetworkDevice(id: "d", name: "Kamera 1", config: cameraConfig()), password: "").device.name,
                       "Kamera 1 (2)")
        let long = String(repeating: "x", count: 50)
        XCTAssertEqual(store.save(NetworkDevice(id: "e", name: long, config: cameraConfig()), password: "").device.name.count, 40)
        let reloaded = DeviceStore(directory: dir, credentials: creds)
        XCTAssertEqual(reloaded.devices.map(\.id), ["a", "b", "c", "d", "e"])
    }

    func testSavingKeepsChannelSelectionOutOfDevice() {
        let store = DeviceStore(directory: tempDir(), credentials: MemoryCredentials())
        var config = recorderConfig()
        config.recorderChannel = ch1
        let saved = store.save(NetworkDevice(id: "n", name: "Ofis NVR", config: config), password: "pw").device
        XCTAssertNil(saved.config.recorderChannel)
        XCTAssertEqual(saved.summary, "Hikvision · 10.0.0.5")
    }

    func testPasswordsArePerDeviceAndDeletedWithDevice() {
        let creds = MemoryCredentials()
        let store = DeviceStore(directory: tempDir(), credentials: creds)
        store.save(NetworkDevice(id: "a", name: "A", config: cameraConfig()), password: "pa")
        store.save(NetworkDevice(id: "b", name: "B", config: recorderConfig()), password: "pb")
        XCTAssertEqual(creds.password(account: DeviceStore.account("a")), "pa")
        XCTAssertEqual(store.password(for: "b"), "pb")
        store.delete("b")
        XCTAssertNil(store.device("b"))
        XCTAssertEqual(creds.password(account: DeviceStore.account("b")), "")
        XCTAssertEqual(store.password(for: "b"), "")
    }

    func testKeychainFailureKeepsSessionPasswordAndWarns() {
        let creds = MemoryCredentials()
        creds.failWrites = true
        let store = DeviceStore(directory: tempDir(), credentials: creds)
        let result = store.save(NetworkDevice(id: "a", name: "A", config: cameraConfig()), password: "gizli")
        XCTAssertNotNil(result.warning)
        XCTAssertEqual(store.password(for: "a"), "gizli")
    }

    func testLookup() {
        let store = DeviceStore(directory: tempDir(), credentials: MemoryCredentials())
        store.save(NetworkDevice(id: "cam", name: "Kapı", config: cameraConfig()), password: "")
        store.save(NetworkDevice(id: "nvr", name: "Ofis NVR", config: recorderConfig()), password: "")
        store.setChannels([ch1, ch2], for: "nvr")

        guard case .ok(let rec) = store.lookup(CameraRef(sourceId: "nvr", channelId: "2"), substream: false) else {
            return XCTFail("kanal bulunmalı")
        }
        XCTAssertEqual(rec.recorderChannel, ch2)
        XCTAssertFalse(rec.substream)
        guard case .ok(let cam) = store.lookup(CameraRef(sourceId: "cam", channelId: nil)) else {
            return XCTFail("kamera bulunmalı")
        }
        XCTAssertEqual(cam.substream, cameraConfig().substream)
        XCTAssertEqual(store.lookup(CameraRef(sourceId: "nvr", channelId: "9")), .channelMissing)
        XCTAssertEqual(store.lookup(CameraRef(sourceId: "yok", channelId: nil)), .deleted)
        XCTAssertEqual(store.title(for: CameraRef(sourceId: "nvr", channelId: "2")), "Kanal 2")
        XCTAssertEqual(store.title(for: CameraRef(sourceId: "cam", channelId: nil)), "Kapı")
        XCTAssertEqual(store.title(for: CameraRef(sourceId: "yok", channelId: nil)), "Kamera silinmiş")
        XCTAssertEqual(store.summary(for: CameraRef(sourceId: "nvr", channelId: "1")), "Ofis NVR · Bant 1")
        XCTAssertEqual(store.summary(for: nil), "Seçilmedi")
    }

    func testRecorderClientIsSharedUntilSettingsChange() throws {
        let store = DeviceStore(directory: tempDir(), credentials: MemoryCredentials())
        let device = NetworkDevice(id: "t", name: "TRASSIR", config: recorderConfig(.trassir))
        store.save(device, password: "a")
        let first = try XCTUnwrap(store.recorderClient(for: "t"))
        let again = try XCTUnwrap(store.recorderClient(for: "t"))
        XCTAssertTrue((first as AnyObject) === (again as AnyObject), "aynı cihaz tek oturum kullanmalı")
        store.save(device, password: "b")
        let changed = try XCTUnwrap(store.recorderClient(for: "t"))
        XCTAssertFalse((first as AnyObject) === (changed as AnyObject), "şifre değişince yeni istemci")
        XCTAssertNil(store.recorderClient(for: "yok"))
    }

    func testMigrationFromLegacyCamera() throws {
        let defaults = tempDefaults()
        let creds = MemoryCredentials()
        creds.setPassword("eski", account: "camera")
        defaults.set(try JSONEncoder().encode(cameraConfig()), forKey: "bs.netcam")
        let store = DeviceStore(directory: tempDir(), credentials: creds)
        let ref = try XCTUnwrap(store.migrateLegacy(defaults: defaults))
        let device = try XCTUnwrap(store.device(ref.sourceId))
        XCTAssertEqual(device.name, "Kamera 1")
        XCTAssertNil(ref.channelId)
        XCTAssertEqual(store.password(for: device.id), "eski")
        XCTAssertEqual(creds.password(account: "camera"), "eski", "eski hesap bir sürüm boyunca silinmez")
        XCTAssertNotNil(defaults.data(forKey: "bs.netcam"), "eski ayar silinmez")
    }

    func testMigrationFromLegacyRecorderKeepsChannel() throws {
        let defaults = tempDefaults()
        let creds = MemoryCredentials()
        creds.setPassword("nvr-pw", account: "recorder")
        var legacy = recorderConfig(.dahua)
        legacy.recorderChannel = ch1
        defaults.set(try JSONEncoder().encode(legacy), forKey: "bs.netcam")
        let store = DeviceStore(directory: tempDir(), credentials: creds)
        let ref = try XCTUnwrap(store.migrateLegacy(defaults: defaults))
        XCTAssertEqual(store.device(ref.sourceId)?.name, "NVR 1")
        XCTAssertEqual(ref.channelId, "1")
        XCTAssertEqual(store.channels[ref.sourceId], [ch1])
        XCTAssertEqual(store.password(for: ref.sourceId), "nvr-pw")
        XCTAssertEqual(store.summary(for: ref), "NVR 1 · Bant 1")
    }

    func testMigrationRunsOnce() throws {
        let defaults = tempDefaults()
        defaults.set(try JSONEncoder().encode(cameraConfig()), forKey: "bs.netcam")
        let store = DeviceStore(directory: tempDir(), credentials: MemoryCredentials())
        XCTAssertNotNil(store.migrateLegacy(defaults: defaults))
        XCTAssertNil(store.migrateLegacy(defaults: defaults))
        XCTAssertEqual(store.devices.count, 1)
    }

    func testMigrationWithoutUsableLegacySettingDoesNothing() {
        let defaults = tempDefaults()
        let store = DeviceStore(directory: tempDir(), credentials: MemoryCredentials())
        XCTAssertNil(store.migrateLegacy(defaults: defaults))
        XCTAssertTrue(defaults.bool(forKey: DeviceStore.migratedKey))
        XCTAssertTrue(store.devices.isEmpty)
    }

    func testCorruptFileIsQuarantined() throws {
        let dir = tempDir()
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try Data("[[[".utf8).write(to: dir.appendingPathComponent("devices.json"))
        let store = DeviceStore(directory: dir, credentials: MemoryCredentials())
        XCTAssertTrue(store.devices.isEmpty)
        XCTAssertNotNil(store.problem)
        let names = try FileManager.default.contentsOfDirectory(atPath: dir.path)
        XCTAssertTrue(names.contains { $0.hasPrefix("devices.corrupt-") }, "\(names)")
    }
}
```

- [ ] **Step 2: Implement `Devices.swift`.** Create `apps/ios/BantSayac/Core/Devices.swift`:

```swift
import Foundation
import Security

/// Akış niteliği: ızgarada alt akış, tek kamerada ana akış
enum TileQuality: String, Sendable {
    case sub, main
}

/// Ağdaki bir cihaz: doğrudan IP kamera ya da kayıt cihazı (NVR/XVR). Şifresi Keychain'de (`device.<id>`).
struct NetworkDevice: Codable, Identifiable, Equatable, Sendable {
    var id: String
    var name: String
    /// Bağlantı ayarı; `recorderChannel` cihazda tutulmaz (kanallar `DeviceStore.channels`'ta)
    var config: NetworkCameraConfig

    var kind: NetworkDeviceKind { config.kind }

    /// "Hikvision · 192.168.1.64" (listelerde)
    var summary: String {
        switch kind {
        case .camera: return config.summary
        case .recorder:
            return config.recorderReady ? "\(config.recorderBrand.title) · \(config.cleanRecorderHost)" : "Ayarlanmadı"
        }
    }

    static func newID() -> String { UUID().uuidString.lowercased() }
}

/// Şifre deposu (gerçeği Keychain; testlerde bellek)
protocol CredentialStore: Sendable {
    func password(account: String) -> String
    /// Boş şifre kaydı siler. Dönüş: Keychain durum kodu (sessizce yutulmaz).
    @discardableResult func setPassword(_ password: String, account: String) -> OSStatus
}

/// Ağ cihazı şifreleri iPhone Keychain'de (cihaz kilidi açıldıktan sonra erişilebilir, yedekle taşınmaz).
/// Hesaplar: `device.<id>`; eski sürümlerin hesapları "camera" ve "recorder" (geçişte okunur, silinmez).
struct KeychainCredentials: CredentialStore {
    private static let service = "com.oguzmeric.bantsayac.netcam"

    func password(account: String) -> String {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: Self.service, kSecAttrAccount as String: account,
                                    kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return "" }
        return String(data: data, encoding: .utf8) ?? ""
    }

    @discardableResult
    func setPassword(_ password: String, account: String) -> OSStatus {
        let base: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                   kSecAttrService as String: Self.service, kSecAttrAccount as String: account]
        SecItemDelete(base as CFDictionary)
        guard !password.isEmpty else { return errSecSuccess }
        var add = base
        add[kSecValueData as String] = Data(password.utf8)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        return SecItemAdd(add as CFDictionary, nil)
    }
}

/// Bir kameranın bağlantı ayarı ya da neden bulunamadığı
enum CameraLookup: Equatable {
    case ok(NetworkCameraConfig)
    case deleted
    case channelMissing
}

/// Kamera ve kayıt cihazları (sayım ve İzleme ortak listesi). Liste `devices.json`'da (atomik; bozuksa kenara alınır),
/// şifreler Keychain'de. Kayıt cihazının kanal listesi önbellekte: kutu adları ve seçim çevrimdışı da görünür.
@MainActor
final class DeviceStore: ObservableObject {
    static let nameLimit = 40
    static let migratedKey = "bs.devicesMigrated"

    @Published private(set) var devices: [NetworkDevice] = []
    /// Kayıt cihazlarının kanal listesi (cihaz kimliği → kanallar)
    @Published private(set) var channels: [String: [RecorderChannel]] = [:]
    /// Dosya bozuktu ya da yazılamadı: Cihazlar ekranında gösterilir
    @Published private(set) var problem: String?

    private struct Stored: Codable {
        var version = 1
        var devices: [NetworkDevice]
        var channels: [String: [RecorderChannel]]
    }

    private let file: JSONFile
    private let credentials: CredentialStore
    private var readOnly = false
    /// Bu oturumda girilen şifreler: Keychain yazılamasa da (imzasız simülatör) bağlantı çalışır
    private var sessionPasswords: [String: String] = [:]
    /// Kayıt cihazı istemcisi cihaz başına bir tane (TRASSIR: tek oturum); ayar ya da şifre değişince yenilenir
    private var clients: [String: (identity: String, client: RecorderClient)] = [:]

    init(directory: URL = AppFiles.directory, credentials: CredentialStore = KeychainCredentials()) {
        file = JSONFile(url: directory.appendingPathComponent("devices.json"))
        self.credentials = credentials
        switch file.load(Stored.self) {
        case .missing:
            break
        case .loaded(let stored):
            devices = stored.devices
            channels = stored.channels
        case .corrupt(let moved):
            if let moved {
                problem = "Cihaz listesi okunamadı; kenara alındı (\(moved)). Cihazları yeniden ekle."
            } else {
                readOnly = true
                problem = "Cihaz listesi okunamadı; değişiklikler kaydedilmeyecek."
            }
        }
    }

    static func account(_ id: String) -> String { "device.\(id)" }

    func device(_ id: String) -> NetworkDevice? { devices.first { $0.id == id } }

    /// Kayıtlı şifre: önce bu oturumda girilen, yoksa Keychain
    func password(for id: String) -> String {
        sessionPasswords[id] ?? credentials.password(account: Self.account(id))
    }

    /// Ekler ya da günceller. Ad kırpılır (en çok 40); boşsa "Kamera 1" / "NVR 1"; başka cihazda varsa " (2)".
    /// Dönüş: kaydedilen cihaz ve şifre güvenli depoya yazılamadıysa kullanıcıya gösterilecek uyarı.
    @discardableResult
    func save(_ device: NetworkDevice, password: String) -> (device: NetworkDevice, warning: String?) {
        var d = device
        d.config.recorderChannel = nil
        let cleaned = d.name.trimmingCharacters(in: .whitespacesAndNewlines)
        d.name = UniqueName.make(cleaned.isEmpty ? defaultName(for: d.kind) : cleaned, limit: Self.nameLimit,
                                 taken: Set(devices.filter { $0.id != d.id }.map(\.name)))
        if let i = devices.firstIndex(where: { $0.id == d.id }) {
            devices[i] = d
        } else {
            devices.append(d)
        }
        if d.kind == .camera { channels[d.id] = nil }
        persist()
        sessionPasswords[d.id] = password
        clients[d.id] = nil
        let status = credentials.setPassword(password, account: Self.account(d.id))
        let warning = status == errSecSuccess ? nil
            : "Şifre güvenli depoya kaydedilemedi (kod \(status)). Bu oturumda kullanılır; uygulama yeniden açılınca tekrar girmen gerekebilir."
        return (d, warning)
    }

    func setChannels(_ list: [RecorderChannel], for id: String) {
        guard device(id)?.kind == .recorder else { return }
        channels[id] = list
        persist()
    }

    /// Cihaz, kanal listesi ve şifresi silinir
    func delete(_ id: String) {
        devices.removeAll { $0.id == id }
        channels[id] = nil
        sessionPasswords[id] = nil
        clients[id] = nil
        credentials.setPassword("", account: Self.account(id))
        persist()
    }

    /// Kameranın bağlantı ayarı. `substream` nil: cihazın kendi ayarı (sayım); ızgara alt, tek kamera ana akış ister.
    func lookup(_ ref: CameraRef, substream: Bool? = nil) -> CameraLookup {
        guard let d = device(ref.sourceId) else { return .deleted }
        var config = d.config
        if let substream { config.substream = substream }
        switch d.kind {
        case .camera:
            return ref.channelId == nil ? .ok(config) : .channelMissing
        case .recorder:
            guard let cid = ref.channelId, let channel = channels[d.id]?.first(where: { $0.id == cid }) else {
                return .channelMissing
            }
            config.recorderChannel = channel
            return .ok(config)
        }
    }

    /// Kutu ve seçicide gösterilen ad
    func title(for ref: CameraRef) -> String {
        guard let d = device(ref.sourceId) else { return "Kamera silinmiş" }
        guard d.kind == .recorder, let cid = ref.channelId else { return d.name }
        return channels[d.id]?.first { $0.id == cid }?.title ?? "Kanal \(cid)"
    }

    /// Sayım kaynağı özeti: "Ofis NVR · Bant 1"
    func summary(for ref: CameraRef?) -> String {
        guard let ref else { return "Seçilmedi" }
        guard let d = device(ref.sourceId) else { return "Kamera silinmiş" }
        return d.kind == .recorder ? "\(d.name) · \(title(for: ref))" : d.name
    }

    /// Kayıt cihazının istemcisi; aynı ayar ve şifreyle hep aynısı (TRASSIR'da tek oturum, kanal başına jeton)
    func recorderClient(for id: String) -> RecorderClient? {
        guard let d = device(id), d.kind == .recorder else { return nil }
        let pw = password(for: id)
        let c = d.config
        let identity = [c.recorderBrand.rawValue, c.cleanRecorderHost, String(c.effectiveHTTPPort),
                        String(c.effectiveRTSPPort), c.recorderUsername, pw].joined(separator: "|")
        if let cached = clients[id], cached.identity == identity { return cached.client }
        let client = NetworkStreamPlan.recorderClient(c, password: pw)
        clients[id] = (identity, client)
        return client
    }

    /// Eski sürümlerin tek kamera/NVR ayarını (`bs.netcam` + Keychain "camera"/"recorder") listeye taşır.
    /// Bir kez çalışır (`bs.devicesMigrated`); eski anahtarlar bir sürüm boyunca silinmez.
    /// Dönüş: sayımın kullanacağı kamera (eski ayarda seçili olan).
    func migrateLegacy(defaults: UserDefaults = .standard) -> CameraRef? {
        guard !defaults.bool(forKey: Self.migratedKey) else { return nil }
        defaults.set(true, forKey: Self.migratedKey)
        guard let data = defaults.data(forKey: "bs.netcam"),
              let legacy = try? JSONDecoder().decode(NetworkCameraConfig.self, from: data) else { return nil }
        guard legacy.kind == .camera ? legacy.rtspURL != nil : legacy.recorderReady else { return nil }
        let pw = credentials.password(account: legacy.kind.rawValue)
        let saved = save(NetworkDevice(id: NetworkDevice.newID(), name: "", config: legacy), password: pw).device
        guard legacy.kind == .recorder else { return CameraRef(sourceId: saved.id, channelId: nil) }
        guard let channel = legacy.recorderChannel else { return nil }
        setChannels([channel], for: saved.id)
        return CameraRef(sourceId: saved.id, channelId: channel.id)
    }

    #if DEBUG || UITEST
    /// UI testi: her test boş listeyle başlar
    func removeAll() {
        for d in devices { delete(d.id) }
    }
    #endif

    // MARK: - İç

    private func defaultName(for kind: NetworkDeviceKind) -> String {
        let prefix = kind == .camera ? "Kamera" : "NVR"
        let names = Set(devices.map(\.name))
        var n = 1
        while names.contains("\(prefix) \(n)") { n += 1 }
        return "\(prefix) \(n)"
    }

    private func persist() {
        guard !readOnly else { return }
        do {
            try file.save(Stored(devices: devices, channels: channels))
        } catch {
            problem = "Cihaz listesi kaydedilemedi: \(error.localizedDescription)"
        }
    }
}
```

- [ ] **Step 3: Commit and run CI.** Commit with the message `iPhone izleme: cihaz listesi, cihaz başına şifre, eski ayarın taşınması`, then run CI. Expected: `exit=0`, with all 11 `DeviceStoreTests` passing and the earlier tests still green.

---

### Task 3: Counting moves to the device list

**Files:**
- Modify: `apps/ios/BantSayac/Core/NetworkCamera.swift` (delete the `CameraCredentialStore` enum, lines 151–180)
- Modify: `apps/ios/BantSayac/Camera/NetworkStreamPlan.swift`
- Modify: `apps/ios/BantSayac/UI/CountingViewModel.swift`
- Modify: `apps/ios/BantSayac/UI/NetworkCameraForm.swift` (replace lines 1–511; make `ChannelThumbnail` internal)
- Create: `apps/ios/BantSayac/UI/DeviceListView.swift`, `apps/ios/BantSayac/UI/CameraPickerView.swift`
- Modify: `apps/ios/BantSayac/UI/OnboardingView.swift`
- Modify: `apps/ios/BantSayacUITests/BantSayacUITests.swift` (`openRecorderForm`, `pickTestAndSave`)

**Interfaces:**
- Consumes: everything from Task 2; `ChannelThumbnailLoader` (existing, `NetworkCameraForm.swift`).
- Produces:
  - `NetworkStreamPlan.make(_:password:client:)`
  - `CountingViewModel`:
    - properties: `devices: DeviceStore`, `countCamera: CameraRef?`, `countDevice: NetworkDevice?`, `countCameraSummary: String`
    - methods: `selectCountCamera(_:)`, `deviceSaved(_:)`, `deleteDevice(_:)`
  - views: `NetworkCameraForm(vm:device:initialKind:selectsForCounting:)`, `DeviceListView(vm:)`, `CameraPickerView(devices:selected:unavailable:allowsEmpty:onPick:)`, `CountCameraPicker(vm:)`
  - accessibility ids:
    - Settings: `countCameraLink`, `devicesLink`
    - Device list: `addCamera`, `addRecorder`, `device.<name>`
    - Device form: `deviceName`
    - Camera picker: `camera.<title>`, `pickEmpty`, `refreshChannels.<device name>`
    - Ids kept: `saveNetworkCamera`, `recorderHost`, `recorderPassword`, `listChannels`, `channel.<title>`, `testConnection`, `testResult`, `testError`, `channelError`, `recorderBrand`, `recorderHTTPPort`, `recorderRTSPPort`

- [ ] **Step 1: Shared recorder client in the stream plan.** In `apps/ios/BantSayac/Camera/NetworkStreamPlan.swift`, replace the `make` function with:

```swift
    /// Ayarlar eksikse nil. `client`: cihazın paylaşılan kayıt cihazı istemcisi (TRASSIR'da tek oturum); nil ise yenisi.
    static func make(_ config: NetworkCameraConfig, password: String, client: RecorderClient? = nil) -> NetworkStreamPlan? {
        switch config.kind {
        case .camera:
            guard let url = config.rtspURL else { return nil }
            // Tam adreste kullanıcı adı/şifre yazılmışsa ve ayrı girilmemişse onları kullan
            let user = config.username.isEmpty ? (url.user ?? "") : config.username
            let pass = password.isEmpty ? (url.password ?? "") : password
            return NetworkStreamPlan(resolver: { url }, username: user, password: pass, keepAlive: nil)
        case .recorder:
            guard config.recorderReady, let channel = config.recorderChannel else { return nil }
            let client = client ?? recorderClient(config, password: password)
            let substream = config.substream
            return NetworkStreamPlan(resolver: { try await client.streamURL(channel, substream: substream) },
                                     username: config.recorderUsername, password: password,
                                     keepAlive: { url in await client.keepAlive(url) })
        }
    }
```

- [ ] **Step 2: Remove the old credential enum.** In `apps/ios/BantSayac/Core/NetworkCamera.swift`, delete everything from the comment `/// Ağ kamerası ve kayıt cihazı şifreleri iPhone Keychain'de` to the end of `enum CameraCredentialStore { … }`. `KeychainCredentials` in `Devices.swift` replaces it and uses the same service and legacy account names. Also remove `import Security` from that file if nothing else in it uses Security.

- [ ] **Step 3: `CountingViewModel`.** Make these edits in `apps/ios/BantSayac/UI/CountingViewModel.swift`:

(a) Replace the lines

```swift
    @Published private(set) var networkConfig = NetworkCameraConfig.load()
    @Published private(set) var networkState: NetworkCameraState?
    private var networkSource: NetworkCameraSource?
    /// Kaydedilen şifreler bellekte de tutulur: Keychain yazılamasa bile oturum boyunca bağlantı çalışır
    private var networkPasswords: [NetworkDeviceKind: String] = [:]
```

with

```swift
    /// Ağ cihazları (kamera ve kayıt cihazları) ve şifreleri; sayım ve İzleme ortak listesi
    let devices: DeviceStore
    /// Sayılan ağ kamerası (cihaz + kanal); nil: seçilmedi
    @Published private(set) var countCamera: CameraRef? = CountingViewModel.loadCountCamera()
    @Published private(set) var networkState: NetworkCameraState?
    private var networkSource: NetworkCameraSource?
```

(b) In `init()`, after `self.staffFeedback = StaffTeachFeedback()`, insert `self.devices = DeviceStore()`. At the very end of `init()`, after the thermal `NotificationCenter` sink, insert:

```swift
        // Eski sürümün tek kamera/NVR ayarı bir kez listeye taşınır; sayım aynı kamerayla sürer
        if let migrated = devices.migrateLegacy(), countCamera == nil {
            countCamera = migrated
            Self.saveCountCamera(migrated)
        }
```

(c) In `runUITestNetwork`, replace the body lines from `var config = NetworkCameraConfig()` through the `if status != errSecSuccess …` line with:

```swift
        devices.removeAll()
        var config = NetworkCameraConfig()
        config.brand = .custom
        config.customURL = url
        config.username = username
        let saved = devices.save(NetworkDevice(id: NetworkDevice.newID(), name: "Test kamerası", config: config),
                                 password: password)
        if let warning = saved.warning { testHookError = warning }
        countCamera = CameraRef(sourceId: saved.device.id, channelId: nil)
```

Keep the following lines (`sourceKind = .network`, `startNetwork()`, …) unchanged.

(d) Replace the body of `prepareUITestForms()` with:

```swift
        networkReconnect = true                           // gerçek kullanım gibi: koparsa yeniden bağlanır
        devices.removeAll()
        countCamera = nil
        Self.saveCountCamera(nil)
        UserDefaults.standard.removeObject(forKey: "bs.netcam")
        UserDefaults.standard.set(true, forKey: DeviceStore.migratedKey)
        sourceKind = .phone                               // kaydedince ağ kaynağına geçiş de sınansın
        UserDefaults.standard.set(VideoSourceKind.phone.rawValue, forKey: "bs.source")
        for kind in NetworkDeviceKind.allCases { KeychainCredentials().setPassword("", account: kind.rawValue) }
```

(e) Replace `saveNetworkConfig(_:password:)`, `storedPassword(for:)` and `startNetwork()` (the whole span from `/// Ayarları ve şifreyi kaydeder` through the end of `startNetwork()`) with:

```swift
    private static let countCameraKey = "bs.countCamera"

    nonisolated private static func loadCountCamera() -> CameraRef? {
        guard let data = UserDefaults.standard.data(forKey: countCameraKey) else { return nil }
        return try? JSONDecoder().decode(CameraRef.self, from: data)
    }

    private static func saveCountCamera(_ ref: CameraRef?) {
        if let ref, let data = try? JSONEncoder().encode(ref) {
            UserDefaults.standard.set(data, forKey: countCameraKey)
        } else {
            UserDefaults.standard.removeObject(forKey: countCameraKey)
        }
    }

    /// Sayılan kameranın cihazı (sihirbaz)
    var countDevice: NetworkDevice? { countCamera.flatMap { devices.device($0.sourceId) } }

    /// "Ofis NVR · Bant 1" / "Seçilmedi"
    var countCameraSummary: String { devices.summary(for: countCamera) }

    /// Sayılacak kamerayı seçer (nil: seçim kalkar); ağ kaynağındaysa yeniden bağlanır.
    func selectCountCamera(_ ref: CameraRef?) {
        countCamera = ref
        Self.saveCountCamera(ref)
        if sourceKind == .network && !isVideoMode { startNetwork() }
    }

    /// Cihaz kaydedildi: sayılan kamera bu cihazdaysa yeni ayarla yeniden bağlanır.
    func deviceSaved(_ id: String) {
        if countCamera?.sourceId == id && sourceKind == .network && !isVideoMode { startNetwork() }
    }

    /// Cihaz silinir; sayım bu cihazdaysa durur ve kamera seçimi kalkar.
    func deleteDevice(_ id: String) {
        devices.delete(id)
        guard countCamera?.sourceId == id else { return }
        setRunning(false)
        selectCountCamera(nil)
    }

    private func startNetwork() {
        stopNetwork()
        camera.stop()
        guard let ref = countCamera else {
            networkState = .ended("Sayılacak kamera seçilmedi (Ayarlar → Görüntü kaynağı)")
            return
        }
        let config: NetworkCameraConfig
        switch devices.lookup(ref) {
        case .ok(let c):
            config = c
        case .deleted:
            networkState = .ended("Kamera silinmiş (Ayarlar → Görüntü kaynağı)")
            return
        case .channelMissing:
            networkState = .ended("Kanal kayıt cihazında bulunamadı (Ayarlar → Görüntü kaynağı)")
            return
        }
        guard let plan = NetworkStreamPlan.make(config, password: devices.password(for: ref.sourceId),
                                                client: devices.recorderClient(for: ref.sourceId)) else {
            networkState = .ended("Ağ kamerası ayarlanmadı (Ayarlar → Görüntü kaynağı)")
            return
        }
        processor.resetClock()
        processor.resetTracking(resetBackground: true)
        processor.setEmitFrameImages(true)
        frameImage = nil
        let source = plan.makeSource()
        source.reconnect = networkReconnect
        let processor = self.processor
        let gate = frameGate
        source.onFrame = { pb, ts in gate.submit(pb, ts: ts, to: processor) }
        // ViewModel uygulama boyunca yaşar; durum bildirimi için güçlü referans güvenli (ve Sendable)
        source.onState = { [self] state in
            Task { @MainActor in self.networkStateChanged(state, source: source) }
        }
        networkSource = source
        networkState = .connecting
        source.start()
    }
```

Finally, remove `import Security` from `CountingViewModel.swift` if nothing else there uses it.

- [ ] **Step 4: Settings section, counted-camera picker, device form.** In `apps/ios/BantSayac/UI/NetworkCameraForm.swift`:
  - Replace everything from line 1 up to (not including) `// MARK: - Kamera listesi küçük resimleri` with the code below.
  - Change `private struct ChannelThumbnail` to `struct ChannelThumbnail`.
  - Leave `ChannelThumbnailLoader` and `AsyncLimiter` untouched.

```swift
import SwiftUI
import ImageIO

/// Ayarlar → Görüntü kaynağı: kaynak, sayılan kamera ve cihaz listesi.
struct VideoSourceSection: View {
    @ObservedObject var vm: CountingViewModel
    @ObservedObject var devices: DeviceStore

    init(vm: CountingViewModel) {
        _vm = ObservedObject(wrappedValue: vm)
        _devices = ObservedObject(wrappedValue: vm.devices)
    }

    var body: some View {
        Section {
            Picker("Kaynak", selection: Binding(get: { vm.sourceKind }, set: { vm.setSource($0) })) {
                ForEach(VideoSourceKind.allCases) { Text($0.title).tag($0) }
            }
            NavigationLink {
                CountCameraPicker(vm: vm)
            } label: {
                LabeledContent("Sayılan kamera") {
                    Text(vm.countCameraSummary).lineLimit(1)
                }
            }
            .accessibilityIdentifier("countCameraLink")
            NavigationLink {
                DeviceListView(vm: vm)
            } label: {
                LabeledContent("Cihazlar") {
                    Text(devices.devices.isEmpty ? "Yok" : "\(devices.devices.count)")
                }
            }
            .accessibilityIdentifier("devicesLink")
            if vm.sourceKind == .network, let state = vm.networkState {
                Text(state.text).font(.caption).foregroundStyle(state.isPlaying ? .green : .orange)
            }
        } header: {
            Text("Görüntü kaynağı")
        } footer: {
            Text("Ağ kamerası: telefon, IP kameranın ya da kayıt cihazındaki (NVR/XVR) bir kameranın yayınını alır ve aynı sayım/kalite kontrolünü yapar. Cihazları bir kez ekle; sayılacak kamerayı ve İzleme şablonlarındaki kameraları bu listeden seç. Telefon cihaza ağ üzerinden ulaşabilmeli (aynı yerel ağ ya da VPN). Uygulama açık ve telefon şarjda kalmalı.")
        }
    }
}

/// Ayarlar → Görüntü kaynağı → Sayılan kamera
struct CountCameraPicker: View {
    @ObservedObject var vm: CountingViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        CameraPickerView(devices: vm.devices, selected: vm.countCamera) { ref in
            guard let ref else { return }
            vm.selectCountCamera(ref)
            vm.setSource(.network)
            dismiss()
        }
        .navigationTitle("Sayılan kamera")
        .navigationBarTitleDisplayMode(.inline)
    }
}

/// Bir cihazın (IP kamera ya da kayıt cihazı) ayarları, kanal listesi, bağlantı sınaması ve kaydı.
struct NetworkCameraForm: View {
    @ObservedObject var vm: CountingViewModel
    @Environment(\.dismiss) private var dismiss
    private let deviceID: String
    private let isNew: Bool
    /// Kaydedince seçili kamera her zaman sayıma alınır (sihirbaz); değilse yalnızca sayım kamerası yoksa
    private let selectsForCounting: Bool
    @State private var name: String
    @State private var config: NetworkCameraConfig
    @State private var password: String
    @State private var portText: String
    @State private var httpPortText: String
    @State private var rtspPortText: String
    @State private var testing = false
    @State private var result: NetworkCameraSource.ProbeResult?
    @State private var errorText: String?
    @State private var saveWarning: String?
    // Kayıt cihazı kamera listesi
    @State private var channels: [RecorderChannel]
    @State private var listing = false
    @State private var channelError: String?
    @State private var search = ""
    @State private var listClient: RecorderClient?
    /// Her listeleme ve cihaz değişikliğinde artar; geç gelen eski yanıt yok sayılır
    @State private var listRequest = 0
    @StateObject private var thumbnails = ChannelThumbnailLoader()
    @FocusState private var focused: Bool

    /// `device`: düzenlenecek cihaz (nil: yeni, türü `initialKind`).
    init(vm: CountingViewModel, device: NetworkDevice? = nil, initialKind: NetworkDeviceKind = .camera,
         selectsForCounting: Bool = false) {
        _vm = ObservedObject(wrappedValue: vm)
        deviceID = device?.id ?? NetworkDevice.newID()
        isNew = device == nil
        self.selectsForCounting = selectsForCounting
        // Başlangıç değerleri burada: onAppear'da atansaydı "cihaz değişti" kuralı kanal listesini silerdi.
        var c = device?.config ?? NetworkCameraConfig()
        if device == nil { c.kind = initialKind }
        let pw = device.map { vm.devices.password(for: $0.id) } ?? ""
        _config = State(initialValue: c)
        _name = State(initialValue: device?.name ?? "")
        _password = State(initialValue: pw)
        _channels = State(initialValue: device.map { vm.devices.channels[$0.id] ?? [] } ?? [])
        _listClient = State(initialValue: device != nil && c.kind == .recorder && c.recorderReady
                            ? NetworkStreamPlan.recorderClient(c, password: pw) : nil)
        _portText = State(initialValue: String(c.port))
        _httpPortText = State(initialValue: c.recorderHTTPPort.map(String.init) ?? "")
        _rtspPortText = State(initialValue: c.recorderRTSPPort.map(String.init) ?? "")
    }

    // Gövde küçük parçalara bölünür: tek büyük ifade derleyicinin tip denetimini zaman aşımına uğratıyordu.
    var body: some View {
        observingChanges(formContent)
            .alert("Şifre", isPresented: warningShown) {
                Button("Tamam") { saveWarning = nil; dismiss() }
            } message: {
                Text(saveWarning ?? "")
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Tamam") { focused = false }
                }
            }
    }

    private var title: String {
        if !isNew { return "Cihazı düzenle" }
        return config.kind == .camera ? "Kamera ekle" : "Kayıt cihazı ekle"
    }

    private var warningShown: Binding<Bool> {
        Binding(get: { saveWarning != nil }, set: { if !$0 { saveWarning = nil } })
    }

    private var formContent: some View {
        Form {
            nameSection
            if config.kind == .camera {
                cameraSections
            } else {
                recorderSections
            }
            substreamSection
            testSection
            saveSection
        }
    }

    private func observingChanges<Content: View>(_ content: Content) -> some View {
        content
            .onChange(of: portText) { _, text in
                config.port = Int(text.filter(\.isNumber)) ?? 0
            }
            .onChange(of: httpPortText) { _, text in
                config.recorderHTTPPort = Int(text.filter(\.isNumber))
            }
            .onChange(of: rtspPortText) { _, text in
                config.recorderRTSPPort = Int(text.filter(\.isNumber))
            }
            .onChange(of: config) { _, _ in
                result = nil
                errorText = nil
            }
            .onChange(of: recorderIdentity) { _, _ in
                recorderChanged()
            }
    }

    /// Başka bir cihaz: eski liste ve seçim geçersiz
    private func recorderChanged() {
        listRequest += 1                                  // süren listeleme eski cihaza ait: sonucu yazılmaz
        listing = false
        channels = []
        channelError = nil
        listClient = nil
        config.recorderChannel = nil
        thumbnails.reset()
    }

    private var nameSection: some View {
        Section {
            TextField(config.kind == .camera ? "Ad (ör. Bant kamerası)" : "Ad (ör. Ofis NVR)", text: $name)
                .focused($focused)
                .accessibilityIdentifier("deviceName")
        } header: {
            Text("Ad")
        } footer: {
            Text(config.kind == .camera
                 ? "Ağa doğrudan bağlı kamera. Ad boş kalırsa \"Kamera 1\" gibi bir ad verilir."
                 : "Kameralar bir kayıt cihazına (NVR/XVR) bağlıysa: cihazı bir kez ekle; kameraları sayım ve İzleme'de listeden seç. Ad boş kalırsa \"NVR 1\" gibi bir ad verilir.")
        }
    }

    private var substreamSection: some View {
        Section {
            Toggle("Alt akış (önerilir)", isOn: $config.substream)
        } footer: {
            Text("Sayım için alt akış (ör. 640×360) yeterli; ağı, pili ve ısınmayı azaltır. İzleme ızgarası her zaman alt akışı, tek kamera ana akışı kullanır.")
        }
    }

    private var saveSection: some View {
        Section {
            Button {
                save()
            } label: {
                Label("Kaydet", systemImage: "checkmark")
            }
            .disabled(!canSave)
            .accessibilityIdentifier("saveNetworkCamera")
        }
    }

    private var canSave: Bool { config.kind == .camera ? config.rtspURL != nil : config.recorderReady }

    // MARK: - Kamera

    @ViewBuilder private var cameraSections: some View {
        Section {
            Picker("Marka", selection: $config.brand) {
                ForEach(CameraBrand.allCases) { Text($0.title).tag($0) }
            }
            if config.brand == .custom {
                TextField("rtsp://192.168.1.64:554/…", text: $config.customURL)
                    .keyboardType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .focused($focused)
            } else {
                LabeledContent("IP adresi") {
                    TextField("192.168.1.64", text: $config.host)
                        .keyboardType(.numbersAndPunctuation)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .multilineTextAlignment(.trailing)
                        .focused($focused)
                }
                LabeledContent("Port") {
                    TextField("554", text: $portText)
                        .keyboardType(.numbersAndPunctuation)
                        .multilineTextAlignment(.trailing)
                        .focused($focused)
                }
                Stepper("Kanal: \(config.channel)", value: $config.channel, in: 1...64)
            }
        } header: {
            Text("Kamera")
        } footer: {
            if let url = config.rtspURL {
                Text("Adres: \(url.absoluteString)").textSelection(.enabled)
            } else {
                Text(config.brand == .custom ? "rtsp:// ile başlayan tam adresi girin."
                                             : "Kameranın IP adresini girin (ör. 192.168.1.64).")
            }
        }

        Section {
            TextField("Kullanıcı adı", text: $config.username)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .focused($focused)
            SecureField("Şifre", text: $password)
                .focused($focused)
        } header: {
            Text("Giriş")
        } footer: {
            Text("Şifre yalnızca bu iPhone'un güvenli anahtar deposunda (Keychain) saklanır.")
        }
    }

    // MARK: - Kayıt cihazı

    /// Değişince kamera listesi ve seçim sıfırlanır
    private var recorderIdentity: String {
        "\(config.recorderBrand.rawValue)|\(config.cleanRecorderHost)|\(config.effectiveHTTPPort)|\(config.effectiveRTSPPort)|\(config.recorderUsername)"
    }

    @ViewBuilder private var recorderSections: some View {
        recorderDeviceSection
        recorderLoginSection
        channelsSection
    }

    private var recorderDeviceSection: some View {
        Section {
            Picker("Marka", selection: $config.recorderBrand) {
                ForEach(RecorderBrand.allCases) { Text($0.title).tag($0) }
            }
            .pickerStyle(.segmented)
            .accessibilityIdentifier("recorderBrand")
            LabeledContent("IP adresi") {
                TextField("192.168.1.10", text: $config.recorderHost)
                    .keyboardType(.numbersAndPunctuation)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .multilineTextAlignment(.trailing)
                    .focused($focused)
                    .accessibilityIdentifier("recorderHost")
            }
            portsGroup
        } header: {
            Text("Kayıt cihazı")
        } footer: {
            Text(recorderFooter)
        }
    }

    private var portsGroup: some View {
        DisclosureGroup("Portlar") {
            LabeledContent(config.recorderBrand == .trassir ? "SDK portu" : "Web portu") {
                TextField(String(config.recorderBrand.defaultHTTPPort), text: $httpPortText)
                    .keyboardType(.numberPad)
                    .multilineTextAlignment(.trailing)
                    .focused($focused)
                    .accessibilityIdentifier("recorderHTTPPort")
            }
            LabeledContent("Görüntü portu") {
                TextField(String(config.recorderBrand.defaultRTSPPort), text: $rtspPortText)
                    .keyboardType(.numberPad)
                    .multilineTextAlignment(.trailing)
                    .focused($focused)
                    .accessibilityIdentifier("recorderRTSPPort")
            }
        }
    }

    private var recorderFooter: String {
        switch config.recorderBrand {
        case .trassir:
            return "TRASSIR'da Ayarlar → Web sunucusu (SDK) açık olmalı. Varsayılan portlar: SDK 8080, görüntü 555."
        case .hikvision, .dahua:
            return "Kayıt cihazının web arayüzüne girdiğin kullanıcı ile. Varsayılan portlar: web 80, görüntü 554."
        }
    }

    private var recorderLoginSection: some View {
        Section {
            TextField("Kullanıcı adı", text: $config.recorderUsername)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .focused($focused)
                .accessibilityIdentifier("recorderUser")
            SecureField("Şifre", text: $password)
                .focused($focused)
                .accessibilityIdentifier("recorderPassword")
        } header: {
            Text("Giriş")
        } footer: {
            Text("Şifre yalnızca bu iPhone'un güvenli anahtar deposunda (Keychain) saklanır.")
        }
    }

    private var channelsSection: some View {
        Section {
            listButton
            channelStatusRows
            ForEach(filteredChannels) { channel in
                channelRow(channel)
            }
        } header: {
            Text(channels.isEmpty ? "Kameralar" : "Kameralar (\(channels.count))")
        } footer: {
            Text(channels.isEmpty ? "" : "Dokunduğun kamera bağlantı testinde kullanılır; sayım için henüz kamera seçilmediyse sayım da bu kamerayla başlar.")
        }
    }

    private var listButton: some View {
        Button {
            listChannels()
        } label: {
            HStack {
                Label(channels.isEmpty ? "Kameraları listele" : "Listeyi yenile", systemImage: "list.bullet.rectangle")
                if listing {
                    Spacer()
                    ProgressView()
                }
            }
        }
        .disabled(listing || !config.recorderReady)
        .accessibilityIdentifier("listChannels")
    }

    @ViewBuilder private var channelStatusRows: some View {
        if let channelError {
            Label(channelError, systemImage: "xmark.octagon.fill")
                .foregroundStyle(.red)
                .accessibilityElement(children: .combine)       // simge + metin tek öğe: metin okunur
                .accessibilityIdentifier("channelError")
            Text(recorderHelp).font(.caption).foregroundStyle(.secondary)
        }
        if channels.count > 8 {
            TextField("Kamera ara (ad ya da kanal no)", text: $search)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .focused($focused)
        }
    }

    private var filteredChannels: [RecorderChannel] {
        let q = search.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else { return channels }
        return channels.filter { ch in
            ch.title.lowercased().contains(q) || ch.number.map { String($0) == q } == true
        }
    }

    private func channelRow(_ channel: RecorderChannel) -> some View {
        Button {
            config.recorderChannel = channel
        } label: {
            HStack(spacing: 12) {
                ChannelThumbnail(image: thumbnails.images[channel.id], failed: thumbnails.failed.contains(channel.id))
                VStack(alignment: .leading, spacing: 2) {
                    Text(channel.title).foregroundStyle(.primary).lineLimit(2)
                    if let subtitle = channel.subtitle {
                        Text(subtitle).font(.caption).foregroundStyle(.secondary)
                    }
                }
                Spacer()
                if config.recorderChannel?.id == channel.id {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(.tint)
                }
            }
        }
        .accessibilityIdentifier("channel.\(channel.title)")
        .accessibilityAddTraits(config.recorderChannel?.id == channel.id ? .isSelected : [])
        .task(id: channel.id) {
            // Yalnızca ekranda görünen satırlar yükler; aynı anda en fazla 3 istek (64–128 kanallı cihazlar)
            guard let client = listClient else { return }
            await thumbnails.load(channel, client: client, username: config.recorderUsername, password: password)
        }
    }

    private var recorderHelp: String {
        switch config.recorderBrand {
        case .trassir:
            return "Kontrol et: IP adresi · telefon aynı ağda mı · TRASSIR'da Ayarlar → Web sunucusu (SDK) açık mı, port 8080 mi · kullanıcının kameraları izleme yetkisi var mı."
        case .hikvision, .dahua:
            return "Kontrol et: IP adresi · telefon aynı ağda mı · web portu (varsayılan 80) · kullanıcı adı/şifre (kayıt cihazının web arayüzündeki ile aynı)."
        }
    }

    private func listChannels() {
        focused = false
        listing = true
        channelError = nil
        search = ""
        // Satırlar kaldırılır: yeni liste gelince her satırın küçük resim görevi baştan başlar
        // (aynı kimlikli satır kalsaydı görev yeniden çalışmaz, sıfırlanan küçük resim hiç gelmezdi)
        channels = []
        thumbnails.reset()
        listRequest += 1
        let mine = listRequest
        let client = NetworkStreamPlan.recorderClient(config, password: password)
        listClient = client
        Task { @MainActor in
            do {
                let list = try await client.channels()
                guard mine == listRequest else { return }  // bu arada cihaz değişti ya da yeniden listelendi
                channels = list
                // Seçili kamera hâlâ var mı (ad değişmiş olabilir)
                if let selected = config.recorderChannel {
                    config.recorderChannel = list.first { $0.id == selected.id }
                }
            } catch {
                guard mine == listRequest else { return }
                channels = []
                channelError = error.localizedDescription
            }
            listing = false
        }
    }

    // MARK: - Sınama ve kayıt

    private var testSection: some View {
        Section {
            Button {
                test()
            } label: {
                HStack {
                    Label("Bağlantıyı test et", systemImage: "antenna.radiowaves.left.and.right")
                    if testing { Spacer(); ProgressView() }
                }
            }
            .disabled(testing || !config.isComplete)
            .accessibilityIdentifier("testConnection")
            if let result {
                if let thumb = result.thumbnail {
                    Image(decorative: thumb, scale: 1).resizable().scaledToFit()
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                }
                Label("Bağlandı · \(result.width)×\(result.height) · \(result.codec)",
                      systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                    .accessibilityElement(children: .combine)       // simge + metin tek öğe: metin okunur
                    .accessibilityIdentifier("testResult")
                if result.width > 1280 {
                    Text("Sayım için alt akış (ör. 640×360) yeterli ve daha az pil/ısı demek.")
                        .font(.caption).foregroundStyle(.orange)
                }
            }
            if let errorText {
                Label(errorText, systemImage: "xmark.octagon.fill").foregroundStyle(.red)
                    .accessibilityElement(children: .combine)       // simge + metin tek öğe: metin okunur
                    .accessibilityIdentifier("testError")
                Text(config.kind == .camera
                     ? "Kontrol et: IP adresi doğru mu · telefon kamerayla aynı ağda mı (misafir Wi-Fi çoğu zaman kameralara erişemez) · kamerada RTSP açık mı, port 554 mü · kullanıcı adı/şifre · marka/kanal doğru mu (olmazsa \"Diğer\" ile tam adres). iPhone \"Yerel ağ\" izni istediyse izin ver."
                     : recorderHelp)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        } footer: {
            Text(config.kind == .recorder && config.recorderChannel == nil ? "Test için listeden bir kamera seç." : "")
        }
    }

    private func test() {
        guard let plan = NetworkStreamPlan.make(config, password: password) else { return }
        focused = false
        testing = true
        result = nil
        errorText = nil
        Task { @MainActor in
            switch await NetworkCameraSource.probe(resolver: plan.resolver, username: plan.username,
                                                   password: plan.password) {
            case .success(let r): result = r
            case .failure(let e): errorText = e.localizedDescription
            }
            testing = false
        }
    }

    private func save() {
        focused = false
        let selected = config.recorderChannel
        let saved = vm.devices.save(NetworkDevice(id: deviceID, name: name, config: config), password: password)
        if config.kind == .recorder { vm.devices.setChannels(channels, for: deviceID) }
        vm.deviceSaved(deviceID)
        let ref: CameraRef? = config.kind == .camera
            ? CameraRef(sourceId: deviceID, channelId: nil)
            : selected.map { CameraRef(sourceId: deviceID, channelId: $0.id) }
        if let ref, selectsForCounting || vm.countCamera == nil {
            vm.selectCountCamera(ref)
            vm.setSource(.network)
        }
        if let warning = saved.warning {
            saveWarning = warning                    // sessizce geçme: kullanıcıya göster, sonra kapat
        } else {
            dismiss()
        }
    }
}

```

- [ ] **Step 5: Device list.** Create `apps/ios/BantSayac/UI/DeviceListView.swift`:

```swift
import SwiftUI

/// Ayarlar → Görüntü kaynağı → Cihazlar: kamera ve kayıt cihazları (ekle, düzenle, sil).
struct DeviceListView: View {
    @ObservedObject var vm: CountingViewModel
    @ObservedObject var devices: DeviceStore
    @State private var adding: NetworkDeviceKind?
    @State private var pendingDelete: NetworkDevice?

    init(vm: CountingViewModel) {
        _vm = ObservedObject(wrappedValue: vm)
        _devices = ObservedObject(wrappedValue: vm.devices)
    }

    var body: some View {
        List {
            Section {
                ForEach(devices.devices) { device in
                    NavigationLink {
                        NetworkCameraForm(vm: vm, device: device)
                    } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(device.name)
                            Text(device.summary).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        }
                    }
                    .accessibilityIdentifier("device.\(device.name)")
                    .swipeActions {
                        Button("Sil", role: .destructive) { pendingDelete = device }
                    }
                }
                if devices.devices.isEmpty {
                    Text("Henüz cihaz yok.").foregroundStyle(.secondary)
                }
            } footer: {
                if let problem = devices.problem {
                    Text(problem).foregroundStyle(.red)
                }
            }
            Section {
                Button { adding = .camera } label: {
                    Label("Kamera ekle", systemImage: "web.camera")
                }
                .accessibilityIdentifier("addCamera")
                Button { adding = .recorder } label: {
                    Label("Kayıt cihazı ekle (NVR/XVR)", systemImage: "externaldrive.connected.to.line.below")
                }
                .accessibilityIdentifier("addRecorder")
            } footer: {
                Text("Kayıt cihazı bir kez eklenir; kameraları (kanalları) sayım ve İzleme için listeden seçilir. Silmek için satırı sola kaydır.")
            }
        }
        .navigationTitle("Cihazlar")
        .navigationBarTitleDisplayMode(.inline)
        .navigationDestination(item: $adding) { kind in
            NetworkCameraForm(vm: vm, device: nil, initialKind: kind)
        }
        .alert("Cihaz silinsin mi?", isPresented: deleteShown, presenting: pendingDelete) { device in
            Button("Sil", role: .destructive) { vm.deleteDevice(device.id) }
            Button("Vazgeç", role: .cancel) {}
        } message: { device in
            Text("\(device.name) ve şifresi bu iPhone'dan silinir. Bu cihazı kullanan İzleme kutuları \"Kamera silinmiş\" gösterir.")
        }
    }

    private var deleteShown: Binding<Bool> {
        Binding(get: { pendingDelete != nil }, set: { if !$0 { pendingDelete = nil } })
    }
}
```

- [ ] **Step 6: Camera picker.** Create `apps/ios/BantSayac/UI/CameraPickerView.swift`:

```swift
import SwiftUI

/// Cihaz listesinden kamera seçimi (sayım ve İzleme şablonu). Kayıt cihazlarında kanallar küçük resimle.
struct CameraPickerView: View {
    @ObservedObject var devices: DeviceStore
    let selected: CameraRef?
    /// Seçilemeyen kameralar (şablonda başka kutuda olanlar)
    var unavailable: Set<CameraRef> = []
    /// "Boş bırak" satırı (şablon kutusu)
    var allowsEmpty = false
    let onPick: (CameraRef?) -> Void

    var body: some View {
        List {
            if allowsEmpty {
                Button { onPick(nil) } label: {
                    Label("Boş bırak", systemImage: "square.dashed")
                }
                .accessibilityIdentifier("pickEmpty")
            }
            if devices.devices.isEmpty {
                Text("Henüz cihaz yok. Ayarlar → Görüntü kaynağı → Cihazlar'dan kamera ya da kayıt cihazı ekle.")
                    .foregroundStyle(.secondary)
            }
            ForEach(devices.devices) { device in
                DeviceCamerasSection(devices: devices, device: device, selected: selected,
                                     unavailable: unavailable, onPick: onPick)
            }
        }
    }
}

/// Bir cihazın kameraları: doğrudan kamerada tek satır, kayıt cihazında kanallar (+ listeyi yenile)
private struct DeviceCamerasSection: View {
    @ObservedObject var devices: DeviceStore
    let device: NetworkDevice
    let selected: CameraRef?
    let unavailable: Set<CameraRef>
    let onPick: (CameraRef?) -> Void
    @StateObject private var thumbnails = ChannelThumbnailLoader()
    @State private var listing = false
    @State private var error: String?

    var body: some View {
        Section {
            if device.kind == .camera {
                row(CameraRef(sourceId: device.id, channelId: nil), title: device.name, subtitle: device.summary,
                    channel: nil)
            } else {
                ForEach(channelList) { channel in
                    row(CameraRef(sourceId: device.id, channelId: channel.id), title: channel.title,
                        subtitle: channel.subtitle, channel: channel)
                }
                refreshButton
                if let error {
                    Label(error, systemImage: "xmark.octagon.fill")
                        .foregroundStyle(.red)
                        .accessibilityElement(children: .combine)
                }
            }
        } header: {
            Text(device.name)
        }
    }

    private var channelList: [RecorderChannel] { devices.channels[device.id] ?? [] }

    private var refreshButton: some View {
        Button {
            refresh()
        } label: {
            HStack {
                Label(channelList.isEmpty ? "Kanalları listele" : "Kanalları yenile", systemImage: "arrow.clockwise")
                if listing { Spacer(); ProgressView() }
            }
        }
        .disabled(listing)
        .accessibilityIdentifier("refreshChannels.\(device.name)")
    }

    private func row(_ ref: CameraRef, title: String, subtitle: String?, channel: RecorderChannel?) -> some View {
        let blocked = unavailable.contains(ref)
        return Button {
            onPick(ref)
        } label: {
            HStack(spacing: 12) {
                if let channel {
                    ChannelThumbnail(image: thumbnails.images[channel.id], failed: thumbnails.failed.contains(channel.id))
                } else {
                    Image(systemName: "web.camera").font(.title2).frame(width: 96, height: 54)
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).foregroundStyle(blocked ? .secondary : .primary).lineLimit(2)
                    if let subtitle {
                        Text(subtitle).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    }
                    if blocked {
                        Text("Bu şablonda zaten var").font(.caption).foregroundStyle(.orange)
                    }
                }
                Spacer()
                if selected == ref {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(.tint)
                }
            }
        }
        .disabled(blocked)
        .accessibilityIdentifier("camera.\(title)")
        .accessibilityAddTraits(selected == ref ? .isSelected : [])
        .task(id: channel?.id) {
            guard let channel, let client = devices.recorderClient(for: device.id) else { return }
            await thumbnails.load(channel, client: client, username: device.config.recorderUsername,
                                  password: devices.password(for: device.id))
        }
    }

    private func refresh() {
        guard let client = devices.recorderClient(for: device.id) else { return }
        listing = true
        error = nil
        Task { @MainActor in
            do {
                devices.setChannels(try await client.channels(), for: device.id)
            } catch {
                self.error = error.localizedDescription
            }
            listing = false
        }
    }
}
```

- [ ] **Step 7: Onboarding.** In `apps/ios/BantSayac/UI/OnboardingView.swift`:
  - In the `.sheet(item: $networkFormKind)` closure, replace `NetworkCameraForm(vm: vm, initialKind: kind)` with `NetworkCameraForm(vm: vm, initialKind: kind, selectsForCounting: true)`.
  - In `.onAppear`, replace the block `if vm.sourceKind == .network { source = vm.networkConfig.kind == .recorder ? .recorder : .camera }` with:

```swift
            if vm.sourceKind == .network, let device = vm.countDevice {
                source = device.kind == .recorder ? .recorder : .camera
            }
```

  - Replace the `networkReady` property with:

```swift
    private var networkReady: Bool {
        guard let ref = vm.countCamera, case .ok(let config) = vm.devices.lookup(ref) else { return false }
        return config.kind == (source == .recorder ? .recorder : .camera)
    }
```

  - In `sourceStep`, replace `"Ayarlandı: \(vm.networkConfig.summary)"` with `"Ayarlandı: \(vm.countCameraSummary)"`.

- [ ] **Step 8: Adapt UI tests to the Cihazlar flow.** In `apps/ios/BantSayacUITests/BantSayacUITests.swift`, replace `openRecorderForm(brand:)` with:

```swift
    /// Temiz ayarlarla açar (kamera izni istenmez), Ayarlar → Cihazlar → Kayıt cihazı ekle → marka.
    private func openRecorderForm(brand: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment["BS_TEST_FORMS"] = "1"
        app.launch()
        app.tabBars.buttons["Ayarlar"].tap()
        let link = element(app, "devicesLink")
        XCTAssertTrue(link.waitForExistence(timeout: 10))
        link.tap()
        let add = element(app, "addRecorder")
        XCTAssertTrue(add.waitForExistence(timeout: 10))
        add.tap()
        let brandPicker = element(app, "recorderBrand")
        XCTAssertTrue(brandPicker.waitForExistence(timeout: 10))
        brandPicker.buttons[brand].tap()
        return app
    }
```

In `pickTestAndSave`, replace the block from `let live = app.staticTexts.matching(…)` through the end of the function with:

```swift
        // Kaydedince Cihazlar listesine dönülür; sayım için kamera seçili değildi: sayım bu kamerayla başlar
        let device = element(app, "device.NVR 1")
        XCTAssertTrue(device.waitForExistence(timeout: 10), "cihaz listede yok")
        app.navigationBars.buttons["Ayarlar"].tap()
        let live = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", "Canlı ·")).firstMatch
        let playing = live.waitForExistence(timeout: 60)
        if !playing {
            let states = app.staticTexts.allElementsBoundByIndex.map(\.label)
                .filter { $0.contains("Yayın") || $0.contains("Bağlan") || $0.contains("yeniden") }
            print("KAYIT CİHAZI yayın durumu: \(states)")
        }
        XCTAssertTrue(playing, "kaydettikten sonra yayın başlamadı")
        print("KAYIT CİHAZI yayın: \(live.label)")
        XCTAssertTrue(element(app, "countCameraLink").label.contains("NVR 1 · \(camera)"),
                      "sayılan kamera: \(element(app, "countCameraLink").label)")
    }
```

- [ ] **Step 9: Commit, then run CI and the UI tests.**
  - Commit with the message `iPhone: sayım cihaz listesinden kamera seçer (Cihazlar, sayılan kamera, sihirbaz)`.
  - Run CI. Expected: `ios` exit 0.
  - Dispatch `ios-uitest` and wait for it. Expected: success, with the three recorder tests, the onboarding test, the network count test and the video test all passing.
  - On a UI test failure, read the `KAYIT CİHAZI` / `=== EKRAN` lines in the log tail, fix, and re-run.

---

### Task 4: Image distributor (`CameraHub`) and counting feed

**Files:**
- Create: `apps/ios/BantSayac/Camera/CameraHub.swift`, `apps/ios/BantSayac/Camera/HubStreams.swift`
- Modify: `apps/ios/BantSayac/Camera/NetworkCameraSource.swift` (`onProblem`; `retry` gets a `problem` argument)
- Modify: `apps/ios/BantSayac/UI/CountingViewModel.swift` (owns `hub`, feeds it, resets it on device changes)
- Test: `apps/ios/BantSayacTests/CameraHubTests.swift`

**Interfaces:**
- Consumes: `CameraRef`, `TileQuality`, `DeviceStore.lookup/password/recorderClient`, `NetworkStreamPlan.make(_:password:client:)`, `NetworkCameraState`, `UncheckedSendable`.
- Produces:
  - `TileStatus` (with `text: String?`, `init(_ problem: StreamProblem)`, `init(counting: NetworkCameraState)`)
  - `StreamProblem.of(_:)`
  - `HubKey(ref:quality:)`
  - protocols: `HubSubscriber` (`hubFrame(_:)`, `hubStatus(_:)`) and `HubStream` (`start(onFrame:onStatus:)`, `stop()`)
  - `HubOpen` (`.stream` / `.rejected`)
  - `@MainActor CameraHub(opener:now:)`:
    - constants: `maxSub` 16, `maxMain` 1, `graceSeconds` 5
    - state: `openCount`, `status(_:)`
    - methods: `subscribe`, `unsubscribe`, `retry`, `reset(sourceId:)`, `sweep`, `closeIdle`, `setExternal`, `externalStatus`, and `nonisolated externalFrame`
  - `NetworkHubStream(plan:)`, `DeviceStore.hubOpen(_:)`
  - `CountingViewModel.hub`

- [ ] **Step 1: Write the failing tests.** Create `apps/ios/BantSayacTests/CameraHubTests.swift`:

```swift
import XCTest
import CoreVideo
@testable import BantSayac

/// Sahte bağlantı: başlat/durdur sayılır, kare ve durum elle verilir.
final class FakeStream: HubStream, @unchecked Sendable {
    private(set) var started = 0
    private(set) var stopped = 0
    private var onFrame: (@Sendable (CVPixelBuffer) -> Void)?
    private var onStatus: (@Sendable (TileStatus) -> Void)?

    func start(onFrame: @escaping @Sendable (CVPixelBuffer) -> Void,
               onStatus: @escaping @Sendable (TileStatus) -> Void) {
        started += 1
        self.onFrame = onFrame
        self.onStatus = onStatus
    }

    func stop() { stopped += 1 }
    func emit(_ frame: CVPixelBuffer) { onFrame?(frame) }
    func emit(_ status: TileStatus) { onStatus?(status) }
}

final class FakeSubscriber: HubSubscriber, @unchecked Sendable {
    private(set) var frames: [CVPixelBuffer] = []
    private(set) var statuses: [TileStatus] = []
    var lastStatus: TileStatus? { statuses.last }
    func hubFrame(_ frame: CVPixelBuffer) { frames.append(frame) }
    func hubStatus(_ status: TileStatus) { statuses.append(status) }
}

func makeTestFrame() -> CVPixelBuffer {
    var pb: CVPixelBuffer?
    CVPixelBufferCreate(kCFAllocatorDefault, 4, 4, kCVPixelFormatType_32BGRA, nil, &pb)
    return pb!
}

/// Görüntü dağıtıcısı: paylaşım, kapanış payı, sınırlar, sayım beslemesi (sahte bağlantıyla, ağsız).
@MainActor
final class CameraHubTests: XCTestCase {
    private var clock = 0.0
    private var opened: [HubKey: [FakeStream]] = [:]
    private var rejections: [CameraRef: TileStatus] = [:]

    private func makeHub() -> CameraHub {
        CameraHub(opener: { [unowned self] key in
            if let status = self.rejections[key.ref] { return .rejected(status) }
            let stream = FakeStream()
            self.opened[key, default: []].append(stream)
            return .stream(stream)
        }, now: { [unowned self] in self.clock })
    }

    private func ref(_ n: Int) -> CameraRef { CameraRef(sourceId: "nvr", channelId: String(n)) }
    private func sub(_ n: Int) -> HubKey { HubKey(ref: ref(n), quality: .sub) }
    private func main(_ n: Int) -> HubKey { HubKey(ref: ref(n), quality: .main) }

    func testOneReaderPerKeyIsShared() {
        let hub = makeHub()
        let a = FakeSubscriber(), b = FakeSubscriber()
        hub.subscribe(sub(1), a)
        hub.subscribe(sub(1), b)
        XCTAssertEqual(opened[sub(1)]?.count, 1)
        let f = makeTestFrame()
        opened[sub(1)]?.first?.emit(f)
        XCTAssertTrue(a.frames.last === f)
        XCTAssertTrue(b.frames.last === f)
        XCTAssertEqual(hub.openCount.sub, 1)
    }

    func testIdleReaderClosesAfterGrace() {
        let hub = makeHub()
        let a = FakeSubscriber()
        hub.subscribe(sub(1), a)
        hub.unsubscribe(sub(1), a)
        clock = 4.9
        hub.sweep()
        XCTAssertEqual(opened[sub(1)]?.first?.stopped, 0)
        clock = 5.0
        hub.sweep()
        XCTAssertEqual(opened[sub(1)]?.first?.stopped, 1)
        XCTAssertEqual(hub.openCount.sub, 0)
    }

    func testResubscribeWithinGraceKeepsConnection() {
        let hub = makeHub()
        let a = FakeSubscriber(), b = FakeSubscriber()
        hub.subscribe(sub(1), a)
        hub.unsubscribe(sub(1), a)
        clock = 3
        hub.subscribe(sub(1), b)
        clock = 20
        hub.sweep()
        XCTAssertEqual(opened[sub(1)]?.count, 1)
        XCTAssertEqual(opened[sub(1)]?.first?.stopped, 0)
    }

    func testSixteenSubStreamsThenLimitUntilOneIsFree() {
        let hub = makeHub()
        let subs = (1...17).map { _ in FakeSubscriber() }
        for n in 1...16 { hub.subscribe(sub(n), subs[n - 1]) }
        hub.subscribe(sub(17), subs[16])
        XCTAssertEqual(subs[16].lastStatus, .limit)
        XCTAssertNil(opened[sub(17)])
        hub.unsubscribe(sub(1), subs[0])               // boşa çıkan okuyucu hemen yer açar
        XCTAssertEqual(opened[sub(1)]?.first?.stopped, 1)
        XCTAssertEqual(opened[sub(17)]?.count, 1)
        XCTAssertEqual(subs[16].lastStatus, .connecting)
        XCTAssertEqual(hub.openCount.sub, 16)
    }

    func testTemplateSwitchReusesCommonAndEvictsIdle() {
        let hub = makeHub()
        let old = (1...16).map { _ in FakeSubscriber() }
        for n in 1...16 { hub.subscribe(sub(n), old[n - 1]) }
        for n in 1...16 { hub.unsubscribe(sub(n), old[n - 1]) }
        let new = (9...24).map { _ in FakeSubscriber() }   // 9–16 ortak, 17–24 yeni
        for (i, n) in (9...24).enumerated() { hub.subscribe(sub(n), new[i]) }
        for n in 9...16 {
            XCTAssertEqual(opened[sub(n)]?.count, 1, "ortak kamera \(n) yeniden açılmamalı")
            XCTAssertEqual(opened[sub(n)]?.first?.stopped, 0)
        }
        for s in new { XCTAssertNotEqual(s.lastStatus, .limit) }
        XCTAssertEqual(hub.openCount.sub, 16)
    }

    func testOneMainStream() {
        let hub = makeHub()
        let a = FakeSubscriber(), b = FakeSubscriber()
        hub.subscribe(main(1), a)
        hub.subscribe(main(2), b)
        XCTAssertEqual(b.lastStatus, .limit)
        XCTAssertEqual(hub.openCount.main, 1)
    }

    func testRejectedTileShowsReasonWithoutConnection() {
        let hub = makeHub()
        rejections[ref(1)] = .deleted
        let a = FakeSubscriber()
        hub.subscribe(sub(1), a)
        XCTAssertEqual(a.lastStatus, .deleted)
        XCTAssertNil(opened[sub(1)])
        XCTAssertEqual(hub.openCount.sub, 0)
    }

    func testCountedCameraUsesCountingStream() {
        let hub = makeHub()
        hub.setExternal(ref(1))
        let a = FakeSubscriber(), b = FakeSubscriber()
        hub.subscribe(sub(1), a)
        hub.subscribe(main(1), b)
        XCTAssertNil(opened[sub(1)])
        XCTAssertNil(opened[main(1)])
        let f = makeTestFrame()
        hub.externalFrame(f)
        XCTAssertTrue(a.frames.last === f)
        XCTAssertTrue(b.frames.last === f)
        hub.externalStatus(.playing)
        XCTAssertEqual(a.lastStatus, .playing)
        XCTAssertEqual(hub.openCount.sub + hub.openCount.main, 0)
    }

    func testCountingTakesOverOpenReader() {
        let hub = makeHub()
        let a = FakeSubscriber()
        hub.subscribe(sub(1), a)
        hub.setExternal(ref(1))
        XCTAssertEqual(opened[sub(1)]?.first?.stopped, 1)
        XCTAssertEqual(hub.openCount.sub, 0)
        let f = makeTestFrame()
        hub.externalFrame(f)
        XCTAssertTrue(a.frames.last === f)
    }

    func testCountingStopsThenTileOpensOwnConnection() {
        let hub = makeHub()
        hub.setExternal(ref(1))
        let a = FakeSubscriber()
        hub.subscribe(sub(1), a)
        hub.setExternal(nil)
        XCTAssertEqual(opened[sub(1)]?.count, 1)
        XCTAssertEqual(opened[sub(1)]?.first?.started, 1)
    }

    func testLastFrameShownWhenComingBack() throws {
        let hub = makeHub()
        let a = FakeSubscriber(), b = FakeSubscriber()
        hub.subscribe(sub(1), a)
        let f = makeTestFrame()
        try XCTUnwrap(opened[sub(1)]?.first).emit(f)
        hub.unsubscribe(sub(1), a)
        clock = 6
        hub.sweep()
        XCTAssertEqual(hub.openCount.sub, 0)
        hub.subscribe(sub(1), b)
        XCTAssertTrue(b.frames.first === f, "son kare hemen görünmeli")
        XCTAssertEqual(opened[sub(1)]?.count, 2)
    }

    func testMainShowsSubFrameUntilItsOwnArrives() throws {
        let hub = makeHub()
        let a = FakeSubscriber(), b = FakeSubscriber()
        hub.subscribe(sub(1), a)
        let f = makeTestFrame()
        try XCTUnwrap(opened[sub(1)]?.first).emit(f)
        hub.subscribe(main(1), b)
        XCTAssertTrue(b.frames.first === f)
    }

    func testRetryAfterPasswordError() throws {
        let hub = makeHub()
        let a = FakeSubscriber()
        hub.subscribe(sub(1), a)
        try XCTUnwrap(opened[sub(1)]?.first).emit(.authFailed)
        XCTAssertEqual(a.lastStatus, .authFailed)
        hub.retry(sub(1))
        XCTAssertEqual(opened[sub(1)]?.first?.stopped, 1)
        XCTAssertEqual(opened[sub(1)]?.count, 2)
        XCTAssertEqual(a.lastStatus, .connecting)
    }

    func testDeviceResetReopensWithNewSettings() {
        let hub = makeHub()
        let a = FakeSubscriber()
        hub.subscribe(sub(1), a)
        rejections[ref(1)] = .deleted
        hub.reset(sourceId: "nvr")
        XCTAssertEqual(opened[sub(1)]?.first?.stopped, 1)
        XCTAssertEqual(a.lastStatus, .deleted)
        XCTAssertEqual(hub.openCount.sub, 0)
    }

    func testBackgroundClosesIdleImmediately() {
        let hub = makeHub()
        let a = FakeSubscriber()
        hub.subscribe(sub(1), a)
        hub.unsubscribe(sub(1), a)
        hub.closeIdle()
        XCTAssertEqual(opened[sub(1)]?.first?.stopped, 1)
    }
}

final class StreamProblemTests: XCTestCase {
    func testClassification() {
        XCTAssertEqual(StreamProblem.of(RTSPClient.Failure.unauthorized), .auth)
        XCTAssertEqual(StreamProblem.of(RTSPClient.Failure.status(453, "Not Enough Bandwidth")), .refused)
        XCTAssertEqual(StreamProblem.of(RTSPClient.Failure.status(503, "Service Unavailable")), .refused)
        XCTAssertEqual(StreamProblem.of(RTSPClient.Failure.status(404, "Not Found")), .offline)
        XCTAssertEqual(StreamProblem.of(RTSPClient.Failure.unsupportedCodec("MJPEG")), .unsupported)
        XCTAssertEqual(StreamProblem.of(RecorderError.unauthorized), .auth)
        XCTAssertEqual(StreamProblem.of(RecorderError.unreachable("zaman aşımı")), .offline)
        XCTAssertEqual(StreamProblem.of(nil), .offline)
        XCTAssertEqual(TileStatus(StreamProblem.refused).text, "NVR bağlantı sınırına ulaştı")
        XCTAssertEqual(TileStatus(counting: .reconnecting(seconds: 2, reason: "x")), .connecting)
    }
}
```

- [ ] **Step 2: Implement `CameraHub.swift`.** Create `apps/ios/BantSayac/Camera/CameraHub.swift`:

```swift
import Foundation
import CoreVideo

/// İzleme kutusunun durumu; `text` kutu ortasındaki Türkçe metin (canlıyken ve boşken nil)
enum TileStatus: Equatable, Sendable {
    case idle, connecting, playing, offline, authFailed, nvrLimit, limit, deleted, channelMissing, unsupported

    var text: String? {
        switch self {
        case .idle, .playing: return nil
        case .connecting: return "Bağlanıyor…"
        case .offline: return "Bağlantı yok"
        case .authFailed: return "Şifre hatalı"
        case .nvrLimit: return "NVR bağlantı sınırına ulaştı"
        case .limit: return "Sınır aşıldı"
        case .deleted: return "Kamera silinmiş"
        case .channelMissing: return "Kanal bulunamadı"
        case .unsupported: return "Görüntü biçimi desteklenmiyor"
        }
    }
}

/// Bağlantı sorununun türü (NetworkCameraSource → izleme kutusu)
enum StreamProblem: Equatable, Sendable {
    case offline, auth, refused, unsupported

    static func of(_ error: Error?) -> StreamProblem {
        if let failure = error as? RTSPClient.Failure {
            switch failure {
            case .unauthorized: return .auth
            case .status(let code, _) where code == 453 || code == 503: return .refused
            case .unsupportedCodec: return .unsupported
            default: return .offline
            }
        }
        if let recorder = error as? RecorderError {
            switch recorder {
            case .unauthorized: return .auth
            case .http(let code) where code == 503 || code == 429: return .refused
            default: return .offline
            }
        }
        return .offline
    }
}

extension TileStatus {
    init(_ problem: StreamProblem) {
        switch problem {
        case .offline: self = .offline
        case .auth: self = .authFailed
        case .refused: self = .nvrLimit
        case .unsupported: self = .unsupported
        }
    }

    /// Sayım akışının durumu kutuda: koparken "Bağlanıyor…" (son kare kalır)
    init(counting state: NetworkCameraState) {
        switch state {
        case .playing: self = .playing
        case .connecting, .reconnecting: self = .connecting
        case .ended: self = .offline
        }
    }
}

struct HubKey: Hashable, Sendable {
    let ref: CameraRef
    let quality: TileQuality
}

/// Kutu: kareyi ve durumu alır. Herhangi bir iş parçacığından çağrılır; hızlı dönmeli.
protocol HubSubscriber: AnyObject, Sendable {
    func hubFrame(_ frame: CVPixelBuffer)
    func hubStatus(_ status: TileStatus)
}

/// Hub'ın açtığı bağlantı (gerçeği NetworkHubStream; testte sahte). `start` bir kez çağrılır.
protocol HubStream: AnyObject, Sendable {
    func start(onFrame: @escaping @Sendable (CVPixelBuffer) -> Void,
               onStatus: @escaping @Sendable (TileStatus) -> Void)
    func stop()
}

enum HubOpen {
    case stream(HubStream)
    case rejected(TileStatus)
}

/// Bir okuyucunun aboneleri, son karesi ve durumu (kilitli: kareler çözücü iş parçacığından gelir).
final class HubFanout: @unchecked Sendable {
    private let lock = NSLock()
    private var subscribers: [ObjectIdentifier: HubSubscriber] = [:]
    private var frame: CVPixelBuffer?
    private var status: TileStatus = .connecting

    var isEmpty: Bool {
        lock.lock(); defer { lock.unlock() }
        return subscribers.isEmpty
    }

    var lastFrame: CVPixelBuffer? {
        lock.lock(); defer { lock.unlock() }
        return frame
    }

    var currentStatus: TileStatus {
        lock.lock(); defer { lock.unlock() }
        return status
    }

    /// Abone eklenir; son kare (yoksa `fallback`) ve durum hemen verilir.
    func add(_ subscriber: HubSubscriber, fallback: CVPixelBuffer?) {
        lock.lock()
        subscribers[ObjectIdentifier(subscriber)] = subscriber
        let f = frame ?? fallback
        let st = status
        lock.unlock()
        if let f { subscriber.hubFrame(f) }
        subscriber.hubStatus(st)
    }

    /// Dönüş: hiç abone kalmadı mı
    @discardableResult
    func remove(_ subscriber: HubSubscriber) -> Bool {
        lock.lock(); defer { lock.unlock() }
        subscribers[ObjectIdentifier(subscriber)] = nil
        return subscribers.isEmpty
    }

    func deliver(_ f: CVPixelBuffer) {
        lock.lock()
        frame = f
        let subs = Array(subscribers.values)
        lock.unlock()
        for s in subs { s.hubFrame(f) }
    }

    func setStatus(_ st: TileStatus) {
        lock.lock()
        guard st != status else { lock.unlock(); return }
        status = st
        let subs = Array(subscribers.values)
        lock.unlock()
        for s in subs { s.hubStatus(st) }
    }
}

/// Sayımın akışından gelen kareler (çözücü iş parçacığı) sayılan kameranın kutularına
final class ExternalFeed: @unchecked Sendable {
    private let lock = NSLock()
    private var fans: [HubFanout] = []
    private var status: TileStatus = .connecting

    var currentStatus: TileStatus {
        lock.lock(); defer { lock.unlock() }
        return status
    }

    func add(_ fan: HubFanout) {
        lock.lock(); fans.append(fan); lock.unlock()
    }

    func remove(_ fan: HubFanout) {
        lock.lock(); fans.removeAll { $0 === fan }; lock.unlock()
    }

    func reset() {
        lock.lock(); fans = []; status = .connecting; lock.unlock()
    }

    func frame(_ f: CVPixelBuffer) {
        lock.lock(); let current = fans; lock.unlock()
        for fan in current { fan.deliver(f) }
    }

    func setStatus(_ st: TileStatus) {
        lock.lock(); status = st; let current = fans; lock.unlock()
        for fan in current { fan.setStatus(st) }
    }
}

/// İzleme görüntü dağıtıcısı (docs/superpowers/specs/2026-10-11-iphone-izleme-design.md §3):
/// - kamera ve nitelik başına tek okuyucu; kutular aynı kareyi paylaşır;
/// - sayılan kamera sayımın akışından beslenir (NVR'a ikinci bağlantı yok);
/// - abonesi kalmayan okuyucu 5 sn sonra kapanır; yer gerekince hemen çıkarılır;
/// - aynı anda en çok 16 alt ve 1 ana akış (sayımın kendi bağlantısı sayılmaz).
/// Denetim ana iş parçacığında; kareler kilitli `HubFanout` üzerinden doğrudan kutulara gider.
@MainActor
final class CameraHub {
    static let maxSub = 16
    static let maxMain = 1
    static let graceSeconds = 5.0
    static let lastFrameSeconds = 60.0

    private enum Source {
        case stream(HubStream)
        case external
        case waiting
        case rejected(TileStatus)
    }

    private final class Reader {
        let key: HubKey
        let fan = HubFanout()
        var source: Source = .waiting
        /// Abonesi kalmadığı an (nil: abonesi var)
        var idleSince: Double?

        init(key: HubKey) { self.key = key }

        var isStream: Bool {
            if case .stream = source { return true }
            return false
        }
    }

    private var readers: [HubKey: Reader] = [:]
    private var lastFrames: [CameraRef: (frame: UncheckedSendable<CVPixelBuffer>, at: Double)] = [:]
    private var external: CameraRef?
    private nonisolated let feed = ExternalFeed()
    private let opener: (HubKey) -> HubOpen
    private let now: () -> Double

    init(opener: @escaping (HubKey) -> HubOpen,
         now: @escaping () -> Double = { ProcessInfo.processInfo.systemUptime }) {
        self.opener = opener
        self.now = now
    }

    /// Açık bağlantı sayısı (teşhis ve test)
    var openCount: (sub: Int, main: Int) {
        var sub = 0, main = 0
        for r in readers.values where r.isStream {
            if r.key.quality == .sub { sub += 1 } else { main += 1 }
        }
        return (sub, main)
    }

    func status(_ key: HubKey) -> TileStatus? { readers[key]?.fan.currentStatus }

    func subscribe(_ key: HubKey, _ subscriber: HubSubscriber) {
        let reader: Reader
        if let existing = readers[key] {
            reader = existing
        } else {
            reader = Reader(key: key)
            readers[key] = reader
            attach(reader)
        }
        reader.idleSince = nil
        reader.fan.add(subscriber, fallback: fallbackFrame(for: key))
    }

    func unsubscribe(_ key: HubKey, _ subscriber: HubSubscriber) {
        guard let reader = readers[key], reader.fan.remove(subscriber) else { return }
        if reader.isStream {
            reader.idleSince = now()
        } else {
            discard(reader)                         // açık bağlantısı yok: tutmaya gerek yok
        }
        promoteWaiting()
    }

    /// Şifre hatası ya da NVR reddi sonrası (kutuya dokunuş): bağlantı baştan açılır.
    func retry(_ key: HubKey) {
        guard let reader = readers[key] else { return }
        if case .external = reader.source { return }
        if case .stream(let s) = reader.source { s.stop() }
        reader.source = .waiting
        open(reader)
    }

    /// Cihaz düzenlendi ya da silindi: o cihazın okuyucuları yeni ayarla yeniden açılır (sayım beslemesi hariç).
    func reset(sourceId: String) {
        for reader in Array(readers.values) where reader.key.ref.sourceId == sourceId {
            if case .external = reader.source { continue }
            if reader.fan.isEmpty {
                discard(reader)
                continue
            }
            if case .stream(let s) = reader.source { s.stop() }
            reader.source = .waiting
            open(reader)
        }
    }

    /// Saniyede bir: süresi dolan boştaki okuyucular kapanır, bekleyenler açılır, eski son kareler bırakılır.
    func sweep() {
        let t = now()
        for reader in Array(readers.values) {
            if let idle = reader.idleSince, t - idle >= Self.graceSeconds { discard(reader) }
        }
        promoteWaiting()
        lastFrames = lastFrames.filter { t - $0.value.at < Self.lastFrameSeconds }
    }

    /// Uygulama arka plana geçti: boştaki okuyucular beklemeden kapanır (iOS uygulamayı askıya alır).
    func closeIdle() {
        for reader in Array(readers.values) where reader.idleSince != nil { discard(reader) }
    }

    /// Sayılan ağ kamerası (nil: ağ sayımı yok). Bu kameranın kutuları sayımın akışından beslenir.
    func setExternal(_ ref: CameraRef?) {
        guard ref != external else { return }
        let old = external
        external = ref
        feed.reset()
        for reader in Array(readers.values) {
            if reader.key.ref == old {                     // eski sayım kamerası: kendi bağlantısına döner
                if reader.fan.isEmpty {
                    discard(reader)
                } else {
                    reader.source = .waiting
                    open(reader)
                }
            } else if reader.key.ref == ref {              // yeni sayım kamerası: kendi bağlantısı kapanır
                if reader.fan.isEmpty {
                    discard(reader)
                    continue
                }
                if case .stream(let s) = reader.source { s.stop() }
                reader.source = .external
                reader.fan.setStatus(feed.currentStatus)
                feed.add(reader.fan)
            }
        }
    }

    /// Sayımın çözücü iş parçacığından her kare
    nonisolated func externalFrame(_ frame: CVPixelBuffer) { feed.frame(frame) }

    func externalStatus(_ status: TileStatus) { feed.setStatus(status) }

    // MARK: - İç

    private func attach(_ reader: Reader) {
        if reader.key.ref == external {
            reader.source = .external
            reader.fan.setStatus(feed.currentStatus)
            feed.add(reader.fan)
        } else {
            open(reader)
        }
    }

    private func open(_ reader: Reader) {
        if !hasCapacity(reader.key.quality) { evictIdle(reader.key.quality) }
        guard hasCapacity(reader.key.quality) else {
            reader.source = .waiting
            reader.fan.setStatus(.limit)
            return
        }
        switch opener(reader.key) {
        case .rejected(let status):
            reader.source = .rejected(status)
            reader.fan.setStatus(status)
        case .stream(let stream):
            reader.source = .stream(stream)
            reader.fan.setStatus(.connecting)
            let fan = reader.fan
            stream.start(onFrame: { frame in fan.deliver(frame) },
                         onStatus: { status in fan.setStatus(status) })
        }
    }

    private func hasCapacity(_ quality: TileQuality) -> Bool {
        let open = openCount
        return quality == .sub ? open.sub < Self.maxSub : open.main < Self.maxMain
    }

    /// Yer gerekince abonesi olmayan en eski okuyucu hemen kapanır (şablon geçişinde "Sınır aşıldı" görünmesin)
    private func evictIdle(_ quality: TileQuality) {
        let idle = readers.values.filter { $0.key.quality == quality && $0.isStream && $0.idleSince != nil }
        guard let oldest = idle.min(by: { ($0.idleSince ?? 0) < ($1.idleSince ?? 0) }) else { return }
        discard(oldest)
    }

    private func promoteWaiting() {
        for reader in Array(readers.values) {
            guard case .waiting = reader.source, !reader.fan.isEmpty else { continue }
            open(reader)
        }
    }

    private func fallbackFrame(for key: HubKey) -> CVPixelBuffer? {
        let other = HubKey(ref: key.ref, quality: key.quality == .sub ? .main : .sub)
        return readers[other]?.fan.lastFrame ?? lastFrames[key.ref]?.frame.value
    }

    private func discard(_ reader: Reader) {
        switch reader.source {
        case .stream(let s): s.stop()
        case .external: feed.remove(reader.fan)
        case .waiting, .rejected: break
        }
        if let f = reader.fan.lastFrame { lastFrames[reader.key.ref] = (UncheckedSendable(value: f), now()) }
        if readers[reader.key] === reader { readers[reader.key] = nil }
    }
}
```

- [ ] **Step 3: Implement `HubStreams.swift` and `NetworkCameraSource.onProblem`.** Create `apps/ios/BantSayac/Camera/HubStreams.swift`:

```swift
import Foundation
import CoreVideo

/// Gerçek izleme bağlantısı: NetworkCameraSource (RTSP → VideoToolbox). Yeniden bağlanma kaynağın kendisinde
/// (1, 2, 4 … 30 sn; şifre hatasında denenmez).
final class NetworkHubStream: HubStream, @unchecked Sendable {
    private let source: NetworkCameraSource

    init(plan: NetworkStreamPlan) {
        source = plan.makeSource()
    }

    func start(onFrame: @escaping @Sendable (CVPixelBuffer) -> Void,
               onStatus: @escaping @Sendable (TileStatus) -> Void) {
        source.onFrame = { frame, _ in onFrame(frame) }
        source.onState = { state in
            switch state {
            case .connecting: onStatus(.connecting)
            case .playing: onStatus(.playing)
            case .reconnecting, .ended: break        // sorunun türünü onProblem bildirir
            }
        }
        source.onProblem = { problem in onStatus(TileStatus(problem)) }
        source.start()
    }

    func stop() { source.stop() }
}

extension DeviceStore {
    /// CameraHub açıcısı: cihaz ve kanal bulunursa bağlantı, yoksa kutu durumu.
    func hubOpen(_ key: HubKey) -> HubOpen {
        let config: NetworkCameraConfig
        switch lookup(key.ref, substream: key.quality == .sub) {
        case .ok(let c): config = c
        case .deleted: return .rejected(.deleted)
        case .channelMissing: return .rejected(.channelMissing)
        }
        let id = key.ref.sourceId
        guard let plan = NetworkStreamPlan.make(config, password: password(for: id), client: recorderClient(for: id)) else {
            return .rejected(.offline)
        }
        return .stream(NetworkHubStream(plan: plan))
    }
}
```

In `apps/ios/BantSayac/Camera/NetworkCameraSource.swift`:
  - Add after the `onFrame` property:

```swift
    /// Kendi kuyruğunda, `onState`'ten hemen önce: bağlantı sorununun türü (izleme kutusu metni)
    var onProblem: (@Sendable (StreamProblem) -> Void)?
```

  - In `resolved(_:serial:)`, change the failure branch's call to `retry(reason: error.localizedDescription, fatal: fatal, problem: .of(error))`.
  - In `closed(_:client:)`, change the call to:

```swift
        retry(reason: failure?.errorDescription ?? "Bağlantı kapandı",
              fatal: failure == .unauthorized || failure == .badURL, problem: .of(failure))
```

  - Change the signature to `private func retry(reason: String, fatal: Bool, problem: StreamProblem)` and make `onProblem?(problem)` its first line.

- [ ] **Step 4: The counting view model owns and feeds the hub.** In `apps/ios/BantSayac/UI/CountingViewModel.swift`:

(a) After `let devices: DeviceStore`, add:

```swift
    /// İzleme görüntü dağıtıcısı: kamera başına tek bağlantı; sayılan kamera sayımın akışından beslenir
    let hub: CameraHub
```

(b) In `init()`, replace `self.devices = DeviceStore()` with:

```swift
        let devices = DeviceStore()
        self.devices = devices
        self.hub = CameraHub(opener: { key in devices.hubOpen(key) })
```

(c) Change `deviceSaved` and `deleteDevice` to:

```swift
    /// Cihaz kaydedildi: İzleme kutuları yeni ayarla açılır; sayılan kamera bu cihazdaysa sayım da yeniden bağlanır.
    func deviceSaved(_ id: String) {
        hub.reset(sourceId: id)
        if countCamera?.sourceId == id && sourceKind == .network && !isVideoMode { startNetwork() }
    }

    /// Cihaz silinir; İzleme kutuları "Kamera silinmiş" olur; sayım bu cihazdaysa durur ve kamera seçimi kalkar.
    func deleteDevice(_ id: String) {
        devices.delete(id)
        hub.reset(sourceId: id)
        guard countCamera?.sourceId == id else { return }
        setRunning(false)
        selectCountCamera(nil)
    }
```

(d) Replace `stopNetwork()` with:

```swift
    /// `keepHubFeed`: hemen yeni sayım bağlantısı açılacak (İzleme kutuları kendi bağlantısına dönüp geri gelmesin)
    private func stopNetwork(keepHubFeed: Bool = false) {
        networkSource?.stop()
        networkSource = nil
        networkState = nil
        if !keepHubFeed { hub.setExternal(nil) }
    }
```

(e) In `startNetwork()`:
  - Change the first line to `stopNetwork(keepHubFeed: true)`.
  - Insert `hub.setExternal(nil)` before each of the four early `return`s: no camera, deleted, channel missing, no plan.
  - Replace `source.onFrame = { pb, ts in gate.submit(pb, ts: ts, to: processor) }` with:

```swift
        let hub = self.hub
        hub.setExternal(ref)
        source.onFrame = { pb, ts in
            hub.externalFrame(pb)                         // İzleme'de bu kameranın kutusu sayımın karesini gösterir
            gate.submit(pb, ts: ts, to: processor)
        }
```

(f) In `networkStateChanged(_:source:)`, after `networkState = state`, add `hub.externalStatus(TileStatus(counting: state))`.

- [ ] **Step 5: Commit and run CI.** Commit with the message `iPhone izleme: görüntü dağıtıcısı (kamera başına tek bağlantı, sayım beslemesi, sınırlar)`, then run CI. Expected: `exit=0`, all 16 `CameraHubTests` and `StreamProblemTests` passing, zero strict-concurrency warnings.

---

### Task 5: Watch model and tile rendering

**Files:**
- Create: `apps/ios/BantSayac/UI/Watch/TileRendering.swift`, `apps/ios/BantSayac/UI/Watch/WatchModel.swift`
- Test: `apps/ios/BantSayacTests/WatchModelTests.swift`

**Interfaces:**
- Consumes: `CameraHub`, `HubKey`, `HubSubscriber`, `TileStatus`, `TemplateStore`, `DeviceStore`, `ViewLayouts`, `UncheckedSendable`, `FakeStream`, `MemoryCredentials` (tests).
- Produces:
  - `SampleBuffers.make(_:)`
  - `TileSink` (`HubSubscriber`): `attach(_:)`, `detach(_:)`, `takeFrameCount()`, `setStatusHandler(_:)`
  - `TileVideoView(sink:)`
  - `TemplateDraft` (`new()`, `init(_ template:)`)
  - `@MainActor TileModel`: `id`, `ref`, `quality`, `title`, `sink`, `status`, `fps`, `frames`, `key`, `subscribe(_:)`, `unsubscribe(_:)`, `collectStats()`
  - `@MainActor WatchModel(templates:devices:hub:defaults:thermal:)`:
    - state: `currentID`, `tiles`, `single`, `diagnostics`, `thermalWarning`, `current`, `layout`
    - methods: `select(_:)`, `rebuildTiles()`, `setVisible(_:)`, `setForeground(_:)`, `tick()`, `tapped(_:)`, `retry(_:)`, `openSingle(_:)`, `closeSingle()`, `createFromRecorder(_:) async throws -> Int`, `saveTemplate(_:) throws`, `deleteCurrent() throws`

- [ ] **Step 1: Write the failing tests.** Create `apps/ios/BantSayacTests/WatchModelTests.swift`:

```swift
import XCTest
@testable import BantSayac

/// İzleme modeli: görünürlük, şablon geçişi, tek kamera, silinmiş cihaz (sahte bağlantıyla, ağsız).
@MainActor
final class WatchModelTests: XCTestCase {
    private var clock = 0.0
    private var opened: [HubKey: [FakeStream]] = [:]

    private struct Env {
        let model: WatchModel
        let devices: DeviceStore
        let templates: TemplateStore
        let hub: CameraHub
    }

    private func makeEnv(channels count: Int = 6) -> Env {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("bs-watch-\(UUID().uuidString)", isDirectory: true)
        let suite = "bs-watch-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        addTeardownBlock {
            try? FileManager.default.removeItem(at: dir)
            UserDefaults().removePersistentDomain(forName: suite)
        }
        let devices = DeviceStore(directory: dir, credentials: MemoryCredentials())
        var config = NetworkCameraConfig()
        config.kind = .recorder
        config.recorderBrand = .dahua
        config.recorderHost = "nvr.test"
        devices.save(NetworkDevice(id: "nvr", name: "Ofis NVR", config: config), password: "x")
        devices.setChannels((1...count).map {
            RecorderChannel(id: String($0), name: "Kamera \($0)", number: $0, hasSubstream: true)
        }, for: "nvr")
        let hub = CameraHub(opener: { [unowned self] key in
            guard devices.device(key.ref.sourceId) != nil else { return .rejected(.deleted) }
            let stream = FakeStream()
            self.opened[key, default: []].append(stream)
            return .stream(stream)
        }, now: { [unowned self] in self.clock })
        let templates = TemplateStore(directory: dir)
        let model = WatchModel(templates: templates, devices: devices, hub: hub, defaults: defaults,
                               thermal: { .nominal })
        return Env(model: model, devices: devices, templates: templates, hub: hub)
    }

    private func refs(_ ns: [Int]) -> [CameraRef?] { ns.map { CameraRef(sourceId: "nvr", channelId: String($0)) } }

    private func waitUntil(_ condition: () -> Bool) async {
        let deadline = Date().addingTimeInterval(2)
        while !condition() && Date() < deadline { try? await Task.sleep(for: .milliseconds(10)) }
    }

    func testVisibleTemplateOpensOneSubStreamPerCamera() throws {
        let env = makeEnv()
        let t = try env.templates.create(name: "Giriş", layout: "4", tiles: refs([1, 2, 3, 4]))
        env.model.select(t.id)
        XCTAssertTrue(opened.isEmpty, "görünmezken bağlantı açılmamalı")
        env.model.setVisible(true)
        XCTAssertEqual(opened.count, 4)
        XCTAssertTrue(opened.keys.allSatisfy { $0.quality == .sub })
        XCTAssertEqual(env.model.tiles.map(\.title), ["Kamera 1", "Kamera 2", "Kamera 3", "Kamera 4"])
    }

    func testLeavingTabClosesAfterGrace() throws {
        let env = makeEnv()
        let t = try env.templates.create(name: "Giriş", layout: "4", tiles: refs([1, 2, 3, 4]))
        env.model.select(t.id)
        env.model.setVisible(true)
        env.model.setVisible(false)
        clock = 4
        env.model.tick()
        XCTAssertEqual(env.hub.openCount.sub, 4)
        clock = 5
        env.model.tick()
        XCTAssertEqual(env.hub.openCount.sub, 0)
    }

    func testBackgroundClosesImmediately() throws {
        let env = makeEnv()
        let t = try env.templates.create(name: "Giriş", layout: "4", tiles: refs([1, 2, 3, 4]))
        env.model.select(t.id)
        env.model.setVisible(true)
        env.model.setForeground(false)
        XCTAssertEqual(env.hub.openCount.sub, 0)
        env.model.setForeground(true)
        XCTAssertEqual(env.hub.openCount.sub, 4)
    }

    func testSwitchingTemplatesKeepsCommonCameras() throws {
        let env = makeEnv()
        let a = try env.templates.create(name: "A", layout: "4", tiles: refs([1, 2, 3, 4]))
        let b = try env.templates.create(name: "B", layout: "4", tiles: refs([3, 4, 5, 6]))
        env.model.select(a.id)
        env.model.setVisible(true)
        env.model.select(b.id)
        for n in [3, 4] {
            let key = HubKey(ref: CameraRef(sourceId: "nvr", channelId: String(n)), quality: .sub)
            XCTAssertEqual(opened[key]?.count, 1, "ortak kamera \(n) yeniden açılmamalı")
            XCTAssertEqual(opened[key]?.first?.stopped, 0)
        }
        XCTAssertEqual(env.model.currentID, b.id)
        clock = 5
        env.model.tick()
        XCTAssertEqual(env.hub.openCount.sub, 4)
    }

    func testSingleCameraUsesMainStreamAndPausesGrid() throws {
        let env = makeEnv()
        let t = try env.templates.create(name: "Giriş", layout: "4", tiles: refs([1, 2, 3, 4]))
        env.model.select(t.id)
        env.model.setVisible(true)
        env.model.openSingle(env.model.tiles[1])
        let mainKey = HubKey(ref: CameraRef(sourceId: "nvr", channelId: "2"), quality: .main)
        XCTAssertEqual(opened[mainKey]?.count, 1)
        clock = 5
        env.model.tick()
        XCTAssertEqual(env.hub.openCount.sub, 0, "tek kamera açıkken ızgara bağlantıları kapanır")
        XCTAssertEqual(env.hub.openCount.main, 1)
        env.model.closeSingle()
        XCTAssertNil(env.model.single)
        XCTAssertEqual(env.hub.openCount.sub, 4)
    }

    func testTapOnPasswordErrorRetriesInsteadOfOpening() async throws {
        let env = makeEnv()
        let t = try env.templates.create(name: "Giriş", layout: "1", tiles: refs([1]))
        env.model.select(t.id)
        env.model.setVisible(true)
        let key = HubKey(ref: CameraRef(sourceId: "nvr", channelId: "1"), quality: .sub)
        opened[key]?.first?.emit(.authFailed)
        await waitUntil { env.model.tiles[0].status == .authFailed }
        XCTAssertEqual(env.model.tiles[0].status, .authFailed)
        env.model.tapped(env.model.tiles[0])
        XCTAssertNil(env.model.single)
        XCTAssertEqual(opened[key]?.count, 2)
    }

    func testDeletedDeviceTileShowsDeleted() async throws {
        let env = makeEnv()
        let t = try env.templates.create(name: "Giriş", layout: "2", tiles: refs([1, 2]))
        env.devices.delete("nvr")
        env.model.select(t.id)
        env.model.setVisible(true)
        await waitUntil { env.model.tiles[0].status == .deleted }
        XCTAssertEqual(env.model.tiles[0].status, .deleted)
        XCTAssertEqual(env.model.tiles[0].title, "Kamera silinmiş")
        XCTAssertTrue(opened.isEmpty)
    }

    func testCreateFromRecorderUsesCachedChannels() async throws {
        let env = makeEnv(channels: 5)
        let device = try XCTUnwrap(env.devices.device("nvr"))
        let count = try await env.model.createFromRecorder(device)
        XCTAssertEqual(count, 5)
        XCTAssertEqual(env.model.current?.layout, "6")
        XCTAssertEqual(env.model.current?.name, "Ofis NVR")
    }

    func testSaveDraftCreatesThenUpdates() throws {
        let env = makeEnv()
        var draft = TemplateDraft.new()
        draft.name = "Depo"
        draft.tiles = refs([1, 2, 3, 4])
        try env.model.saveTemplate(draft)
        let saved = try XCTUnwrap(env.model.current)
        XCTAssertEqual(saved.name, "Depo")
        var edit = TemplateDraft(saved)
        edit.layout = "1"
        edit.tiles = refs([5])
        try env.model.saveTemplate(edit)
        XCTAssertEqual(env.model.current?.id, saved.id)
        XCTAssertEqual(env.model.tiles.map(\.title), ["Kamera 5"])
        try env.model.deleteCurrent()
        XCTAssertNil(env.model.current)
    }
}
```

- [ ] **Step 2: Tile rendering.** Create `apps/ios/BantSayac/UI/Watch/TileRendering.swift`:

```swift
import AVFoundation
import CoreMedia
import SwiftUI
import UIKit

/// Çözülmüş kareyi hemen gösterilecek örneğe sarar (piksel kopyası yok).
enum SampleBuffers {
    static func make(_ frame: CVPixelBuffer) -> CMSampleBuffer? {
        var format: CMVideoFormatDescription?
        guard CMVideoFormatDescriptionCreateForImageBuffer(allocator: kCFAllocatorDefault, imageBuffer: frame,
                                                           formatDescriptionOut: &format) == noErr,
              let format else { return nil }
        var timing = CMSampleTimingInfo(duration: .invalid,
                                        presentationTimeStamp: CMClockGetTime(CMClockGetHostTimeClock()),
                                        decodeTimeStamp: .invalid)
        var sample: CMSampleBuffer?
        guard CMSampleBufferCreateReadyWithImageBuffer(allocator: kCFAllocatorDefault, imageBuffer: frame,
                                                       formatDescription: format, sampleTiming: &timing,
                                                       sampleBufferOut: &sample) == noErr,
              let sample else { return nil }
        if let attachments = CMSampleBufferGetSampleAttachmentsArray(sample, createIfNecessary: true),
           CFArrayGetCount(attachments) > 0 {
            let dict = unsafeBitCast(CFArrayGetValueAtIndex(attachments, 0), to: CFMutableDictionary.self)
            CFDictionarySetValue(dict, Unmanaged.passUnretained(kCMSampleAttachmentKey_DisplayImmediately).toOpaque(),
                                 Unmanaged.passUnretained(kCFBooleanTrue).toOpaque())
        }
        return sample
    }
}

/// Hub'dan gelen kareyi kutunun görüntü katmanına verir ve kare sayar. Kareler çözücü iş parçacığından gelir;
/// katmana kendi sırasında verilir. Son kare saklanır: katman yeniden kurulunca (döndürme) hemen görünür.
final class TileSink: HubSubscriber, @unchecked Sendable {
    private let lock = NSLock()
    private var layer: AVSampleBufferDisplayLayer?
    private var last: CVPixelBuffer?
    private var frameCount = 0
    private var statusHandler: (@Sendable (TileStatus) -> Void)?
    private let queue = DispatchQueue(label: "bantsayac.tile")

    func setStatusHandler(_ handler: @escaping @Sendable (TileStatus) -> Void) {
        lock.lock(); statusHandler = handler; lock.unlock()
    }

    func attach(_ layer: AVSampleBufferDisplayLayer) {
        lock.lock()
        self.layer = layer
        let frame = last
        lock.unlock()
        if let frame { show(frame, on: layer) }
    }

    func detach(_ layer: AVSampleBufferDisplayLayer) {
        lock.lock()
        if self.layer === layer { self.layer = nil }
        lock.unlock()
    }

    /// Son çağrıdan beri gelen kare sayısı
    func takeFrameCount() -> Int {
        lock.lock(); defer { lock.unlock() }
        let n = frameCount
        frameCount = 0
        return n
    }

    func hubFrame(_ frame: CVPixelBuffer) {
        lock.lock()
        frameCount += 1
        last = frame
        let target = layer
        lock.unlock()
        if let target { show(frame, on: target) }
    }

    func hubStatus(_ status: TileStatus) {
        lock.lock()
        let handler = statusHandler
        lock.unlock()
        handler?(status)
    }

    private func show(_ frame: CVPixelBuffer, on layer: AVSampleBufferDisplayLayer) {
        guard let sample = SampleBuffers.make(frame) else { return }
        let job = UncheckedSendable(value: (layer, sample))
        queue.async {
            let (layer, sample) = job.value
            let renderer = layer.sampleBufferRenderer
            if renderer.status == .failed { renderer.flush() }
            guard renderer.isReadyForMoreMediaData else { return }   // geride kaldıysa kare atlanır
            renderer.enqueue(sample)
        }
    }
}

/// Kutunun görüntüsü: AVSampleBufferDisplayLayer (en-boy oranı korunur, arka plan siyah)
struct TileVideoView: UIViewRepresentable {
    let sink: TileSink

    final class LayerView: UIView {
        override class var layerClass: AnyClass { AVSampleBufferDisplayLayer.self }
        // layerClass yukarıda: katman her zaman bu türdedir
        var displayLayer: AVSampleBufferDisplayLayer { layer as! AVSampleBufferDisplayLayer }
    }

    final class Coordinator {
        var sink: TileSink?
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> LayerView {
        let view = LayerView()
        view.backgroundColor = .black
        view.displayLayer.videoGravity = .resizeAspect
        context.coordinator.sink = sink
        sink.attach(view.displayLayer)
        return view
    }

    func updateUIView(_ view: LayerView, context: Context) {
        guard context.coordinator.sink !== sink else { return }
        context.coordinator.sink?.detach(view.displayLayer)
        context.coordinator.sink = sink
        sink.attach(view.displayLayer)
    }

    static func dismantleUIView(_ view: LayerView, coordinator: Coordinator) {
        coordinator.sink?.detach(view.displayLayer)
    }
}
```

- [ ] **Step 3: Watch model.** Create `apps/ios/BantSayac/UI/Watch/WatchModel.swift`:

```swift
import Foundation

/// Düzenlenen şablon (kaydedilmeden önce)
struct TemplateDraft: Identifiable, Equatable {
    var id: String
    var isNew: Bool
    var name: String
    var layout: String
    var tiles: [CameraRef?]
}

extension TemplateDraft {
    static func new() -> TemplateDraft {
        TemplateDraft(id: UUID().uuidString, isNew: true, name: "", layout: "4", tiles: Array(repeating: nil, count: 4))
    }

    init(_ template: ViewTemplate) {
        self.init(id: template.id, isNew: false, name: template.name, layout: template.layout, tiles: template.tiles)
    }
}

/// Izgaradaki bir kutu (ya da tek kamera): hub aboneliği, durum ve kare sayacı.
@MainActor
final class TileModel: ObservableObject, Identifiable {
    let id: Int
    let ref: CameraRef?
    let quality: TileQuality
    let title: String
    let sink = TileSink()
    @Published private(set) var status: TileStatus = .idle
    /// Son saniyedeki kare sayısı (teşhis)
    @Published private(set) var fps = 0
    /// Toplam gelen kare (arayüz testi; saniyede bir güncellenir)
    @Published private(set) var frames = 0
    private var subscribed = false

    var key: HubKey? { ref.map { HubKey(ref: $0, quality: quality) } }

    init(id: Int, ref: CameraRef?, title: String, quality: TileQuality = .sub) {
        self.id = id
        self.ref = ref
        self.title = title
        self.quality = quality
        sink.setStatusHandler { [weak self] status in
            guard let model = self else { return }
            Task { @MainActor in model.status = status }
        }
    }

    func subscribe(_ hub: CameraHub) {
        guard !subscribed, let key else { return }
        subscribed = true
        hub.subscribe(key, sink)
    }

    func unsubscribe(_ hub: CameraHub) {
        guard subscribed, let key else { return }
        subscribed = false
        hub.unsubscribe(key, sink)
    }

    func collectStats() {
        let n = sink.takeFrameCount()
        if n != fps { fps = n }
        if n > 0 { frames += n }
    }
}

/// İzleme sekmesi: seçili şablon, kutular, tek kamera, görünürlük (sekme + ön plan) ve ısı uyarısı.
/// Kutular yalnızca sekme görünür ve uygulama ön plandayken abonedir; ayrılınca hub 5 sn sonra kapatır.
@MainActor
final class WatchModel: ObservableObject {
    let templates: TemplateStore
    let devices: DeviceStore
    let hub: CameraHub
    @Published private(set) var currentID: String?
    @Published private(set) var tiles: [TileModel] = []
    /// Tam ekran tek kamera (ana akış); açıkken ızgara kutuları bırakılır
    @Published private(set) var single: TileModel?
    @Published var diagnostics = false
    @Published private(set) var thermalWarning = false

    private var visible = false
    private var foreground = true
    private let defaults: UserDefaults
    private let thermal: () -> ProcessInfo.ThermalState
    private var ticker: Task<Void, Never>?
    private static let currentKey = "bs.watch.current"

    init(templates: TemplateStore, devices: DeviceStore, hub: CameraHub, defaults: UserDefaults = .standard,
         thermal: @escaping () -> ProcessInfo.ThermalState = { ProcessInfo.processInfo.thermalState }) {
        self.templates = templates
        self.devices = devices
        self.hub = hub
        self.defaults = defaults
        self.thermal = thermal
        #if DEBUG || UITEST
        if ProcessInfo.processInfo.environment["BS_TEST_FORMS"] != nil { templates.removeAll() }
        #endif
        let saved = defaults.string(forKey: Self.currentKey)
        select(templates.template(saved)?.id ?? templates.templates.first?.id)
        // Saniyede bir: hub temizliği (sekmeden çıkınca da sürer), kare hızı, ısı
        ticker = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                guard let self else { return }
                self.tick()
            }
        }
    }

    var current: ViewTemplate? { templates.template(currentID) }
    var layout: ViewLayout? { current.flatMap { ViewLayouts.layout($0.layout) } }

    func select(_ id: String?) {
        let template = templates.template(id)
        currentID = template?.id
        defaults.set(template?.id, forKey: Self.currentKey)
        rebuildTiles()
    }

    /// Kutular şablonun güncel haliyle kurulur; ortak kameraların bağlantısı sürer (hub aynı okuyucuyu verir).
    func rebuildTiles() {
        let old = tiles
        tiles = (current?.tiles ?? []).enumerated().map { index, ref in
            TileModel(id: index, ref: ref, title: ref.map { devices.title(for: $0) } ?? "")
        }
        for tile in old { tile.unsubscribe(hub) }
        applyActive()
    }

    /// Sekme göründü/gizlendi. Görününce adlar ve kutular yenilenir (cihaz adı değişmiş olabilir).
    func setVisible(_ on: Bool) {
        guard on != visible else { return }
        visible = on
        if on { rebuildTiles() } else { applyActive() }
    }

    /// Uygulama ön planda mı. Arka plana geçince bağlantılar hemen kapanır (iOS uygulamayı askıya alır).
    func setForeground(_ on: Bool) {
        guard on != foreground else { return }
        foreground = on
        applyActive()
        if !on { hub.closeIdle() }
    }

    func tick() {
        hub.sweep()
        for tile in tiles { tile.collectStats() }
        single?.collectStats()
        let warm = thermal().rawValue >= ProcessInfo.ThermalState.serious.rawValue
        if warm != thermalWarning { thermalWarning = warm }
    }

    /// Kutuya dokunuş: şifre hatası ya da NVR reddinde yeniden dener, yoksa tek kamerayı açar.
    func tapped(_ tile: TileModel) {
        switch tile.status {
        case .authFailed, .nvrLimit: retry(tile)
        default: openSingle(tile)
        }
    }

    func retry(_ tile: TileModel) {
        if let key = tile.key { hub.retry(key) }
    }

    /// Tek kamera: ana akış (ilk karesi gelene dek alt akışın son karesi görünür); ızgara kutuları bırakılır.
    func openSingle(_ tile: TileModel) {
        guard let ref = tile.ref, single == nil else { return }
        single = TileModel(id: -1, ref: ref, title: tile.title, quality: .main)
        applyActive()
    }

    func closeSingle() {
        single?.unsubscribe(hub)
        single = nil
        applyActive()
    }

    /// Kayıt cihazının kanallarından şablon (kanal listesi yoksa önce cihazdan alınır). Dönüş: kanal sayısı.
    func createFromRecorder(_ device: NetworkDevice) async throws -> Int {
        var list = devices.channels[device.id] ?? []
        if list.isEmpty {
            guard let client = devices.recorderClient(for: device.id) else { throw RecorderError.noChannels }
            list = try await client.channels()
            devices.setChannels(list, for: device.id)
        }
        let template = try templates.createFromRecorder(name: device.name, deviceId: device.id, channels: list)
        select(template.id)
        return list.count
    }

    func saveTemplate(_ draft: TemplateDraft) throws {
        let saved: ViewTemplate
        if draft.isNew {
            saved = try templates.create(name: draft.name, layout: draft.layout, tiles: draft.tiles)
        } else {
            saved = try templates.update(ViewTemplate(id: draft.id, name: draft.name, layout: draft.layout,
                                                      tiles: draft.tiles, createdAt: 0, updatedAt: 0))
        }
        select(saved.id)
    }

    func deleteCurrent() throws {
        guard let id = currentID else { return }
        try templates.delete(id)
        select(templates.templates.first?.id)
    }

    // MARK: - İç

    private func applyActive() {
        let gridActive = visible && foreground && single == nil
        for tile in tiles {
            if gridActive { tile.subscribe(hub) } else { tile.unsubscribe(hub) }
        }
        if let single {
            if visible && foreground { single.subscribe(hub) } else { single.unsubscribe(hub) }
        }
    }
}
```

- [ ] **Step 4: Commit and run CI.** Commit with the message `iPhone izleme: izleme modeli ve kutu çizimi (AVSampleBufferDisplayLayer)`, then run CI. Expected: `exit=0`, all 9 `WatchModelTests` passing.

---

### Task 6: İzleme tab, template editor, single camera, landscape

**Files:**
- Create: `apps/ios/BantSayac/UI/Watch/WatchView.swift`, `apps/ios/BantSayac/UI/Watch/TemplateEditor.swift`, `apps/ios/BantSayac/UI/Watch/SingleCameraView.swift`, `apps/ios/BantSayac/App/OrientationLock.swift`
- Modify: `apps/ios/BantSayac/App/BantSayacApp.swift`, `apps/ios/BantSayac/UI/RootView.swift`, `apps/ios/project.yml` (`UISupportedInterfaceOrientations`)

**Interfaces:**
- Consumes: everything from Task 5; `CameraPickerView` (Task 3); `CountingViewModel.countCamera/selectCountCamera/setSource/isRunning/sourceKind/isVideoMode/profile/total/totalOut/hub/devices`.
- Produces:
  - `WatchView(vm:onCountCamera:onOpenSettings:)`, `TemplateEditor(model:draft:)`, `SingleCameraView`, `OrientationLock.allowLandscape(_:)`, `AppDelegate`
  - accessibility ids:
    - Watch screen: `watchHeader`, `templatePicker`, `addTemplate`, `editTemplate`, `emptyNewTemplate`, `emptyFromRecorder`, `tile.<i>`, `countBadge`
    - Template editor: `templateName`, `layout.<id>`, `slot.<i>`, `saveTemplate`, `deleteTemplate`
    - Single camera: `singleCamera`, `singleVideo`, `closeSingle`, `countThisCamera`

- [ ] **Step 1: Landscape support.** In `apps/ios/project.yml`, change `UISupportedInterfaceOrientations: [UIInterfaceOrientationPortrait]` to:

```yaml
        # Yatay yalnızca İzleme sekmesinde serbest (App/OrientationLock.swift); diğer ekranlar dikey kalır
        UISupportedInterfaceOrientations: [UIInterfaceOrientationPortrait, UIInterfaceOrientationLandscapeLeft, UIInterfaceOrientationLandscapeRight]
```

Create `apps/ios/BantSayac/App/OrientationLock.swift`:

```swift
import UIKit

/// Uygulama dikey çalışır; İzleme sekmesi görünürken yatay da serbest (ızgara tam ekran).
@MainActor
enum OrientationLock {
    private(set) static var mask: UIInterfaceOrientationMask = .portrait

    static func allowLandscape(_ allow: Bool) {
        let newMask: UIInterfaceOrientationMask = allow ? .allButUpsideDown : .portrait
        guard newMask != mask else { return }
        mask = newMask
        guard let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first else { return }
        for window in scene.windows { window.rootViewController?.setNeedsUpdateOfSupportedInterfaceOrientations() }
        if !allow { scene.requestGeometryUpdate(.iOS(interfaceOrientations: .portrait)) { _ in } }
    }
}

final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(_ application: UIApplication,
                     supportedInterfaceOrientationsFor window: UIWindow?) -> UIInterfaceOrientationMask {
        OrientationLock.mask
    }
}
```

Replace the body of `apps/ios/BantSayac/App/BantSayacApp.swift` with:

```swift
import SwiftUI

@main
struct BantSayacApp: App {
    /// Yön kilidi (İzleme sekmesinde yatay serbest)
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup {
            RootView()
        }
    }
}
```

- [ ] **Step 2: Single camera overlay.** Create `apps/ios/BantSayac/UI/Watch/SingleCameraView.swift`:

```swift
import SwiftUI

/// Tam ekran tek kamera (ana akış). İzleme sekmesinin içinde katman: sekme görünür kalır.
struct SingleCameraView: View {
    @ObservedObject var tile: TileModel
    let onClose: () -> Void
    let onCount: () -> Void

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            TileVideoView(sink: tile.sink)
                .ignoresSafeArea()
                .accessibilityElement()
                .accessibilityLabel(tile.title)
                .accessibilityValue("\(tile.status.text ?? "canlı") · kare \(tile.frames)")
                .accessibilityIdentifier("singleVideo")
            if let text = tile.status.text {
                Text(text)
                    .font(.callout.bold())
                    .padding(10)
                    .background(.black.opacity(0.6))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            }
            VStack {
                HStack {
                    Text(tile.title)
                        .font(.headline)
                        .padding(.horizontal, 10).padding(.vertical, 6)
                        .background(.black.opacity(0.5))
                        .clipShape(Capsule())
                    Spacer()
                    Button(action: onClose) {
                        Image(systemName: "xmark.circle.fill").font(.title).symbolRenderingMode(.hierarchical)
                    }
                    .accessibilityLabel("Kapat")
                    .accessibilityIdentifier("closeSingle")
                }
                Spacer()
                Button(action: onCount) {
                    Label("Bu kamerayı say", systemImage: "number")
                }
                .buttonStyle(.borderedProminent)
                .accessibilityIdentifier("countThisCamera")
            }
            .padding()
        }
        .accessibilityIdentifier("singleCamera")
    }
}
```

- [ ] **Step 3: Template editor.** Create `apps/ios/BantSayac/UI/Watch/TemplateEditor.swift`:

```swift
import SwiftUI

/// Şablon düzenleyici: ad, düzen (9 seçenek), kutulara kamera (dokun: seç; basılı tut: değiştir/boşalt), sil.
struct TemplateEditor: View {
    @ObservedObject var model: WatchModel
    @State var draft: TemplateDraft
    @Environment(\.dismiss) private var dismiss
    @State private var picking: Int?
    @State private var error: String?
    @State private var dropped = 0
    @State private var confirmDelete = false

    private struct Slot: Identifiable {
        let index: Int
        var id: Int { index }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Ad") {
                    TextField("Şablon adı (ör. Giriş katı)", text: $draft.name)
                        .accessibilityIdentifier("templateName")
                }
                Section("Düzen") {
                    layoutPicker
                }
                Section {
                    tilesPreview
                } header: {
                    Text("Kutular")
                } footer: {
                    Text(footerText)
                }
                if let error {
                    Section {
                        Text(error).foregroundStyle(.red)
                    }
                }
                if !draft.isNew {
                    Section {
                        Button("Şablonu sil", role: .destructive) { confirmDelete = true }
                            .accessibilityIdentifier("deleteTemplate")
                    }
                }
            }
            .navigationTitle(draft.isNew ? "Yeni şablon" : "Şablonu düzenle")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Vazgeç") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Kaydet") { save() }
                        .accessibilityIdentifier("saveTemplate")
                }
            }
            .sheet(item: pickingSlot) { slot in
                NavigationStack {
                    CameraPickerView(devices: model.devices, selected: draft.tiles[slot.index],
                                     unavailable: unavailable(except: slot.index), allowsEmpty: true) { ref in
                        draft.tiles[slot.index] = ref
                        picking = nil
                    }
                    .navigationTitle("Kutu \(slot.index + 1)")
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar {
                        ToolbarItem(placement: .cancellationAction) {
                            Button("Kapat") { picking = nil }
                        }
                    }
                }
            }
            .alert("Şablon silinsin mi?", isPresented: $confirmDelete) {
                Button("Sil", role: .destructive) { delete() }
                Button("Vazgeç", role: .cancel) {}
            } message: {
                Text("\(draft.name) şablonu bu iPhone'dan silinir; kameralar ve cihazlar silinmez.")
            }
        }
    }

    private var footerText: String {
        let hint = "Kutuya dokun: kamera seç. Basılı tut: değiştir ya da boşalt."
        return dropped > 0 ? "\(hint)\n\(dropped) kamera yeni düzene sığmadı." : hint
    }

    private var pickingSlot: Binding<Slot?> {
        Binding(get: { picking.map(Slot.init(index:)) }, set: { picking = $0?.index })
    }

    private var layoutPicker: some View {
        LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 5), spacing: 10) {
            ForEach(ViewLayouts.catalog) { layout in
                Button {
                    setLayout(layout)
                } label: {
                    VStack(spacing: 4) {
                        LayoutIcon(layout: layout).frame(width: 44, height: 28)
                        Text(layout.id).font(.caption2)
                    }
                    .padding(4)
                    .background(RoundedRectangle(cornerRadius: 6)
                        .stroke(draft.layout == layout.id ? Color.accentColor : .clear, lineWidth: 2))
                }
                .buttonStyle(.plain)
                .accessibilityLabel(layout.name)
                .accessibilityAddTraits(draft.layout == layout.id ? .isSelected : [])
                .accessibilityIdentifier("layout.\(layout.id)")
            }
        }
    }

    private var tilesPreview: some View {
        let layout = ViewLayouts.layout(draft.layout)
        return GeometryReader { geo in
            if let layout {
                let rects = layout.rects(in: geo.size, gap: 4)
                ZStack(alignment: .topLeading) {
                    ForEach(Array(rects.enumerated()), id: \.offset) { index, rect in
                        slotView(index)
                            .frame(width: rect.width, height: rect.height)
                            .position(x: rect.midX, y: rect.midY)
                    }
                }
            }
        }
        .aspectRatio(layout?.aspectRatio ?? 16.0 / 9.0, contentMode: .fit)
    }

    private func slotView(_ index: Int) -> some View {
        let ref = index < draft.tiles.count ? draft.tiles[index] : nil
        return Button {
            picking = index
        } label: {
            ZStack {
                RoundedRectangle(cornerRadius: 4).fill(Color.secondary.opacity(ref == nil ? 0.15 : 0.35))
                if let ref {
                    Text(model.devices.title(for: ref))
                        .font(.caption2)
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                        .padding(2)
                } else {
                    Image(systemName: "plus").foregroundStyle(.secondary)
                }
            }
        }
        .buttonStyle(.plain)
        .contextMenu {
            if ref != nil {
                Button("Değiştir") { picking = index }
                Button("Boşalt", role: .destructive) { draft.tiles[index] = nil }
            }
        }
        .accessibilityIdentifier("slot.\(index)")
    }

    private func setLayout(_ layout: ViewLayout) {
        guard layout.id != draft.layout else { return }
        let result = TemplateStore.retile(draft.tiles, to: layout)
        draft.layout = layout.id
        draft.tiles = result.tiles
        dropped = result.dropped
    }

    private func unavailable(except index: Int) -> Set<CameraRef> {
        Set(draft.tiles.enumerated().compactMap { i, ref in i == index ? nil : ref })
    }

    private func save() {
        do {
            try model.saveTemplate(draft)
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func delete() {
        do {
            try model.deleteCurrent()
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// Düzenin küçük simgesi (düzen seçicide)
struct LayoutIcon: View {
    let layout: ViewLayout

    var body: some View {
        GeometryReader { geo in
            ForEach(Array(layout.rects(in: geo.size, gap: 2).enumerated()), id: \.offset) { _, rect in
                Rectangle()
                    .fill(Color.secondary.opacity(0.5))
                    .frame(width: rect.width, height: rect.height)
                    .position(x: rect.midX, y: rect.midY)
            }
        }
    }
}
```

- [ ] **Step 4: Watch tab.** Create `apps/ios/BantSayac/UI/Watch/WatchView.swift`:

```swift
import AVFoundation
import SwiftUI

/// İzleme sekmesi: şablonlu ızgarada canlı kameralar (docs/superpowers/specs/2026-10-11-iphone-izleme-design.md §2).
/// Yan çevirince ızgara tam ekran; kutuya dokununca tek kamera (ana akış).
struct WatchView: View {
    let vm: CountingViewModel
    let onCountCamera: () -> Void
    let onOpenSettings: () -> Void
    @StateObject private var model: WatchModel
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.verticalSizeClass) private var verticalSizeClass
    @State private var editing: TemplateDraft?
    @State private var notice: String?
    @State private var pickingRecorder = false
    @State private var confirmCount: TileModel?

    init(vm: CountingViewModel, onCountCamera: @escaping () -> Void, onOpenSettings: @escaping () -> Void) {
        self.vm = vm
        self.onCountCamera = onCountCamera
        self.onOpenSettings = onOpenSettings
        _model = StateObject(wrappedValue: WatchModel(templates: TemplateStore(), devices: vm.devices, hub: vm.hub))
    }

    private var isLandscape: Bool { verticalSizeClass == .compact }
    private var barsHidden: Bool { isLandscape || model.single != nil }

    var body: some View {
        NavigationStack {
            ZStack {
                Color.black.ignoresSafeArea()
                content
                if let single = model.single {
                    SingleCameraView(tile: single, onClose: { model.closeSingle() },
                                     onCount: { countRequested(single) })
                        .zIndex(1)
                }
            }
            .navigationTitle("İzleme")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { toolbarItems }
            .toolbar(barsHidden ? .hidden : .visible, for: .navigationBar)
            .toolbar(barsHidden ? .hidden : .visible, for: .tabBar)
            .statusBarHidden(isLandscape)
        }
        .sheet(item: $editing) { draft in
            TemplateEditor(model: model, draft: draft)
        }
        .confirmationDialog("Hangi kayıt cihazı?", isPresented: $pickingRecorder, titleVisibility: .visible) {
            ForEach(recorders) { device in
                Button(device.name) { createFromRecorder(device) }
            }
            Button("Vazgeç", role: .cancel) {}
        }
        .alert("Sayım bu kameraya geçsin mi?", isPresented: confirmShown, presenting: confirmCount) { tile in
            Button("Geç") { if let ref = tile.ref { switchCounting(to: ref) } }
            Button("Vazgeç", role: .cancel) {}
        } message: { tile in
            Text("Süren sayım \(tile.title) kamerasıyla devam eder.")
        }
        .onAppear {
            OrientationLock.allowLandscape(true)
            model.setVisible(true)
        }
        .onDisappear {
            OrientationLock.allowLandscape(false)
            model.setVisible(false)
        }
        .onChange(of: scenePhase) { _, phase in
            model.setForeground(phase != .background)
        }
    }

    // MARK: - İçerik

    @ViewBuilder private var content: some View {
        if model.devices.devices.isEmpty {
            emptyDevices
        } else if model.current == nil {
            emptyTemplates
        } else {
            VStack(spacing: 6) {
                if !isLandscape { header }
                if model.thermalWarning { banner("Telefon ısındı, daha küçük bir şablon önerilir.", icon: "thermometer.high", color: .orange) }
                if let problem = model.templates.problem { banner(problem, icon: "exclamationmark.triangle", color: .red) }
                if let notice { banner(notice, icon: "info.circle", color: .blue) }
                grid
            }
        }
    }

    private var header: some View {
        HStack {
            Text(model.current?.name ?? "")
                .font(.headline)
                .foregroundStyle(.white)
                .lineLimit(1)
            Spacer()
            if model.diagnostics {
                Text(diagnosticsText)
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal)
        .contentShape(Rectangle())
        .onLongPressGesture { model.diagnostics.toggle() }
        .accessibilityIdentifier("watchHeader")
    }

    private var diagnosticsText: String {
        let open = model.hub.openCount
        let heat: String
        switch ProcessInfo.processInfo.thermalState {
        case .nominal: heat = "normal"
        case .fair: heat = "ılık"
        case .serious: heat = "ciddi"
        case .critical: heat = "kritik"
        @unknown default: heat = "?"
        }
        return "bağlantı \(open.sub)+\(open.main) · ısı \(heat)"
    }

    private func banner(_ text: String, icon: String, color: Color) -> some View {
        HStack {
            Label(text, systemImage: icon).font(.caption)
            Spacer()
            if text == notice {
                Button { notice = nil } label: { Image(systemName: "xmark") }
                    .accessibilityLabel("Kapat")
            }
        }
        .padding(8)
        .foregroundStyle(.white)
        .background(color.opacity(0.75))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .padding(.horizontal)
    }

    private var grid: some View {
        GeometryReader { geo in
            if let layout = model.layout {
                let canvas = AVMakeRect(aspectRatio: CGSize(width: layout.aspectRatio, height: 1),
                                        insideRect: CGRect(origin: .zero, size: geo.size))
                let rects = layout.rects(in: canvas.size)
                ZStack(alignment: .topLeading) {
                    ForEach(model.tiles) { tile in
                        if tile.id < rects.count {
                            let rect = rects[tile.id]
                            TileView(tile: tile, vm: vm, diagnostics: model.diagnostics)
                                .frame(width: rect.width, height: rect.height)
                                .position(x: canvas.minX + rect.midX, y: canvas.minY + rect.midY)
                                .onTapGesture { model.tapped(tile) }
                        }
                    }
                }
            }
        }
        .ignoresSafeArea(edges: isLandscape ? .all : [])
    }

    private var emptyDevices: some View {
        ContentUnavailableView {
            Label("Cihaz yok", systemImage: "video.slash")
        } description: {
            Text("Önce Ayarlar → Görüntü kaynağı → Cihazlar'dan kamera ya da NVR ekle.")
        } actions: {
            Button("Ayarlar'a git") { onOpenSettings() }
                .buttonStyle(.borderedProminent)
        }
    }

    private var emptyTemplates: some View {
        ContentUnavailableView {
            Label("Şablon yok", systemImage: "square.grid.2x2")
        } description: {
            Text("Kameraları birlikte izlemek için bir şablon oluştur.")
        } actions: {
            Button("Yeni şablon") { editing = TemplateDraft.new() }
                .buttonStyle(.borderedProminent)
                .accessibilityIdentifier("emptyNewTemplate")
            Button("NVR'dan şablon") { startFromRecorder() }
                .accessibilityIdentifier("emptyFromRecorder")
        }
    }

    // MARK: - Araç çubuğu

    @ToolbarContentBuilder private var toolbarItems: some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) {
            Menu {
                ForEach(model.templates.templates) { template in
                    Button {
                        model.select(template.id)
                    } label: {
                        if template.id == model.currentID {
                            Label(template.name, systemImage: "checkmark")
                        } else {
                            Text(template.name)
                        }
                    }
                }
            } label: {
                Label("Şablonlar", systemImage: "rectangle.grid.2x2")
            }
            .disabled(model.templates.templates.isEmpty)
            .accessibilityIdentifier("templatePicker")
        }
        ToolbarItemGroup(placement: .topBarTrailing) {
            if let current = model.current {
                Button("Düzenle") { editing = TemplateDraft(current) }
                    .accessibilityIdentifier("editTemplate")
            }
            Menu {
                Button("Yeni şablon") { editing = TemplateDraft.new() }
                Button("NVR'dan şablon") { startFromRecorder() }
            } label: {
                Image(systemName: "plus")
            }
            .accessibilityLabel("Şablon ekle")
            .accessibilityIdentifier("addTemplate")
        }
    }

    // MARK: - İşler

    private var recorders: [NetworkDevice] { model.devices.devices.filter { $0.kind == .recorder } }

    private func startFromRecorder() {
        switch recorders.count {
        case 0: notice = "Önce bir kayıt cihazı ekle (Ayarlar → Görüntü kaynağı → Cihazlar)."
        case 1: createFromRecorder(recorders[0])
        default: pickingRecorder = true
        }
    }

    private func createFromRecorder(_ device: NetworkDevice) {
        Task {
            do {
                let total = try await model.createFromRecorder(device)
                notice = total > ViewLayouts.maxTiles ? "\(total) kanaldan 16'sı eklendi." : nil
            } catch {
                notice = error.localizedDescription
            }
        }
    }

    private var confirmShown: Binding<Bool> {
        Binding(get: { confirmCount != nil }, set: { if !$0 { confirmCount = nil } })
    }

    private func countRequested(_ tile: TileModel) {
        guard let ref = tile.ref else { return }
        if vm.isRunning, vm.countCamera != ref {
            confirmCount = tile
        } else {
            switchCounting(to: ref)
        }
    }

    private func switchCounting(to ref: CameraRef) {
        vm.selectCountCamera(ref)
        vm.setSource(.network)
        model.closeSingle()
        onCountCamera()
    }
}

/// Izgaradaki kutu: görüntü, ad, durum metni, sayaç rozeti, (teşhiste) kare hızı
private struct TileView: View {
    @ObservedObject var tile: TileModel
    let vm: CountingViewModel
    let diagnostics: Bool

    var body: some View {
        ZStack {
            Color(white: 0.12)
            if tile.ref != nil {
                TileVideoView(sink: tile.sink)
            }
            if tile.ref == nil {
                Image(systemName: "plus").foregroundStyle(.secondary)
            } else if let text = tile.status.text {
                Text(text)
                    .font(.caption.bold())
                    .foregroundStyle(.white)
                    .padding(6)
                    .background(.black.opacity(0.6))
                    .clipShape(RoundedRectangle(cornerRadius: 6))
            }
            VStack {
                HStack {
                    Spacer()
                    CountBadge(vm: vm, ref: tile.ref)
                }
                Spacer()
                HStack {
                    Text(tile.title)
                        .font(.caption2)
                        .foregroundStyle(.white)
                        .lineLimit(1)
                        .padding(.horizontal, 4).padding(.vertical, 2)
                        .background(.black.opacity(0.5))
                    Spacer()
                    if diagnostics && tile.ref != nil {
                        Text("\(tile.fps) kare/sn")
                            .font(.caption2.monospacedDigit())
                            .foregroundStyle(.white)
                            .padding(.horizontal, 4).padding(.vertical, 2)
                            .background(.black.opacity(0.5))
                    }
                }
            }
            .padding(4)
        }
        .clipped()
        .contentShape(Rectangle())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(tile.ref == nil ? "Boş kutu" : tile.title)
        .accessibilityValue("\(tile.status.text ?? "canlı") · kare \(tile.frames)")
        .accessibilityAddTraits(.isButton)
        .accessibilityIdentifier("tile.\(tile.id)")
    }
}

/// Sayılan kameranın kutusunda sayaç (ağ sayımı bu kameradayken)
private struct CountBadge: View {
    @ObservedObject var vm: CountingViewModel
    let ref: CameraRef?

    var body: some View {
        if let ref, ref == vm.countCamera, vm.sourceKind == .network, !vm.isVideoMode {
            Text(vm.profile.mode == .detect ? "Giriş \(vm.total) · Çıkış \(vm.totalOut)" : "Toplam \(vm.total)")
                .font(.caption2.bold())
                .foregroundStyle(.white)
                .padding(.horizontal, 6).padding(.vertical, 3)
                .background(Color.blue.opacity(0.85))
                .clipShape(Capsule())
                .accessibilityIdentifier("countBadge")
        }
    }
}
```

- [ ] **Step 5: Fifth tab.** In `apps/ios/BantSayac/UI/RootView.swift`:
  - Change the doc comment's first line to `/// Sekmeler: Canlı · İzleme · Genel bakış · Öğret · Ayarlar. Kamera ve sayım sekme değişse de sürer.`
  - After `@State private var showSplash …`, add:

```swift
    private enum Tab: Hashable { case live, watch, overview, teach, settings }
    /// İzleme'den "Bu kamerayı say" Canlı'ya, "Ayarlar'a git" Ayarlar'a geçirir
    @State private var tab: Tab = .live
```

  - Replace the `TabView { … }` contents with:

```swift
        TabView(selection: $tab) {
            ContentView(vm: vm)
                .tabItem { Label("Canlı", systemImage: "viewfinder") }
                .tag(Tab.live)
            WatchView(vm: vm, onCountCamera: { tab = .live }, onOpenSettings: { tab = .settings })
                .tabItem { Label("İzleme", systemImage: "square.grid.2x2") }
                .tag(Tab.watch)
            OverviewView(vm: vm, teach: vm.teach)
                .tabItem { Label("Genel bakış", systemImage: "chart.bar.fill") }
                .tag(Tab.overview)
            TeachView(vm: vm, teach: vm.teach)
                .tabItem { Label("Öğret", systemImage: "plus.viewfinder") }
                .tag(Tab.teach)
            SettingsView(vm: vm, settings: vm.settings, logger: vm.logger, showsDone: false)
                .onDisappear { vm.applySettings() }
                .tabItem { Label("Ayarlar", systemImage: "slider.horizontal.3") }
                .tag(Tab.settings)
        }
```

- [ ] **Step 6: Commit and run CI.** Commit with the message `iPhone: İzleme sekmesi (şablonlu ızgara, düzenleyici, tek kamera, yatay tam ekran)`, then run CI. Expected: `exit=0`, zero strict-concurrency warnings, all unit tests green.

---

### Task 7: Grid UI test and documentation

**Files:**
- Modify: `apps/ios/BantSayacUITests/BantSayacUITests.swift`
- Modify: `docs/02-contracts.md` §8, `docs/04-ios-app.md`, `docs/10-field-setup.md` §3c, `docs/12-durum.md`, `apps/ios/README.md`, `docs/superpowers/specs/2026-10-11-iphone-izleme-design.md` (status line)

**Interfaces:**
- Consumes: the accessibility ids from Tasks 3 and 6.
- Produces: `testWatchGridFromRecorderAndCountCamera`, `waitForFrames(_:timeout:)`.

- [ ] **Step 1: Grid UI test.** In `apps/ios/BantSayacUITests/BantSayacUITests.swift`, add after `testRecorderDahuaPicksCameraAndPlays`:

```swift
    // MARK: - İzleme (çoklu kamera ızgarası)

    /// Kutunun erişilebilirlik değeri "… · kare N": N > 0 olunca kare akıyor
    private func waitForFrames(_ el: XCUIElement, timeout: TimeInterval) -> Bool {
        let predicate = NSPredicate(format: "value MATCHES %@", ".*kare [1-9][0-9]*$")
        return XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: predicate, object: el)],
                                timeout: timeout) == .completed
    }

    /// Dahua kayıt cihazı → NVR'dan 4'lü şablon → kutularda kare akar (sayılan kamera sayımın akışını paylaşır)
    /// → tek kamera (ana akış) → "Bu kamerayı say" Canlı sekmesinde bu kamerayı sayar.
    func testWatchGridFromRecorderAndCountCamera() throws {
        let nvr = try mockRecorder()
        let app = openRecorderForm(brand: "Dahua")
        fill(element(app, "recorderHost"), nvr.host)
        app.buttons["Portlar"].tap()
        fill(element(app, "recorderHTTPPort"), nvr.httpPort)
        fill(element(app, "recorderRTSPPort"), nvr.rtspPort)
        fill(element(app, "recorderPassword"), nvr.password)
        pickTestAndSave(app, camera: "Bant 1", expectedOthers: ["Kapı", "Depo", "Kanal 4"], absent: [])

        app.tabBars.buttons["İzleme"].tap()
        let fromRecorder = element(app, "emptyFromRecorder")
        XCTAssertTrue(fromRecorder.waitForExistence(timeout: 10), "boş şablon ekranı yok")
        fromRecorder.tap()
        for i in 0..<4 {
            let tile = element(app, "tile.\(i)")
            XCTAssertTrue(tile.waitForExistence(timeout: 10), "kutu \(i) yok")
            XCTAssertTrue(waitForFrames(tile, timeout: 60), "kutu \(i) kare almadı: \(String(describing: tile.value))")
        }
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "izleme-4lu"
        shot.lifetime = .keepAlways
        add(shot)

        element(app, "tile.1").tap()
        let single = element(app, "singleVideo")
        XCTAssertTrue(single.waitForExistence(timeout: 10), "tek kamera açılmadı")
        XCTAssertTrue(waitForFrames(single, timeout: 60), "tek kamera kare almadı: \(String(describing: single.value))")
        element(app, "countThisCamera").tap()
        let state = element(app, "networkState")
        XCTAssertTrue(waitForLabel(state, containing: "Canlı", timeout: 60), "sayım yeni kamerada başlamadı: \(state.label)")
    }
```

- [ ] **Step 2: Docs.**

(a) `docs/02-contracts.md` §8:
  - In the first paragraph, replace `(web ve ileride iPhone)` with `(web ve iPhone)`.
  - Replace the bullet starting `- Kamera kimlikleri **platforma özgüdür**` with:

```markdown
- Kamera kimlikleri **platforma özgüdür**: web'de analiz sunucusunun kaynak kimliği, iPhone'da cihaz kimliği (UUID) ve kayıt cihazının kanal kimliği (TRASSIR GUID'i ya da kanal numarası; doğrudan kamerada `null`). Biçim ortaktır; şablonlar platformlar arasında eşitlenmez.
```

  - After the paragraph starting `**Python kataloğu**`, add:

```markdown
**iPhone** `view-layouts.json`'ı kopya olmadan uygulama paketine kaynak olarak ekler (`apps/ios/project.yml`); `BantSayacTests/ViewLayoutsTests` düzen kimliklerini, kutu sayılarını ve `smallestFor`'un web'deki `smallest_for` ile aynı sonucu verdiğini sınar; `TemplateStoreTests` `examples/view-template-4.json`'ı okur ve kanalsız kutuda `channelId: null` yazıldığını denetler.
```

(b) `docs/04-ios-app.md`:
  - In §1e, replace the first line `Karar (2026-10-02): önce **telefon + 1 IP kamera**; çoklu kamera gerekirse web/edge tarafına (F2) taşınır.` with `Karar (2026-10-02): önce **telefon + 1 IP kamera**. 2026-10-11'den beri cihaz listesi (§1j): birden çok kamera ve kayıt cihazı; sayım listeden bir kamera seçer.`
  - In §1g, replace the bullet starting `- **Ayar kaydı:**` with:

```markdown
- **Ayar kaydı:** cihazlar `Application Support/BantSayac/devices.json`'da (§1j); `NetworkCameraConfig` eski sürümlerin kaydını okur (eksik alan = varsayılan; derleme 12 kaydı birim testli). Şifreler Keychain'de cihaz başına `device.<id>` hesabında; eski tek ayar (`bs.netcam`, hesaplar `camera`/`recorder`) ilk açılışta bir kez listeye taşınır ve bir sürüm boyunca silinmez.
```

  - Insert a new section before `## 1h. Çokgen ilgi alanı (ROI)`:

```markdown
## 1j. Cihazlar ve İzleme (çoklu kamera ızgarası)
Tasarım: `docs/superpowers/specs/2026-10-11-iphone-izleme-design.md`. Görüntü telefona doğrudan NVR'dan/kameradan gelir; ofisteki bilgisayar gerekmez.
- **Cihazlar** (Ayarlar → Görüntü kaynağı → Cihazlar): birden çok IP kamera ve kayıt cihazı (TRASSIR/Hikvision/Dahua). Ad 1–40 karakter (boşsa "Kamera 1" / "NVR 1"; çakışmada " (2)"). Kayıt cihazının kanal listesi önbellekte (çevrimdışı da ad ve seçim). Silmek onaylıdır; şifre de silinir.
- **Sayılan kamera** (Ayarlar → Görüntü kaynağı → Sayılan kamera, `bs.countCamera`): listeden bir kamera. Sayım için kamera seçilmemişken kaydedilen cihazın seçili kamerası sayıma alınır (sihirbazda her zaman).
- **İzleme sekmesi:** şablon seçici, yeni şablon, "NVR'dan şablon" (kanal sayısına uyan en küçük düzen, en çok 16 kanal), düzenleyici (9 düzen, kutuya dokun: kamera; basılı tut: değiştir/boşalt). Şablonlar telefonda (`views.json`, sözleşme biçimi `02-contracts.md` §8), web ile eşitlenmez. Yan çevirince ızgara tam ekran (yalnızca bu sekmede; diğer sekmeler dikey). Kutuya dokun: tek kamera (ana akış; ilk karesine dek alt akışın son karesi) ve "Bu kamerayı say". Şablon adına uzun bas: teşhis (bağlantı sayısı, ısı; kutularda kare/sn).
- **Görüntü dağıtıcısı** (`Camera/CameraHub.swift`): kamera ve nitelik başına tek RTSP okuyucusu; kutular aynı kareyi paylaşır. Sayılan kamera sayımın akışından beslenir (NVR'a ikinci bağlantı yok). En çok 16 alt + 1 ana akış; abonesi kalmayan okuyucu 5 sn sonra kapanır, yer gerekince hemen çıkarılır (şablon geçişinde "Sınır aşıldı" yok); uygulama arka plana geçince hemen kapanır. Kayıt cihazı istemcisi cihaz başına tek (TRASSIR'da tek oturum, kanal başına jeton). Kareler `AVSampleBufferDisplayLayer`'a kopyasız verilir.
- **Kutu durumları:** Bağlanıyor… · Bağlantı yok · Şifre hatalı (yeniden denenmez; kutuya dokun) · NVR bağlantı sınırına ulaştı (RTSP 453/503) · Sınır aşıldı · Kamera silinmiş · Kanal bulunamadı · Görüntü biçimi desteklenmiyor. Telefon "ciddi" ısınınca uyarı (akış kesilmez).
- **Test:** birim (`ViewLayoutsTests`, `TemplateStoreTests`, `DeviceStoreTests`, `CameraHubTests`, `WatchModelTests`; ağsız) ve uçtan uca UI (`testWatchGridFromRecorderAndCountCamera`: sahte Dahua NVR, MediaMTX).
```

(c) `docs/10-field-setup.md` §3c: after the first paragraph (`Sahada kameraların çoğu kayıt cihazına bağlıdır; …`), add:

```markdown
iPhone'da cihazlar bir kez eklenir (Ayarlar → Görüntü kaynağı → Cihazlar): birden çok kayıt cihazı ve doğrudan kamera olabilir. Sayılacak kamera ve İzleme sekmesindeki şablonların kameraları bu listeden seçilir; "NVR'dan şablon" kayıt cihazının kanallarıyla tek dokunuşta ızgara kurar. İzleme ızgarası kutu başına alt akışla bağlanır: kayıt cihazının eşzamanlı uzak izleme sınırı 16 kutuyu kaldırmayabilir (kutuda "NVR bağlantı sınırına ulaştı").
```

(d) `docs/12-durum.md`:
  - In §5g, replace the bullet starting `- **iPhone ekranı ayrı alt proje (B):**` with `- **iPhone ekranı:** §5h.`
  - Insert before `## 6. Araştırma ve tasarım notları`:

```markdown
## 5h. iPhone çoklu kamera izleme: cihaz listesi + şablonlu ızgara (2026-10-11)

Tasarım: `docs/superpowers/specs/2026-10-11-iphone-izleme-design.md`; ayrıntı `04-ios-app.md` §1j.
- **Ne var:** Cihazlar listesi (birden çok NVR ve IP kamera; eski tek kamera ayarı bir kez taşınır); sayım kamerasını listeden seçer; İzleme sekmesi (9 düzen, şablon düzenleyici, "NVR'dan şablon", kutu durumları, sayaç rozeti, tek kamera ana akışla, "Bu kamerayı say", yan çevirince tam ekran, ısı uyarısı); kamera başına tek bağlantı ve sayımla paylaşım; 16 alt + 1 ana akış sınırı.
- **Kullanıcı kararları (2026-10-11):** görüntü doğrudan NVR'dan/kameradan (ofis paneli üzerinden değil); birden çok NVR ve kamera; sayım aynı listeden; kutuların hepsi akıcı canlı (fotoğraf yenileme yok).
- **Doğrulama durumu:** birim testleri (düzen kataloğu sözleşmeden, şablon ve cihaz depoları, eski ayarın taşınması, dağıtıcı: paylaşım/sınır/kapanış/sayım beslemesi, izleme modeli) ve CI simülatöründe uçtan uca test (sahte Dahua NVR: 4'lü şablon, tek kamera, sayıma geçiş). **Hiçbir test gerçek kameraya ya da NVR'a bağlanmaz.**
- **Ölçüm BEKLİYOR; şimdilik başarım iddiası yok.** Kullanıcının iPhone'unda ofis NVR'ı ile: 4, 9 ve 16'lı şablonda kutu başına kare/sn (şablon adına uzun bas), 10 dk izlemede ısı durumu ve pil yüzdesi düşüşü, sayım çalışırken sayım kare hızı. NVR'ın gerçek eşzamanlı bağlantı sınırı da yazılacak.
- **Bilinen sınırlar:** şablonlar web ile eşitlenmez; TRASSIR'da 16 kutunun her biri ayrı jeton ister (tek oturum); poz güvenlik alarmı ızgarada yok (telefonda çalışmaz); kayıt cihazının kanal listesi değişirse İzleme'de "Kanal bulunamadı" görünür, Kameralar → "Kanalları yenile".
```

(e) `apps/ios/README.md`: insert before `## Bilinen sınırlar`:

```markdown
## Cihazlar ve İzleme

Ayarlar → Görüntü kaynağı → **Cihazlar**'a IP kameralar ve kayıt cihazları (NVR/XVR) bir kez eklenir; sayılacak kamera **Sayılan kamera**'dan seçilir. **İzleme** sekmesi kameraları şablonlu ızgarada (2, 3, 4, 6, 8, 9, 12, 16'lı) canlı gösterir; görüntü doğrudan cihazlardan gelir ve telefondan çıkmaz. Ayrıntı: `docs/04-ios-app.md` §1j.
```

(f) Spec status line: in `docs/superpowers/specs/2026-10-11-iphone-izleme-design.md`, change `Durum: tasarım onaylandı, uygulanmadı` to `Durum: uygulandı (ölçüm bekliyor; docs/12-durum.md §5h)`.

- [ ] **Step 3: Commit, then run CI and the UI tests.**
  - Commit the test and the docs separately, with the messages `iPhone izleme: uçtan uca ızgara testi (sahte Dahua NVR)` and `Belgeler: iPhone çoklu kamera izleme (cihazlar, İzleme, ölçüm bekliyor)`.
  - Run CI, then dispatch `ios-uitest`.
  - Expected: both green. In the uitest log, `testWatchGridFromRecorderAndCountCamera` passes and the attachment `izleme-4lu` is saved.

---

### Task 8 (controller, with the user): merge, TestFlight, measurement

- After the final review: fast-forward `main`, push, then dispatch `testflight.yml` on `main`.
  - Add the build row to `docs/12-durum.md` §2.
  - Notify the user when the build lands.
- With the user, on the office NVR: measure 4/9/16 tiles (fps per tile, 10 min heat/battery, counting fps impact) and record it in `docs/12-durum.md` §5h. Not part of the automated plan.
