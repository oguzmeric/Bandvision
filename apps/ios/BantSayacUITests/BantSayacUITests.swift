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
        for second in [5, 10] {                       // teşhis: oynatma sırasında ekran
            sleep(5)
            let shot = XCTAttachment(screenshot: app.screenshot())
            shot.name = "ag-kamerasi-\(second)sn"
            shot.lifetime = .keepAlways
            add(shot)
            print("AĞ SAYAÇLARI \(second) sn: \(app.staticTexts["networkStats"].label) | sayı \(app.staticTexts["liveCount"].label)")
        }
        let ended = waitForLabel(state, containing: "Yayın bitti", timeout: 180)
        print("AĞ DURUMU: \(state.label)")
        print("AĞ SAYAÇLARI son: \(app.staticTexts["networkStats"].label)")
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

    // MARK: - Kayıt cihazı (NVR/XVR): ayar ekranından kamera seçimi ve yayın

    /// CI'da tools/mock_nvr.py sahte TRASSIR/Hikvision/Dahua kayıt cihazlarını taklit eder (ios-uitest.yml).
    private struct MockRecorder {
        let host: String
        let httpPort: String
        let rtspPort: String
        let password: String
    }

    private func mockRecorder() throws -> MockRecorder {
        let env = ProcessInfo.processInfo.environment
        guard let host = env["BS_NVR_HOST"] else {
            throw XCTSkip("Sahte kayıt cihazı yok (CI'da tools/mock_nvr.py ile çalışır)")
        }
        return MockRecorder(host: host, httpPort: env["BS_NVR_HTTP_PORT"] ?? "", rtspPort: env["BS_NVR_RTSP_PORT"] ?? "",
                            password: env["BS_NVR_PASS"] ?? "")
    }

    private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any)[id].firstMatch
    }

    /// Açık klavye alttaki alanı örtebilir (dokunuş klavyeye gider): önce kapatılır, alan görünür yapılır.
    private func fill(_ field: XCUIElement, _ text: String, clear: Int = 0) {
        XCTAssertTrue(field.waitForExistence(timeout: 10), "alan yok: \(field)")
        dismissKeyboard(XCUIApplication())
        if !field.isHittable { XCUIApplication().swipeUp(velocity: .slow) }
        field.tap()
        if clear > 0 { field.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: clear)) }
        field.typeText(text)
    }

    private func dismissKeyboard(_ app: XCUIApplication) {
        let done = app.toolbars.buttons["Tamam"].firstMatch
        if done.exists { done.tap() }
    }

    /// Temiz ayarlarla açar (kamera izni istenmez), Ayarlar → Ağ kamerası → Kayıt cihazı → marka.
    private func openRecorderForm(brand: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment["BS_TEST_FORMS"] = "1"
        app.launch()
        app.tabBars.buttons["Ayarlar"].tap()
        let link = element(app, "networkCameraLink")
        XCTAssertTrue(link.waitForExistence(timeout: 10))
        link.tap()
        let kind = element(app, "deviceKind")
        XCTAssertTrue(kind.waitForExistence(timeout: 10))
        kind.buttons["Kayıt cihazı"].tap()
        element(app, "recorderBrand").buttons[brand].tap()
        return app
    }

    /// Liste tembel: ekran dışındaki satır ağaçta yoktur. Aşağı kaydırarak görünür yapar.
    @discardableResult
    private func reveal(_ app: XCUIApplication, _ el: XCUIElement, swipes: Int = 8) -> Bool {
        var n = 0
        while !(el.exists && el.isHittable) && n < swipes {
            app.swipeUp(velocity: .slow)
            n += 1
        }
        return el.exists
    }

    /// Listele → kamera seç → bağlantıyı test et → kaydet → Ayarlar'da yayın "Canlı".
    private func pickTestAndSave(_ app: XCUIApplication, camera: String, expectedOthers: [String], absent: [String]) {
        dismissKeyboard(app)
        let list = element(app, "listChannels")
        reveal(app, list)
        list.tap()
        // Liste gelince düğme "Listeyi yenile" olur (düğme ekranda kalır; satırlar aşağıda olabilir)
        let loaded = waitForLabel(list, containing: "yenile", timeout: 40)
        if !loaded {
            let error = element(app, "channelError")
            print("KAYIT CİHAZI hata: \(error.exists ? error.label : "yok")")
        }
        XCTAssertTrue(loaded, "kameralar listelenmedi")
        let row = element(app, "channel.\(camera)")
        XCTAssertTrue(reveal(app, row), "listede yok: \(camera)")
        row.tap()
        for other in expectedOthers {
            XCTAssertTrue(reveal(app, element(app, "channel.\(other)")), "listede yok: \(other)")
        }
        for name in absent {
            XCTAssertFalse(element(app, "channel.\(name)").exists, "listede olmamalı: \(name)")
        }

        let test = element(app, "testConnection")
        XCTAssertTrue(reveal(app, test))
        test.tap()
        let ok = element(app, "testResult")
        let error = element(app, "testError")
        let deadline = Date().addingTimeInterval(40)
        while !ok.exists && !error.exists && Date() < deadline {
            app.swipeUp(velocity: .slow)                   // sonuç bölümün altında belirir
            sleep(1)
        }
        if error.exists { print("KAYIT CİHAZI test hatası: \(error.label)") }
        XCTAssertTrue(ok.exists, "bağlantı testi başarısız")
        print("KAYIT CİHAZI test: \(ok.label)")

        let save = element(app, "saveNetworkCamera")
        XCTAssertTrue(reveal(app, save))
        save.tap()
        // İmzasız simülatörde Keychain yazılamaz (-34018): uygulama uyarır, kullanıcı "Tamam" der (cihazda çıkmaz)
        let warning = app.alerts["Şifre"]
        if warning.waitForExistence(timeout: 5) {
            print("KAYIT CİHAZI uyarı: \(warning.staticTexts.allElementsBoundByIndex.map(\.label).joined(separator: " | "))")
            warning.buttons["Tamam"].tap()
        }
        let live = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", "Canlı ·")).firstMatch
        XCTAssertTrue(live.waitForExistence(timeout: 60), "kaydettikten sonra yayın başlamadı")
        print("KAYIT CİHAZI yayın: \(live.label)")
    }

    /// TRASSIR: SDK oturumu (HTTPS, kendinden imzalı), kanal listesi (kayıp kanal gösterilmez), jetonlu RTSP (555).
    func testRecorderTrassirPicksCameraAndPlays() throws {
        let nvr = try mockRecorder()
        let app = openRecorderForm(brand: "TRASSIR")
        fill(element(app, "recorderHost"), nvr.host)
        // Önce yanlış şifre: anlaşılır hata
        fill(element(app, "recorderPassword"), "yanlis-sifre")
        dismissKeyboard(app)
        let list = element(app, "listChannels")
        reveal(app, list)
        list.tap()
        let error = element(app, "channelError")
        XCTAssertTrue(error.waitForExistence(timeout: 30), "yanlış şifrede hata gösterilmedi")
        XCTAssertTrue(error.label.contains("şifre"), "beklenmeyen hata: \(error.label)")
        // Doğru şifre (varsayılan portlar: SDK 8080, görüntü 555)
        fill(element(app, "recorderPassword"), nvr.password, clear: 20)
        pickTestAndSave(app, camera: "Bant 1", expectedOthers: ["Kapı"], absent: ["Kayıp kamera"])
    }

    /// Hikvision: ISAPI kanal listesi (Digest), adı boş kanal "Kanal 2", RTSP /Streaming/Channels/102.
    func testRecorderHikvisionPicksCameraAndPlays() throws {
        let nvr = try mockRecorder()
        let app = openRecorderForm(brand: "Hikvision")
        fill(element(app, "recorderHost"), nvr.host)
        app.buttons["Portlar"].tap()
        fill(element(app, "recorderHTTPPort"), nvr.httpPort)
        fill(element(app, "recorderRTSPPort"), nvr.rtspPort)
        fill(element(app, "recorderPassword"), nvr.password)
        pickTestAndSave(app, camera: "Bant 1", expectedOthers: ["Kanal 2"], absent: [])
    }

    /// Dahua: ChannelTitle kanal listesi (Digest), RTSP /cam/realmonitor?channel=1&subtype=1.
    func testRecorderDahuaPicksCameraAndPlays() throws {
        let nvr = try mockRecorder()
        let app = openRecorderForm(brand: "Dahua")
        fill(element(app, "recorderHost"), nvr.host)
        app.buttons["Portlar"].tap()
        fill(element(app, "recorderHTTPPort"), nvr.httpPort)
        fill(element(app, "recorderRTSPPort"), nvr.rtspPort)
        fill(element(app, "recorderPassword"), nvr.password)
        pickTestAndSave(app, camera: "Bant 1", expectedOthers: ["Kapı", "Depo", "Kanal 4"], absent: [])
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
