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
