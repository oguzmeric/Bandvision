import XCTest
import CoreVideo
@testable import BantSayac

/// Sahte bağlantı: başlat/durdur sayılır, kare ve durum elle verilir.
final class FakeStream: HubStream, @unchecked Sendable {
    private(set) var started = 0
    private(set) var stopped = 0
    private var onFrame: (@Sendable (CVPixelBuffer) -> Void)?
    private var onStatus: (@Sendable (TileStatus) -> Void)?

    func start(onFrame: @escaping @Sendable (CVPixelBuffer) -> Void,
               onStatus: @escaping @Sendable (TileStatus) -> Void) {
        started += 1
        self.onFrame = onFrame
        self.onStatus = onStatus
    }

    func stop() { stopped += 1 }
    func emit(_ frame: CVPixelBuffer) { onFrame?(frame) }
    func emit(_ status: TileStatus) { onStatus?(status) }
}

final class FakeSubscriber: HubSubscriber, @unchecked Sendable {
    private(set) var frames: [CVPixelBuffer] = []
    private(set) var statuses: [TileStatus] = []
    var lastStatus: TileStatus? { statuses.last }
    func hubFrame(_ frame: CVPixelBuffer) { frames.append(frame) }
    func hubStatus(_ status: TileStatus) { statuses.append(status) }
}

func makeTestFrame() -> CVPixelBuffer {
    var pb: CVPixelBuffer?
    CVPixelBufferCreate(kCFAllocatorDefault, 4, 4, kCVPixelFormatType_32BGRA, nil, &pb)
    return pb!
}

/// Görüntü dağıtıcısı: paylaşım, kapanış payı, sınırlar, sayım beslemesi (sahte bağlantıyla, ağsız).
@MainActor
final class CameraHubTests: XCTestCase {
    private var clock = 0.0
    private var opened: [HubKey: [FakeStream]] = [:]
    private var rejections: [CameraRef: TileStatus] = [:]

    private func makeHub() -> CameraHub {
        CameraHub(opener: { [unowned self] key in
            if let status = self.rejections[key.ref] { return .rejected(status) }
            let stream = FakeStream()
            self.opened[key, default: []].append(stream)
            return .stream(stream)
        }, now: { [unowned self] in self.clock })
    }

    private func ref(_ n: Int) -> CameraRef { CameraRef(sourceId: "nvr", channelId: String(n)) }
    private func sub(_ n: Int) -> HubKey { HubKey(ref: ref(n), quality: .sub) }
    private func main(_ n: Int) -> HubKey { HubKey(ref: ref(n), quality: .main) }

    func testOneReaderPerKeyIsShared() {
        let hub = makeHub()
        let a = FakeSubscriber(), b = FakeSubscriber()
        hub.subscribe(sub(1), a)
        hub.subscribe(sub(1), b)
        XCTAssertEqual(opened[sub(1)]?.count, 1)
        let f = makeTestFrame()
        opened[sub(1)]?.first?.emit(f)
        XCTAssertTrue(a.frames.last === f)
        XCTAssertTrue(b.frames.last === f)
        XCTAssertEqual(hub.openCount.sub, 1)
    }

    func testIdleReaderClosesAfterGrace() {
        let hub = makeHub()
        let a = FakeSubscriber()
        hub.subscribe(sub(1), a)
        hub.unsubscribe(sub(1), a)
        clock = 4.9
        hub.sweep()
        XCTAssertEqual(opened[sub(1)]?.first?.stopped, 0)
        clock = 5.0
        hub.sweep()
        XCTAssertEqual(opened[sub(1)]?.first?.stopped, 1)
        XCTAssertEqual(hub.openCount.sub, 0)
    }

    func testResubscribeWithinGraceKeepsConnection() {
        let hub = makeHub()
        let a = FakeSubscriber(), b = FakeSubscriber()
        hub.subscribe(sub(1), a)
        hub.unsubscribe(sub(1), a)
        clock = 3
        hub.subscribe(sub(1), b)
        clock = 20
        hub.sweep()
        XCTAssertEqual(opened[sub(1)]?.count, 1)
        XCTAssertEqual(opened[sub(1)]?.first?.stopped, 0)
    }

    func testSixteenSubStreamsThenLimitUntilOneIsFree() {
        let hub = makeHub()
        let subs = (1...17).map { _ in FakeSubscriber() }
        for n in 1...16 { hub.subscribe(sub(n), subs[n - 1]) }
        hub.subscribe(sub(17), subs[16])
        XCTAssertEqual(subs[16].lastStatus, .limit)
        XCTAssertNil(opened[sub(17)])
        hub.unsubscribe(sub(1), subs[0])               // boşa çıkan okuyucu hemen yer açar
        XCTAssertEqual(opened[sub(1)]?.first?.stopped, 1)
        XCTAssertEqual(opened[sub(17)]?.count, 1)
        XCTAssertEqual(subs[16].lastStatus, .connecting)
        XCTAssertEqual(hub.openCount.sub, 16)
    }

    func testTemplateSwitchReusesCommonAndEvictsIdle() {
        let hub = makeHub()
        let old = (1...16).map { _ in FakeSubscriber() }
        for n in 1...16 { hub.subscribe(sub(n), old[n - 1]) }
        for n in 1...16 { hub.unsubscribe(sub(n), old[n - 1]) }
        let new = (9...24).map { _ in FakeSubscriber() }   // 9–16 ortak, 17–24 yeni
        for (i, n) in (9...24).enumerated() { hub.subscribe(sub(n), new[i]) }
        for n in 9...16 {
            XCTAssertEqual(opened[sub(n)]?.count, 1, "ortak kamera \(n) yeniden açılmamalı")
            XCTAssertEqual(opened[sub(n)]?.first?.stopped, 0)
        }
        for s in new { XCTAssertNotEqual(s.lastStatus, .limit) }
        XCTAssertEqual(hub.openCount.sub, 16)
    }

    func testOneMainStream() {
        let hub = makeHub()
        let a = FakeSubscriber(), b = FakeSubscriber()
        hub.subscribe(main(1), a)
        hub.subscribe(main(2), b)
        XCTAssertEqual(b.lastStatus, .limit)
        XCTAssertEqual(hub.openCount.main, 1)
    }

    func testRejectedTileShowsReasonWithoutConnection() {
        let hub = makeHub()
        rejections[ref(1)] = .deleted
        let a = FakeSubscriber()
        hub.subscribe(sub(1), a)
        XCTAssertEqual(a.lastStatus, .deleted)
        XCTAssertNil(opened[sub(1)])
        XCTAssertEqual(hub.openCount.sub, 0)
    }

    func testCountedCameraUsesCountingStream() {
        let hub = makeHub()
        hub.setExternal(ref(1))
        let a = FakeSubscriber(), b = FakeSubscriber()
        hub.subscribe(sub(1), a)
        hub.subscribe(main(1), b)
        XCTAssertNil(opened[sub(1)])
        XCTAssertNil(opened[main(1)])
        let f = makeTestFrame()
        hub.externalFrame(f)
        XCTAssertTrue(a.frames.last === f)
        XCTAssertTrue(b.frames.last === f)
        hub.externalStatus(.playing)
        XCTAssertEqual(a.lastStatus, .playing)
        XCTAssertEqual(hub.openCount.sub + hub.openCount.main, 0)
    }

    func testCountingTakesOverOpenReader() {
        let hub = makeHub()
        let a = FakeSubscriber()
        hub.subscribe(sub(1), a)
        hub.setExternal(ref(1))
        XCTAssertEqual(opened[sub(1)]?.first?.stopped, 1)
        XCTAssertEqual(hub.openCount.sub, 0)
        let f = makeTestFrame()
        hub.externalFrame(f)
        XCTAssertTrue(a.frames.last === f)
    }

    func testCountingStopsThenTileOpensOwnConnection() {
        let hub = makeHub()
        hub.setExternal(ref(1))
        let a = FakeSubscriber()
        hub.subscribe(sub(1), a)
        hub.setExternal(nil)
        XCTAssertEqual(opened[sub(1)]?.count, 1)
        XCTAssertEqual(opened[sub(1)]?.first?.started, 1)
    }

    func testLastFrameShownWhenComingBack() throws {
        let hub = makeHub()
        let a = FakeSubscriber(), b = FakeSubscriber()
        hub.subscribe(sub(1), a)
        let f = makeTestFrame()
        try XCTUnwrap(opened[sub(1)]?.first).emit(f)
        hub.unsubscribe(sub(1), a)
        clock = 6
        hub.sweep()
        XCTAssertEqual(hub.openCount.sub, 0)
        hub.subscribe(sub(1), b)
        XCTAssertTrue(b.frames.first === f, "son kare hemen görünmeli")
        XCTAssertEqual(opened[sub(1)]?.count, 2)
    }

    func testMainShowsSubFrameUntilItsOwnArrives() throws {
        let hub = makeHub()
        let a = FakeSubscriber(), b = FakeSubscriber()
        hub.subscribe(sub(1), a)
        let f = makeTestFrame()
        try XCTUnwrap(opened[sub(1)]?.first).emit(f)
        hub.subscribe(main(1), b)
        XCTAssertTrue(b.frames.first === f)
    }

    func testRetryAfterPasswordError() throws {
        let hub = makeHub()
        let a = FakeSubscriber()
        hub.subscribe(sub(1), a)
        try XCTUnwrap(opened[sub(1)]?.first).emit(.authFailed)
        XCTAssertEqual(a.lastStatus, .authFailed)
        hub.retry(sub(1))
        XCTAssertEqual(opened[sub(1)]?.first?.stopped, 1)
        XCTAssertEqual(opened[sub(1)]?.count, 2)
        XCTAssertEqual(a.lastStatus, .connecting)
    }

    func testDeviceResetReopensWithNewSettings() {
        let hub = makeHub()
        let a = FakeSubscriber()
        hub.subscribe(sub(1), a)
        rejections[ref(1)] = .deleted
        hub.reset(sourceId: "nvr")
        XCTAssertEqual(opened[sub(1)]?.first?.stopped, 1)
        XCTAssertEqual(a.lastStatus, .deleted)
        XCTAssertEqual(hub.openCount.sub, 0)
    }

    func testBackgroundClosesIdleImmediately() {
        let hub = makeHub()
        let a = FakeSubscriber()
        hub.subscribe(sub(1), a)
        hub.unsubscribe(sub(1), a)
        hub.closeIdle()
        XCTAssertEqual(opened[sub(1)]?.first?.stopped, 1)
    }
}

final class StreamProblemTests: XCTestCase {
    func testClassification() {
        XCTAssertEqual(StreamProblem.of(RTSPClient.Failure.unauthorized), .auth)
        XCTAssertEqual(StreamProblem.of(RTSPClient.Failure.status(453, "Not Enough Bandwidth")), .refused)
        XCTAssertEqual(StreamProblem.of(RTSPClient.Failure.status(503, "Service Unavailable")), .refused)
        XCTAssertEqual(StreamProblem.of(RTSPClient.Failure.status(404, "Not Found")), .offline)
        XCTAssertEqual(StreamProblem.of(RTSPClient.Failure.unsupportedCodec("MJPEG")), .unsupported)
        XCTAssertEqual(StreamProblem.of(RecorderError.unauthorized), .auth)
        XCTAssertEqual(StreamProblem.of(RecorderError.unreachable("zaman aşımı")), .offline)
        XCTAssertEqual(StreamProblem.of(nil), .offline)
        XCTAssertEqual(TileStatus(StreamProblem.refused).text, "NVR bağlantı sınırına ulaştı")
        XCTAssertEqual(TileStatus(counting: .reconnecting(seconds: 2, reason: "x")), .connecting)
    }
}
