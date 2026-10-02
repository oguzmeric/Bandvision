import AVFoundation
import CoreVideo
import QuartzCore

/// Video dosyasını kare kare okuyup kamera yerine işleme hattına verir (manuel test, masa başı kalibrasyon).
/// Oynatıcı gibi davranır: istenen saniyeden oynat, duraklat, hız değiştir.
///
/// - Kareler kamerayla aynı biçimde (420f, tam aralık) gelir; videonun yönü (`preferredTransform`, ör. telefonla
///   dik çekim) video kompozisyonuyla uygulanır, yani işlenen kare ekranda göründüğü gibidir.
/// - Okuma kendi kuyruğunda yapılır; her kare `processingQueue.sync` ile işlenir. Böylece kalibrasyon gibi
///   komutlar kareler arasında araya girebilir.
/// - Her `play(from:)` yeni bir "nesil" başlatır: önceki okuma döngüsü bir sonraki karede durur ve bitiş
///   bildirmez. AVAssetReader yeniden kullanılamadığı için her oynatma kendi okuyucusunu kurar.
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

    let url: URL
    let info: Info
    private let asset: AVURLAsset
    private let track: AVAssetTrack
    private let composition: AVVideoComposition

    private let readQueue = DispatchQueue(label: "bantsayac.video", qos: .userInitiated)
    private let lock = NSLock()
    private var generation = 0
    private var pausedValue = false
    private var speedValue = 1.0

    private init(url: URL, asset: AVURLAsset, track: AVAssetTrack, composition: AVVideoComposition, info: Info) {
        self.url = url
        self.asset = asset
        self.track = track
        self.composition = composition
        self.info = info
    }

    /// Videoyu açar ve meta verisini okur (oynatmaya başlamaz).
    static func open(url: URL) async throws -> VideoFileSource {
        let asset = AVURLAsset(url: url)
        guard let track = try await asset.loadTracks(withMediaType: .video).first else { throw Failure.noVideoTrack }
        let duration = try await asset.load(.duration).seconds
        let fps = Double(try await track.load(.nominalFrameRate))
        let composition = try await AVMutableVideoComposition.videoComposition(withPropertiesOf: asset)
        let info = Info(duration: duration.isFinite ? duration : 0, fps: fps, size: composition.renderSize)
        return VideoFileSource(url: url, asset: asset, track: track, composition: composition, info: info)
    }

    var speed: Double {
        get { lock.lock(); defer { lock.unlock() }; return speedValue }
        set { lock.lock(); speedValue = newValue; lock.unlock() }
    }

    var isPaused: Bool {
        get { lock.lock(); defer { lock.unlock() }; return pausedValue }
        set { lock.lock(); pausedValue = newValue; lock.unlock() }
    }

    /// Okumayı durdurur (bitiş bildirilmez).
    func stop() {
        lock.lock(); generation += 1; lock.unlock()
    }

    private func isCurrent(_ g: Int) -> Bool {
        lock.lock(); defer { lock.unlock() }; return generation == g
    }

    /// `start` saniyesinden okumaya başlar; önceki okuma durur. Nesil numarasını döndürür.
    /// - onFrame: processingQueue üzerinde çağrılır.
    /// - onPosition: videodaki konum (sn), okuma kuyruğunda.
    /// - onEnd: video sona erdiğinde ya da hata olduğunda (bu nesil hâlâ geçerliyse), okuma kuyruğunda.
    @discardableResult
    func play(from start: Double, processingQueue: DispatchQueue,
              onFrame: @escaping @Sendable (CVPixelBuffer, Double) -> Void,
              onPosition: @escaping @Sendable (Double) -> Void,
              onEnd: @escaping @Sendable (Int, Error?) -> Void) -> Int {
        lock.lock()
        generation += 1
        let g = generation
        pausedValue = false
        lock.unlock()

        readQueue.async { [self] in
            guard isCurrent(g) else { return }
            do {
                try readLoop(generation: g, from: start, processingQueue: processingQueue,
                             onFrame: onFrame, onPosition: onPosition)
                if isCurrent(g) { onEnd(g, nil) }
            } catch {
                if isCurrent(g) { onEnd(g, error) }
            }
        }
        return g
    }

    private func readLoop(generation g: Int, from start: Double, processingQueue: DispatchQueue,
                          onFrame: @Sendable (CVPixelBuffer, Double) -> Void,
                          onPosition: @Sendable (Double) -> Void) throws {
        let reader: AVAssetReader
        do { reader = try AVAssetReader(asset: asset) } catch { throw Failure.cannotRead(error.localizedDescription) }
        let begin = max(0, min(start, info.duration))
        if begin > 0 {
            reader.timeRange = CMTimeRange(start: CMTime(seconds: begin, preferredTimescale: 600),
                                           duration: .positiveInfinity)
        }
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
        defer { if reader.status == .reading { reader.cancelReading() } }

        var wallStart: CFTimeInterval?
        var videoStart = 0.0
        var lastReported = -1.0
        while isCurrent(g) {
            if isPaused {
                wallStart = nil                         // devam edince saat yeniden eşlenir
                Thread.sleep(forTimeInterval: 0.05)
                continue
            }
            guard let sample = output.copyNextSampleBuffer() else { break }
            guard let pb = CMSampleBufferGetImageBuffer(sample) else { continue }
            let ts = CMSampleBufferGetPresentationTimeStamp(sample).seconds

            // Hız: videonun zamanını duvar saatiyle eşle (hız değişince ya da geride kalınca yeniden eşle)
            let speed = self.speed
            if speed > 0 {
                let now = CACurrentMediaTime()
                if wallStart == nil { wallStart = now; videoStart = ts }
                let due = wallStart! + (ts - videoStart) / speed
                if due > now { Thread.sleep(forTimeInterval: min(due - now, 0.5)) }
                if now - due > 1.0 { wallStart = now; videoStart = ts }
            } else {
                wallStart = nil
            }

            guard isCurrent(g) else { break }
            processingQueue.sync { onFrame(pb, ts) }

            if abs(ts - lastReported) >= 0.1 {
                lastReported = ts
                onPosition(ts)
            }
        }
        if isCurrent(g) {
            if reader.status == .failed {
                throw Failure.cannotRead(reader.error?.localizedDescription ?? "okuma hatası")
            }
            onPosition(info.duration)
        }
    }
}
