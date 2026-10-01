import AVFoundation
import CoreVideo

/// Video dosyasını kare kare okuyup kamera yerine işleme hattına verir (manuel test, masa başı kalibrasyon).
///
/// - Kareler kamerayla aynı biçimde (420f, tam aralık) gelir; videonun yönü (`preferredTransform`, ör. telefonla
///   dik çekim) video kompozisyonuyla uygulanır, yani işlenen kare ekranda göründüğü gibidir.
/// - Okuma kendi kuyruğunda yapılır; her kare `processingQueue.sync` ile işlenir. Böylece kalibrasyon gibi
///   komutlar kareler arasında araya girebilir.
/// - `speed`: 1 = gerçek zamanlı, 2 = iki kat, 0 = olabildiğince hızlı. Zaman damgası her durumda videonunkidir.
final class VideoFileSource: @unchecked Sendable {
    struct Info: Sendable {
        let duration: Double
        let fps: Double
        let size: CGSize
    }

    enum Failure: LocalizedError {
        case noVideoTrack
        case cannotRead(String)

        var errorDescription: String? {
            switch self {
            case .noVideoTrack: return "Dosyada video bulunamadı."
            case .cannotRead(let why): return "Video okunamadı: \(why)"
            }
        }
    }

    private let readQueue = DispatchQueue(label: "bantsayac.video", qos: .userInitiated)
    private let lock = NSLock()
    private var cancelled = false
    private var speedValue = 1.0

    var speed: Double {
        get { lock.lock(); defer { lock.unlock() }; return speedValue }
        set { lock.lock(); speedValue = newValue; lock.unlock() }
    }

    func cancel() {
        lock.lock(); cancelled = true; lock.unlock()
    }

    private var isCancelled: Bool {
        lock.lock(); defer { lock.unlock() }; return cancelled
    }

    /// Videoyu sonuna kadar (ya da iptal edilene kadar) okur. Tamamlanınca döner.
    /// - onFrame: processingQueue üzerinde çağrılır.
    /// - onProgress: 0...1, okuma kuyruğunda çağrılır (ana kuyruğa aktarmak çağıranın işi).
    func run(url: URL, processingQueue: DispatchQueue,
             onFrame: @escaping @Sendable (CVPixelBuffer, Double) -> Void,
             onProgress: @escaping @Sendable (Double) -> Void) async throws -> Info {
        let asset = AVURLAsset(url: url)
        guard let track = try await asset.loadTracks(withMediaType: .video).first else { throw Failure.noVideoTrack }
        let duration = try await asset.load(.duration).seconds
        let fps = Double(try await track.load(.nominalFrameRate))
        let composition = try await AVMutableVideoComposition.videoComposition(withPropertiesOf: asset)
        let info = Info(duration: duration, fps: fps, size: composition.renderSize)

        let reader: AVAssetReader
        do { reader = try AVAssetReader(asset: asset) } catch { throw Failure.cannotRead(error.localizedDescription) }
        let output = AVAssetReaderVideoCompositionOutput(
            videoTracks: [track],
            videoSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarFullRange])
        output.videoComposition = composition
        output.alwaysCopiesSampleData = false
        guard reader.canAdd(output) else { throw Failure.cannotRead("çıkış eklenemedi") }
        reader.add(output)
        guard reader.startReading() else {
            throw Failure.cannotRead(reader.error?.localizedDescription ?? "bilinmeyen hata")
        }

        let job = ReadJob(reader: reader, output: output, duration: duration, source: self,
                          processingQueue: processingQueue, onFrame: onFrame, onProgress: onProgress)
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            readQueue.async {
                do { try job.loop(); cont.resume() } catch { cont.resume(throwing: error) }
            }
        }
        return info
    }

    /// Okuma döngüsü; AVFoundation nesneleri yalnızca okuma kuyruğunda kullanılır.
    private final class ReadJob: @unchecked Sendable {
        let reader: AVAssetReader
        let output: AVAssetReaderVideoCompositionOutput
        let duration: Double
        unowned let source: VideoFileSource
        let processingQueue: DispatchQueue
        let onFrame: @Sendable (CVPixelBuffer, Double) -> Void
        let onProgress: @Sendable (Double) -> Void

        init(reader: AVAssetReader, output: AVAssetReaderVideoCompositionOutput, duration: Double,
             source: VideoFileSource, processingQueue: DispatchQueue,
             onFrame: @escaping @Sendable (CVPixelBuffer, Double) -> Void,
             onProgress: @escaping @Sendable (Double) -> Void) {
            self.reader = reader
            self.output = output
            self.duration = duration
            self.source = source
            self.processingQueue = processingQueue
            self.onFrame = onFrame
            self.onProgress = onProgress
        }

        func loop() throws {
            var wallStart: CFTimeInterval?
            var videoStart = 0.0
            var lastProgress = -1.0
            while !source.isCancelled, let sample = output.copyNextSampleBuffer() {
                guard let pb = CMSampleBufferGetImageBuffer(sample) else { continue }
                let ts = CMSampleBufferGetPresentationTimeStamp(sample).seconds

                // Hız: videonun zamanını duvar saatiyle eşle (hız değişince yeniden eşle)
                let speed = source.speed
                if speed > 0 {
                    let now = CACurrentMediaTime()
                    if wallStart == nil { wallStart = now; videoStart = ts }
                    let due = wallStart! + (ts - videoStart) / speed
                    if due > now { Thread.sleep(forTimeInterval: min(due - now, 0.5)) }
                    if now - due > 1.0 { wallStart = now; videoStart = ts }   // geride kaldıysak yakalamaya çalışma
                } else {
                    wallStart = nil
                }

                processingQueue.sync { onFrame(pb, ts) }

                let progress = duration > 0 ? min(1, ts / duration) : 0
                if progress - lastProgress >= 0.01 {
                    lastProgress = progress
                    onProgress(progress)
                }
            }
            if source.isCancelled {
                reader.cancelReading()
            } else if reader.status == .failed {
                throw Failure.cannotRead(reader.error?.localizedDescription ?? "okuma hatası")
            }
            onProgress(1)
        }
    }
}
