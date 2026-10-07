import XCTest
@testable import BantSayac

/// Sözleşmedeki `countMode: "safety"` ve `safety` bloğu (poz güvenlik alarmı, yalnızca bilgisayarda çalışır):
/// iPhone hatasız okur ve geri yazar (alan kaybolmaz); sayım yapmaz.
final class SafetyProfileTests: XCTestCase {
    private static let block = #"{"handsUp":{"enabled":true,"seconds":3},"lying":{"enabled":false,"seconds":12.5},"sendImage":true}"#

    /// Sözleşme varsayılanları: ikisi açık, 3 ve 10 sn, resim kapalı
    private static let contractDefaults = SafetyConfig(handsUp: .init(enabled: true, seconds: 3),
                                                       lying: .init(enabled: true, seconds: 10),
                                                       sendImage: false)

    private static func decodeBlock(_ json: String) throws -> SafetyConfig {
        try JSONDecoder().decode(SafetyConfig.self, from: Data(json.utf8))
    }

    func testSafetyProfileDecodesAndRoundTrips() throws {
        var dict = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(ProductProfile.generic())) as? [String: Any])
        dict["countMode"] = "safety"
        dict["safety"] = try JSONSerialization.jsonObject(with: Data(Self.block.utf8))
        let p = try JSONDecoder().decode(ProductProfile.self, from: JSONSerialization.data(withJSONObject: dict))
        XCTAssertEqual(p.mode, .safety)
        XCTAssertFalse(p.isTwoWay)
        XCTAssertEqual(p.safety, SafetyConfig(handsUp: .init(enabled: true, seconds: 3),
                                              lying: .init(enabled: false, seconds: 12.5),
                                              sendImage: true))
        // iPhone'da kaydedilip geri okunsa da güvenlik ayarı korunur
        let back = try JSONDecoder().decode(ProductProfile.self, from: JSONEncoder().encode(p))
        XCTAssertEqual(back, p)
        let json = String(decoding: try JSONEncoder().encode(p), as: UTF8.self)
        XCTAssertTrue(json.contains("\"safety\""))
        XCTAssertTrue(json.contains("\"countMode\":\"safety\""))
    }

    /// Şemada `safety` alanları zorunlu değil, Python eksikleri varsayılanla doldurur: iPhone da aynısını yapmalı
    /// (okunamayan blok profil listesini bozar).
    func testPartialSafetyBlockDecodesWithContractDefaults() throws {
        XCTAssertEqual(try Self.decodeBlock("{}"), Self.contractDefaults)
        var withImage = Self.contractDefaults
        withImage.sendImage = true
        XCTAssertEqual(try Self.decodeBlock(#"{"sendImage":true}"#), withImage)
        // Verilen kural korunur, eksik olan varsayılan olur
        var customLying = Self.contractDefaults
        customLying.lying = .init(enabled: false, seconds: 20)
        XCTAssertEqual(try Self.decodeBlock(#"{"lying":{"enabled":false,"seconds":20}}"#), customLying)
        // Kural katı kalır: yarım kural kabul edilmez
        XCTAssertThrowsError(try Self.decodeBlock(#"{"handsUp":{"enabled":true}}"#))
    }

    func testProfileWithEmptySafetyBlockDecodes() throws {
        var dict = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(ProductProfile.generic())) as? [String: Any])
        dict["countMode"] = "safety"
        dict["safety"] = [String: Any]()
        let p = try JSONDecoder().decode(ProductProfile.self, from: JSONSerialization.data(withJSONObject: dict))
        XCTAssertEqual(p.mode, .safety)
        XCTAssertEqual(p.safety, Self.contractDefaults)
    }

    func testProfilesWithoutSafetyBlockStayNil() throws {
        let p = ProductProfile.egg()
        XCTAssertNil(p.safety)
        let data = try JSONEncoder().encode(p)
        XCTAssertFalse(String(decoding: data, as: UTF8.self).contains("safety"))
        let back = try JSONDecoder().decode(ProductProfile.self, from: data)
        XCTAssertNil(back.safety)
        XCTAssertEqual(back.mode, .blob)
    }

    /// Sabit liste denetimi (sözleşmedeki `countMode` sıralaması elle yazılmıştır); şema dosyasını okumaz.
    func testCountModeRawValues() {
        XCTAssertEqual(CountMode.allCases.map(\.rawValue), ["blob", "linescan", "detect", "safety"])
        XCTAssertEqual(CountMode.safety.title, "Güvenlik (yalnızca bilgisayar)")
    }
}
