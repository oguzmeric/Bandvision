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
