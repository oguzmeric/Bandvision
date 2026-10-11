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
