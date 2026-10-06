import XCTest
@testable import BantSayac

/// Personel rengi (§4.10 eki): Python referansıyla eşdeğerlik — staff_parity.json (tools/make_staff_fixture.py)
final class StaffColorTests: XCTestCase {
    private struct Fixture: Decodable {
        struct Points: Decodable { let w: Int; let h: Int; let box: [Double]; let anchor: String; let pts: [[Int]] }
        struct Vote: Decodable { let rgb: [[Int]]; let colors: [[Double]]; let vote: Bool? }
        struct Dominant: Decodable { let rgb: [[Int]]; let lab: [Double]? }
        struct Frame: Decodable { let d: [[Double]]; let v: [Int] }
        struct Scenario: Decodable { let name: String; let line: Double; let maxAge: Int; let frames: [Frame]; let events: [[Int]] }
        struct Image: Decodable { let w: Int; let h: Int; let px: String }
        struct VoteFrame: Decodable {
            let name: String; let image: Int; let box: [Double]; let others: [[Double]]; let anchor: String
            let colors: [[Double]]; let vote: Bool?
        }
        struct TeachFrame: Decodable {
            let name: String; let image: Int; let boxes: [[Double]]; let point: [Double]; let anchor: String; let lab: [Double]?
        }
        let lab: [[Double]]
        let points: [Points]
        let votes: [Vote]
        let dominant: [Dominant]
        let tracker: [Scenario]
        let palette: [[Int]]
        let images: [Image]
        let voteFrames: [VoteFrame]
        let teachFrames: [TeachFrame]
    }

    /// Fikstür karesi: palet + satır sıralı indeks dizgisi (her piksel tek karakter)
    private struct Pixels {
        static let alphabet = Array("0123456789abcdefghijklmnopqrstuvwxyz".utf8)
        let w: Int, h: Int
        let rgb: [(UInt8, UInt8, UInt8)]
        init(_ img: Fixture.Image, palette: [[Int]]) {
            w = img.w; h = img.h
            rgb = img.px.utf8.map { ch in
                let c = palette[Pixels.alphabet.firstIndex(of: ch)!]
                return (UInt8(c[0]), UInt8(c[1]), UInt8(c[2]))
            }
        }
        func at(_ x: Int, _ y: Int) -> (UInt8, UInt8, UInt8) { rgb[y * w + x] }
    }

    private static func nbox(_ v: [Double]) -> NBox { NBox(x1: v[0], y1: v[1], x2: v[2], y2: v[3]) }

    private func fixture() throws -> Fixture {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "staff_parity", withExtension: "json"))
        return try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: url))
    }

    private func labs(_ rgb: [[Int]]) -> [LabColor] { rgb.map { StaffColor.lab(UInt8($0[0]), UInt8($0[1]), UInt8($0[2])) } }

    func testLabConversionMatchesPython() throws {
        for row in try fixture().lab {
            let c = StaffColor.lab(UInt8(row[0]), UInt8(row[1]), UInt8(row[2]))
            XCTAssertEqual(c.L, row[3], accuracy: 1e-4); XCTAssertEqual(c.a, row[4], accuracy: 1e-4); XCTAssertEqual(c.b, row[5], accuracy: 1e-4)
        }
    }

    func testGridPointsMatchPython() throws {
        for p in try fixture().points {
            let box = NBox(x1: p.box[0], y1: p.box[1], x2: p.box[2], y2: p.box[3])
            let got = StaffColor.gridPoints(StaffColor.torsoRegion(box, CountAnchor(rawValue: p.anchor)!))
                .map { StaffColor.pixel($0.x, $0.y, width: p.w, height: p.h) }.map { [$0.0, $0.1] }
            XCTAssertEqual(got, p.pts)
        }
    }

    func testVotesMatchPython() throws {
        for v in try fixture().votes {
            let colors = v.colors.map { LabColor(L: $0[0], a: $0[1], b: $0[2]) }
            XCTAssertEqual(StaffColor.voteLabs(labs(v.rgb), colors: colors), v.vote)
        }
    }

    func testDominantMatchesPython() throws {
        for d in try fixture().dominant {
            let c = StaffColor.dominant(labs(d.rgb))
            if let ref = d.lab {
                let got = try XCTUnwrap(c)
                XCTAssertEqual(got.L, ref[0], accuracy: 1e-4); XCTAssertEqual(got.a, ref[1], accuracy: 1e-4); XCTAssertEqual(got.b, ref[2], accuracy: 1e-4)
            } else {
                XCTAssertNil(c)
            }
        }
    }

    func testTrackerStaffDecisionsMatchPython() throws {
        for s in try fixture().tracker {
            var params = MotParams()
            params.maxAge = s.maxAge
            let tracker = MotTracker(params: params)
            var got: [[Int]] = []
            for (k, f) in s.frames.enumerated() {
                let dets = f.d.map { Detection(box: NBox(x1: $0[0], y1: $0[1], x2: $0[2], y2: $0[3]), score: $0[4]) }
                var voteOf: [NBox: Bool?] = [:]
                for (d, v) in zip(dets, f.v) { voteOf[d.box] = v < 0 ? nil : (v == 1) }
                let (ins, outs) = tracker.update(dets, sideOf: { _, y in y - s.line },
                                                 staffVote: { box, _ in voteOf[box] ?? nil })
                got += ins.map { [k, $0.id, 1, 0] } + outs.map { [k, $0.id, -1, 0] }
                got += tracker.staffEntered.map { [k, $0.id, 1, 1] } + tracker.staffExited.map { [k, $0.id, -1, 1] }
            }
            XCTAssertEqual(got, s.events, "\(s.name): Swift ve Python personel kararları farklı")
        }
    }

    func testFrameVoteEntryPointMatchesPython() throws {
        let fx = try fixture()
        let images = fx.images.map { Pixels($0, palette: fx.palette) }
        XCTAssertFalse(fx.voteFrames.isEmpty)
        for v in fx.voteFrames {
            let img = images[v.image]
            let got = StaffColor.vote(box: Self.nbox(v.box), others: v.others.map(Self.nbox), anchor: CountAnchor(rawValue: v.anchor)!,
                                      colors: v.colors.map { LabColor(L: $0[0], a: $0[1], b: $0[2]) },
                                      width: img.w, height: img.h, rgbAt: img.at)
            XCTAssertEqual(got, v.vote, "\(v.name): Swift ve Python kare oyu farklı")
        }
    }

    func testFrameTeachEntryPointMatchesPython() throws {
        let fx = try fixture()
        let images = fx.images.map { Pixels($0, palette: fx.palette) }
        XCTAssertFalse(fx.teachFrames.isEmpty)
        for t in fx.teachFrames {
            let img = images[t.image]
            let got = StaffColor.teach(boxes: t.boxes.map(Self.nbox), point: (t.point[0], t.point[1]),
                                       anchor: CountAnchor(rawValue: t.anchor)!, width: img.w, height: img.h, rgbAt: img.at)
            if let ref = t.lab {
                let c = try XCTUnwrap(got, "\(t.name): Swift nil, Python renk verdi")
                XCTAssertEqual(c.L, ref[0], accuracy: 1e-4, t.name)
                XCTAssertEqual(c.a, ref[1], accuracy: 1e-4, t.name)
                XCTAssertEqual(c.b, ref[2], accuracy: 1e-4, t.name)
            } else {
                XCTAssertNil(got, "\(t.name): Python nil (çok karanlık), Swift renk verdi")
            }
        }
    }

    func testSafetyRules() {
        XCTAssertFalse(StaffColor.isStaff(votes: 2, staffVotes: 2))
        XCTAssertTrue(StaffColor.isStaff(votes: 4, staffVotes: 2))
        XCTAssertTrue(StaffColor.isAchromatic(StaffColor.lab(25, 35, 80)))
        XCTAssertFalse(StaffColor.isAchromatic(StaffColor.lab(240, 120, 20)))
    }
}
