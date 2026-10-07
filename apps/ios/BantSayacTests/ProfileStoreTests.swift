import XCTest
@testable import BantSayac

/// Kayıtlı profil listesinin okunması: tek bir bozuk kayıt (ör. bilinmeyen gelecek sürüm yöntemi) tüm profilleri
/// silmemeli; okunamayan veri varsayılana dönmeden önce yedeklenmeli.
final class ProfileStoreTests: XCTestCase {
    private func object(_ p: ProductProfile) throws -> Any {
        try JSONSerialization.jsonObject(with: JSONEncoder().encode(p))
    }

    /// Eski bir uygulamanın tanımadığı yöntemle kaydedilmiş, öteki alanları tam bir kayıt
    private func futureModeRecord() throws -> Any {
        var d = try XCTUnwrap(object(.egg()) as? [String: Any])
        d["name"] = "Gelecek"
        d["countMode"] = "futuremode"
        return d
    }

    private static func makeSuite() throws -> (defaults: UserDefaults, name: String) {
        let name = "bantsayac.tests.\(UUID().uuidString)"
        return (try XCTUnwrap(UserDefaults(suiteName: name)), name)
    }

    private static let defaultNames = [ProductProfile.egg(), .flourSack(), .box(), .generic(), .people()].map(\.name)

    func testLossyDecodeKeepsGoodRecordsInOrder() throws {
        let data = try JSONSerialization.data(withJSONObject: [object(.egg()), futureModeRecord(), object(.people())])
        let r = try XCTUnwrap(ProfileListCodec.decode(data))
        XCTAssertEqual(r.profiles.map(\.name), ["Yumurta", "Mağaza girişi"])
        XCTAssertEqual(r.skipped, 1)
    }

    func testLossyDecodeKeepsProfileWithPartialSafetyBlock() throws {
        var safe = try XCTUnwrap(object(.generic()) as? [String: Any])
        safe["countMode"] = "safety"
        safe["safety"] = ["sendImage": true]
        let data = try JSONSerialization.data(withJSONObject: [object(.egg()), safe])
        let r = try XCTUnwrap(ProfileListCodec.decode(data))
        XCTAssertEqual(r.skipped, 0)
        XCTAssertEqual(r.profiles.count, 2)
        XCTAssertEqual(r.profiles[1].safety?.sendImage, true)
        XCTAssertEqual(r.profiles[1].safety?.lying.seconds, 10)
    }

    func testLossyDecodeReturnsNilWhenNotAnArray() {
        XCTAssertNil(ProfileListCodec.decode(Data(#"{"a":1}"#.utf8)))
        XCTAssertNil(ProfileListCodec.decode(Data("bozuk".utf8)))
    }

    @MainActor
    func testStoreKeepsGoodProfilesWhenOneRecordIsBad() throws {
        let (suite, name) = try Self.makeSuite()
        defer { suite.removePersistentDomain(forName: name) }
        let data = try JSONSerialization.data(withJSONObject: [object(.egg()), futureModeRecord(), object(.people())])
        suite.set(data, forKey: ProfileStore.profilesKey)

        let store = ProfileStore(defaults: suite)
        XCTAssertEqual(store.profiles.map(\.name), ["Yumurta", "Mağaza girişi"])
        XCTAssertEqual(suite.data(forKey: ProfileStore.backupKey), data)       // atlanan kayıt yedekte
        // Liste yeniden yazıldı: sonraki açılışta atlanan kayıt kalmaz, yedek ezilmez
        let stored = try XCTUnwrap(suite.data(forKey: ProfileStore.profilesKey))
        XCTAssertEqual(ProfileListCodec.decode(stored)?.skipped, 0)
        XCTAssertEqual(ProfileListCodec.decode(stored)?.profiles.count, 2)
    }

    @MainActor
    func testStoreFallsBackToDefaultsAndBacksUpWhenEveryRecordFails() throws {
        let (suite, name) = try Self.makeSuite()
        defer { suite.removePersistentDomain(forName: name) }
        let data = try JSONSerialization.data(withJSONObject: [futureModeRecord(), futureModeRecord()])
        suite.set(data, forKey: ProfileStore.profilesKey)

        let store = ProfileStore(defaults: suite)
        XCTAssertEqual(store.profiles.map(\.name), Self.defaultNames)
        XCTAssertEqual(suite.data(forKey: ProfileStore.backupKey), data)
    }

    @MainActor
    func testStoreBacksUpUnreadableData() throws {
        let (suite, name) = try Self.makeSuite()
        defer { suite.removePersistentDomain(forName: name) }
        let data = Data(#"{"a":1}"#.utf8)
        suite.set(data, forKey: ProfileStore.profilesKey)

        let store = ProfileStore(defaults: suite)
        XCTAssertEqual(store.profiles.map(\.name), Self.defaultNames)
        XCTAssertEqual(suite.data(forKey: ProfileStore.backupKey), data)
    }

    @MainActor
    func testValidDataIsKeptWithoutBackup() throws {
        let (suite, name) = try Self.makeSuite()
        defer { suite.removePersistentDomain(forName: name) }
        let egg = ProductProfile.egg(), people = ProductProfile.people()
        suite.set(try JSONEncoder().encode([egg, people]), forKey: ProfileStore.profilesKey)

        let store = ProfileStore(defaults: suite)
        XCTAssertEqual(store.profiles, [egg, people])
        XCTAssertNil(suite.data(forKey: ProfileStore.backupKey))
    }

    @MainActor
    func testEmptyStoreStartsWithDefaultsWithoutBackup() throws {
        let (suite, name) = try Self.makeSuite()
        defer { suite.removePersistentDomain(forName: name) }
        let store = ProfileStore(defaults: suite)
        XCTAssertEqual(store.profiles.map(\.name), Self.defaultNames)
        XCTAssertNil(suite.data(forKey: ProfileStore.backupKey))
    }
}
