import AVFoundation
import CoreVideo

/// Arka kamerayı 720p / 60 fps'te açar, kareleri işleme kuyruğuna verir.
/// Kareler donanımda portreye döndürülür (videoRotationAngle = 90).
final class CameraManager: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate, @unchecked Sendable {
    let session = AVCaptureSession()
    let processingQueue = DispatchQueue(label: "bantsayac.processing", qos: .userInitiated)
    private let sessionQueue = DispatchQueue(label: "bantsayac.session")
    private let output = AVCaptureVideoDataOutput()
    private var device: AVCaptureDevice?
    private var configured = false

    /// processingQueue üzerinde çağrılır: (kare, sunum zamanı sn).
    var frameHandler: ((CVPixelBuffer, Double) -> Void)?

    /// completion ana kuyrukta çağrılır.
    func requestAccess(_ completion: @escaping @MainActor @Sendable (Bool) -> Void) {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            DispatchQueue.main.async { completion(true) }
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { ok in
                DispatchQueue.main.async { completion(ok) }
            }
        default:
            DispatchQueue.main.async { completion(false) }
        }
    }

    /// completion ana kuyrukta çağrılır.
    func configureAndStart(_ completion: @escaping @MainActor @Sendable (Bool) -> Void) {
        sessionQueue.async {
            let ok = self.configured || self.configure()
            if ok && !self.session.isRunning { self.session.startRunning() }
            DispatchQueue.main.async { completion(ok) }
        }
    }

    func stop() {
        sessionQueue.async {
            if self.session.isRunning { self.session.stopRunning() }
        }
    }

    // MARK: - Ayarlar

    func setTorch(level: Float) {
        withDevice { d in
            guard d.hasTorch else { return }
            if level <= 0.01 {
                if d.isTorchModeSupported(.off) { d.torchMode = .off }
            } else {
                try? d.setTorchModeOn(level: min(level, AVCaptureDevice.maxAvailableTorchLevel))
            }
        }
    }

    /// denominator <= 0 → otomatik pozlama. Aksi halde 1/denominator saniye, ISO telafi edilir.
    func setShutter(denominator: Int) {
        withDevice { d in
            if denominator <= 0 {
                if d.isExposureModeSupported(.continuousAutoExposure) {
                    d.exposureMode = .continuousAutoExposure
                }
                return
            }
            guard d.isExposureModeSupported(.custom) else { return }
            let fmt = d.activeFormat
            let wanted = CMTime(value: 1, timescale: CMTimeScale(denominator))
            let dur = CMTimeMaximum(fmt.minExposureDuration, CMTimeMinimum(fmt.maxExposureDuration, wanted))
            let currentSeconds = max(d.exposureDuration.seconds, 1.0 / 10000)
            var iso = d.iso * Float(currentSeconds / dur.seconds)
            iso = min(fmt.maxISO, max(fmt.minISO, iso))
            d.setExposureModeCustom(duration: dur, iso: iso, completionHandler: nil)
        }
    }

    func setFocusLocked(_ locked: Bool) {
        withDevice { d in
            if locked, d.isFocusModeSupported(.locked) {
                d.focusMode = .locked
            } else if d.isFocusModeSupported(.continuousAutoFocus) {
                d.focusMode = .continuousAutoFocus
            }
        }
    }

    // MARK: - Delegate

    func captureOutput(_ output: AVCaptureOutput,
                       didOutput sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        guard let pb = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        frameHandler?(pb, CMSampleBufferGetPresentationTimeStamp(sampleBuffer).seconds)
    }

    // MARK: - Kurulum

    private func withDevice(_ body: @escaping @Sendable (AVCaptureDevice) -> Void) {
        sessionQueue.async {
            guard let d = self.device else { return }
            do {
                try d.lockForConfiguration()
                body(d)
                d.unlockForConfiguration()
            } catch { }
        }
    }

    private func configure() -> Bool {
        session.beginConfiguration()
        defer { session.commitConfiguration() }

        guard let dev = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
              let input = try? AVCaptureDeviceInput(device: dev),
              session.canAddInput(input) else { return false }
        session.addInput(input)

        output.videoSettings = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarFullRange
        ]
        output.alwaysDiscardsLateVideoFrames = true
        output.setSampleBufferDelegate(self, queue: processingQueue)
        guard session.canAddOutput(output) else { return false }
        session.addOutput(output)

        if let c = output.connection(with: .video), c.isVideoRotationAngleSupported(90) {
            c.videoRotationAngle = 90
        }

        device = dev
        configureFormat(dev)
        configured = true
        return true
    }

    /// 1280x720 format seç; 60 fps destekleyenlerden en "sade" olanı (yüksek hızlı/binned formatlardan kaçın).
    private func configureFormat(_ d: AVCaptureDevice) {
        func maxFPS(_ f: AVCaptureDevice.Format) -> Double {
            f.videoSupportedFrameRateRanges.map { $0.maxFrameRate }.max() ?? 0
        }
        let hd = d.formats.filter {
            let dim = CMVideoFormatDescriptionGetDimensions($0.formatDescription)
            return dim.width == 1280 && dim.height == 720
        }
        let preferred = hd.filter { maxFPS($0) >= 60 }.min { maxFPS($0) < maxFPS($1) }
            ?? hd.max { maxFPS($0) < maxFPS($1) }

        guard let fmt = preferred else {
            if session.canSetSessionPreset(.hd1280x720) { session.sessionPreset = .hd1280x720 }
            return
        }
        let fps = Int32(min(60, maxFPS(fmt)))
        do {
            try d.lockForConfiguration()
            d.activeFormat = fmt
            let dur = CMTime(value: 1, timescale: fps)
            d.activeVideoMinFrameDuration = dur
            d.activeVideoMaxFrameDuration = dur
            if d.isFocusModeSupported(.continuousAutoFocus) { d.focusMode = .continuousAutoFocus }
            d.unlockForConfiguration()
        } catch { }
    }
}
