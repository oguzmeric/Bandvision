import Foundation
import CoreVideo
import CoreGraphics
import QuartzCore
import CoreImage
import ImageIO

struct EngineSnapshot {
    var frameSize: CGSize
    var blobs: [Blob]
    var tracks: [TrackMarker]
    var fps: Double
    var mask: CGImage?
    /// DEBUG: ortalama süreler (ms) — UI testi teşhisi için
    var perf: String = ""

    static var empty: EngineSnapshot {
        EngineSnapshot(frameSize: CGSize(width: 720, height: 1280),
                       blobs: [], tracks: [], fps: 0, mask: nil, perf: "")
    }
}

/// Çizgiyi ilk kez geçen ürünün tam çözünürlüklü kırpıntısı (kalite kontrol kartı için).
struct CountCrop: Sendable {
    let trackId: Int
    let delta: Int
    let time: Date
    /// JPEG, uzun kenar en fazla 256 px
    let jpeg: Data
}

/// Eşzamanlılık denetiminde Sendable olmayan bir değeri (CVPixelBuffer, CIContext) güvenle başka kuyruğa
/// taşımak için. Yalnızca değerin aynı anda tek kuyrukta kullanıldığı yerlerde.
struct UncheckedSendable<T>: @unchecked Sendable {
    let value: T
}

enum CalibrationEvent {
    case backgroundProgress(Double)
    case backgroundDone(threshold: Int)
    case sampleProgress(done: Int, target: Int)
    case sampleDone(expectedArea: Double)
}

/// Tüm görüntü işleme hattı. Durum yalnızca `queue` üzerinde değişir;
/// dışarıya sonuçlar ana kuyrukta callback ile verilir.
final class FrameProcessor: @unchecked Sendable {
    private enum CalibState {
        case none
        case background(frame: Int, maxDiff: Int)
        case sample(areas: [Double], target: Int)
    }

    let queue: DispatchQueue
    private let segmenter = BackgroundSegmenter()
    private let tracker = BlobTracker()
    private var profile = ProductProfile.generic()
    private var counting = false
    private var total = 0
    private var showMask = false
    private var calib: CalibState = .none

    /// Profil parametrelerinin tanımlı olduğu kare hızı (§7). F1.1'de ProductProfile'a `source.referenceFps` olarak girer.
    private let referenceFps = 60.0
    /// Kaynak kare zaman damgaları (son 2 sn): §7 ölçeklemesinde kullanılan gerçek fps.
    private var stamps: [Double] = []
    private var emitFrameImages = false
    private lazy var ciContext = CIContext()
    /// Ekran karesi ayrı kuyrukta üretilir: sayım hiçbir zaman ekranı beklemez. Kuyruk meşgulse kare atlanır.
    private let displayQueue = DispatchQueue(label: "bantsayac.display", qos: .userInitiated)
    private var displayBusy = false            // yalnızca `queue` üzerinde
    private var lastDisplay: CFTimeInterval = 0

    private var lastPublish: CFTimeInterval = 0
    // Ölçüm (üssel ortalama, ms)
    private var perfGap = 0.0, perfCore = 0.0, perfImage = 0.0
    private var perfLastEnd: CFTimeInterval = 0
    private var fpsWindowStart: CFTimeInterval = 0
    private var fpsFrames = 0
    private var fps: Double = 0

    // Hepsi ana kuyrukta çağrılır.
    var onSnapshot: (@MainActor (EngineSnapshot) -> Void)?
    var onCount: (@MainActor (_ delta: Int, _ total: Int) -> Void)?
    var onCrop: (@MainActor (CountCrop) -> Void)?
    var onCalibration: (@MainActor (CalibrationEvent) -> Void)?
    /// Video ve ağ kamerası modunda ekranda gösterilen kare (iPhone kamerasında önizleme katmanı kullanılır).
    var onFrameImage: (@MainActor (CGImage) -> Void)?

    init(queue: DispatchQueue) {
        self.queue = queue
    }

    // MARK: - Dışarıdan kontrol (thread-safe)

    func setProfile(_ p: ProductProfile) { queue.async { self.profile = p } }
    func setCounting(_ on: Bool) { queue.async { self.counting = on } }
    func setTotal(_ t: Int) { queue.async { self.total = t } }
    func setShowMask(_ on: Bool) { queue.async { self.showMask = on } }
    /// Video modunda işlenen kareyi de anlık görüntüyle yayınla.
    func setEmitFrameImages(_ on: Bool) { queue.async { self.emitFrameImages = on } }
    /// Kaynak değişti (kamera ↔ video): fps penceresini sıfırla.
    func resetClock() { queue.async { self.stamps.removeAll() } }

    func resetTracking(resetBackground: Bool) {
        queue.async {
            self.tracker.reset()
            if resetBackground { self.segmenter.reset() }
        }
    }

    func startBackgroundLearning() {
        queue.async {
            self.tracker.reset()
            self.calib = .background(frame: 0, maxDiff: 0)
        }
    }

    func startSampleLearning(target: Int) {
        queue.async {
            self.tracker.reset()
            self.calib = .sample(areas: [], target: target)
        }
    }

    func cancelCalibration() { queue.async { self.calib = .none } }

    // MARK: - Kare işleme (queue üzerinde)

    /// ts: kaynağın sunum zamanı (sn). Kamera ve video aynı yoldan gelir.
    func process(_ pixelBuffer: CVPixelBuffer, ts: Double) {
        guard let frame = GrayFrame.make(from: pixelBuffer, targetWidth: profile.processingWidth) else { return }
        process(gray: frame, ts: ts, pixelBuffer: pixelBuffer)
    }

    func process(gray frame: GrayFrame, ts: Double, pixelBuffer: CVPixelBuffer? = nil) {
        let start = CACurrentMediaTime()
        if perfLastEnd > 0 { perfGap = 0.9 * perfGap + 0.1 * (start - perfLastEnd) * 1000 }
        defer {
            let end = CACurrentMediaTime()
            perfCore = 0.9 * perfCore + 0.1 * (end - start) * 1000
            perfLastEnd = end
        }
        tickFPS()
        // §7: gerçek fps'e göre profil parametrelerini ölçekle (Python Pipeline.process ile aynı)
        let fps = updateSourceFPS(ts)
        let k = referenceFps / max(1.0, fps)
        let maxDist = min(0.5, profile.maxMatchDistance * k)
        let rate = 1 - pow(1 - profile.backgroundRate, k)
        let maxMissed = max(2, roundHalfEven(6 / k))

        // §5 Boş bant öğrenme: ~1 sn (en az 15 kare)
        if case .background(let n, let maxDiff) = calib {
            let nTotal = max(15, roundHalfEven(fps * 1.0))
            segmenter.learn(frame, rate: n == 0 ? 1 : 0.15)
            var m = maxDiff
            if n >= Int(0.4 * Double(nTotal)) {
                m = max(m, segmenter.diffPercentile(frame, roi: profile.roi, percentile: 0.995))
            }
            let next = n + 1
            if next >= nTotal {
                let th = min(100, max(12, Int(Double(m) * 1.5) + 8))
                profile.diffThreshold = th
                calib = .none
                tracker.reset()
                emit(.backgroundDone(threshold: th))
            } else {
                calib = .background(frame: next, maxDiff: m)
                if next % 6 == 0 { emit(.backgroundProgress(Double(next) / Double(nTotal))) }
            }
            publish(frame: frame, blobs: [], pixelBuffer: pixelBuffer)
            if let pb = pixelBuffer { emitDisplayImage(pb, sourceWidth: frame.sourceWidth) }
            return
        }

        var learningSample = false
        if case .sample = calib { learningSample = true }
        let expected = learningSample ? 0 : profile.expectedArea

        let raw = segmenter.segment(frame, roi: profile.roi,
                                    threshold: profile.diffThreshold,
                                    closeIterations: profile.closeIterations,
                                    backgroundRate: Float(rate),
                                    keepMask: showMask)
        let minArea = expected > 0 ? expected * profile.minAreaFactor : profile.minAreaAbs
        var blobs = raw.filter { $0.area >= minArea }

        if profile.splitTouching && expected > 0 {
            for i in blobs.indices {
                let ratio = blobs[i].area / expected
                blobs[i].multiplicity = ratio < 1.5
                    ? 1
                    : min(profile.maxMultiplicity, max(1, roundHalfEven(ratio)))
            }
        }

        let events = tracker.update(blobs: blobs,
                                    direction: profile.direction,
                                    line: Double(profile.linePosition),
                                    maxDistance: maxDist,
                                    minHits: profile.minHits,
                                    maxMissed: maxMissed)
        if !events.isEmpty { handle(events, pixelBuffer: pixelBuffer) }
        publish(frame: frame, blobs: blobs, pixelBuffer: pixelBuffer)
        if let pb = pixelBuffer { emitDisplayImage(pb, sourceWidth: frame.sourceWidth) }
    }

    private func handle(_ events: [CountEvent], pixelBuffer: CVPixelBuffer?) {
        if case .sample(var areas, let target) = calib {
            areas += events.filter { $0.isFirstCrossing && $0.medianArea > 0 }.map { $0.medianArea }
            if areas.count >= target {
                let med = median(areas)
                profile.expectedArea = med
                calib = .none
                emit(.sampleDone(expectedArea: med))
            } else {
                calib = .sample(areas: areas, target: target)
                emit(.sampleProgress(done: areas.count, target: target))
            }
            return
        }
        guard counting else { return }
        let delta = events.reduce(0) { $0 + $1.delta }
        guard delta > 0 else { return }
        total += delta
        let t = total
        DispatchQueue.main.async { [weak self] in self?.onCount?(delta, t) }

        guard let pb = pixelBuffer else { return }
        for e in events where e.isFirstCrossing {
            guard let jpeg = cropJPEG(pb, bbox: e.bbox) else { continue }
            let crop = CountCrop(trackId: e.trackId, delta: e.delta, time: Date(), jpeg: jpeg)
            DispatchQueue.main.async { [weak self] in self?.onCrop?(crop) }
        }
    }

    /// Lekenin kutusunu %15 payla genişletip tam çözünürlüklü kareden kırpar.
    private func cropJPEG(_ pb: CVPixelBuffer, bbox: CGRect) -> Data? {
        let w = CGFloat(CVPixelBufferGetWidth(pb)), h = CGFloat(CVPixelBufferGetHeight(pb))
        var r = CGRect(x: bbox.minX * w, y: bbox.minY * h, width: bbox.width * w, height: bbox.height * h)
        let pad = 0.15 * max(r.width, r.height)
        r = r.insetBy(dx: -pad, dy: -pad).intersection(CGRect(x: 0, y: 0, width: w, height: h))
        guard r.width >= 8, r.height >= 8 else { return nil }
        // CIImage'ın orijini sol alttadır
        let image = CIImage(cvPixelBuffer: pb)
            .cropped(to: CGRect(x: r.minX, y: h - r.maxY, width: r.width, height: r.height))
        let scale = min(1, 256 / max(r.width, r.height))
        let scaled = image.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        return ciContext.jpegRepresentation(
            of: scaled, colorSpace: CGColorSpaceCreateDeviceRGB(),
            options: [CIImageRepresentationOption(rawValue: kCGImageDestinationLossyCompressionQuality as String): 0.8])
    }

    // MARK: - Yardımcılar

    private func updateSourceFPS(_ ts: Double) -> Double {
        if let last = stamps.last, ts <= last { stamps.removeAll() }   // geri sarma / kaynak değişimi
        stamps.append(ts)
        while stamps.count > 2 && ts - stamps[0] > 2.0 { stamps.removeFirst() }
        if stamps.count >= 3, let last = stamps.last, last > stamps[0] {
            return Double(stamps.count - 1) / (last - stamps[0])
        }
        return referenceFps
    }

    private func tickFPS() {
        let now = CACurrentMediaTime()
        if fpsWindowStart == 0 { fpsWindowStart = now }
        fpsFrames += 1
        if now - fpsWindowStart >= 1 {
            fps = Double(fpsFrames) / (now - fpsWindowStart)
            fpsFrames = 0
            fpsWindowStart = now
        }
    }

    private func emit(_ e: CalibrationEvent) {
        DispatchQueue.main.async { [weak self] in self?.onCalibration?(e) }
    }

    private func publish(frame: GrayFrame, blobs: [Blob], pixelBuffer: CVPixelBuffer?) {
        let now = CACurrentMediaTime()
        guard now - lastPublish >= 1.0 / 12.0 else { return }
        lastPublish = now
        var maskImage: CGImage?
        if showMask, let m = segmenter.lastMask {
            maskImage = Self.makeMaskImage(m, w: frame.width, h: frame.height)
        }
        let snap = EngineSnapshot(frameSize: CGSize(width: frame.sourceWidth, height: frame.sourceHeight),
                                  blobs: blobs, tracks: tracker.markers, fps: fps, mask: maskImage,
                                  perf: String(format: "bekleme %.0f ms · çekirdek %.0f ms · ekran %.0f ms",
                                               perfGap, perfCore, perfImage))
        DispatchQueue.main.async { [weak self] in self?.onSnapshot?(snap) }
    }

    /// Ekran karesini ayrı kuyrukta üretir (en fazla ~24/sn). Önceki kare bitmediyse bu kare atlanır.
    private func emitDisplayImage(_ pb: CVPixelBuffer, sourceWidth: Int) {
        let now = CACurrentMediaTime()
        guard emitFrameImages, !displayBusy, now - lastDisplay >= 1.0 / 24.0 else { return }
        displayBusy = true
        lastDisplay = now
        let buffer = UncheckedSendable(value: pb)
        let context = UncheckedSendable(value: ciContext)
        displayQueue.async { [weak self] in
            let t0 = CACurrentMediaTime()
            // Ekranda en fazla ~540 px genişlik gerekir; küçültüp üretmek tam çözünürlüğe göre çok ucuz
            let scale = min(1, 540 / CGFloat(max(1, sourceWidth)))
            let small = CIImage(cvPixelBuffer: buffer.value)
                .transformed(by: CGAffineTransform(scaleX: scale, y: scale))
            let image = context.value.createCGImage(small, from: small.extent)
            let ms = (CACurrentMediaTime() - t0) * 1000
            guard let self else { return }
            self.queue.async {
                self.displayBusy = false
                self.perfImage = 0.9 * self.perfImage + 0.1 * ms
            }
            if let image {
                DispatchQueue.main.async { [weak self] in self?.onFrameImage?(image) }
            }
        }
    }

    private static func makeMaskImage(_ mask: [UInt8], w: Int, h: Int) -> CGImage? {
        guard mask.count == w * h else { return nil }
        var rgba = [UInt8](repeating: 0, count: w * h * 4)
        for i in 0..<(w * h) where mask[i] != 0 {
            let o = i * 4
            rgba[o] = 40; rgba[o + 1] = 255; rgba[o + 2] = 120; rgba[o + 3] = 255
        }
        guard let provider = CGDataProvider(data: Data(rgba) as CFData) else { return nil }
        return CGImage(width: w, height: h, bitsPerComponent: 8, bitsPerPixel: 32,
                       bytesPerRow: w * 4, space: CGColorSpaceCreateDeviceRGB(),
                       bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue),
                       provider: provider, decode: nil, shouldInterpolate: false,
                       intent: .defaultIntent)
    }
}
