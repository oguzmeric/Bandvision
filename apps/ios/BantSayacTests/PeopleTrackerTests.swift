import XCTest
@testable import BantSayac

/// Kişi izleyicisi (algoritma §4.10). Python referansıyla eşdeğerlik: `people_parity.json`
/// (tools/make_people_fixture.py) — her senaryoda aynı karede aynı iz kimliğiyle aynı giriş/çıkış olayları.
final class PeopleTrackerTests: XCTestCase {
    private struct Fixture: Decodable {
        struct Frame: Decodable {
            let d: [[Double]]
            let m: [[Double]]
        }
        struct Scenario: Decodable {
            let name: String
            let anchor: String
            let line: Double
            let maxAge: Int
            let motion: Bool
            let frames: [Frame]
            let events: [[Int]]
        }
        let scenarios: [Scenario]
    }

    func testParityWithPythonReference() throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "people_parity", withExtension: "json"),
                                "people_parity.json test paketinde yok")
        let fixture = try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: url))
        XCTAssertEqual(fixture.scenarios.count, 7)
        for s in fixture.scenarios {
            var params = MotParams()
            params.maxAge = s.maxAge
            let tracker = MotTracker(params: params)
            let anchor = CountAnchor(rawValue: s.anchor) ?? .center
            var got: [[Int]] = []
            for (k, f) in s.frames.enumerated() {
                let dets = f.d.map { Detection(box: NBox(x1: $0[0], y1: $0[1], x2: $0[2], y2: $0[3]), score: $0[4]) }
                let blobs = f.m.map { NBox(x1: $0[0], y1: $0[1], x2: $0[2], y2: $0[3]) }
                let (ins, outs) = tracker.update(dets, sideOf: { _, y in y - s.line }, anchor: anchor,
                                                 motion: s.motion ? blobs : nil)
                got += ins.map { [k, $0.id, 1] } + outs.map { [k, $0.id, -1] }
            }
            XCTAssertEqual(got, s.events, "\(s.name): Swift ve Python olayları farklı")
        }
    }

    // MARK: - Davranış (Python test_people_track.py ile aynı senaryolar)

    private static let line = 0.55

    private func box(_ cx: Double, _ cy: Double, w: Double = 0.08, h: Double = 0.16) -> NBox {
        NBox(x1: cx - w / 2, y1: cy - h / 2, x2: cx + w / 2, y2: cy + h / 2)
    }

    private func run(_ frames: [[Detection]], motion: [[NBox]]? = nil) -> (ins: Int, outs: Int) {
        var params = MotParams()
        params.maxAge = 30
        let t = MotTracker(params: params)
        var ins = 0, outs = 0
        for (k, f) in frames.enumerated() {
            let r = t.update(f, sideOf: { _, y in y - Self.line }, motion: motion?[k])
            ins += r.entered.count
            outs += r.exited.count
        }
        return (ins, outs)
    }

    private func walk(_ y0: Double, _ y1: Double, _ n: Int, x: Double = 0.5) -> [[Detection]] {
        (0..<n).map { k in [Detection(box: box(x, y0 + (y1 - y0) * Double(k) / Double(n - 1)), score: 0.8)] }
    }

    func testEnterAndExit() {
        XCTAssertTrue(run(walk(0.2, 0.9, 40)) == (1, 0))
        XCTAssertTrue(run(walk(0.9, 0.2, 40)) == (0, 1))
    }

    func testLoiteringOnLineIsNotCounted() {
        let frames = (0..<150).map { k in [Detection(box: box(0.5, Self.line + 0.015 * sin(Double(k) / 3)), score: 0.8)] }
        XCTAssertTrue(run(frames) == (0, 0))
    }

    func testTurnBackCountsOneEntryOneExit() {
        XCTAssertTrue(run(walk(0.2, 0.8, 30) + walk(0.8, 0.2, 30)) == (1, 1))
    }

    func testThreePeopleSideBySideCountedOnceEach() {
        let frames = (0..<40).map { k in
            [0.3, 0.45, 0.6].map { x in
                Detection(box: box(x, 0.2 + 0.7 * Double(k) / 39, w: 0.07), score: 0.8)
            }
        }
        XCTAssertTrue(run(frames) == (3, 0))
    }

    func testPartBoxDoesNotCreateSecondPerson() {
        let frames = (0..<40).map { k -> [Detection] in
            let y = 0.2 + 0.7 * Double(k) / 39
            return [Detection(box: NBox(x1: 0.46, y1: y - 0.08, x2: 0.54, y2: y + 0.08), score: 0.5),
                    Detection(box: NBox(x1: 0.468, y1: y - 0.08, x2: 0.532, y2: y + 0.008), score: 0.9)]
        }
        XCTAssertTrue(run(frames) == (1, 0))
    }

    func testMotionOnlyObjectIsNeverCounted() {
        let frames = [[Detection]](repeating: [], count: 40)
        let motion = (0..<40).map { k in [box(0.5, 0.2 + 0.7 * Double(k) / 39)] }
        XCTAssertTrue(run(frames, motion: motion) == (0, 0))
    }

    func testUndetectedBelowCameraThenDetectedCountsEntry() {
        var frames: [[Detection]] = []
        var motion: [[NBox]] = []
        for k in 0..<40 {
            let y = 0.2 + 0.7 * Double(k) / 39
            frames.append(y > Self.line + 0.1 ? [Detection(box: box(0.5, y), score: 0.8)] : [])
            motion.append([box(0.5, y)])
        }
        XCTAssertTrue(run(frames, motion: motion) == (1, 0))
    }

    func testSuppressPartsKeepsLargestFirstAndMaxScore() {
        let big = Detection(box: NBox(x1: 0, y1: 0, x2: 0.2, y2: 0.4), score: 0.4)
        let part = Detection(box: NBox(x1: 0.02, y1: 0, x2: 0.18, y2: 0.2), score: 0.9)
        let other = Detection(box: NBox(x1: 0.5, y1: 0.5, x2: 0.6, y2: 0.6), score: 0.7)
        let out = suppressParts([other, part, big], contain: 0.85, partArea: 0.75)
        XCTAssertEqual(out, [Detection(box: big.box, score: 0.9), other])
    }

    // MARK: - Hareket lekeleri ve çizgi

    func testMotionDetectorFindsMovingSquareOnly() {
        let w = 160, h = 120
        func frame(_ x0: Int) -> GrayFrame {
            var px = [UInt8](repeating: 60, count: w * h)
            for y in 40..<70 { for x in x0..<(x0 + 20) { px[y * w + x] = 200 } }
            return GrayFrame(width: w, height: h, sourceWidth: w, sourceHeight: h, pixels: px)
        }
        let profile = ProductProfile.people()
        let md = MotionDetector()
        XCTAssertTrue(md.detect(frame(20), profile: profile).isEmpty)          // ilk kare: arka plan
        let blobs = md.detect(frame(80), profile: profile)
        XCTAssertFalse(blobs.isEmpty)
        XCTAssertTrue(blobs.contains { $0.x1 < 90.0 / 160 && $0.x2 > 95.0 / 160 }, "yeni konumdaki kare bulunmalı")
    }

    func testSideFunctionUsesDirectionAsEntry() {
        var p = ProductProfile.people()
        p.linePosition = 0.5
        p.direction = .down
        XCTAssertGreaterThan(peopleSideFunction(p, width: 720, height: 1280).side(0.5, 0.7), 0)
        p.direction = .up
        XCTAssertGreaterThan(peopleSideFunction(p, width: 720, height: 1280).side(0.5, 0.3), 0)
    }
}
