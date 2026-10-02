import Foundation

/// Ayarlardan ağ akışının nasıl açılacağı: adres (her bağlanışta yeniden alınır), RTSP kimliği ve canlı tutma.
/// Canlı yayın da "Bağlantıyı test et" de bunu kullanır; iki yol aynı davranır.
struct NetworkStreamPlan {
    let resolver: NetworkCameraSource.URLResolver
    let username: String
    let password: String
    let keepAlive: (@Sendable (URL) async -> Void)?

    /// Ayarlar eksikse nil.
    static func make(_ config: NetworkCameraConfig, password: String) -> NetworkStreamPlan? {
        switch config.kind {
        case .camera:
            guard let url = config.rtspURL else { return nil }
            // Tam adreste kullanıcı adı/şifre yazılmışsa ve ayrı girilmemişse onları kullan
            let user = config.username.isEmpty ? (url.user ?? "") : config.username
            let pass = password.isEmpty ? (url.password ?? "") : password
            return NetworkStreamPlan(resolver: { url }, username: user, password: pass, keepAlive: nil)
        case .recorder:
            guard config.recorderReady, let channel = config.recorderChannel else { return nil }
            let client = recorderClient(config, password: password)
            let substream = config.substream
            return NetworkStreamPlan(resolver: { try await client.streamURL(channel, substream: substream) },
                                     username: config.recorderUsername, password: password,
                                     keepAlive: { url in await client.keepAlive(url) })
        }
    }

    static func recorderClient(_ config: NetworkCameraConfig, password: String) -> RecorderClient {
        RecorderClients.make(brand: config.recorderBrand, host: config.cleanRecorderHost,
                             httpPort: config.effectiveHTTPPort, rtspPort: config.effectiveRTSPPort,
                             username: config.recorderUsername, password: password)
    }

    func makeSource() -> NetworkCameraSource {
        let source = NetworkCameraSource(resolver: resolver, username: username, password: password)
        source.keepAlive = keepAlive
        return source
    }
}
