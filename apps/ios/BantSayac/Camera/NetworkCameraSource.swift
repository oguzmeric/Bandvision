import Foundation
import CoreMedia
import CoreVideo
import CoreImage
import VideoToolbox

enum NetworkCameraState: Equatable, Sendable {
    case connecting
    case playing(codec: String, width: Int, height: Int)
    case reconnecting(seconds: Int, reason: String)
    /// Yeniden bağlanma kapalıyken (test) yayın bitti
    case ended(String?)

    var text: String {
        switch self {
        case .connecting: return "Bağlanıyor…"
        case .playing(let codec, let w, let h): return "Canlı · \(w)×\(h) · \(codec)"
        case .reconnecting(let s, let reason): return "\(reason) · \(s) sn sonra yeniden denenecek"
        case .ended(let reason): return reason.map { "Yayın bitti: \($0)" } ?? "Yayın bitti"
        }
    }

    var isPlaying: Bool { if case .playing = self { return true } else { return false } }
}

/// Ağ kamerası: RTSP → VideoToolbox → CVPixelBuffer (420f, kamera ile aynı biçim) → işleme hattı.
/// Bağlantı koparsa 1, 2, 4 … 30 sn aralıkla yeniden bağlanır.
final class NetworkCameraSource: @unchecked Sendable {
    let url: URL
    private let username: String
    private let password: String
    private let queue = DispatchQueue(label: "bantsayac.netcam")
    private var client: RTSPClient?
    let decoder = H26xDecoder()
    private var stopped = false
    private var attempt = 0
    private var announcedPlaying = false

    /// false: bağlantı bitince yeniden denenmez (test ve sınama)
    var reconnect = true
    /// Kendi kuyruğunda
    var onState: (@Sendable (NetworkCameraState) -> Void)?
    /// Çözücü iş parçacığında; çağıran işleme hattına aktarmaktan (ve geride kalınca kare atlamaktan) sorumlu
    var onFrame: (@Sendable (CVPixelBuffer, Double) -> Void)?

    init(url: URL, username: String, password: String) {
        self.url = url
        self.username = username
        self.password = password
        decoder.onFrame = { [weak self] pb, ts in self?.decoded(pb, ts) }
    }

    func start() {
        queue.async { [self] in
            stopped = false
            connect()
        }
    }

    func stop() {
        queue.async { [self] in
            stopped = true
            client?.stop()
            client = nil
            decoder.reset()
        }
    }

    private func connect() {
        announcedPlaying = false
        decoder.reset()
        let c = RTSPClient(url: url, username: username, password: password)
        // İç kapanışa zayıf değişkeni değil, açılmış güçlü referansı ver (eşzamanlılık denetimi)
        c.onStreamInfo = { [weak self] info in
            guard let self else { return }
            self.queue.async { self.decoder.configure(info) }
        }
        c.onAccessUnit = { [weak self] nalus, ts in
            guard let self else { return }
            self.queue.async { self.decoder.decode(nalus, rtpTimestamp: ts) }
        }
        c.onClose = { [weak self] failure in
            guard let self else { return }
            self.queue.async { self.closed(failure, client: c) }
        }
        client = c
        onState?(.connecting)
        c.start()
    }

    private func closed(_ failure: RTSPClient.Failure?, client c: RTSPClient) {
        guard client === c, !stopped else { return }
        client = nil
        decoder.reset()
        let reason = failure?.errorDescription ?? "Bağlantı kapandı"
        guard reconnect, failure != .unauthorized, failure != .badURL else {
            onState?(.ended(reason))
            return
        }
        attempt += 1
        let delay = min(30, 1 << min(attempt - 1, 5))
        onState?(.reconnecting(seconds: delay, reason: reason))
        queue.asyncAfter(deadline: .now() + .seconds(delay)) { [weak self] in
            guard let self, !self.stopped, self.client == nil else { return }
            self.connect()
        }
    }

    /// Çözücü iş parçacığında: kare hemen aktarılır, durum değişikliği kendi kuyruğunda yapılır.
    private func decoded(_ pb: CVPixelBuffer, _ ts: Double) {
        onFrame?(pb, ts)
        let width = CVPixelBufferGetWidth(pb), height = CVPixelBufferGetHeight(pb)
        queue.async { [weak self] in
            guard let self, !self.announcedPlaying, !self.stopped else { return }
            self.announcedPlaying = true
            self.attempt = 0
            self.onState?(.playing(codec: self.decoder.codec.rawValue, width: width, height: height))
        }
    }

    // MARK: - Bağlantı sınaması

    struct ProbeResult: Sendable {
        let width: Int
        let height: Int
        let codec: String
        let thumbnail: CGImage?
    }

    /// Bağlanır, ilk kareyi çözer, küçük resim üretir ve kapatır (Ayarlar → Bağlantıyı test et).
    static func probe(url: URL, username: String, password: String,
                      timeout: Double = 12) async -> Result<ProbeResult, Error> {
        await withCheckedContinuation { (cont: CheckedContinuation<Result<ProbeResult, Error>, Never>) in
            let source = NetworkCameraSource(url: url, username: username, password: password)
            source.reconnect = false
            let once = Once()
            // Geri çağrılar kaynağı zayıf tutar (döngü olmasın); kaynağı zaman aşımı kapanışı canlı tutar.
            let finish: @Sendable (Result<ProbeResult, Error>, NetworkCameraSource?) -> Void = { result, src in
                guard once.claim() else { return }
                src?.stop()
                cont.resume(returning: result)
            }
            source.onFrame = { [weak source] pb, _ in
                let scale = min(1, 480 / CGFloat(max(1, CVPixelBufferGetWidth(pb))))
                let image = CIImage(cvPixelBuffer: pb).transformed(by: CGAffineTransform(scaleX: scale, y: scale))
                let thumb = CIContext().createCGImage(image, from: image.extent)
                let codec = source?.decoder.codec.rawValue ?? ""
                finish(.success(ProbeResult(width: CVPixelBufferGetWidth(pb), height: CVPixelBufferGetHeight(pb),
                                            codec: codec, thumbnail: thumb)), source)
            }
            source.onState = { [weak source] state in
                if case .ended(let reason) = state {
                    finish(.failure(ProbeError(message: reason ?? "Bağlantı kapandı")), source)
                }
            }
            source.start()
            DispatchQueue.global().asyncAfter(deadline: .now() + timeout) {
                finish(.failure(ProbeError(message: "\(Int(timeout)) sn içinde görüntü gelmedi")), source)
            }
        }
    }

    struct ProbeError: LocalizedError {
        let message: String
        var errorDescription: String? { message }
    }

    /// Bir kez çalışacak işler için iş parçacığı güvenli bayrak.
    final class Once: @unchecked Sendable {
        private let lock = NSLock()
        private var done = false
        func claim() -> Bool {
            lock.lock(); defer { lock.unlock() }
            if done { return false }
            done = true
            return true
        }
    }
}

/// H.264 / H.265 erişim birimlerini VideoToolbox ile çözer. Yalnızca NetworkCameraSource kuyruğunda kullanılır;
/// `codec` okuması dışında başka iş parçacığından erişilmez.
final class H26xDecoder: @unchecked Sendable {
    private(set) var codec: RTSPClient.Codec = .h264
    private var vps: Data?
    private var sps: Data?
    private var pps: Data?
    private var format: CMVideoFormatDescription?
    private var session: VTDecompressionSession?
    private var waitingForKeyframe = true
    private var lastTS: UInt32?
    private var wraps: Int64 = 0
    private var firstTS: Int64?

    /// VideoToolbox iş parçacığında: (kare, akış başından beri saniye)
    var onFrame: ((CVPixelBuffer, Double) -> Void)?

    func configure(_ info: RTSPClient.StreamInfo) {
        reset()
        codec = info.codec
        for set in info.parameterSets { _ = store(set) }
    }

    func reset() {
        if let session { VTDecompressionSessionInvalidate(session) }
        session = nil
        format = nil
        vps = nil
        sps = nil
        pps = nil
        waitingForKeyframe = true
        lastTS = nil
        wraps = 0
        firstTS = nil
    }

    func decode(_ nalus: [Data], rtpTimestamp: UInt32) {
        var slices: [Data] = []
        var keyframe = false
        var changed = false
        for nal in nalus where !nal.isEmpty {
            let type = nalType(nal)
            if isParameterSet(type) {
                changed = store(nal) || changed
            } else if !isSkippable(type) {
                slices.append(nal)
                if isKeyframe(type) { keyframe = true }
            }
        }
        if changed || session == nil { rebuildSession() }
        guard let session, let format, !slices.isEmpty else { return }
        if waitingForKeyframe {
            guard keyframe else { return }
            waitingForKeyframe = false
        }
        guard let sample = makeSample(slices, format: format, pts: unwrap(rtpTimestamp)) else { return }
        let status = VTDecompressionSessionDecodeFrame(session, sampleBuffer: sample, flags: [], infoFlagsOut: nil) {
            [weak self] status, _, imageBuffer, pts, _ in
            guard status == noErr, let pb = imageBuffer, let self else { return }
            self.onFrame?(pb, pts.seconds)
        }
        if status == kVTInvalidSessionErr {           // uygulama arka plandan dönünce oturum geçersizleşebilir
            rebuildSession()
            waitingForKeyframe = true
        }
    }

    // MARK: - NAL türleri

    private func nalType(_ nal: Data) -> Int {
        let b = Int(nal[nal.startIndex])
        return codec == .h264 ? b & 0x1F : (b >> 1) & 0x3F
    }

    private func isParameterSet(_ t: Int) -> Bool { codec == .h264 ? (t == 7 || t == 8) : (32...34).contains(t) }
    private func isSkippable(_ t: Int) -> Bool { codec == .h264 ? (t == 9 || t == 12) : (t == 35 || t == 38) }
    private func isKeyframe(_ t: Int) -> Bool { codec == .h264 ? t == 5 : (16...21).contains(t) }

    /// Parametre setini saklar; değiştiyse true.
    private func store(_ nal: Data) -> Bool {
        let t = nalType(nal)
        switch (codec, t) {
        case (.h264, 7), (.h265, 33):
            defer { sps = nal }
            return sps != nal
        case (.h264, 8), (.h265, 34):
            defer { pps = nal }
            return pps != nal
        case (.h265, 32):
            defer { vps = nal }
            return vps != nal
        default:
            return false
        }
    }

    private func rebuildSession() {
        if let session { VTDecompressionSessionInvalidate(session) }
        session = nil
        format = nil
        let sets: [Data]
        switch codec {
        case .h264:
            guard let sps, let pps else { return }
            sets = [sps, pps]
        case .h265:
            guard let vps, let sps, let pps else { return }
            sets = [vps, sps, pps]
        }
        guard let fmt = Self.makeFormat(sets, hevc: codec == .h265) else { return }
        let attrs: [CFString: Any] = [
            kCVPixelBufferPixelFormatTypeKey: kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,
            kCVPixelBufferIOSurfacePropertiesKey: [String: Any]()]
        var s: VTDecompressionSession?
        let status = VTDecompressionSessionCreate(allocator: kCFAllocatorDefault, formatDescription: fmt,
                                                  decoderSpecification: nil,
                                                  imageBufferAttributes: attrs as CFDictionary,
                                                  outputCallback: nil, decompressionSessionOut: &s)
        guard status == noErr, let s else { return }
        format = fmt
        session = s
        waitingForKeyframe = true
    }

    private static func makeFormat(_ sets: [Data], hevc: Bool) -> CMVideoFormatDescription? {
        let buffers: [UnsafeMutablePointer<UInt8>] = sets.map { d in
            let p = UnsafeMutablePointer<UInt8>.allocate(capacity: d.count)
            d.copyBytes(to: p, count: d.count)
            return p
        }
        defer { buffers.forEach { $0.deallocate() } }
        let pointers = buffers.map { UnsafePointer($0) }
        let sizes = sets.map(\.count)
        var fmt: CMFormatDescription?
        let status: OSStatus
        if hevc {
            status = CMVideoFormatDescriptionCreateFromHEVCParameterSets(
                allocator: kCFAllocatorDefault, parameterSetCount: sets.count, parameterSetPointers: pointers,
                parameterSetSizes: sizes, nalUnitHeaderLength: 4, extensions: nil, formatDescriptionOut: &fmt)
        } else {
            status = CMVideoFormatDescriptionCreateFromH264ParameterSets(
                allocator: kCFAllocatorDefault, parameterSetCount: sets.count, parameterSetPointers: pointers,
                parameterSetSizes: sizes, nalUnitHeaderLength: 4, formatDescriptionOut: &fmt)
        }
        return status == noErr ? fmt : nil
    }

    /// NAL'ları 4 bayt uzunluk önekli (AVCC/HVCC) tek örnekte birleştirir.
    private func makeSample(_ nalus: [Data], format: CMVideoFormatDescription, pts: CMTime) -> CMSampleBuffer? {
        var payload = Data(capacity: nalus.reduce(0) { $0 + $1.count + 4 })
        for nal in nalus {
            var length = UInt32(nal.count).bigEndian
            withUnsafeBytes(of: &length) { payload.append(contentsOf: $0) }
            payload.append(nal)
        }
        let count = payload.count
        var block: CMBlockBuffer?
        guard CMBlockBufferCreateWithMemoryBlock(allocator: kCFAllocatorDefault, memoryBlock: nil, blockLength: count,
                                                 blockAllocator: kCFAllocatorDefault, customBlockSource: nil,
                                                 offsetToData: 0, dataLength: count, flags: 0,
                                                 blockBufferOut: &block) == noErr, let block else { return nil }
        let copied = payload.withUnsafeBytes { raw -> OSStatus in
            guard let base = raw.baseAddress else { return -1 }
            return CMBlockBufferReplaceDataBytes(with: base, blockBuffer: block, offsetIntoDestination: 0,
                                                 dataLength: count)
        }
        guard copied == noErr else { return nil }
        var timing = CMSampleTimingInfo(duration: .invalid, presentationTimeStamp: pts, decodeTimeStamp: .invalid)
        var size = count
        var sample: CMSampleBuffer?
        guard CMSampleBufferCreateReady(allocator: kCFAllocatorDefault, dataBuffer: block, formatDescription: format,
                                        sampleCount: 1, sampleTimingEntryCount: 1, sampleTimingArray: &timing,
                                        sampleSizeEntryCount: 1, sampleSizeArray: &size,
                                        sampleBufferOut: &sample) == noErr else { return nil }
        return sample
    }

    /// 32 bit RTP zaman damgasını taşmaya karşı açar; akış başı 0 sn (90 kHz saat).
    private func unwrap(_ ts: UInt32) -> CMTime {
        if let last = lastTS, ts < last, last - ts > 0x8000_0000 { wraps += 1 }
        lastTS = ts
        let value = Int64(ts) + (wraps << 32)
        if firstTS == nil { firstTS = value }
        return CMTime(value: value - (firstTS ?? value), timescale: 90_000)
    }
}

/// Canlı kaynaktan gelen kareyi işleme kuyruğuna verir; önceki kare hâlâ işleniyorsa yenisini atlar.
/// Böylece işleme yavaşlarsa gecikme birikmez, hep en yeni kare işlenir (kameradaki alwaysDiscardsLateVideoFrames gibi).
final class FrameGate: @unchecked Sendable {
    private let lock = NSLock()
    private var busy = false
    private(set) var dropped = 0

    func submit(_ pb: CVPixelBuffer, ts: Double, to processor: FrameProcessor) {
        lock.lock()
        if busy {
            dropped += 1
            lock.unlock()
            return
        }
        busy = true
        lock.unlock()
        let frame = UncheckedSendable(value: pb)
        processor.queue.async { [self] in
            processor.process(frame.value, ts: ts)
            lock.lock()
            busy = false
            lock.unlock()
        }
    }
}
