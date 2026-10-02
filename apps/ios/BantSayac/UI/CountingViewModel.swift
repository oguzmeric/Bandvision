import Foundation
import SwiftUI
import Combine

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
    @Published var profile: ProductProfile {
        didSet { processor.setProfile(profile) }
    }
    @Published private(set) var total = 0
    @Published private(set) var snapshot: EngineSnapshot = .empty
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

    // Kalite kontrol (A aşaması): son ürün kartları ve örnekle öğretme
    @Published private(set) var inspections: [InspectionRecord] = []
    @Published private(set) var inspectionStats = InspectionStats()
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
        processor.setTotal(total)
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
        processor.onSnapshot = { [weak self] snap in
            self?.snapshot = snap
        }
        processor.onCalibration = { [weak self] event in
            self?.handleCalibration(event)
        }
        processor.onCrop = { [weak self] crop in
            self?.handleCrop(crop)
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

    func startCamera() {
        camera.requestAccess { [weak self] granted in
            guard let self else { return }
            guard granted else {
                self.cameraError = "Kamera izni yok. Ayarlar > Bant Sayaç > Kamera'dan izin verin."
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
        processor.setTotal(0)
        processor.resetTracking(resetBackground: false)
        logger.resetSession()
    }

    // MARK: - Kalibrasyon

    func beginCalibration() {
        wasRunningBeforeCalibration = isRunning
        setRunning(false)
        isCalibrating = true
        calibrationMessage = "Sarı alanı ve turuncu çizgiyi ayarla, sonra boş bandı öğret."
        processor.setShowMask(true)
    }

    func learnBackground() {
        calibrationMessage = "Boş bant öğreniliyor… Bantta ürün olmasın."
        processor.startBackgroundLearning()
    }

    func learnSample() {
        calibrationMessage = "Ürünleri TEK TEK ve aralıklı geçir: 0/8"
        processor.startSampleLearning(target: 8)
    }

    func saveCalibration() {
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
        }
    }

    // MARK: - Video

    /// Videoyu açar, kamerayı durdurur ve baştan oynatır.
    func openVideo(url: URL) async throws {
        let source = try await VideoFileSource.open(url: url)
        if let old = videoSource {
            old.stop()
            if old.url != url { try? FileManager.default.removeItem(at: old.url) }
        }
        if video == nil { liveTotal = total }
        camera.stop()
        if isCalibrating { cancelCalibration() }
        source.speed = videoSpeed
        videoSource = source
        video = VideoRun(name: url.lastPathComponent, duration: source.info.duration)
        processor.setEmitFrameImages(true)
        processor.setCounting(true)
        seekVideo(to: 0)
    }

    /// Videonun `t` saniyesinden oynatır. Sayaç sıfırlanır; 0'dan başlıyorsa ve ayar açıksa arka plan
    /// ilk ~1 sn'den yeniden öğrenilir (§5). Ortadan başlıyorsa önceden öğrenilen arka plan korunur.
    func seekVideo(to t: Double) {
        guard let source = videoSource, video != nil else { return }
        let target = max(0, min(t, source.info.duration))
        let fromStart = target < 0.05
        clearInspections()
        total = 0
        processor.setTotal(0)
        processor.resetClock()
        processor.resetTracking(resetBackground: fromStart)
        if fromStart && videoLearnBackground && !isCalibrating {
            processor.startBackgroundLearning()
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
        if let source = videoSource {
            source.stop()
            try? FileManager.default.removeItem(at: source.url)
        }
        videoSource = nil
        video = nil
        if isCalibrating { cancelCalibration() }
        processor.setEmitFrameImages(false)
        processor.resetClock()
        processor.resetTracking(resetBackground: true)
        clearInspections()
        total = liveTotal
        processor.setTotal(liveTotal)
        processor.setCounting(isRunning)
        startCamera()
    }

    private func videoPositionChanged(_ pos: Double, source: VideoFileSource) {
        guard videoSource === source, video?.finished == false else { return }
        video?.position = pos
    }

    private func videoEnded(generation g: Int, source: VideoFileSource, error: String?) {
        guard videoSource === source, g == videoGeneration else { return }   // yerine yenisi başladı
        video?.finished = true
        video?.playing = false
        video?.error = error
        if error == nil { video?.position = source.info.duration }
    }

    // MARK: - Kalite kontrol

    private func handleCrop(_ crop: CountCrop) {
        let judge = teach.enabled && teach.isReady
        var record = InspectionRecord(trackId: crop.trackId, delta: crop.delta, time: crop.time, jpeg: crop.jpeg)
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
    }

    /// Karttaki ürünü örnek olarak öğret ("İyi" ya da kusur adı).
    func teachExample(_ record: InspectionRecord, as label: String) {
        teach.addExample(jpeg: record.jpeg, label: label)
    }

    private func clearInspections() {
        inspections.removeAll()
        inspectionStats = InspectionStats()
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
        if wasSelected { selectProfile(store.selectedID) }
    }
}
