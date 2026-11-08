import XCTest
@testable import BantSayac

/// Sözleşmedeki `countMode: "fire"` ve `fire` bloğu (yangın/duman erken uyarısı, yalnızca bilgisayarda çalışır):
/// iPhone hatasız okur ve geri yazar (alan, hariç bölgeler dahil, kaybolmaz); işlemez.
final class FireProfileTests: XCTestCase {
    private static let block = #"{"fire":{"enabled":false,"seconds":5},"smoke":{"enabled":true,"seconds":20},"sensitivity":"high","ignoreZones":[[[0.1,0.1],[0.4,0.1],[0.25,0.4]]],"sendImage":true}"#

    /// Sözleşme varsayılanları: alev açık 3 sn, duman açık 8 sn, hassasiyet normal, bölge yok, resim kapalı
    private static let contractDefaults = FireConfig(fire: .init(enabled: true, seconds: 3),
                                                     smoke: .init(enabled: true, seconds: 8),
                                                     sensitivity: "normal", ignoreZones: [], sendImage: false)

    private static func decodeBlock(_ json: String) throws -> FireConfig {
        try JSONDecoder().decode(FireConfig.self, from: Data(json.utf8))
    }

    func testFireProfileDecodesAndRoundTrips() throws {
        var dict = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(ProductProfile.generic())) as? [String: Any])
        dict["countMode"] = "fire"
        dict["fire"] = try JSONSerialization.jsonObject(with: Data(Self.block.utf8))
        let p = try JSONDecoder().decode(ProductProfile.self, from: JSONSerialization.data(withJSONObject: dict))
        XCTAssertEqual(p.mode, .fire)
        XCTAssertTrue(p.isPcOnly)
        XCTAssertFalse(p.isTwoWay)
        XCTAssertEqual(p.fire, FireConfig(fire: .init(enabled: false, seconds: 5),
                                          smoke: .init(enabled: true, seconds: 20),
                                          sensitivity: "high",
                                          ignoreZones: [[[0.1, 0.1], [0.4, 0.1], [0.25, 0.4]]],
                                          sendImage: true))
        // iPhone'da kaydedilip geri okunsa da yangın ayarı (hariç bölgeler dahil) korunur
        let back = try JSONDecoder().decode(ProductProfile.self, from: JSONEncoder().encode(p))
        XCTAssertEqual(back, p)
        let json = String(decoding: try JSONEncoder().encode(p), as: UTF8.self)
        XCTAssertTrue(json.contains("\"fire\":{"))
        XCTAssertTrue(json.contains("\"countMode\":\"fire\""))
        XCTAssertTrue(json.contains("\"ignoreZones\""))
    }

    /// Şemada `fire` alanları zorunlu değil (`{}` geçerli), Python eksikleri varsayılanla doldurur: iPhone da aynısını
    /// yapmalı (okunamayan blok profil listesini bozar).
    func testPartialFireBlockDecodesWithContractDefaults() throws {
        XCTAssertEqual(try Self.decodeBlock("{}"), Self.contractDefaults)
        var withImage = Self.contractDefaults
        withImage.sendImage = true
        XCTAssertEqual(try Self.decodeBlock(#"{"sendImage":true}"#), withImage)
        var customSmoke = Self.contractDefaults
        customSmoke.smoke = .init(enabled: false, seconds: 12)
        XCTAssertEqual(try Self.decodeBlock(#"{"smoke":{"enabled":false,"seconds":12}}"#), customSmoke)
        // Kural katı kalır: yarım kural kabul edilmez
        XCTAssertThrowsError(try Self.decodeBlock(#"{"fire":{"enabled":true}}"#))
    }

    func testProfileWithEmptyFireBlockDecodes() throws {
        var dict = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(ProductProfile.generic())) as? [String: Any])
        dict["countMode"] = "fire"
        dict["fire"] = [String: Any]()
        let p = try JSONDecoder().decode(ProductProfile.self, from: JSONSerialization.data(withJSONObject: dict))
        XCTAssertEqual(p.mode, .fire)
        XCTAssertEqual(p.fire, Self.contractDefaults)
    }

    func testProfilesWithoutFireBlockStayNil() throws {
        let p = ProductProfile.egg()
        XCTAssertNil(p.fire)
        let data = try JSONEncoder().encode(p)
        XCTAssertFalse(String(decoding: data, as: UTF8.self).contains("\"fire\""))
        let back = try JSONDecoder().decode(ProductProfile.self, from: data)
        XCTAssertNil(back.fire)
        XCTAssertEqual(back.mode, .blob)
    }

    func testFireModeTitleAndPcOnly() {
        XCTAssertEqual(CountMode.fire.rawValue, "fire")
        XCTAssertEqual(CountMode.fire.title, "Yangın / duman (yalnızca bilgisayar)")
        var p = ProductProfile.egg()
        XCTAssertFalse(p.isPcOnly)
        p.countMode = .safety
        XCTAssertTrue(p.isPcOnly)
    }
}
