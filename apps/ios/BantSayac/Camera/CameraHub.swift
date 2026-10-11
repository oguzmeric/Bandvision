import Foundation
import CoreVideo

/// İzleme kutusunun durumu; `text` kutu ortasındaki Türkçe metin (canlıyken ve boşken nil)
enum TileStatus: Equatable, Sendable {
    case idle, connecting, playing, offline, authFailed, nvrLimit, limit, deleted, channelMissing, unsupported

    var text: String? {
        switch self {
        case .idle, .playing: return nil
        case .connecting: return "Bağlanıyor…"
        case .offline: return "Bağlantı yok"
        case .authFailed: return "Şifre hatalı"
        case .nvrLimit: return "NVR bağlantı sınırına ulaştı"
        case .limit: return "Sınır aşıldı"
        case .deleted: return "Kamera silinmiş"
        case .channelMissing: return "Kanal bulunamadı"
        case .unsupported: return "Görüntü biçimi desteklenmiyor"
        }
    }
}

/// Bağlantı sorununun türü (NetworkCameraSource → izleme kutusu)
enum StreamProblem: Equatable, Sendable {
    case offline, auth, refused, unsupported

    static func of(_ error: Error?) -> StreamProblem {
        if let failure = error as? RTSPClient.Failure {
            switch failure {
            case .unauthorized: return .auth
            case .status(let code, _) where code == 453 || code == 503: return .refused
            case .unsupportedCodec: return .unsupported
            default: return .offline
            }
        }
        if let recorder = error as? RecorderError {
            switch recorder {
            case .unauthorized: return .auth
            case .http(let code) where code == 503 || code == 429: return .refused
            default: return .offline
            }
        }
        return .offline
    }
}

extension TileStatus {
    init(_ problem: StreamProblem) {
        switch problem {
        case .offline: self = .offline
        case .auth: self = .authFailed
        case .refused: self = .nvrLimit
        case .unsupported: self = .unsupported
        }
    }

    /// Sayım akışının durumu kutuda: koparken "Bağlanıyor…" (son kare kalır)
    init(counting state: NetworkCameraState) {
        switch state {
        case .playing: self = .playing
        case .connecting, .reconnecting: self = .connecting
        case .ended: self = .offline
        }
    }
}

struct HubKey: Hashable, Sendable {
    let ref: CameraRef
    let quality: TileQuality
}

/// Kutu: kareyi ve durumu alır. Herhangi bir iş parçacığından çağrılır; hızlı dönmeli.
protocol HubSubscriber: AnyObject, Sendable {
    func hubFrame(_ frame: CVPixelBuffer)
    func hubStatus(_ status: TileStatus)
}

/// Hub'ın açtığı bağlantı (gerçeği NetworkHubStream; testte sahte). `start` bir kez çağrılır.
protocol HubStream: AnyObject, Sendable {
    func start(onFrame: @escaping @Sendable (CVPixelBuffer) -> Void,
               onStatus: @escaping @Sendable (TileStatus) -> Void)
    func stop()
}

enum HubOpen {
    case stream(HubStream)
    case rejected(TileStatus)
}

/// Bir okuyucunun aboneleri, son karesi ve durumu (kilitli: kareler çözücü iş parçacığından gelir).
final class HubFanout: @unchecked Sendable {
    private let lock = NSLock()
    private var subscribers: [ObjectIdentifier: HubSubscriber] = [:]
    private var frame: CVPixelBuffer?
    private var status: TileStatus = .connecting

    var isEmpty: Bool {
        lock.lock(); defer { lock.unlock() }
        return subscribers.isEmpty
    }

    var lastFrame: CVPixelBuffer? {
        lock.lock(); defer { lock.unlock() }
        return frame
    }

    var currentStatus: TileStatus {
        lock.lock(); defer { lock.unlock() }
        return status
    }

    /// Abone eklenir; son kare (yoksa `fallback`) ve durum hemen verilir.
    func add(_ subscriber: HubSubscriber, fallback: CVPixelBuffer?) {
        lock.lock()
        subscribers[ObjectIdentifier(subscriber)] = subscriber
        let f = frame ?? fallback
        let st = status
        lock.unlock()
        if let f { subscriber.hubFrame(f) }
        subscriber.hubStatus(st)
    }

    /// Dönüş: hiç abone kalmadı mı
    @discardableResult
    func remove(_ subscriber: HubSubscriber) -> Bool {
        lock.lock(); defer { lock.unlock() }
        subscribers[ObjectIdentifier(subscriber)] = nil
        return subscribers.isEmpty
    }

    func deliver(_ f: CVPixelBuffer) {
        lock.lock()
        frame = f
        let subs = Array(subscribers.values)
        lock.unlock()
        for s in subs { s.hubFrame(f) }
    }

    func setStatus(_ st: TileStatus) {
        lock.lock()
        guard st != status else { lock.unlock(); return }
        status = st
        let subs = Array(subscribers.values)
        lock.unlock()
        for s in subs { s.hubStatus(st) }
    }
}

/// Sayımın akışından gelen kareler (çözücü iş parçacığı) sayılan kameranın kutularına
final class ExternalFeed: @unchecked Sendable {
    private let lock = NSLock()
    private var fans: [HubFanout] = []
    private var status: TileStatus = .connecting

    var currentStatus: TileStatus {
        lock.lock(); defer { lock.unlock() }
        return status
    }

    func add(_ fan: HubFanout) {
        lock.lock(); fans.append(fan); lock.unlock()
    }

    func remove(_ fan: HubFanout) {
        lock.lock(); fans.removeAll { $0 === fan }; lock.unlock()
    }

    func reset() {
        lock.lock(); fans = []; status = .connecting; lock.unlock()
    }

    func frame(_ f: CVPixelBuffer) {
        lock.lock(); let current = fans; lock.unlock()
        for fan in current { fan.deliver(f) }
    }

    func setStatus(_ st: TileStatus) {
        lock.lock(); status = st; let current = fans; lock.unlock()
        for fan in current { fan.setStatus(st) }
    }
}

/// İzleme görüntü dağıtıcısı (docs/superpowers/specs/2026-10-11-iphone-izleme-design.md §3):
/// - kamera ve nitelik başına tek okuyucu; kutular aynı kareyi paylaşır;
/// - sayılan kamera sayımın akışından beslenir (NVR'a ikinci bağlantı yok);
/// - abonesi kalmayan okuyucu 5 sn sonra kapanır; yer gerekince hemen çıkarılır;
/// - aynı anda en çok 16 alt ve 1 ana akış (sayımın kendi bağlantısı sayılmaz).
/// Denetim ana iş parçacığında; kareler kilitli `HubFanout` üzerinden doğrudan kutulara gider.
@MainActor
final class CameraHub {
    static let maxSub = 16
    static let maxMain = 1
    static let graceSeconds = 5.0
    static let lastFrameSeconds = 60.0

    private enum Source {
        case stream(HubStream)
        case external
        case waiting
        case rejected(TileStatus)
    }

    private final class Reader {
        let key: HubKey
        let fan = HubFanout()
        var source: Source = .waiting
        /// Abonesi kalmadığı an (nil: abonesi var)
        var idleSince: Double?

        init(key: HubKey) { self.key = key }

        var isStream: Bool {
            if case .stream = source { return true }
            return false
        }
    }

    private var readers: [HubKey: Reader] = [:]
    private var lastFrames: [CameraRef: (frame: UncheckedSendable<CVPixelBuffer>, at: Double)] = [:]
    private var external: CameraRef?
    private nonisolated let feed = ExternalFeed()
    private let opener: (HubKey) -> HubOpen
    private let now: () -> Double

    init(opener: @escaping (HubKey) -> HubOpen,
         now: @escaping () -> Double = { ProcessInfo.processInfo.systemUptime }) {
        self.opener = opener
        self.now = now
    }

    /// Açık bağlantı sayısı (teşhis ve test)
    var openCount: (sub: Int, main: Int) {
        var sub = 0, main = 0
        for r in readers.values where r.isStream {
            if r.key.quality == .sub { sub += 1 } else { main += 1 }
        }
        return (sub, main)
    }

    func status(_ key: HubKey) -> TileStatus? { readers[key]?.fan.currentStatus }

    func subscribe(_ key: HubKey, _ subscriber: HubSubscriber) {
        let reader: Reader
        if let existing = readers[key] {
            reader = existing
        } else {
            reader = Reader(key: key)
            readers[key] = reader
            attach(reader)
        }
        reader.idleSince = nil
        reader.fan.add(subscriber, fallback: fallbackFrame(for: key))
    }

    func unsubscribe(_ key: HubKey, _ subscriber: HubSubscriber) {
        guard let reader = readers[key], reader.fan.remove(subscriber) else { return }
        if reader.isStream {
            reader.idleSince = now()
        } else {
            discard(reader)                         // açık bağlantısı yok: tutmaya gerek yok
        }
        promoteWaiting()
    }

    /// Şifre hatası ya da NVR reddi sonrası (kutuya dokunuş): bağlantı baştan açılır.
    func retry(_ key: HubKey) {
        guard let reader = readers[key] else { return }
        if case .external = reader.source { return }
        if case .stream(let s) = reader.source { s.stop() }
        reader.source = .waiting
        open(reader)
    }

    /// Cihaz düzenlendi ya da silindi: o cihazın okuyucuları yeni ayarla yeniden açılır (sayım beslemesi hariç).
    func reset(sourceId: String) {
        for reader in Array(readers.values) where reader.key.ref.sourceId == sourceId {
            if case .external = reader.source { continue }
            if reader.fan.isEmpty {
                discard(reader)
                continue
            }
            if case .stream(let s) = reader.source { s.stop() }
            reader.source = .waiting
            open(reader)
        }
    }

    /// Saniyede bir: süresi dolan boştaki okuyucular kapanır, bekleyenler açılır, eski son kareler bırakılır.
    func sweep() {
        let t = now()
        for reader in Array(readers.values) {
            if let idle = reader.idleSince, t - idle >= Self.graceSeconds { discard(reader) }
        }
        promoteWaiting()
        lastFrames = lastFrames.filter { t - $0.value.at < Self.lastFrameSeconds }
    }

    /// Uygulama arka plana geçti: boştaki okuyucular beklemeden kapanır (iOS uygulamayı askıya alır).
    func closeIdle() {
        for reader in Array(readers.values) where reader.idleSince != nil { discard(reader) }
    }

    /// Sayılan ağ kamerası (nil: ağ sayımı yok). Bu kameranın kutuları sayımın akışından beslenir.
    func setExternal(_ ref: CameraRef?) {
        guard ref != external else { return }
        let old = external
        external = ref
        feed.reset()
        for reader in Array(readers.values) {
            if reader.key.ref == old {                     // eski sayım kamerası: kendi bağlantısına döner
                if reader.fan.isEmpty {
                    discard(reader)
                } else {
                    reader.source = .waiting
                    open(reader)
                }
            } else if reader.key.ref == ref {              // yeni sayım kamerası: kendi bağlantısı kapanır
                if reader.fan.isEmpty {
                    discard(reader)
                    continue
                }
                if case .stream(let s) = reader.source { s.stop() }
                reader.source = .external
                reader.fan.setStatus(feed.currentStatus)
                feed.add(reader.fan)
            }
        }
    }

    /// Sayımın çözücü iş parçacığından her kare
    nonisolated func externalFrame(_ frame: CVPixelBuffer) { feed.frame(frame) }

    func externalStatus(_ status: TileStatus) { feed.setStatus(status) }

    // MARK: - İç

    private func attach(_ reader: Reader) {
        if reader.key.ref == external {
            reader.source = .external
            reader.fan.setStatus(feed.currentStatus)
            feed.add(reader.fan)
        } else {
            open(reader)
        }
    }

    private func open(_ reader: Reader) {
        if !hasCapacity(reader.key.quality) { evictIdle(reader.key.quality) }
        guard hasCapacity(reader.key.quality) else {
            reader.source = .waiting
            reader.fan.setStatus(.limit)
            return
        }
        switch opener(reader.key) {
        case .rejected(let status):
            reader.source = .rejected(status)
            reader.fan.setStatus(status)
        case .stream(let stream):
            reader.source = .stream(stream)
            reader.fan.setStatus(.connecting)
            let fan = reader.fan
            stream.start(onFrame: { frame in fan.deliver(frame) },
                         onStatus: { status in fan.setStatus(status) })
        }
    }

    private func hasCapacity(_ quality: TileQuality) -> Bool {
        let open = openCount
        return quality == .sub ? open.sub < Self.maxSub : open.main < Self.maxMain
    }

    /// Yer gerekince abonesi olmayan en eski okuyucu hemen kapanır (şablon geçişinde "Sınır aşıldı" görünmesin)
    private func evictIdle(_ quality: TileQuality) {
        let idle = readers.values.filter { $0.key.quality == quality && $0.isStream && $0.idleSince != nil }
        guard let oldest = idle.min(by: { ($0.idleSince ?? 0) < ($1.idleSince ?? 0) }) else { return }
        discard(oldest)
    }

    private func promoteWaiting() {
        for reader in Array(readers.values) {
            guard case .waiting = reader.source, !reader.fan.isEmpty else { continue }
            open(reader)
        }
    }

    private func fallbackFrame(for key: HubKey) -> CVPixelBuffer? {
        let other = HubKey(ref: key.ref, quality: key.quality == .sub ? .main : .sub)
        return readers[other]?.fan.lastFrame ?? lastFrames[key.ref]?.frame.value
    }

    private func discard(_ reader: Reader) {
        switch reader.source {
        case .stream(let s): s.stop()
        case .external: feed.remove(reader.fan)
        case .waiting, .rejected: break
        }
        if let f = reader.fan.lastFrame { lastFrames[reader.key.ref] = (UncheckedSendable(value: f), now()) }
        if readers[reader.key] === reader { readers[reader.key] = nil }
    }
}
