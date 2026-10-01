import Foundation
import SwiftUI
import Combine

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

    let camera: CameraManager
    let processor: FrameProcessor
    let store: ProfileStore
    let settings: AppSettings
    let logger: CountLogger

    private var wasRunningBeforeCalibration = false
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
            self.logger.record(delta: delta, total: total)
        }
        processor.onSnapshot = { [weak self] snap in
            self?.snapshot = snap
        }
        processor.onCalibration = { [weak self] event in
            self?.handleCalibration(event)
        }
        camera.frameHandler = processor.process

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
        if wasRunningBeforeCalibration { setRunning(true) }
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

    // MARK: - Profiller

    func selectProfile(_ id: UUID) {
        store.select(id)
        profile = store.selectedProfile
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
