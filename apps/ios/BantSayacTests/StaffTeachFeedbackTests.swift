import XCTest
@testable import BantSayac

/// iPhone personel rengi öğretme geri bildirimi: kare akmıyorsa uyarı, sonuç gelince bekleme biter, başarıda uyarı kalkar
final class StaffTeachFeedbackTests: XCTestCase {
    @MainActor
    func testTimeoutFiresWhenNoResultArrives() async throws {
        let f = StaffTeachFeedback(timeout: .milliseconds(50))
        var fired = 0
        f.onTimeout = { fired += 1 }
        f.tapped()
        XCTAssertTrue(f.isWaiting)
        try await Task.sleep(for: .milliseconds(400))
        XCTAssertEqual(fired, 1)
        XCTAssertFalse(f.isWaiting)
    }

    @MainActor
    func testResultCancelsTimeout() async throws {
        let f = StaffTeachFeedback(timeout: .milliseconds(50))
        var fired = 0
        f.onTimeout = { fired += 1 }
        f.tapped()
        f.resolved()
        f.tapped()
        f.reset()
        try await Task.sleep(for: .milliseconds(400))
        XCTAssertEqual(fired, 0)
    }

    @MainActor
    func testNoticeIsClearedAfterLaterSuccess() {
        let f = StaffTeachFeedback()
        let hint = "Turuncu çizgiyi kişilerin tamamen geçtiği yere koy."
        var msg = f.notice(StaffTeachFeedback.darkMessage, current: hint)
        XCTAssertEqual(msg, StaffTeachFeedback.darkMessage)
        msg = f.notice(StaffTeachFeedback.noFrameMessage, current: msg)    // ikinci uyarı ilk iletiyi korur
        XCTAssertEqual(f.cleared(current: msg), hint)
        XCTAssertEqual(f.cleared(current: hint), hint)                      // uyarı yoksa ileti değişmez

        _ = f.notice(StaffTeachFeedback.darkMessage, current: hint)
        XCTAssertEqual(f.cleared(current: "Arka plan hazır."), "Arka plan hazır.")   // araya başka ileti girdi
    }
}
