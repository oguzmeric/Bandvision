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

    @discardableResult
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

    /// Geçersiz kayıt (ayarsız kayıt cihazı) sessizce atılmaz: dosyanın kopyası kenara alınır, sonraki kayıt onu silmez.
    func testInvalidDeviceRecordIsCopiedAsideNotDropped() throws {
        let dir = tempDir()
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let original = """
        {"channels":{},"devices":[\
        {"config":{"kind":"camera","host":"10.0.0.64"},"id":"cam","name":"Kapı"},\
        {"config":{"kind":"recorder","recorderBrand":"hikvision","recorderHost":""},"id":"nvr","name":"Ofis NVR"}],\
        "version":1}
        """
        try Data(original.utf8).write(to: dir.appendingPathComponent("devices.json"))

        let store = DeviceStore(directory: dir, credentials: MemoryCredentials())
        XCTAssertEqual(store.devices.map(\.id), ["cam"])
        let problem = try XCTUnwrap(store.problem)
        let copies = try FileManager.default.contentsOfDirectory(atPath: dir.path).filter { $0.hasPrefix("devices.corrupt-") }
        XCTAssertEqual(copies.count, 1, "özgün dosyanın kopyası kenara alınmalı: \(copies)")
        let copyURL = dir.appendingPathComponent(try XCTUnwrap(copies.first))
        XCTAssertTrue(problem.contains(copyURL.lastPathComponent), "uyarı kopyanın adını söylemeli: \(problem)")
        XCTAssertEqual(try String(contentsOf: copyURL, encoding: .utf8), original, "kopya özgün baytları taşımalı")

        // Sonraki kayıt canlı dosyayı yeniden yazar; kenardaki kopya yerinde kalır
        store.save(NetworkDevice(id: "yeni", name: "Yeni", config: cameraConfig()), password: "")
        XCTAssertTrue(FileManager.default.fileExists(atPath: copyURL.path))
        XCTAssertEqual(try String(contentsOf: copyURL, encoding: .utf8), original)
        let reloaded = DeviceStore(directory: dir, credentials: MemoryCredentials())
        XCTAssertEqual(reloaded.devices.map(\.id), ["cam", "yeni"])
        XCTAssertNil(reloaded.problem)
    }
}
