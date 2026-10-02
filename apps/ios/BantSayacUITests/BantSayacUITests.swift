import XCTest

/// Uçtan uca: uygulamayı simülatörde açar, sayısı bilinen klibi (tools/make_ui_test_clip.py) Swift çekirdeğiyle
/// saydırır ve Python referansıyla aynı sonucu bekler; ardından sekmeleri ve video sayfasını dolaşır.
@MainActor
final class BantSayacUITests: XCTestCase {
    private struct ClipMeta: Decodable {
        let count: Int
        let expectedArea: Double
    }

    override func setUp() {
        continueAfterFailure = false
    }

    private func clipMeta() throws -> ClipMeta {
        let bundle = Bundle(for: BantSayacUITests.self)
        let url = try XCTUnwrap(bundle.url(forResource: "ui_test_clip", withExtension: "json"))
        return try JSONDecoder().decode(ClipMeta.self, from: Data(contentsOf: url))
    }

    /// CI'da MediaMTX test klibini Digest kimlik doğrulamalı bir IP kamera gibi yayınlar (ios-uitest.yml).
    private func rtspServer() throws -> (url: String, user: String, pass: String) {
        let env = ProcessInfo.processInfo.environment
        guard let url = env["BS_RTSP_URL"] else { throw XCTSkip("RTSP test sunucusu yok (CI'da MediaMTX ile çalışır)") }
        return (url, env["BS_RTSP_USER"] ?? "", env["BS_RTSP_PASS"] ?? "")
    }

    private func waitForLabel(_ element: XCUIElement, containing text: String, timeout: TimeInterval) -> Bool {
        let predicate = NSPredicate(format: "label CONTAINS %@", text)
        return XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: predicate, object: element)],
                                timeout: timeout) == .completed
    }

    /// Ağ kamerası (RTSP + Digest + H.264 + VideoToolbox) üzerinden sayım, Python referansıyla aynı olmalı.
    func testNetworkCameraCountMatchesReference() throws {
        let server = try rtspServer()
        let meta = try clipMeta()
        let app = XCUIApplication()
        app.launchEnvironment["BS_TEST_RTSP_URL"] = server.url
        app.launchEnvironment["BS_TEST_RTSP_USER"] = server.user
        app.launchEnvironment["BS_TEST_RTSP_PASS"] = server.pass
        app.launchEnvironment["BS_TEST_EXPECTED_AREA"] = String(meta.expectedArea)
        app.launch()

        let state = app.descendants(matching: .any)["networkState"].firstMatch
        XCTAssertTrue(waitForLabel(state, containing: "Canlı", timeout: 60), "yayın başlamadı: \(state.label)")
        let ended = waitForLabel(state, containing: "Yayın bitti", timeout: 180)
        print("AĞ DURUMU: \(state.label)")
        let hook = app.staticTexts["testHookError"]
        if hook.exists { print("TEST KANCASI: \(hook.label)") }
        print("ÖLÇÜM: \(app.staticTexts["perfStats"].label)")
        XCTAssertTrue(ended, "yayın bitmedi")
        let countText = app.staticTexts["liveCount"].label
        XCTAssertEqual(Int(countText), meta.count, "ağ kamerası sayımı \(countText), Python referansı \(meta.count)")
    }

    /// Yanlış şifrede anlaşılır hata, boşuna yeniden deneme yok.
    func testNetworkCameraWrongPasswordIsExplained() throws {
        let server = try rtspServer()
        let app = XCUIApplication()
        app.launchEnvironment["BS_TEST_RTSP_URL"] = server.url
        app.launchEnvironment["BS_TEST_RTSP_USER"] = server.user
        app.launchEnvironment["BS_TEST_RTSP_PASS"] = "yanlis-sifre"
        app.launch()
        let state = app.descendants(matching: .any)["networkState"].firstMatch
        XCTAssertTrue(waitForLabel(state, containing: "şifre", timeout: 30), "beklenen şifre hatası yok: \(state.label)")
    }

    func testVideoCountMatchesReferenceAndScreensOpen() throws {
        let bundle = Bundle(for: BantSayacUITests.self)
        let clip = try XCTUnwrap(bundle.url(forResource: "ui_test_clip", withExtension: "mp4"), "test klibi pakette yok")
        let metaURL = try XCTUnwrap(bundle.url(forResource: "ui_test_clip", withExtension: "json"))
        let meta = try JSONDecoder().decode(ClipMeta.self, from: Data(contentsOf: metaURL))

        let app = XCUIApplication()
        app.launchEnvironment["BS_TEST_VIDEO"] = clip.path
        app.launchEnvironment["BS_TEST_EXPECTED_AREA"] = String(meta.expectedArea)
        app.launch()

        // 1) Video sonuna kadar sayılır, sayı referansla aynı olmalı
        // CI sanal makinesinde GPU yok: ekran karesi ~0,5 sn sürüyor; cihazda saniyeler içinde biter
        let finished = app.staticTexts["videoFinished"].waitForExistence(timeout: 600)
        print("ÖLÇÜM: \(app.staticTexts["perfStats"].label)")
        if !finished {
            // Teşhis: ekranda ne var (konum, hata metni, hangi sekme)
            print("=== EKRAN (erişilebilirlik ağacı) ===")
            print(app.debugDescription)
            print("=== SON ===")
            let shot = XCTAttachment(screenshot: app.screenshot())
            shot.lifetime = .keepAlways
            add(shot)
            XCTFail("video bitmedi")
            return
        }
        let countText = app.staticTexts["videoCount"].label
        XCTAssertEqual(Int(countText), meta.count, "Swift sayımı \(countText), Python referansı \(meta.count)")

        // 2) Sekmeler açılıyor, kartlar oluşmuş
        app.tabBars.buttons["Genel bakış"].tap()
        XCTAssertTrue(app.navigationBars["Genel bakış"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Son ürünler"].exists)

        app.tabBars.buttons["Öğret"].tap()
        XCTAssertTrue(app.navigationBars["Öğret"].waitForExistence(timeout: 10))

        app.tabBars.buttons["Ayarlar"].tap()
        XCTAssertTrue(app.navigationBars["Ayarlar"].waitForExistence(timeout: 10))

        // 3) Canlı sekmesi: video sayfası açılıp kapanıyor (önceki derlemede menüden açılış tepkisizdi)
        app.tabBars.buttons["Canlı"].tap()
        let filmButton = app.buttons["Video ile test"]
        XCTAssertTrue(filmButton.waitForExistence(timeout: 10))
        filmButton.tap()
        XCTAssertTrue(app.navigationBars["Video ile test"].waitForExistence(timeout: 10))
        app.navigationBars["Video ile test"].buttons["Kapat"].tap()
        XCTAssertTrue(app.staticTexts["videoCount"].waitForExistence(timeout: 10))
    }
}
