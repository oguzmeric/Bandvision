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
    /// İz kimliği → sayım sıra numarası ("34", bitişik çiftte "35–36"); ürünün üstünde gösterilir
    var countLabels: [Int: String] = [:]
    /// Kişi sayımı (§4.10): görünen kişiler ve sayım çizgisi (normalize)
    var people: [PersonMarker] = []
    var peopleLine: (NormPoint, NormPoint)?

    static var empty: EngineSnapshot {
        EngineSnapshot(frameSize: CGSize(width: 720, height: 1280),
                       blobs: [], tracks: [], fps: 0, mask: nil, perf: "")
    }
}

/// Kişi sayımında ekranda çizilen kişi: kutu, iz kuyruğu ve sayıldıysa "G3" / "Ç2" etiketi
struct PersonMarker: Identifiable {
    let id: Int
    let box: CGRect
    let trail: [CGPoint]
    /// "G3" (3. giriş) ya da "Ç2" (2. çıkış); sayılmadıysa nil
    let label: String?
    var isEntry: Bool { label?.hasPrefix("G") ?? false }
    /// Personel geçişi ("P"): giriş/çıkışa eklenmez
    var isStaff: Bool { label == "P" }
}

/// Çizgiyi ilk kez geçen ürünün tam çözünürlüklü kırpıntısı (kalite kontrol kartı için).
struct CountCrop: Sendable {
    let trackId: Int
    let delta: Int
    /// Sayım sıra numarası (ekranda ürünün üstündekiyle aynı)
    let label: String
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
    /// Gürültü eşiği üst sınıra dayandı: öğrenirken bantta ürün/hareket vardı. Eşik değiştirilmedi.
    case backgroundRejected(measured: Int)
    case sampleProgress(done: Int, target: Int)
    case sampleDone(expectedArea: Double)
    /// Şerit tarama (§4.9): ürün boyu öğrenildi (ROI akış uzunluğuna oranla)
    case lengthDone(productLength: Double)
}

/// Tüm görüntü işleme hattı. Durum yalnızca `queue` üzerinde değişir;
/// dışarıya sonuçlar ana kuyrukta callback ile verilir.
final class FrameProcessor: @unchecked Sendable {
    private enum CalibState {
        case none
        /// updateThreshold: false → yalnızca arka plan görüntüsü öğrenilir, kayıtlı eşik korunur
        case background(frame: Int, maxDiff: Int, updateThreshold: Bool)
        case sample(areas: [Double], target: Int)
    }

    let queue: DispatchQueue
    private let segmenter = BackgroundSegmenter()
    private let tracker = BlobTracker()
    private let lineScan = LineScanCounter()
    private let people = PeopleCounter()
    /// Kişi sayımı: çıkış toplamı (`total` giriş toplamıdır) ve iz → "G3"/"Ç2" etiketi
    private var totalOut = 0
    private var personLabels: [Int: String] = [:]
    /// Kişi sayımı: personel geçişi toplamları (giriş/çıkıştan ayrı; CSV/webhook'a gitmez)
    private var staffIn = 0
    private var staffOut = 0
    /// Personel rengi öğretme isteği: sonraki kişi karesinde bu noktadan renk alınır (normalize)
    private var pendingTeach: CGPoint?
    private var lastPeople: PeopleFrame?
    private var lastFrameSize = (width: 0, height: 0)
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
    /// Kalite kontrol kırpıntısının JPEG kodlaması da ayrı kuyrukta ve ayrı bağlamda: sayım kuyruğu yalnızca
    /// küçük bir bellek kopyası alır. (Paylaşılan bağlamda ekran üretimini beklemek canlı kaynakta kare kaçırtıyordu.)
    private let cropQueue = DispatchQueue(label: "bantsayac.crop", qos: .utility)
    private let cropContext = CIContext()
    private var lastDisplay: CFTimeInterval = 0

    private var lastPublish: CFTimeInterval = 0
    /// İz kimliği → o izde sayılan ürünlerin sıra numaraları (yalnızca `queue` üzerinde); iz silinince budanır.
    /// Yapışık lekede "34·35"; leke ayrılınca her ürün kendi numarasını taşır.
    private var countNumbers: [Int: [Int]] = [:]
    /// §4.8: son karede kullanılan çizgi çerçevesi (iz işaretlerini görüntüye geri çevirmek için)
    private var lineFrame: LineFrame?
    // Ölçüm (üssel ortalama, ms)
    private var perfGap = 0.0, perfCore = 0.0, perfImage = 0.0
    private var perfLastEnd: CFTimeInterval = 0
    private var lastTs: Double?
    private var maxGapMs = 0.0
    private var backwardsTs = 0
    private var sourceFps = 0.0
    private var fpsWindowStart: CFTimeInterval = 0
    private var fpsFrames = 0
    private var fps: Double = 0

    // Hepsi ana kuyrukta çağrılır.
    var onSnapshot: (@MainActor (EngineSnapshot) -> Void)?
    var onCount: (@MainActor (_ delta: Int, _ total: Int) -> Void)?
    var onCrop: (@MainActor (CountCrop) -> Void)?
    var onCalibration: (@MainActor (CalibrationEvent) -> Void)?
    /// Kişi sayımı (§4.10): bu karede girenler/çıkanlar ve toplamlar (toplam giriş, toplam çıkış)
    var onCrossing: (@MainActor (_ entered: Int, _ exited: Int, _ totalIn: Int, _ totalOut: Int) -> Void)?
    /// Kişi sayımı §4.10 eki: personel geçişi toplamları (giriş, çıkış)
    var onStaff: (@MainActor (_ staffIn: Int, _ staffOut: Int) -> Void)?
    /// Personel rengi öğretme sonucu (çok karanlıksa nil)
    var onStaffColor: (@MainActor (LabColor?) -> Void)?
    /// Video ve ağ kamerası modunda ekranda gösterilen kare (iPhone kamerasında önizleme katmanı kullanılır).
    var onFrameImage: (@MainActor (CGImage) -> Void)?

    init(queue: DispatchQueue) {
        self.queue = queue
    }

    // MARK: - Dışarıdan kontrol (thread-safe)

    func setProfile(_ p: ProductProfile) { queue.async { self.profile = p } }
    func setCounting(_ on: Bool) { queue.async { self.counting = on } }
    func setTotal(_ t: Int) { queue.async { self.total = t } }
    /// Kişi sayımı: giriş ve çıkış toplamları
    func setTotals(in tIn: Int, out tOut: Int) { queue.async { self.total = tIn; self.totalOut = tOut } }
    func setStaffTotals(in sIn: Int, out sOut: Int) { queue.async { self.staffIn = sIn; self.staffOut = sOut } }
    func teachStaffColor(at p: CGPoint) { queue.async { self.pendingTeach = p } }
    /// Bekleyen öğretmeyi bırakır (kare akmadı ya da kalibrasyon kapandı): sonradan eski dokunuştan renk eklenmesin
    func cancelStaffTeach() { queue.async { self.pendingTeach = nil } }
    func setShowMask(_ on: Bool) { queue.async { self.showMask = on } }
    /// Video modunda işlenen kareyi de anlık görüntüyle yayınla.
    func setEmitFrameImages(_ on: Bool) { queue.async { self.emitFrameImages = on } }
    /// Kaynak değişti (kamera ↔ video): fps penceresini sıfırla.
    func resetClock() { queue.async { self.stamps.removeAll() } }

    func resetTracking(resetBackground: Bool) {
        queue.async {
            self.tracker.reset()
            self.lineScan.reset()
            self.people.reset()
            self.personLabels.removeAll()
            self.lastPeople = nil
            self.countNumbers.removeAll()
            if resetBackground { self.segmenter.reset() }
        }
    }

    /// §5 Boş bant öğrenme. `updateThreshold: false` (video başında otomatik): yalnızca arka plan görüntüsü;
    /// kayıtlı eşik değişmez (kullanıcının Kaydet ettiği kalibrasyon sabit kalır).
    func startBackgroundLearning(updateThreshold: Bool = true) {
        queue.async {
            self.tracker.reset()
            self.lineScan.reset()
            self.countNumbers.removeAll()
            self.calib = .background(frame: 0, maxDiff: 0, updateThreshold: updateThreshold)
        }
    }

    func startSampleLearning(target: Int) {
        queue.async {
            self.tracker.reset()
            self.lineScan.reset()
            self.countNumbers.removeAll()
            self.calib = .sample(areas: [], target: target)
        }
    }

    /// Video bitti (§4.9 flush): şerit taramada son karede çizgiye yarım binmiş ürünler merkezlerine göre sayılır.
    /// Kuyruk sıralı olduğundan videonun son karesinden sonra çalışır.
    func finishVideo() {
        queue.async {
            guard self.profile.mode == .linescan else { return }
            if case .sample = self.calib {
                // "Ürün boyunu öğren" sürerken video bitti: eldeki veriyle öğren
                var p = self.profile
                p.productLength = 0
                _ = self.lineScan.flush(profile: p)
                let len = self.lineScan.productLength
                if len > 0 {
                    self.profile.productLength = len
                    self.calib = .none
                    self.emit(.lengthDone(productLength: len))
                }
                return
            }
            guard case .none = self.calib, self.counting else { return }
            self.countLineScan(self.lineScan.flush(profile: self.profile), pixelBuffer: nil)
        }
    }

    func cancelCalibration() { queue.async { self.calib = .none } }

    // MARK: - Kare işleme (queue üzerinde)

    /// ts: kaynağın sunum zamanı (sn). Kamera ve video aynı yoldan gelir.
    func process(_ pixelBuffer: CVPixelBuffer, ts: Double) {
        if profile.mode == .safety {                   // güvenlik alarmı yalnızca bilgisayarda (web analiz sunucusu)
            displaySafetyFrame(pixelBuffer)
            return
        }
        if profile.mode == .detect {
            processPeople(pixelBuffer, ts: ts)
            return
        }
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
        sourceFps = fps
        let k = referenceFps / max(1.0, fps)
        let maxDist = min(0.5, profile.maxMatchDistance * k)
        let rate = 1 - pow(1 - profile.backgroundRate, k)
        let maxMissed = max(2, roundHalfEven(6 / k))
        lastFrameSize = (frame.width, frame.height)

        if profile.mode == .linescan {
            processLineScan(frame, pixelBuffer: pixelBuffer)
            return
        }

        // §5 Boş bant öğrenme: ~1 sn (en az 15 kare)
        if case .background(let n, let maxDiff, let updateThreshold) = calib {
            let nTotal = max(15, roundHalfEven(fps * 1.0))
            segmenter.learn(frame, rate: n == 0 ? 1 : 0.15)
            var m = maxDiff
            if n >= Int(0.4 * Double(nTotal)) {
                m = max(m, segmenter.diffPercentile(frame, roi: profile.roi, polygon: profile.roiPolygon, percentile: 0.995))
            }
            let next = n + 1
            if next >= nTotal {
                let th = min(100, max(12, Int(Double(m) * 1.5) + 8))
                calib = .none
                tracker.reset()
                countNumbers.removeAll()
                if !updateThreshold {
                    emit(.backgroundDone(threshold: profile.diffThreshold))
                } else if th >= 100 {
                    // Gürültü bu kadar yüksekse bantta ürün ya da hareket vardı: eşiği bozma, kullanıcıyı uyar
                    emit(.backgroundRejected(measured: th))
                } else {
                    profile.diffThreshold = th
                    emit(.backgroundDone(threshold: th))
                }
            } else {
                calib = .background(frame: next, maxDiff: m, updateThreshold: updateThreshold)
                if next % 6 == 0 { emit(.backgroundProgress(Double(next) / Double(nTotal))) }
            }
            publish(frame: frame, blobs: [], pixelBuffer: pixelBuffer)
            if let pb = pixelBuffer { emitDisplayImage(pb, sourceWidth: frame.sourceWidth) }
            return
        }

        var learningSample = false
        if case .sample = calib { learningSample = true }
        let expected = learningSample ? 0 : profile.expectedArea

        let lf = profile.countLine.flatMap { LineFrame.build(a: $0.a, b: $0.b, width: frame.width, height: frame.height) }
        lineFrame = lf
        let raw = segmenter.segment(frame, roi: profile.roi, polygon: profile.roiPolygon,
                                    threshold: profile.diffThreshold,
                                    closeIterations: profile.closeIterations,
                                    backgroundRate: Float(rate),
                                    keepMask: showMask,
                                    lineFrame: lf)
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

        let events: [CountEvent]
        if let lf {
            // §4.8: lekeler çizgi çerçevesine; izleyici "aşağı akış, çizgi 0" ile aynen çalışır
            events = tracker.update(blobs: blobs.map(lf.blob),
                                    direction: .down,
                                    line: 0,
                                    maxDistance: maxDist,
                                    minHits: profile.minHits,
                                    maxMissed: maxMissed,
                                    bounds: (lf.bounds.v0, lf.bounds.v1, lf.bounds.u0, lf.bounds.u1))
        } else {
            events = tracker.update(blobs: blobs,
                                    direction: profile.direction,
                                    line: Double(profile.linePosition),
                                    maxDistance: maxDist,
                                    minHits: profile.minHits,
                                    maxMissed: maxMissed)
        }
        applySplits(tracker.lastSplits)
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
        // Sıra numaraları olay sırasıyla; her ürüne kendi numarası (sonradan katılan ürün kendi numarasını ekler)
        var running = total
        for e in events where e.delta > 0 {
            countNumbers[e.trackId, default: []].append(contentsOf: (running + 1)...(running + e.delta))
            running += e.delta
        }
        total += delta
        let t = total
        DispatchQueue.main.async { [weak self] in self?.onCount?(delta, t) }

        guard let pb = pixelBuffer else { return }
        for e in events where e.isFirstCrossing {
            guard let region = Self.copyRegion(pb, bbox: e.bbox) else { continue }
            let buffer = UncheckedSendable(value: region)
            let context = UncheckedSendable(value: cropContext)
            let trackId = e.trackId, delta = e.delta, time = Date(), label = Self.numberLabel(countNumbers[e.trackId] ?? [])
            cropQueue.async { [weak self] in
                guard let jpeg = Self.encodeJPEG(buffer.value, context: context.value), let self else { return }
                let crop = CountCrop(trackId: trackId, delta: delta, label: label, time: time, jpeg: jpeg)
                DispatchQueue.main.async { [weak self] in self?.onCrop?(crop) }
            }
        }
    }

    /// Lekenin kutusunu %15 payla genişletip tam çözünürlüklü kareden küçük bir 420f tampona kopyalar.
    /// Yalnızca satır kopyası (mikro saniyeler): kaynak tampon hemen serbest kalır, kamera/çözücü havuzu tükenmez.
    static func copyRegion(_ src: CVPixelBuffer, bbox: CGRect) -> CVPixelBuffer? {
        let format = CVPixelBufferGetPixelFormatType(src)
        guard format == kCVPixelFormatType_420YpCbCr8BiPlanarFullRange
                || format == kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,
              CVPixelBufferGetPlaneCount(src) == 2 else { return nil }
        let sw = CVPixelBufferGetWidth(src), sh = CVPixelBufferGetHeight(src)
        var r = CGRect(x: bbox.minX * CGFloat(sw), y: bbox.minY * CGFloat(sh),
                       width: bbox.width * CGFloat(sw), height: bbox.height * CGFloat(sh))
        let pad = 0.15 * max(r.width, r.height)
        r = r.insetBy(dx: -pad, dy: -pad).intersection(CGRect(x: 0, y: 0, width: sw, height: sh))
        guard !r.isNull else { return nil }
        // 4:2:0 renk düzlemi yarım çözünürlüklü: köşe ve boyut çift olmalı
        let x = max(0, Int(r.minX)) & ~1, y = max(0, Int(r.minY)) & ~1
        let w = (min(Int(r.maxX.rounded(.up)), sw) - x) & ~1
        let h = (min(Int(r.maxY.rounded(.up)), sh) - y) & ~1
        guard w >= 8, h >= 8 else { return nil }
        var out: CVPixelBuffer?
        let attrs = [kCVPixelBufferIOSurfacePropertiesKey as String: [String: Any]()] as CFDictionary
        guard CVPixelBufferCreate(kCFAllocatorDefault, w, h, format, attrs, &out) == kCVReturnSuccess,
              let dst = out else { return nil }
        CVPixelBufferLockBaseAddress(src, .readOnly)
        CVPixelBufferLockBaseAddress(dst, [])
        defer {
            CVPixelBufferUnlockBaseAddress(dst, [])
            CVPixelBufferUnlockBaseAddress(src, .readOnly)
        }
        for plane in 0..<2 {
            guard let s = CVPixelBufferGetBaseAddressOfPlane(src, plane),
                  let d = CVPixelBufferGetBaseAddressOfPlane(dst, plane) else { return nil }
            let sStride = CVPixelBufferGetBytesPerRowOfPlane(src, plane)
            let dStride = CVPixelBufferGetBytesPerRowOfPlane(dst, plane)
            // Y: 1 bayt/piksel; CbCr: yarım çözünürlükte 2 bayt → iki düzlemde de satır başına `w` bayt, x bayt kayma
            let div = plane == 0 ? 1 : 2
            let source = s + (y / div) * sStride + x
            for row in 0..<(h / div) {
                memcpy(d + row * dStride, source + row * sStride, w)
            }
        }
        return dst
    }

    /// Küçük kırpıntıyı JPEG'e çevirir (uzun kenar en fazla 256 px). `cropQueue` üzerinde çalışır.
    static func encodeJPEG(_ pb: CVPixelBuffer, context: CIContext) -> Data? {
        let image = CIImage(cvPixelBuffer: pb)
        let scale = min(1, 256 / max(image.extent.width, image.extent.height))
        let scaled = image.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        return context.jpegRepresentation(
            of: scaled, colorSpace: CGColorSpaceCreateDeviceRGB(),
            options: [CIImageRepresentationOption(rawValue: kCGImageDestinationLossyCompressionQuality as String): 0.8])
    }

    // MARK: - Yardımcılar

    /// Yapışık lekeden ayrılan ürün kendi numarasını alır: ebeveynin son numaraları çocuğa geçer.
    private func applySplits(_ splits: [(parent: Int, child: Int, counted: Int)]) {
        for s in splits where s.counted > 0 {
            guard var nums = countNumbers[s.parent], !nums.isEmpty else { continue }
            let k = min(s.counted, nums.count)
            countNumbers[s.child] = Array(nums.suffix(k))
            nums.removeLast(k)
            countNumbers[s.parent] = nums.isEmpty ? nil : nums
        }
    }

    /// Ürün üstündeki yazı: tek ürün "34"; yapışık ürünler "34·35"; çok sayıda "34…40".
    static func numberLabel(_ nums: [Int]) -> String {
        guard let first = nums.first, let last = nums.last else { return "" }
        return nums.count <= 3 ? nums.map(String.init).joined(separator: "·") : "\(first)…\(last)"
    }

    // MARK: - Güvenlik alarmı (yalnızca bilgisayar)

    /// Poz güvenlik alarmı bu cihazda çalışmaz: kare yalnızca gösterilir, sayım ve izleme yapılmaz. Bekleyen
    /// kalibrasyon isteği takılı kalmasın diye bırakılır. Kare boyutu yayınlanır; yatay kaynakta (ağ kamerası,
    /// video) görüntü bozulmadan yerleşir.
    private func displaySafetyFrame(_ pb: CVPixelBuffer) {
        tickFPS()
        calib = .none
        let w = CVPixelBufferGetWidth(pb), h = CVPixelBufferGetHeight(pb)
        lastFrameSize = (w, h)
        let now = CACurrentMediaTime()
        if now - lastPublish >= 1.0 / 12.0 {
            lastPublish = now
            let snap = EngineSnapshot(frameSize: CGSize(width: w, height: h), blobs: [], tracks: [], fps: fps, mask: nil)
            DispatchQueue.main.async { [weak self] in self?.onSnapshot?(snap) }
        }
        emitDisplayImage(pb, sourceWidth: w)
    }

    // MARK: - Kişi sayımı (§4.10)

    /// Tanıma + hareket + iki yönlü çizgi. Kalibrasyon yok (öğrenme istekleri hemen biter); görüntü saklanmaz.
    private func processPeople(_ pb: CVPixelBuffer, ts: Double) {
        let start = CACurrentMediaTime()
        defer { perfCore = 0.9 * perfCore + 0.1 * (CACurrentMediaTime() - start) * 1000 }
        tickFPS()
        let fps = updateSourceFPS(ts)
        sourceFps = fps
        switch calib {
        case .background:
            calib = .none
            emit(.backgroundDone(threshold: profile.diffThreshold))
        case .sample:
            calib = .none
        case .none:
            break
        }
        guard let r = people.process(pb, profile: profile, fps: fps) else { return }
        lastPeople = r
        lastFrameSize = (CVPixelBufferGetWidth(pb), CVPixelBufferGetHeight(pb))
        if counting && (!r.entered.isEmpty || !r.exited.isEmpty) {
            for t in r.entered {
                total += 1
                personLabels[t.id] = "G\(total)"
            }
            for t in r.exited {
                totalOut += 1
                personLabels[t.id] = "Ç\(totalOut)"
            }
            let ins = r.entered.count, outs = r.exited.count, tIn = total, tOut = totalOut
            DispatchQueue.main.async { [weak self] in self?.onCrossing?(ins, outs, tIn, tOut) }
        }
        if counting && (!r.staffEntered.isEmpty || !r.staffExited.isEmpty) {
            for t in r.staffEntered + r.staffExited { personLabels[t.id] = "P" }
            staffIn += r.staffEntered.count
            staffOut += r.staffExited.count
            let sIn = staffIn, sOut = staffOut
            DispatchQueue.main.async { [weak self] in self?.onStaff?(sIn, sOut) }
        }
        if let p = pendingTeach {
            pendingTeach = nil
            let boxes = people.lastBoxes, anchor = profile.anchor
            let color = YUVSampler.with(pb) { w, h, rgbAt in
                StaffColor.teach(boxes: boxes, point: (Double(p.x), Double(p.y)), anchor: anchor, width: w, height: h, rgbAt: rgbAt)
            } ?? nil
            DispatchQueue.main.async { [weak self] in self?.onStaffColor?(color) }
        }
        let alive = Set(people.tracker.tracks.map(\.id))
        personLabels = personLabels.filter { alive.contains($0.key) }
        publishPeople(sourceWidth: CVPixelBufferGetWidth(pb), sourceHeight: CVPixelBufferGetHeight(pb))
        emitDisplayImage(pb, sourceWidth: CVPixelBufferGetWidth(pb))
    }

    private func publishPeople(sourceWidth: Int, sourceHeight: Int) {
        let now = CACurrentMediaTime()
        guard now - lastPublish >= 1.0 / 12.0, let r = lastPeople else { return }
        lastPublish = now
        var snap = EngineSnapshot(frameSize: CGSize(width: sourceWidth, height: sourceHeight),
                                  blobs: [], tracks: [], fps: fps, mask: nil,
                                  perf: String(format: "çekirdek %.0f ms · kaynak fps %.1f", perfCore, sourceFps))
        snap.people = r.tracks.map { t in
            PersonMarker(id: t.id,
                         box: CGRect(x: t.box.x1, y: t.box.y1, width: t.box.x2 - t.box.x1, height: t.box.y2 - t.box.y1),
                         trail: t.trail.map { CGPoint(x: $0.x, y: $0.y) },
                         label: personLabels[t.id])
        }
        snap.peopleLine = r.line
        let ready = snap
        DispatchQueue.main.async { [weak self] in self?.onSnapshot?(ready) }
    }

    // MARK: - Şerit tarama (§4.9)

    private func processLineScan(_ frame: GrayFrame, pixelBuffer: CVPixelBuffer?) {
        lineFrame = nil
        if case .background = calib {
            // Şerit tarama boş bant kullanmaz: öğrenme hemen biter, eşik değişmez
            calib = .none
            emit(.backgroundDone(threshold: profile.diffThreshold))
        }
        if case .sample = calib {
            var p = profile
            p.productLength = 0
            _ = lineScan.process(frame, profile: p)
            let len = lineScan.productLength
            if len > 0 {
                profile.productLength = len
                calib = .none
                emit(.lengthDone(productLength: len))
            }
        } else {
            let events = lineScan.process(frame, profile: profile)
            if counting && !events.isEmpty { countLineScan(events, pixelBuffer: pixelBuffer) }
        }
        publish(frame: frame, blobs: [], pixelBuffer: pixelBuffer)
        if let pb = pixelBuffer { emitDisplayImage(pb, sourceWidth: frame.sourceWidth) }
    }

    /// Her olay bir ürün: kendi sıra numarası (ekrandaki işaret kimliği = olay kimliği) ve kalite kartı kırpıntısı.
    private func countLineScan(_ events: [LineScanCounter.Event], pixelBuffer: CVPixelBuffer?) {
        guard !events.isEmpty else { return }
        var running = total
        for e in events {
            countNumbers[e.id, default: []].append(contentsOf: (running + 1)...(running + e.delta))
            running += e.delta
        }
        let delta = running - total
        total = running
        let t = total
        DispatchQueue.main.async { [weak self] in self?.onCount?(delta, t) }
        guard let pb = pixelBuffer, lastFrameSize.width > 0 else { return }
        let markers = lineScan.markers(width: lastFrameSize.width, height: lastFrameSize.height, profile: profile)
        let r = profile.roi
        let len = max(0.05, profile.lineProductLength > 0 ? lineScan.productLength : 0.2)
        for e in events {
            guard let m = markers.first(where: { $0.id == e.id }) else { continue }
            // Ürünün bulunduğu bant parçası: ROI genişliğinde, akış boyunca bir ürün boyu
            let bbox: CGRect
            if profile.direction.isVertical {
                let hgt = len * Double(r.height)
                bbox = CGRect(x: Double(r.minX), y: m.y - hgt / 2, width: Double(r.width), height: hgt)
            } else {
                let wdt = len * Double(r.width)
                bbox = CGRect(x: m.x - wdt / 2, y: Double(r.minY), width: wdt, height: Double(r.height))
            }
            let clipped = bbox.intersection(CGRect(x: 0, y: 0, width: 1, height: 1))
            guard !clipped.isNull, let region = Self.copyRegion(pb, bbox: clipped) else { continue }
            let buffer = UncheckedSendable(value: region)
            let context = UncheckedSendable(value: cropContext)
            let trackId = e.id, time = Date(), label = Self.numberLabel(countNumbers[e.id] ?? [])
            cropQueue.async { [weak self] in
                guard let jpeg = Self.encodeJPEG(buffer.value, context: context.value), let self else { return }
                let crop = CountCrop(trackId: trackId, delta: 1, label: label, time: time, jpeg: jpeg)
                DispatchQueue.main.async { [weak self] in self?.onCrop?(crop) }
            }
        }
    }

    /// İz işaretleri görüntü koordinatında (açılı çizgide çerçeveden geri çevrilir)
    private func displayMarkers() -> [TrackMarker] {
        if profile.mode == .linescan {
            return lineScan.markers(width: lastFrameSize.width, height: lastFrameSize.height, profile: profile)
                .map { TrackMarker(id: $0.id, x: $0.x, y: $0.y, counted: $0.counted) }
        }
        guard let lf = lineFrame else { return tracker.markers }
        return tracker.markers.map {
            let p = lf.toImage($0.x, $0.y)
            return TrackMarker(id: $0.id, x: p.x, y: p.y, counted: $0.counted)
        }
    }

    private func updateSourceFPS(_ ts: Double) -> Double {
        if let last = lastTs {
            if ts <= last { backwardsTs += 1 } else { maxGapMs = max(maxGapMs, (ts - last) * 1000) }
        }
        lastTs = ts
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
        var snap = EngineSnapshot(frameSize: CGSize(width: frame.sourceWidth, height: frame.sourceHeight),
                                  blobs: blobs, tracks: displayMarkers(), fps: fps, mask: maskImage,
                                  perf: String(format: "bekleme %.0f ms · çekirdek %.0f ms · ekran %.0f ms · en uzun aralık %.0f ms · geri giden %d · kaynak fps %.1f · son ts %.2f",
                                               perfGap, perfCore, perfImage, maxGapMs, backwardsTs, sourceFps, lastTs ?? -1))
        // Ekrandan çıkan izlerin numaraları atılır (sözlük büyümesin)
        let live = Set(snap.tracks.map(\.id))
        countNumbers = countNumbers.filter { live.contains($0.key) }
        snap.countLabels = countNumbers.mapValues(Self.numberLabel)
        let ready = snap
        DispatchQueue.main.async { [weak self] in self?.onSnapshot?(ready) }
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
