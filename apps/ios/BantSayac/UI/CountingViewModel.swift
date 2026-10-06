import Foundation
import SwiftUI
import Combine
import Security

/// Video dosyasından sayım oturumu (manuel test). Sayımlar canlı oturumun kaydına/webhook'una karışmaz.
struct VideoRun: Equatable {
    var name: String
    var duration = 0.0
    /// Videodaki güncel konum (sn).
    var position = 0.0
    /// Sayımın başladığı konum: 0 değilse sayı videonun yalnızca bu noktadan sonrasını kapsar.
    var countFrom = 0.0
    var playing = false
    var finished = false
    var error: String?
}

@MainActor
final class CountingViewModel: ObservableObject {
    /// Şerit tarama: ürün boyu bu video için ön taramayla bulundu (kayıtlı profilde yok)
    private var autoProductLength = false
    @Published var profile: ProductProfile {
        didSet { processor.setProfile(profile) }
    }
    @Published private(set) var total = 0
    /// Kişi sayımı (§4.10): çıkış toplamı (`total` giriş toplamıdır)
    @Published private(set) var totalOut = 0
    /// Kişi sayımı: personel geçişleri (giriş/çıkışa eklenmez; yalnızca ekranda)
    @Published private(set) var staffIn = 0
    @Published private(set) var staffOut = 0
    /// Personel rengi öğretme modu: görüntüde dokunulan kişinin gövde rengi alınır
    @Published var teachingStaff = false
    @Published private(set) var snapshot: EngineSnapshot = .empty
    /// Video/ağ kamerası modunda ekranda gösterilen son kare
    @Published private(set) var frameImage: CGImage?
    @Published private(set) var isRunning = false
    @Published private(set) var isCalibrating = false
    @Published private(set) var calibrationMessage = ""
    @Published private(set) var cameraError: String?
    @Published private(set) var thermalState: ProcessInfo.ThermalState = ProcessInfo.processInfo.thermalState
    @Published private(set) var video: VideoRun?
    /// 1 = gerçek zamanlı, 2 = iki kat, 0 = olabildiğince hızlı
    @Published var videoSpeed = 1.0 {
        didSet { videoSource?.speed = videoSpeed }
    }
    /// Video baştan oynatılınca ilk ~1 sn'den arka plan öğrenilsin (videonun başında bant boşsa).
    @Published var videoLearnBackground = UserDefaults.standard.object(forKey: "bs.videoLearnBg") as? Bool ?? true {
        didSet { UserDefaults.standard.set(videoLearnBackground, forKey: "bs.videoLearnBg") }
    }
    var isVideoMode: Bool { video != nil }

    // Görüntü kaynağı: iPhone kamerası ya da ağ kamerası (RTSP)
    @Published private(set) var sourceKind: VideoSourceKind =
        VideoSourceKind(rawValue: UserDefaults.standard.string(forKey: "bs.source") ?? "") ?? .phone
    @Published private(set) var networkConfig = NetworkCameraConfig.load()
    @Published private(set) var networkState: NetworkCameraState?
    private var networkSource: NetworkCameraSource?
    /// Kaydedilen şifreler bellekte de tutulur: Keychain yazılamasa bile oturum boyunca bağlantı çalışır
    private var networkPasswords: [NetworkDeviceKind: String] = [:]
    private let frameGate = FrameGate()
    /// UI testi: yayın bitince yeniden bağlanma (gerçek kullanımda her zaman true)
    private var networkReconnect = true
    /// Önizleme katmanı yerine işlenen kare gösterilir (video ve ağ kamerası)
    var showsFrameImages: Bool { isVideoMode || sourceKind == .network }

    // Kalite kontrol (A aşaması): son ürün kartları ve örnekle öğretme
    @Published private(set) var inspections: [InspectionRecord] = []
    @Published private(set) var inspectionStats = InspectionStats()
    /// Kararı verilmiş izler: görüntüde ürünün yanında "OK 96" / "NOK · Kırık" etiketi
    @Published private(set) var trackVerdicts: [Int: AppearanceVerdict] = [:]
    let teach = TeachStore()

    let camera: CameraManager
    let processor: FrameProcessor
    let store: ProfileStore
    let settings: AppSettings
    let logger: CountLogger

    private var wasRunningBeforeCalibration = false
    private var videoSource: VideoFileSource?
    private var videoGeneration = 0
    private var liveTotal = 0
    private var liveTotalOut = 0
    private var liveStaffIn = 0
    private var liveStaffOut = 0
    private var cancellables = Set<AnyCancellable>()

    init() {
        let camera = CameraManager()
        let store = ProfileStore()
        self.camera = camera
        self.store = store
        self.settings = AppSettings()
        self.logger = CountLogger()
        self.processor = FrameProcessor(queue: camera.processingQueue)
        self.profile = store.selectedProfile

        processor.setProfile(profile)
        total = logger.restoredTotal
        totalOut = logger.restoredTotalOut
        processor.setTotals(in: total, out: totalOut)
        logger.profileName = profile.name
        logger.lineName = settings.lineName
        logger.webhookURL = settings.webhookURL

        processor.onCount = { [weak self] delta, total in
            guard let self else { return }
            self.total = total
            if self.video == nil {                     // video sayımı canlı kayda/webhook'a yazılmaz
                self.logger.record(delta: delta, total: total)
            }
        }
        processor.onCrossing = { [weak self] ins, outs, tIn, tOut in
            guard let self else { return }
            self.total = tIn
            self.totalOut = tOut
            if self.video == nil {                     // video sayımı canlı kayda/webhook'a yazılmaz
                if ins > 0 { self.logger.record(delta: ins, total: tIn, direction: .entry) }
                if outs > 0 { self.logger.record(delta: outs, total: tOut, direction: .exit) }
            }
        }
        processor.onStaff = { [weak self] sIn, sOut in
            self?.staffIn = sIn
            self?.staffOut = sOut
        }
        processor.onStaffColor = { [weak self] color in
            guard let self, self.isCalibrating else { return }
            guard let color else {
                self.calibrationMessage = "Burası çok karanlık; personelin üstüne dokunun."
                return
            }
            var colors = self.profile.staffColors ?? []
            guard colors.count < StaffColor.maxColors else { return }
            colors.append(color)
            self.profile.staffColors = colors
        }
        processor.onSnapshot = { [weak self] snap in
            self?.snapshot = snap
        }
        processor.onCalibration = { [weak self] event in
            self?.handleCalibration(event)
        }
        processor.onCrop = { [weak self] crop in
            self?.handleCrop(crop)
        }
        processor.onFrameImage = { [weak self] image in
            guard let self, self.showsFrameImages else { return }   // geç gelen kare iPhone kamerasına sızmasın
            self.frameImage = image
        }
        teach.load(profileID: profile.id)
        camera.frameHandler = { [processor] pb, ts in processor.process(pb, ts: ts) }

        NotificationCenter.default
            .publisher(for: ProcessInfo.thermalStateDidChangeNotification)
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in
                self?.thermalState = ProcessInfo.processInfo.thermalState
            }
            .store(in: &cancellables)
    }

    // MARK: - Kamera

    /// Seçili kaynağı başlatır (iPhone kamerası ya da ağ kamerası).
    func startCamera() {
        if sourceKind == .network {
            startNetwork()
            return
        }
        stopNetwork()
        camera.requestAccess { [weak self] granted in
            guard let self else { return }
            guard granted else {
                self.cameraError = "Kamera izni yok. Ayarlar > BandVision > Kamera'dan izin verin."
                return
            }
            self.camera.configureAndStart { [weak self] ok in
                guard let self else { return }
                if ok {
                    self.cameraError = nil
                    self.applySettings()
                } else {
                    self.cameraError = "Kamera başlatılamadı."
                }
            }
        }
    }

    func applySettings() {
        camera.setTorch(level: Float(settings.torchLevel))
        camera.setShutter(denominator: settings.shutterDenominator)
        camera.setFocusLocked(settings.focusLocked)
        processor.setShowMask(settings.showMask || isCalibrating)
        logger.lineName = settings.lineName
        logger.webhookURL = settings.webhookURL
    }

    // MARK: - Sayım

    func toggleRunning() { setRunning(!isRunning) }

    private func setRunning(_ on: Bool) {
        isRunning = on
        processor.setCounting(on)
    }

    func reset() {
        clearInspections()
        total = 0
        totalOut = 0
        processor.setTotals(in: 0, out: 0)
        staffIn = 0
        staffOut = 0
        processor.setStaffTotals(in: 0, out: 0)
        processor.resetTracking(resetBackground: false)
        logger.resetSession()
    }

    // MARK: - Kalibrasyon

    func beginCalibration() {
        wasRunningBeforeCalibration = isRunning
        setRunning(false)
        isCalibrating = true
        switch profile.mode {
        case .linescan:
            calibrationMessage = "Sarı alanı bandın üstüne, turuncu çizgiyi akışa dik koy. Ürün boyu ilk ürünlerden kendiliğinden öğrenilir."
        case .detect:
            calibrationMessage = "Turuncu çizgiyi kişilerin tamamen geçtiği yere, yürüme alanının ortasına koy (kapı eşiğine değil). Ok giriş yönünü gösterir."
        case .blob:
            calibrationMessage = "Sarı alanı ve turuncu çizgiyi ayarla, sonra boş bandı öğret."
        }
        processor.setShowMask(profile.mode == .blob)
    }

    func learnBackground() {
        calibrationMessage = "Boş bant öğreniliyor… Bantta ürün olmasın."
        processor.startBackgroundLearning(updateThreshold: true)
    }

    func learnSample() {
        if profile.mode == .linescan {
            calibrationMessage = "Ürün boyu öğreniliyor… Ürünler bantta normal akışında geçsin (bitişik olabilir)."
        } else {
            calibrationMessage = "Ürünleri TEK TEK ve aralıklı geçir: 0/8"
        }
        processor.startSampleLearning(target: 8)
    }

    /// Sayım yöntemini değiştir (§4.9). Şerit tarama açılı çizgiyle çalışmaz: düz çizgiye dönülür.
    func setCountMode(_ mode: CountMode) {
        guard mode != profile.mode else { return }
        if mode == .linescan && profile.countLine != nil {
            let s = snapshot.frameSize
            profile.setCountLine(nil, aspect: s.height > 0 ? Double(s.width / s.height) : 9.0 / 16.0)
        }
        profile.countMode = mode
        processor.setShowMask(mode == .blob)
        calibrationMessage = mode == .linescan
            ? "Bitişik/hacimli ürün: boş bant gerekmez. Ürün boyu ilk ürünlerden öğrenilir ya da \"Ürün boyunu öğren\"."
            : "Ayrık ürün: önce boş bandı öğret, sonra örnek ürün geçir."
    }

    /// Giriş yönünü tersine çevirir (kişi sayımı): giriş ↔ çıkış. Açılı çizgide uçlar yer değiştirir.
    /// Kalibrasyon dışında hemen kaydedilir (kalibrasyonda Kaydet ile).
    func flipEntryDirection() {
        if let cl = profile.countLine {
            let s = snapshot.frameSize
            profile.setCountLine(CountLine(a: cl.b, b: cl.a), aspect: s.height > 0 ? Double(s.width / s.height) : 9.0 / 16.0)
        } else {
            profile.direction = profile.direction.opposite
        }
        processor.resetTracking(resetBackground: false)     // yarım kalmış geçişler yeni yönle karışmasın
        if !isCalibrating { store.update(profile) }
    }

    /// Giriş yönünün kısa açıklaması ("↓ yukarıdan aşağı"; açılı çizgide oka göre)
    var entryDirectionText: String {
        profile.countLine == nil ? "\(profile.direction.arrow) \(profile.direction.title.lowercased())" : "çizgideki ok yönünde"
    }

    /// Personel rengi öğretme: bir sonraki karede bu normalize noktadaki kişinin gövde rengi alınır
    func teachStaffColor(at p: CGPoint) {
        teachingStaff = false
        processor.teachStaffColor(at: p)
    }

    /// Öğretilmiş personel renklerinden birini siler; sonuncusu silinince alan yazılmaz (sözleşme: boş dizi yok)
    func removeStaffColor(at i: Int) {
        guard var colors = profile.staffColors, colors.indices.contains(i) else { return }
        colors.remove(at: i)
        profile.staffColors = colors.isEmpty ? nil : colors
    }

    func saveCalibration() {
        autoProductLength = false            // kullanıcı kaydetti: boy artık profilin
        processor.cancelCalibration()
        store.update(profile)
        finishCalibration()
    }

    func cancelCalibration() {
        processor.cancelCalibration()
        profile = store.selectedProfile
        finishCalibration()
    }

    private func finishCalibration() {
        isCalibrating = false
        teachingStaff = false
        processor.setShowMask(settings.showMask)
        processor.resetTracking(resetBackground: false)
        if video != nil {
            processor.setCounting(true)      // video modunda sayım videoyla birlikte sürer
        } else if wasRunningBeforeCalibration {
            setRunning(true)
        }
    }

    private func handleCalibration(_ e: CalibrationEvent) {
        switch e {
        case .backgroundProgress(let p):
            calibrationMessage = "Boş bant öğreniliyor… %\(Int(p * 100))"
        case .backgroundDone(let th):
            profile.diffThreshold = th
            calibrationMessage = "Arka plan hazır (eşik \(th)). Şimdi örnek ürün geçir."
        case .sampleProgress(let done, let target):
            calibrationMessage = "Ürünleri TEK TEK ve aralıklı geçir: \(done)/\(target)"
        case .sampleDone(let area):
            profile.expectedArea = area
            calibrationMessage = "Ürün boyutu öğrenildi. Kontrol edip Kaydet'e bas."
        case .backgroundRejected:
            calibrationMessage = "Boş bant öğrenilemedi: bantta ürün ya da hareket vardı. Eşik değiştirilmedi; "
                + "bant boşken tekrar dene."
        case .lengthDone(let len):
            profile.productLength = len
            calibrationMessage = String(format: "Ürün boyu öğrenildi (alanın %%%.0f'i). Kontrol edip Kaydet'e bas.",
                                        len * 100)
        }
    }

    // MARK: - Video

    /// Videoyu açar, kamerayı durdurur ve baştan oynatır.
    func openVideo(url: URL) async throws {
        let source = try await VideoFileSource.open(url: url)
        if let old = videoSource {
            old.stop()
            if old.url != url { Self.removeIfTemporaryCopy(old.url) }
        }
        if video == nil {
            liveTotal = total
            liveTotalOut = totalOut
            liveStaffIn = staffIn
            liveStaffOut = staffOut
        }
        camera.stop()
        stopNetwork()
        if isCalibrating { cancelCalibration() }
        source.speed = videoSpeed
        videoSource = source
        video = VideoRun(name: url.lastPathComponent, duration: source.info.duration)
        processor.setEmitFrameImages(true)
        processor.setCounting(true)
        restoreAutoProductLength()
        if profile.mode == .linescan && profile.lineProductLength <= 0 {
            // Şerit tarama: ürün boyunu oynatmadan önce hızlı bir taramayla öğren; böylece sayılar videonun başından
            // itibaren tek tek (ürünün üstünde numarasıyla) gelir, öğrenme bitince topluca eklenmez. Yalnızca bu
            // video için: kayıtlı profil değişmez (Kaydet edilirse kalır).
            let p = profile
            let len = await Task.detached(priority: .userInitiated) {
                Self.prescanProductLength(source, profile: p)
            }.value
            if len > 0 && videoSource === source {
                profile.productLength = len
                autoProductLength = true
            }
        }
        seekVideo(to: 0)
    }

    /// Ön taramayla bulunan ürün boyunu geri al (başka video ya da canlı kaynak kendi boyunu öğrensin).
    private func restoreAutoProductLength() {
        guard autoProductLength else { return }
        autoProductLength = false
        profile.productLength = store.selectedProfile.productLength
    }

    nonisolated private static func prescanProductLength(_ source: VideoFileSource, profile: ProductProfile) -> Double {
        var p = profile
        p.productLength = 0
        let counter = LineScanCounter()
        try? source.scan(maxSeconds: 60) { pb in
            guard let g = GrayFrame.make(from: pb, targetWidth: p.processingWidth) else { return true }
            _ = counter.process(g, profile: p)
            return counter.productLength <= 0
        }
        if counter.productLength <= 0 { _ = counter.flush(profile: p) }
        return counter.productLength
    }

    /// Videonun `t` saniyesinden oynatır. Sayaç sıfırlanır; 0'dan başlıyorsa ve ayar açıksa arka plan
    /// ilk ~1 sn'den yeniden öğrenilir (§5). Ortadan başlıyorsa önceden öğrenilen arka plan korunur.
    func seekVideo(to t: Double) {
        guard let source = videoSource, video != nil else { return }
        let target = max(0, min(t, source.info.duration))
        let fromStart = target < 0.05
        clearInspections()
        total = 0
        totalOut = 0
        processor.setTotals(in: 0, out: 0)
        staffIn = 0
        staffOut = 0
        processor.setStaffTotals(in: 0, out: 0)
        processor.resetClock()
        processor.resetTracking(resetBackground: fromStart)
        if fromStart && videoLearnBackground && !isCalibrating && profile.mode == .blob {
            // Yalnızca arka plan görüntüsü; Kaydet edilmiş eşik korunur (eskiden ürünle başlayan videoda 100'e kaçıyordu)
            processor.startBackgroundLearning(updateThreshold: false)
        }
        video?.position = target
        video?.countFrom = target
        video?.finished = false
        video?.playing = true
        video?.error = nil

        let processor = self.processor
        // ViewModel uygulama boyunca yaşar; bildirimler için güçlü referans güvenli (ve Sendable).
        videoGeneration = source.play(
            from: target, processingQueue: processor.queue,
            onFrame: { pb, ts in processor.process(pb, ts: ts) },
            onPosition: { [self] pos in
                Task { @MainActor in self.videoPositionChanged(pos, source: source) }
            },
            onEnd: { [self] g, error in
                let message = error?.localizedDescription
                Task { @MainActor in self.videoEnded(generation: g, source: source, error: message) }
            })
    }

    func toggleVideoPlayback() {
        guard let source = videoSource, let run = video else { return }
        if run.finished {
            seekVideo(to: 0)
            return
        }
        source.isPaused = run.playing
        video?.playing = !run.playing
    }

    /// Video modundan çık, canlı kameraya ve önceki oturum sayısına dön.
    func exitVideo() {
        restoreAutoProductLength()
        if let source = videoSource {
            source.stop()
            Self.removeIfTemporaryCopy(source.url)
        }
        videoSource = nil
        video = nil
        if isCalibrating { cancelCalibration() }
        processor.setEmitFrameImages(false)
        frameImage = nil
        processor.resetClock()
        processor.resetTracking(resetBackground: true)
        clearInspections()
        total = liveTotal
        totalOut = liveTotalOut
        processor.setTotals(in: liveTotal, out: liveTotalOut)
        staffIn = liveStaffIn
        staffOut = liveStaffOut
        processor.setStaffTotals(in: liveStaffIn, out: liveStaffOut)
        processor.setCounting(isRunning)
        startCamera()
    }

    /// Yalnızca uygulamanın seçim sırasında oluşturduğu geçici kopyaları sil (kullanıcının dosyasını asla).
    private static func removeIfTemporaryCopy(_ url: URL) {
        let tmp = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().path
        guard url.resolvingSymlinksInPath().path.hasPrefix(tmp) else { return }
        try? FileManager.default.removeItem(at: url)
    }

    #if DEBUG || UITEST
    /// UI testi: kamera izni istemeden verilen videoyu yumurta profiliyle en hızlı modda sayar.
    func runUITestVideo(path: String, expectedArea: Double?) {
        if let area = expectedArea { profile.expectedArea = area }
        videoSpeed = 0
        videoLearnBackground = true
        Task {
            do {
                try await openVideo(url: URL(fileURLWithPath: path))
            } catch {
                testHookError = "Test videosu açılamadı: \(error.localizedDescription)"
            }
        }
    }

    /// UI testi: ağ kamerasından (RTSP) yumurta profiliyle sayım; yayın bitince yeniden bağlanmaz.
    func runUITestNetwork(url: String, username: String, password: String, expectedArea: Double?) {
        if let area = expectedArea { profile.expectedArea = area }
        networkReconnect = false
        var config = NetworkCameraConfig()
        config.brand = .custom
        config.customURL = url
        config.username = username
        networkConfig = config
        networkPasswords[.camera] = password
        let status = CameraCredentialStore.setPassword(password, for: .camera)
        if status != errSecSuccess { testHookError = "Keychain kaydı başarısız (durum \(status))" }
        sourceKind = .network
        startNetwork()
        processor.startBackgroundLearning()          // klip boş bantla başlar (§5)
        setRunning(true)
    }

    /// UI testi (ayar ekranları): önceki testten kalan ağ ayarı ve şifreler silinir, kamera açılmaz.
    func prepareUITestForms() {
        networkReconnect = true                           // gerçek kullanım gibi: koparsa yeniden bağlanır
        networkPasswords = [:]
        networkConfig = NetworkCameraConfig()
        networkConfig.save()
        sourceKind = .phone                               // kaydedince ağ kaynağına geçiş de sınansın
        UserDefaults.standard.set(VideoSourceKind.phone.rawValue, forKey: "bs.source")
        for kind in NetworkDeviceKind.allCases { CameraCredentialStore.setPassword("", for: kind) }
    }

    /// UI testi teşhisi: ağ kaynağı ve kapı sayaçları
    var networkDebugText: String {
        guard let networkSource else { return "" }
        return networkSource.decoder.statsText + " · " + frameGate.statsText
    }

    /// UI testinde video açılamazsa ekranda gösterilir (teşhis için).
    @Published var testHookError: String?
    #endif

    private func videoPositionChanged(_ pos: Double, source: VideoFileSource) {
        guard videoSource === source, video?.finished == false else { return }
        video?.position = pos
    }

    private func videoEnded(generation g: Int, source: VideoFileSource, error: String?) {
        guard videoSource === source, g == videoGeneration else { return }   // yerine yenisi başladı
        video?.finished = true
        video?.playing = false
        video?.error = error
        if error == nil {
            video?.position = source.info.duration
            processor.finishVideo()          // şerit tarama: son karede yarım kalan ürünler (§4.9)
        }
    }

    // MARK: - Ağ kamerası

    /// Kaynağı değiştirir; video modundaysa seçim kaydedilir, videodan çıkınca uygulanır.
    func setSource(_ kind: VideoSourceKind) {
        guard kind != sourceKind else { return }
        sourceKind = kind
        UserDefaults.standard.set(kind.rawValue, forKey: "bs.source")
        guard !isVideoMode else { return }
        if isCalibrating { cancelCalibration() }
        if kind == .phone {
            stopNetwork()
            processor.setEmitFrameImages(false)
            frameImage = nil
            processor.resetClock()
            processor.resetTracking(resetBackground: true)
        } else {
            camera.stop()
        }
        startCamera()
    }

    /// Ayarları ve şifreyi kaydeder; ağ kamerası seçiliyse yeni ayarlarla yeniden bağlanır.
    /// Dönüş: şifre güvenli depoya (Keychain) yazılamadıysa kullanıcıya gösterilecek uyarı.
    @discardableResult
    func saveNetworkConfig(_ config: NetworkCameraConfig, password: String) -> String? {
        networkConfig = config
        config.save()
        networkPasswords[config.kind] = password
        let status = CameraCredentialStore.setPassword(password, for: config.kind)
        if sourceKind == .network && !isVideoMode { startNetwork() }
        return status == errSecSuccess ? nil
            : "Şifre güvenli depoya kaydedilemedi (kod \(status)). Bu oturumda kullanılır; uygulama yeniden açılınca tekrar girmen gerekebilir."
    }

    /// Kayıtlı şifre: önce bu oturumda girilen, yoksa Keychain
    func storedPassword(for kind: NetworkDeviceKind) -> String {
        networkPasswords[kind] ?? CameraCredentialStore.password(for: kind)
    }

    private func startNetwork() {
        stopNetwork()
        camera.stop()
        guard let plan = NetworkStreamPlan.make(networkConfig, password: storedPassword(for: networkConfig.kind)) else {
            networkState = .ended("Ağ kamerası ayarlanmadı (Ayarlar → Görüntü kaynağı)")
            return
        }
        processor.resetClock()
        processor.resetTracking(resetBackground: true)
        processor.setEmitFrameImages(true)
        frameImage = nil
        let source = plan.makeSource()
        source.reconnect = networkReconnect
        let processor = self.processor
        let gate = frameGate
        source.onFrame = { pb, ts in gate.submit(pb, ts: ts, to: processor) }
        // ViewModel uygulama boyunca yaşar; durum bildirimi için güçlü referans güvenli (ve Sendable)
        source.onState = { [self] state in
            Task { @MainActor in self.networkStateChanged(state, source: source) }
        }
        networkSource = source
        networkState = .connecting
        source.start()
    }

    private func stopNetwork() {
        networkSource?.stop()
        networkSource = nil
        networkState = nil
    }

    private func networkStateChanged(_ state: NetworkCameraState, source: NetworkCameraSource) {
        guard networkSource === source else { return }
        networkState = state
    }

    // MARK: - Kalite kontrol

    private func handleCrop(_ crop: CountCrop) {
        let judge = teach.enabled && teach.isReady
        var record = InspectionRecord(trackId: crop.trackId, delta: crop.delta, time: crop.time, jpeg: crop.jpeg,
                                      countLabel: crop.label)
        record.pending = judge
        inspections.insert(record, at: 0)
        if inspections.count > InspectionLog.capacity { inspections.removeLast(inspections.count - InspectionLog.capacity) }
        inspectionStats.counted += crop.delta
        guard judge else {
            inspectionStats.unknown += crop.delta
            return
        }
        let id = record.id
        teach.classifier.classify(jpeg: crop.jpeg) { [self] verdict in
            Task { @MainActor in self.applyVerdict(verdict, to: id, delta: crop.delta) }
        }
    }

    private func applyVerdict(_ verdict: AppearanceVerdict?, to id: UUID, delta: Int) {
        if let v = verdict {
            if v.pass { inspectionStats.pass += delta } else { inspectionStats.fail += delta }
        } else {
            inspectionStats.unknown += delta
        }
        guard let i = inspections.firstIndex(where: { $0.id == id }) else { return }   // sıfırlandı
        inspections[i].verdict = verdict
        inspections[i].pending = false
        if let v = verdict {
            trackVerdicts[inspections[i].trackId] = v
            if trackVerdicts.count > 2 * InspectionLog.capacity {      // yalnızca son kartlarınkini tut
                trackVerdicts = Dictionary(inspections.compactMap { r in r.verdict.map { (r.trackId, $0) } },
                                           uniquingKeysWith: { a, _ in a })
            }
        }
    }

    /// Karttaki ürünü örnek olarak öğret ("İyi" ya da kusur adı).
    func teachExample(_ record: InspectionRecord, as label: String) {
        teach.addExample(jpeg: record.jpeg, label: label)
    }

    private func clearInspections() {
        inspections.removeAll()
        inspectionStats = InspectionStats()
        trackVerdicts.removeAll()
    }

    // MARK: - Profiller

    func selectProfile(_ id: UUID) {
        store.select(id)
        profile = store.selectedProfile
        teach.load(profileID: profile.id)
        logger.profileName = profile.name
        processor.resetTracking(resetBackground: true)
    }

    func saveEditedProfile(_ p: ProductProfile) {
        store.update(p)
        if p.id == profile.id {
            profile = p
            logger.profileName = p.name
        }
    }

    func duplicateProfile(_ p: ProductProfile) {
        var copy = p
        copy.id = UUID()
        copy.name = p.name + " (kopya)"
        store.add(copy)
    }

    func deleteProfile(_ id: UUID) {
        let wasSelected = id == store.selectedID
        store.delete(id)
        if !store.profiles.contains(where: { $0.id == id }) { TeachStore.deleteData(profileID: id) }
        if wasSelected { selectProfile(store.selectedID) }
    }
}
