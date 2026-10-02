import XCTest
@testable import BantSayac

/// Çokgen ROI (algoritma §2.0). Sayılar Python referansıyla aynı olmalı:
/// services/edge/tests/test_roi_polygon.py::test_parity_vectors (contracts/examples/profile-box-polygon.json).
final class RoiPolygonTests: XCTestCase {
    private let examplePolygon = [NormPoint(x: 0.30, y: 0.05), NormPoint(x: 0.82, y: 0.05),
                                  NormPoint(x: 0.64, y: 0.95), NormPoint(x: 0.12, y: 0.95)]
    private let exampleROI = CGRect(x: 0.12, y: 0.05, width: 0.7, height: 0.9)

    private func stats(_ m: [UInt8], w: Int, h: Int) -> (inside: Int, sumI: Int, sumJ: Int) {
        var inside = 0, sumI = 0, sumJ = 0
        for j in 0..<h {
            for i in 0..<w where m[j * w + i] != 0 {
                inside += 1
                sumI += i
                sumJ += j
            }
        }
        return (inside, sumI, sumJ)
    }

    private func rowExtent(_ m: [UInt8], w: Int, row j: Int) -> (Int, Int)? {
        let xs = (0..<w).filter { m[j * w + $0] != 0 }
        guard let first = xs.first, let last = xs.last else { return nil }
        return (first, last)
    }

    func testParityVectors240x426() {
        let (w, h) = (240, 426)
        let m = BackgroundSegmenter.roiMask(roi: exampleROI, polygon: examplePolygon, width: w, height: h)
        let s = stats(m, w: w, h: h)
        XCTAssertEqual(s.inside, 47797)
        XCTAssertEqual(s.sumI, 5369916)
        XCTAssertEqual(s.sumJ, 10133596)
        XCTAssertTrue(rowExtent(m, w: w, row: 106)! == (62, 186))
        XCTAssertTrue(rowExtent(m, w: w, row: 213)! == (50, 174))
        XCTAssertTrue(rowExtent(m, w: w, row: 319)! == (38, 162))
        XCTAssertNil(rowExtent(m, w: w, row: 0))
        XCTAssertNil(rowExtent(m, w: w, row: h - 1))
    }

    func testParityVectors160x90() {
        let (w, h) = (160, 90)
        let m = BackgroundSegmenter.roiMask(roi: exampleROI, polygon: examplePolygon, width: w, height: h)
        let s = stats(m, w: w, h: h)
        XCTAssertEqual(s.inside, 6738)
        XCTAssertEqual(s.sumI, 504548)
        XCTAssertEqual(s.sumJ, 296505)
        XCTAssertTrue(rowExtent(m, w: w, row: 22)! == (42, 124))
        XCTAssertTrue(rowExtent(m, w: w, row: 45)! == (33, 116))
        XCTAssertTrue(rowExtent(m, w: w, row: 67)! == (26, 108))
    }

    func testConcavePolygon() {
        let lShape = [NormPoint(x: 0.1, y: 0.1), NormPoint(x: 0.9, y: 0.1), NormPoint(x: 0.9, y: 0.4),
                      NormPoint(x: 0.4, y: 0.4), NormPoint(x: 0.4, y: 0.9), NormPoint(x: 0.1, y: 0.9)]
        let m = BackgroundSegmenter.roiMask(roi: CGRect(x: 0, y: 0, width: 1, height: 1), polygon: lShape,
                                            width: 100, height: 100)
        XCTAssertEqual(m.reduce(0) { $0 + Int($1) }, 3900)
        XCTAssertEqual(m[20 * 100 + 80], 1)
        XCTAssertEqual(m[80 * 100 + 20], 1)
        XCTAssertEqual(m[80 * 100 + 80], 0)
    }

    func testWithoutPolygonMaskIsRectangle() {
        let roi = CGRect(x: 0.05, y: 0.1, width: 0.9, height: 0.8)
        let m = BackgroundSegmenter.roiMask(roi: roi, polygon: nil, width: 240, height: 426)
        let r = BackgroundSegmenter.pixelRect(roi, width: 240, height: 426)
        XCTAssertEqual(m.reduce(0) { $0 + Int($1) }, (r.x1 - r.x0) * (r.y1 - r.y0))
    }

    func testSetPolygonUpdatesBoundingBoxAndLine() {
        var p = ProductProfile.egg()
        p.linePosition = 0.95
        p.setPolygon([NormPoint(x: 0.36, y: 0.1), NormPoint(x: 0.66, y: 0.1),
                      NormPoint(x: 0.64, y: 0.6), NormPoint(x: 0.34, y: 0.6)])
        XCTAssertEqual(p.roi.minX, 0.34, accuracy: 1e-9)
        XCTAssertEqual(p.roi.maxX, 0.66, accuracy: 1e-9)
        XCTAssertEqual(p.roi.maxY, 0.6, accuracy: 1e-9)
        XCTAssertEqual(p.linePosition, 0.58, accuracy: 1e-9)       // çizgi kutunun içine çekildi
        p.setPolygon([NormPoint(x: 0.1, y: 0.1), NormPoint(x: 0.2, y: 0.2)])
        XCTAssertNil(p.roiPolygon)                                    // 3 köşeden az: dikdörtgene döner
    }

    /// Eski sürümün kaydettiği profil (roiPolygon yok) okunabilmeli; çokgen {x, y} biçiminde kodlanmalı.
    func testProfileCodingCompatibility() throws {
        var p = ProductProfile.egg()
        let old = try JSONEncoder().encode(p)
        var dict = try XCTUnwrap(JSONSerialization.jsonObject(with: old) as? [String: Any])
        dict.removeValue(forKey: "roiPolygon")
        let decodedOld = try JSONDecoder().decode(ProductProfile.self,
                                                  from: JSONSerialization.data(withJSONObject: dict))
        XCTAssertNil(decodedOld.roiPolygon)

        p.setPolygon(examplePolygon)
        let data = try JSONEncoder().encode(p)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let first = try XCTUnwrap((json["roiPolygon"] as? [[String: Any]])?.first)
        XCTAssertEqual(first["x"] as? Double, 0.30)
        XCTAssertEqual(first["y"] as? Double, 0.05)
        XCTAssertEqual(try JSONDecoder().decode(ProductProfile.self, from: data), p)
    }
}
