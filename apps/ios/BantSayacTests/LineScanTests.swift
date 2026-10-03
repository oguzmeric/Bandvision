import XCTest
@testable import BantSayac

/// Şerit tarama sayımı (algoritma §4.9). Sayılar Python referansıyla aynı olmalı:
/// services/edge/tests/test_linescan.py (`parity_frames`, `PARITY_EXPECTED`).
final class LineScanTests: XCTestCase {
    private static let w = 96, h = 160

    /// Python `parity_frames` ile aynı tam sayılı üretici: 40 ürün (40–48 px), bazıları bitişik, bazıları aralıklı.
    private static func parityFrames(count: Int = 380, speed: Int = 3) -> [GrayFrame] {
        var items: [(z: Int, len: Int)] = []
        var z = 20
        for k in 0..<40 {
            let len = 40 + (k * 7) % 9
            items.append((z, len))
            z += len + (k % 3 == 0 ? 0 : (k * 5) % 13)
        }
        func value(_ zz: Int, _ x: Int) -> UInt8 {
            if x < 16 || x >= 80 { return 30 }
            if x >= 24 && x < 72 {
                for it in items {
                    let u = zz - it.z
                    if u >= 0 && u < it.len {
                        if u < 2 { return 90 }
                        let tail = it.len - 1 - u
                        return UInt8(200 - (u < 6 ? (6 - u) * 10 : 0) - (tail < 4 ? (4 - tail) * 10 : 0))
                    }
                }
            }
            return UInt8(60 + (zz * 37) % 11 + (x * 13) % 5)
        }
        let zmax = speed * count + h
        var strip = [[UInt8]]()
        strip.reserveCapacity(zmax)
        for zz in 0..<zmax { strip.append((0..<w).map { value(zz, $0) }) }
        return (0..<count).map { t in
            var px = [UInt8]()
            px.reserveCapacity(w * h)
            for y in 0..<h { px += strip[speed * t + (h - 1 - y)] }
            return GrayFrame(width: w, height: h, sourceWidth: w, sourceHeight: h, pixels: px)
        }
    }

    private static func profile(productLength: Double? = nil) -> ProductProfile {
        var p = ProductProfile.generic()
        p.roi = CGRect(x: 16.0 / 96.0, y: 0.05, width: 64.0 / 96.0, height: 0.9)
        p.linePosition = 0.5
        p.direction = .down
        p.maxMultiplicity = 4
        p.countMode = .linescan
        p.productLength = productLength
        return p
    }

    private static func run(_ frames: [GrayFrame], _ p: ProductProfile) -> (total: Int, length: Double) {
        let lc = LineScanCounter()
        var total = 0
        for f in frames { total += lc.process(f, profile: p).reduce(0) { $0 + $1.delta } }
        total += lc.flush(profile: p).reduce(0) { $0 + $1.delta }
        return (total, lc.productLength)
    }

    func testParityVectors() {
        let frames = Self.parityFrames()
        let learned = Self.run(frames, Self.profile())
        XCTAssertEqual(learned.total, 24)                       // Python: PARITY_EXPECTED[0] (elle de 24)
        XCTAssertEqual(learned.length, 0.347222, accuracy: 1e-6)
        let known = Self.run(frames, Self.profile(productLength: 0.3))
        XCTAssertEqual(known.total, 24)
    }

    func testEventsAreSingleProductsWithMarkers() {
        let frames = Self.parityFrames()
        let p = Self.profile(productLength: 0.347222)
        let lc = LineScanCounter()
        var ids = Set<Int>()
        for f in frames {
            let ev = lc.process(f, profile: p)
            XCTAssertTrue(ev.allSatisfy { $0.delta == 1 })
            ids.formUnion(ev.map(\.id))
            for m in lc.markers(width: f.width, height: f.height, profile: p) {
                XCTAssertTrue((0...1).contains(m.x) && (0...1).contains(m.y))
            }
        }
        XCTAssertGreaterThanOrEqual(ids.count, 23)              // her ürün ayrı kimlik (ekrandaki numara)
    }

    func testOldProfilesDecodeWithoutNewFields() throws {
        // Eski kayıtta countMode/productLength yok: sorunsuz açılmalı, leke yöntemiyle
        var p = ProductProfile.egg()
        p.countMode = nil
        p.productLength = nil
        let data = try JSONEncoder().encode(p)
        let json = String(decoding: data, as: UTF8.self)
        XCTAssertFalse(json.contains("countMode"))
        let back = try JSONDecoder().decode(ProductProfile.self, from: data)
        XCTAssertEqual(back.mode, .blob)
        XCTAssertEqual(back.lineProductLength, 0)
        XCTAssertEqual(ProductProfile.flourSack().mode, .linescan)
        XCTAssertEqual(ProductProfile.box().mode, .linescan)
    }
}
