import Foundation
import CoreVideo

/// Gerçek izleme bağlantısı: NetworkCameraSource (RTSP → VideoToolbox). Yeniden bağlanma kaynağın kendisinde
/// (1, 2, 4 … 30 sn; şifre hatasında denenmez).
final class NetworkHubStream: HubStream, @unchecked Sendable {
    private let source: NetworkCameraSource

    init(plan: NetworkStreamPlan) {
        source = plan.makeSource()
    }

    func start(onFrame: @escaping @Sendable (CVPixelBuffer) -> Void,
               onStatus: @escaping @Sendable (TileStatus) -> Void) {
        source.onFrame = { frame, _ in onFrame(frame) }
        source.onState = { state in
            switch state {
            case .connecting: onStatus(.connecting)
            case .playing: onStatus(.playing)
            case .reconnecting, .ended: break        // sorunun türünü onProblem bildirir
            }
        }
        source.onProblem = { problem in onStatus(TileStatus(problem)) }
        source.start()
    }

    func stop() { source.stop() }
}

extension DeviceStore {
    /// CameraHub açıcısı: cihaz ve kanal bulunursa bağlantı, yoksa kutu durumu.
    func hubOpen(_ key: HubKey) -> HubOpen {
        let config: NetworkCameraConfig
        switch lookup(key.ref, substream: key.quality == .sub) {
        case .ok(let c): config = c
        case .deleted: return .rejected(.deleted)
        case .channelMissing: return .rejected(.channelMissing)
        }
        let id = key.ref.sourceId
        guard let plan = NetworkStreamPlan.make(config, password: password(for: id), client: recorderClient(for: id)) else {
            return .rejected(.offline)
        }
        return .stream(NetworkHubStream(plan: plan))
    }
}
