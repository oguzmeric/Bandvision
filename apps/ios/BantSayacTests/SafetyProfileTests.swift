import XCTest
@testable import BantSayac

/// Sözleşmedeki `countMode: "safety"` ve `safety` bloğu (poz güvenlik alarmı, yalnızca bilgisayarda çalışır):
/// iPhone hatasız okur ve geri yazar (alan kaybolmaz); sayım yapmaz.
final class SafetyProfileTests: XCTestCase {
    private static let block = #"{"handsUp":{"enabled":true,"seconds":3},"lying":{"enabled":false,"seconds":12.5},"sendImage":true}"#

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

    func testProfilesWithoutSafetyBlockStayNil() throws {
        let p = ProductProfile.egg()
        XCTAssertNil(p.safety)
        let data = try JSONEncoder().encode(p)
        XCTAssertFalse(String(decoding: data, as: UTF8.self).contains("safety"))
        let back = try JSONDecoder().decode(ProductProfile.self, from: data)
        XCTAssertNil(back.safety)
        XCTAssertEqual(back.mode, .blob)
    }

    func testCountModeValuesMatchContractEnum() {
        XCTAssertEqual(CountMode.allCases.map(\.rawValue), ["blob", "linescan", "detect", "safety"])
        XCTAssertEqual(CountMode.safety.title, "Güvenlik (yalnızca bilgisayar)")
    }
}
