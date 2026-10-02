import XCTest
@testable import BantSayac

/// Açılı sayım çizgisi (algoritma §4.8). Sayılar Python referansıyla aynı olmalı:
/// services/edge/tests/test_angled_line.py (test_parity_vectors, test_segment_frame_boxes_parity).
final class LineFrameTests: XCTestCase {
    private let a = NormPoint(x: 0.12, y: 0.62)
    private let b = NormPoint(x: 0.78, y: 0.38)

    func testParityVectors() throws {
        let lf = try XCTUnwrap(LineFrame.build(a: a, b: b, width: 240, height: 426))
        XCTAssertEqual(lf.alpha, 0.5633802816901409, accuracy: 1e-15)
        XCTAssertEqual(lf.dx, 0.8401843886289171, accuracy: 1e-15)
        XCTAssertEqual(lf.dy, -0.5423008326604828, accuracy: 1e-15)
        XCTAssertEqual(lf.bounds.v0, -0.3628755145154736, accuracy: 1e-15)
        XCTAssertEqual(lf.bounds.v1, 0.8527686356824272, accuracy: 1e-15)
        XCTAssertEqual(lf.bounds.u0, -0.6575769124537358, accuracy: 1e-15)
        XCTAssertEqual(lf.bounds.u1, 0.6881290720402419, accuracy: 1e-15)
        let p = lf.toFrame(0.5, 0.5)
        XCTAssertEqual(p.v, 0.2449465605834768, accuracy: 1e-15)
        XCTAssertEqual(p.u, 0.015276079793253017, accuracy: 1e-15)
        let q = lf.toFrame(0.1, 0.9)
        XCTAssertEqual(q.v, -0.16131109949568356, accuracy: 1e-15)
        XCTAssertEqual(q.u, 0.2291411968987956, accuracy: 1e-15)
        let back = lf.toImage(q.v, q.u)
        XCTAssertEqual(back.x, 0.1, accuracy: 1e-12)
        XCTAssertEqual(back.y, 0.9, accuracy: 1e-12)
        XCTAssertEqual(LineFrame.nearestDirection(a: a, b: b, aspect: 240.0 / 426.0), .down)
    }

    func testFlowIsRightHandAndDegenerateLineIgnored() throws {
        let lf = try XCTUnwrap(LineFrame.build(a: NormPoint(x: 0.1, y: 0.5), b: NormPoint(x: 0.9, y: 0.5),
                                               width: 100, height: 100))
        XCTAssertGreaterThan(lf.toFrame(0.5, 0.6).u, 0)                 // soldan sağa → akış aşağı
        XCTAssertNil(LineFrame.build(a: a, b: a, width: 100, height: 100))
    }

    /// Çerçeve kutusu piksellerden; Python ile aynı giriş ve sayılar.
    func testSegmentFrameBoxesParity() throws {
        let w = 60, h = 40
        var px = [UInt8](repeating: 0, count: w * h)
        for j in 0..<h {
            for i in 0..<w where abs(i - 30) + abs(j - 20) <= 9 || (4...8).contains(i) && (3...7).contains(j) {
                px[j * w + i] = 200
            }
        }
        let frame = GrayFrame(width: w, height: h, sourceWidth: w, sourceHeight: h, pixels: px)
        let empty = GrayFrame(width: w, height: h, sourceWidth: w, sourceHeight: h,
                              pixels: [UInt8](repeating: 0, count: w * h))
        let seg = BackgroundSegmenter()
        seg.learn(empty, rate: 1)
        let lf = try XCTUnwrap(LineFrame.build(a: NormPoint(x: 0.1, y: 0.8), b: NormPoint(x: 0.9, y: 0.3),
                                               width: w, height: h))
        let blobs = seg.segment(frame, roi: CGRect(x: 0, y: 0, width: 1, height: 1), threshold: 50,
                                closeIterations: 0, backgroundRate: 0.02, keepMask: false, lineFrame: lf)
            .sorted { $0.cx < $1.cx }
        XCTAssertEqual(blobs.count, 2)
        XCTAssertEqual(blobs[0].cx, 0.1, accuracy: 1e-12)
        XCTAssertEqual(blobs[0].cy, 0.125, accuracy: 1e-12)
        let f0 = try XCTUnwrap(blobs[0].frameBBox)
        XCTAssertEqual(f0.minX, 0.1884615384615384, accuracy: 1e-12)
        XCTAssertEqual(f0.minY, -0.6846153846153846, accuracy: 1e-12)
        XCTAssertEqual(f0.width, 0.15576923076923074, accuracy: 1e-12)
        XCTAssertEqual(f0.height, 0.15576923076923085, accuracy: 1e-12)
        let f1 = try XCTUnwrap(blobs[1].frameBBox)
        XCTAssertEqual(f1.minX, 0.4692307692307692, accuracy: 1e-12)
        XCTAssertEqual(f1.minY, -0.23653846153846164, accuracy: 1e-12)
        XCTAssertEqual(f1.width, 0.41346153846153855, accuracy: 1e-12)
        XCTAssertEqual(f1.height, 0.41346153846153855, accuracy: 1e-12)
        // Çerçeveye taşınan leke görüntüdeki kutusunu taşır (sayım kırpıntısı için)
        let moved = lf.blob(blobs[1])
        XCTAssertEqual(moved.sourceBBox, blobs[1].bbox)
        XCTAssertEqual(moved.bbox, f1)
    }

    /// Düzden açılıya geçişte akış yönü korunur; eski kayıtlarda alan yok.
    func testStraightToAngledKeepsDirectionAndCoding() throws {
        for d in FlowDirection.allCases {
            var p = ProductProfile.egg()
            p.direction = d
            let line = p.straightCountLine
            XCTAssertEqual(LineFrame.nearestDirection(a: line.a, b: line.b, aspect: 9.0 / 16.0), d, "\(d)")
            p.setCountLine(line, aspect: 9.0 / 16.0)
            XCTAssertEqual(p.direction, d)
            p.setCountLine(nil, aspect: 9.0 / 16.0)
            XCTAssertNil(p.countLine)
        }
        var p = ProductProfile.egg()
        p.setCountLine(CountLine(a: a, b: b), aspect: 240.0 / 426.0)
        let data = try JSONEncoder().encode(p)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let cl = try XCTUnwrap(json["countLine"] as? [String: [String: Double]])
        XCTAssertEqual(cl["a"]?["x"], 0.12)
        XCTAssertEqual(cl["b"]?["y"], 0.38)
        XCTAssertEqual(try JSONDecoder().decode(ProductProfile.self, from: data), p)
        var dict = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(ProductProfile.egg())) as? [String: Any])
        dict.removeValue(forKey: "countLine")
        XCTAssertNil(try JSONDecoder().decode(ProductProfile.self, from: JSONSerialization.data(withJSONObject: dict)).countLine)
    }
}
