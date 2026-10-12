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

    /// Yatay deneyen test yarıda kalsa da sonraki testler dikey başlasın (simülatör yönü testler arasında kalır)
    override func tearDown() {
        XCUIDevice.shared.orientation = .portrait
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

    /// Temiz ayarlarla açar (kamera izni istenmez), Ayarlar → Cihazlar → Kayıt cihazı ekle → marka.
    private func openRecorderForm(brand: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment["BS_TEST_FORMS"] = "1"
        app.launch()
        app.tabBars.buttons["Ayarlar"].tap()
        let link = element(app, "devicesLink")
        XCTAssertTrue(link.waitForExistence(timeout: 10))
        link.tap()
        let add = element(app, "addRecorder")
        XCTAssertTrue(add.waitForExistence(timeout: 10))
        add.tap()
        let brandPicker = element(app, "recorderBrand")
        XCTAssertTrue(brandPicker.waitForExistence(timeout: 10))
        brandPicker.buttons[brand].tap()
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
        // Kaydedince Cihazlar listesine dönülür; sayım için kamera seçili değildi: sayım bu kamerayla başlar
        let device = element(app, "device.NVR 1")
        XCTAssertTrue(device.waitForExistence(timeout: 10), "cihaz listede yok")
        app.navigationBars.buttons["Ayarlar"].tap()
        let live = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", "Canlı ·")).firstMatch
        let playing = live.waitForExistence(timeout: 60)
        if !playing {
            let states = app.staticTexts.allElementsBoundByIndex.map(\.label)
                .filter { $0.contains("Yayın") || $0.contains("Bağlan") || $0.contains("yeniden") }
            print("KAYIT CİHAZI yayın durumu: \(states)")
        }
        XCTAssertTrue(playing, "kaydettikten sonra yayın başlamadı")
        print("KAYIT CİHAZI yayın: \(live.label)")
        XCTAssertTrue(element(app, "countCameraLink").label.contains("NVR 1 · \(camera)"),
                      "sayılan kamera: \(element(app, "countCameraLink").label)")
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

    // MARK: - İzleme (çoklu kamera ızgarası)

    /// Kutunun erişilebilirlik değeri "… · kare N": N kutuya verilen kare sayısıdır (abone olunca son kare bir kez
    /// tekrarlanır), bu yüzden N ≥ 2 olunca kare gerçekten akıyor demektir. SwiftUI sayıyı bölgeye göre biçimler
    /// ("3,666"); binlik ayracı (virgül, nokta, boşluk) kabul edilir.
    private func waitForFrames(_ el: XCUIElement, timeout: TimeInterval) -> Bool {
        let predicate = NSPredicate(format: "value MATCHES %@", ".*kare ([2-9]|[1-9][0-9.,\u{00A0}\u{202F} ]+)$")
        return XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: predicate, object: el)],
                                timeout: timeout) == .completed
    }

    /// Sekme çubuğundan sekmeye geçer. Yön değişiminin ya da çubuk animasyonunun ortasındaki dokunuş boşa gidebilir:
    /// düğme dokunulabilir olunca dokunur, seçilene dek yeniden dener.
    private func selectTab(_ app: XCUIApplication, _ name: String) -> Bool {
        let button = app.tabBars.buttons[name]
        let selected = NSPredicate(format: "isSelected == true")
        for _ in 0..<5 {
            if button.waitForExistence(timeout: 5), button.isHittable { button.tap() }
            let done = XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: selected, object: button)], timeout: 3)
            if done == .completed { return true }
        }
        return false
    }

    private func waitUntilGone(_ el: XCUIElement, timeout: TimeInterval) -> Bool {
        let predicate = NSPredicate(format: "exists == false")
        return XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: predicate, object: el)],
                                timeout: timeout) == .completed
    }

    /// Hata teşhisi: ekranın erişilebilirlik ağacı ve görüntüsü (CI günlüğünde "=== EKRAN" ile aranır)
    private func dumpScreen(_ app: XCUIApplication, _ name: String) {
        print("=== EKRAN (\(name)) ===")
        print(app.debugDescription)
        print("=== SON ===")
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = name
        shot.lifetime = .keepAlways
        add(shot)
    }

    /// Koşul sağlanmazsa ekran dökümü alınır, sonra test düşer (`continueAfterFailure = false`)
    private func require(_ app: XCUIApplication, _ condition: Bool, _ message: @autoclosure () -> String,
                         file: StaticString = #filePath, line: UInt = #line) {
        guard !condition else { return }
        dumpScreen(app, "hata-ekrani")
        XCTFail(message(), file: file, line: line)
    }

    /// Dahua kayıt cihazını ekler (Bant 1 sayılan kamera olur), İzleme sekmesinde "NVR'dan şablon" ile 4'lü ızgarayı kurar.
    private func addDahuaAndOpenWatch(_ nvr: MockRecorder) -> XCUIApplication {
        let app = openRecorderForm(brand: "Dahua")
        fill(element(app, "recorderHost"), nvr.host)
        app.buttons["Portlar"].tap()
        fill(element(app, "recorderHTTPPort"), nvr.httpPort)
        fill(element(app, "recorderRTSPPort"), nvr.rtspPort)
        fill(element(app, "recorderPassword"), nvr.password)
        pickTestAndSave(app, camera: "Bant 1", expectedOthers: ["Kapı", "Depo", "Kanal 4"], absent: [])

        require(app, selectTab(app, "İzleme"), "İzleme sekmesi seçilemedi")
        let fromRecorder = element(app, "emptyFromRecorder")
        require(app, fromRecorder.waitForExistence(timeout: 10), "boş şablon ekranı yok")
        fromRecorder.tap()
        require(app, element(app, "tile.0").waitForExistence(timeout: 10), "şablon kurulmadı: kutu 0 yok")
        return app
    }

    /// Dahua kayıt cihazı → NVR'dan 4'lü şablon → kutularda kare akar (sayılan kamera sayımın akışını paylaşır)
    /// → tek kamera (ana akış) → "Bu kamerayı say" Canlı sekmesinde bu kamerayı sayar.
    func testWatchGridFromRecorderAndCountCamera() throws {
        // Yazdırılan satırlar "KAYIT CİHAZI" önekini taşır: ios-uitest.yml günlük süzgeci yalnızca bunları gösterir
        let nvr = try mockRecorder()
        let app = addDahuaAndOpenWatch(nvr)
        for i in 0..<4 {
            let tile = element(app, "tile.\(i)")
            require(app, tile.waitForExistence(timeout: 10), "kutu \(i) yok")
            let flowing = waitForFrames(tile, timeout: 60)
            print("KAYIT CİHAZI izleme: kutu \(i): \(tile.label) | \(String(describing: tile.value))")
            require(app, flowing, "kutu \(i) kare almadı: \(String(describing: tile.value))")
        }
        // Kutu 0 ("Bant 1") sayılan kameradır: ağ sayımı sürerken rozeti görünür
        let badge = element(app, "countBadge")
        require(app, badge.waitForExistence(timeout: 15), "sayılan kameranın rozeti yok")
        print("KAYIT CİHAZI izleme: rozet: \(badge.label)")
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "izleme-4lu"
        shot.lifetime = .keepAlways
        add(shot)

        element(app, "tile.1").tap()
        let single = element(app, "singleVideo")
        require(app, single.waitForExistence(timeout: 10), "tek kamera açılmadı")
        let singleFlowing = waitForFrames(single, timeout: 60)
        print("KAYIT CİHAZI izleme: tek kamera: \(single.label) | \(String(describing: single.value))")
        require(app, singleFlowing, "tek kamera kare almadı: \(String(describing: single.value))")
        require(app, single.label == "Kapı", "yanlış kamera açıldı: \(single.label)")
        element(app, "countThisCamera").tap()
        let state = element(app, "networkState")
        let counting = waitForLabel(state, containing: "Canlı", timeout: 60)
        print("KAYIT CİHAZI izleme: sayım durumu: \(state.label)")
        require(app, counting, "sayım yeni kamerada başlamadı: \(state.label)")
        // Sayılan kamera gerçekten değişti mi: Ayarlar'daki bağlantı etiketi (durum "Canlı" eski kameradan da gelebilir)
        require(app, selectTab(app, "Ayarlar"), "Ayarlar sekmesi seçilemedi")
        let link = element(app, "countCameraLink")
        require(app, link.waitForExistence(timeout: 10), "sayılan kamera bağlantısı yok")
        print("KAYIT CİHAZI izleme: sayılan kamera: \(link.label)")
        require(app, link.label.contains("NVR 1 · Kapı"), "sayılan kamera değişmedi: \(link.label)")
    }

    /// Yan çevirince yalnızca İzleme sekmesinde çubuklar gizlenir (tam ekran ızgara); diğer sekmeler dikey kalır.
    func testWatchLandscapeHidesBarsOnlyOnWatchTab() throws {
        let nvr = try mockRecorder()
        let app = addDahuaAndOpenWatch(nvr)
        let tabBar = app.tabBars.firstMatch
        require(app, tabBar.exists, "dikeyde sekme çubuğu yok")

        XCUIDevice.shared.orientation = .landscapeLeft
        let hidden = waitUntilGone(tabBar, timeout: 10)
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "izleme-yatay"
        shot.lifetime = .keepAlways
        add(shot)
        require(app, hidden, "İzleme'de yan çevirince sekme çubuğu gizlenmedi")

        XCUIDevice.shared.orientation = .portrait
        require(app, tabBar.waitForExistence(timeout: 10), "dikeye dönünce sekme çubuğu geri gelmedi")

        // Canlı sekmesi dikey kalır: yan çevirmek çubuğu gizlemez
        require(app, selectTab(app, "Canlı"), "Canlı sekmesi seçilemedi")
        XCUIDevice.shared.orientation = .landscapeLeft
        sleep(3)
        require(app, tabBar.exists, "Canlı sekmesinde yan çevirince sekme çubuğu kayboldu")
        XCUIDevice.shared.orientation = .portrait
    }

    // MARK: - Kurulum sihirbazı ve çokgen ROI

    /// Sistem izin penceresi (kamera) çıkarsa izin ver; simülatörde kamera yok, uygulama hatayı ekranda gösterir.
    private func allowSystemAlertIfShown() {
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let alert = springboard.alerts.firstMatch
        if alert.waitForExistence(timeout: 5) {
            print("KURULUM izin penceresi: \(alert.label)")
            alert.buttons.element(boundBy: alert.buttons.count - 1).tap()
        }
    }

    func testOnboardingLeadsToCalibrationWithPolygonArea() throws {
        let app = XCUIApplication()
        app.launchEnvironment["BS_TEST_ONBOARDING"] = "1"
        app.launch()

        let next = element(app, "onboardingNext")
        XCTAssertTrue(next.waitForExistence(timeout: 15), "sihirbaz açılmadı")
        XCTAssertTrue(app.staticTexts["Banttan geçen ürünleri sayar, kalitesini kontrol eder."].exists)
        next.tap()                                                      // Başla

        // Kaynak: kayıt cihazı seçilince bağlantı ayarı ister, form kayıt cihazı türüyle açılır
        element(app, "source.recorder").tap()
        XCTAssertFalse(next.isEnabled, "ağ kaynağı ayarlanmadan devam edilmemeli")
        element(app, "onboardingConnect").tap()
        XCTAssertTrue(element(app, "recorderHost").waitForExistence(timeout: 10), "form kayıt cihazı türüyle açılmadı")
        app.buttons["Kapat"].tap()
        element(app, "source.phone").tap()
        XCTAssertTrue(next.isEnabled)
        next.tap()

        // Ürün → montaj → hazır
        XCTAssertTrue(element(app, "product.Yumurta").waitForExistence(timeout: 5))
        element(app, "product.Yumurta").tap()
        next.tap()
        XCTAssertTrue(app.staticTexts["Montajı kontrol et"].waitForExistence(timeout: 5))
        next.tap()
        XCTAssertTrue(app.staticTexts["Hazır"].waitForExistence(timeout: 5))
        XCTAssertEqual(next.label, "Kalibrasyonla başla")
        next.tap()
        allowSystemAlertIfShown()

        // Canlı ekran kalibrasyonda; alan çokgene çevrilir
        XCTAssertTrue(app.staticTexts["Kalibrasyon"].waitForExistence(timeout: 15), "kalibrasyon paneli açılmadı")
        let shape = element(app, "roiShape")
        XCTAssertTrue(shape.waitForExistence(timeout: 5))
        shape.buttons["Çokgen"].tap()
        let overlay = element(app, "roiOverlay")
        XCTAssertTrue(waitForLabel(overlay, containing: "4 köşeli çokgen", timeout: 5), "çokgen yok: \(overlay.label)")
        XCTAssertTrue(element(app, "resetPolygon").exists)
        shape.buttons["Dikdörtgen"].tap()
        XCTAssertTrue(waitForLabel(overlay, containing: "dikdörtgen", timeout: 5))
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
