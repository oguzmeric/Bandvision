import Foundation

/// Kayıt cihazının (NVR/XVR) kanal listesi, akış adresi ve küçük resim API'si.
protocol RecorderClient: Sendable {
    func channels() async throws -> [RecorderChannel]
    /// Her bağlanışta yeniden çağrılır: TRASSIR'da adres kısa ömürlü bir jeton içerir.
    func streamURL(_ channel: RecorderChannel, substream: Bool) async throws -> URL
    /// JPEG; desteklenmiyorsa hata (arayüz RTSP ile ilk kareye düşer)
    func snapshot(_ channel: RecorderChannel) async throws -> Data
    /// Akış açıkken düzenli çağrılır (TRASSIR jetonu canlı tutulur). Varsayılan: hiçbir şey.
    func keepAlive(_ streamURL: URL) async
}

extension RecorderClient {
    func keepAlive(_ streamURL: URL) async {}
}

enum RecorderClients {
    static func make(brand: RecorderBrand, host: String, httpPort: Int, rtspPort: Int,
                     username: String, password: String) -> RecorderClient {
        let http = DeviceHTTPClient(host: host, port: httpPort, https: brand.usesHTTPS,
                                    username: username, password: password)
        switch brand {
        case .trassir: return TrassirClient(http: http, host: host, rtspPort: rtspPort,
                                            username: username, password: password)
        case .hikvision: return HikvisionClient(http: http, host: host, rtspPort: rtspPort)
        case .dahua: return DahuaClient(http: http, host: host, rtspPort: rtspPort)
        }
    }

    static func rtspURL(host: String, port: Int, path: String) -> URL? {
        URL(string: "rtsp://\(host):\(port)\(path)")
    }
}

// MARK: - HTTP

/// Yerel ağdaki cihazla HTTP(S): Digest/Basic kimlik doğrulama (URLSession yerleşik) ve cihazın kendinden imzalı
/// sertifikası (yalnızca kullanıcının girdiği adres için kabul edilir).
final class DeviceHTTPClient: Sendable {
    let host: String
    let port: Int
    let https: Bool
    private let session: URLSession

    init(host: String, port: Int, https: Bool, username: String, password: String) {
        self.host = host
        self.port = port
        self.https = https
        let config = URLSessionConfiguration.ephemeral          // çerez/önbellek/kimlik diske yazılmaz
        config.timeoutIntervalForRequest = 8
        config.timeoutIntervalForResource = 20
        config.waitsForConnectivity = false
        // Oturum temsilciyi güçlü tutar; temsilci istemciyi tutmaz (döngü yok), istemci bırakılınca oturum kapanır.
        session = URLSession(configuration: config,
                             delegate: DeviceSessionDelegate(host: host, username: username, password: password),
                             delegateQueue: nil)
    }

    deinit { session.finishTasksAndInvalidate() }

    /// `query` değerleri yalnızca ayrılmamış karakterler bırakılarak kodlanır (şifredeki `+`, `&`, `=` güvenli).
    func get(_ path: String, query: [(String, String)] = []) async throws -> Data {
        var c = URLComponents()
        c.scheme = https ? "https" : "http"
        c.host = host
        c.port = port
        c.percentEncodedPath = path
        if !query.isEmpty {
            c.percentEncodedQuery = query.map { "\(Self.encode($0.0))=\(Self.encode($0.1))" }.joined(separator: "&")
        }
        guard let url = c.url else { throw RecorderError.unexpected("geçersiz adres") }
        return try await get(url: url)
    }

    func get(url: URL) async throws -> Data {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(from: url)
        } catch let error as URLError {
            throw Self.describe(error, url: url)
        }
        guard let http = response as? HTTPURLResponse else { throw RecorderError.unexpected("HTTP değil") }
        switch http.statusCode {
        case 200..<300: return data
        case 401: throw RecorderError.unauthorized
        default: throw RecorderError.http(http.statusCode)
        }
    }

    private static let unreserved = CharacterSet(charactersIn:
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")

    static func encode(_ s: String) -> String {
        s.addingPercentEncoding(withAllowedCharacters: unreserved) ?? s
    }

    private static func describe(_ error: URLError, url: URL) -> RecorderError {
        let target = "\(url.host ?? ""):\(url.port.map(String.init) ?? "")"
        switch error.code {
        case .userAuthenticationRequired: return .unauthorized
        case .timedOut: return .unreachable("\(target) yanıt vermedi")
        case .cannotConnectToHost: return .unreachable("\(target) bağlantıyı kabul etmedi")
        case .cannotFindHost, .dnsLookupFailed: return .unreachable("adres bulunamadı")
        case .notConnectedToInternet, .networkConnectionLost: return .unreachable("ağ bağlantısı yok")
        case .secureConnectionFailed, .serverCertificateUntrusted, .serverCertificateHasBadDate,
             .serverCertificateNotYetValid, .serverCertificateHasUnknownRoot:
            return .unreachable("güvenli bağlantı kurulamadı")
        default: return .unreachable(error.localizedDescription)
        }
    }
}

private final class DeviceSessionDelegate: NSObject, URLSessionTaskDelegate, Sendable {
    private let host: String
    private let username: String
    private let password: String

    init(host: String, username: String, password: String) {
        self.host = host
        self.username = username
        self.password = password
    }

    // Oturum düzeyi yöntem yazılmadığı için sunucu güveni sınaması da buraya gelir.
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    didReceive challenge: URLAuthenticationChallenge) async
        -> (URLSession.AuthChallengeDisposition, URLCredential?) {
        let space = challenge.protectionSpace
        switch space.authenticationMethod {
        case NSURLAuthenticationMethodServerTrust:
            // Kayıt cihazları kendinden imzalı sertifika kullanır; yalnızca kullanıcının girdiği adres kabul edilir.
            if space.host == host, let trust = space.serverTrust {
                return (.useCredential, URLCredential(trust: trust))
            }
            return (.performDefaultHandling, nil)
        case NSURLAuthenticationMethodHTTPDigest, NSURLAuthenticationMethodHTTPBasic:
            // İkinci deneme yok: yanlış şifrede cihaz 401 döner → "şifre hatalı"
            if challenge.previousFailureCount == 0, !username.isEmpty {
                return (.useCredential, URLCredential(user: username, password: password, persistence: .none))
            }
            return (.performDefaultHandling, nil)
        default:
            return (.performDefaultHandling, nil)
        }
    }
}

// MARK: - Hikvision (ISAPI)

struct HikvisionClient: RecorderClient {
    let http: DeviceHTTPClient
    let host: String
    let rtspPort: Int

    /// IP kanalları (NVR) ve analog kanallar (DVR/XVR); karma cihazda ikisi birlikte.
    func channels() async throws -> [RecorderChannel] {
        var all: [RecorderChannel] = []
        var firstError: Error?
        for path in ["/ISAPI/ContentMgmt/InputProxy/channels", "/ISAPI/System/Video/inputs/channels"] {
            do {
                let data = try await http.get(path)
                all += RecorderParsers.hikvisionChannels(data)
            } catch RecorderError.unauthorized {
                throw RecorderError.unauthorized
            } catch {
                firstError = firstError ?? error
            }
        }
        var seen = Set<String>()
        let unique = all.filter { seen.insert($0.id).inserted }.sorted { ($0.number ?? 0) < ($1.number ?? 0) }
        if unique.isEmpty { throw firstError ?? RecorderError.noChannels }
        return unique
    }

    func streamURL(_ channel: RecorderChannel, substream: Bool) async throws -> URL {
        guard let n = channel.number,
              let url = RecorderClients.rtspURL(host: host, port: rtspPort,
                                                path: "/Streaming/Channels/\(n)0\(substream ? 2 : 1)") else {
            throw RecorderError.unexpected("kanal numarası yok")
        }
        return url
    }

    func snapshot(_ channel: RecorderChannel) async throws -> Data {
        guard let n = channel.number else { throw RecorderError.unexpected("kanal numarası yok") }
        do {
            return try await http.get("/ISAPI/Streaming/channels/\(n)01/picture")
        } catch RecorderError.unauthorized {
            throw RecorderError.unauthorized
        } catch {
            return try await http.get("/ISAPI/Streaming/channels/\(n)02/picture")
        }
    }
}

// MARK: - Dahua (CGI)

struct DahuaClient: RecorderClient {
    let http: DeviceHTTPClient
    let host: String
    let rtspPort: Int

    func channels() async throws -> [RecorderChannel] {
        let data = try await http.get("/cgi-bin/configManager.cgi",
                                      query: [("action", "getConfig"), ("name", "ChannelTitle")])
        let list = RecorderParsers.dahuaChannels(String(decoding: data, as: UTF8.self))
        if list.isEmpty { throw RecorderError.noChannels }
        return list
    }

    func streamURL(_ channel: RecorderChannel, substream: Bool) async throws -> URL {
        guard let n = channel.number,
              let url = RecorderClients.rtspURL(host: host, port: rtspPort,
                                                path: "/cam/realmonitor?channel=\(n)&subtype=\(substream ? 1 : 0)") else {
            throw RecorderError.unexpected("kanal numarası yok")
        }
        return url
    }

    func snapshot(_ channel: RecorderChannel) async throws -> Data {
        guard let n = channel.number else { throw RecorderError.unexpected("kanal numarası yok") }
        return try await http.get("/cgi-bin/snapshot.cgi", query: [("channel", String(n))])
    }
}

// MARK: - TRASSIR (SDK)

/// TRASSIR SDK (docs/08-trassir-integration.md): `/login` → sid (15 dk, her istekle uzar) → `/channels` →
/// `/get_video?container=rtsp` → jeton (~10 sn) → `rtsp://sunucu:555/<jeton>`.
/// Oturum düşmüşse bir kez yeniden giriş yapılıp istek tekrarlanır.
actor TrassirClient: RecorderClient {
    private let http: DeviceHTTPClient
    private let host: String
    private let rtspPort: Int
    private let username: String
    private let password: String
    private var sid: String?

    init(http: DeviceHTTPClient, host: String, rtspPort: Int, username: String, password: String) {
        self.http = http
        self.host = host
        self.rtspPort = rtspPort
        self.username = username
        self.password = password
    }

    func channels() async throws -> [RecorderChannel] {
        try await withSession { sid in
            let data = try await self.http.get("/channels", query: [("sid", sid)])
            let json = try RecorderParsers.trassirJSON(data)
            if json["success"] != nil, !RecorderParsers.flag(json["success"]) {
                throw RecorderParsers.trassirError((json["error_code"] as? String) ?? "kanal listesi alınamadı")
            }
            let list = RecorderParsers.trassirChannels(json)
            if list.isEmpty { throw RecorderError.noChannels }
            return list
        }
    }

    func streamURL(_ channel: RecorderChannel, substream: Bool) async throws -> URL {
        let token = try await videoToken(channel, container: "rtsp", stream: substream && channel.hasSubstream ? "sub" : "main")
        guard let url = RecorderClients.rtspURL(host: host, port: rtspPort, path: "/" + token) else {
            throw RecorderError.unexpected("jeton")
        }
        return url
    }

    func snapshot(_ channel: RecorderChannel) async throws -> Data {
        let token = try await videoToken(channel, container: "jpeg", stream: channel.hasSubstream ? "sub" : "main")
        guard let url = URL(string: "http://\(host):\(rtspPort)/\(token)") else { throw RecorderError.unexpected("jeton") }
        let data = try await http.get(url: url)
        guard data.starts(with: [0xFF, 0xD8]) else { throw RecorderError.unexpected("JPEG değil") }
        return data
    }

    /// Jeton yalnızca istek geldikçe yaşar; akış açıkken düzenli `?ping`.
    nonisolated func keepAlive(_ streamURL: URL) async {
        guard let url = URL(string: "http://\(host):\(rtspPort)\(streamURL.path)?ping") else { return }
        _ = try? await http.get(url: url)
    }

    private func videoToken(_ channel: RecorderChannel, container: String, stream: String) async throws -> String {
        try await withSession { sid in
            let data = try await self.http.get("/get_video", query: [("channel", channel.id), ("container", container),
                                                                     ("stream", stream), ("sid", sid)])
            let token = try RecorderParsers.trassirValue(try RecorderParsers.trassirJSON(data), key: "token")
            // Jeton yola girer: yalnızca güvenli karakterler
            guard token.allSatisfy({ $0.isLetter || $0.isNumber || "-_.".contains($0) }) else {
                throw RecorderError.unexpected("jeton biçimi")
            }
            return token
        }
    }

    private func withSession<T: Sendable>(_ body: @Sendable (String) async throws -> T) async throws -> T {
        let current = try await session()
        do {
            return try await body(current)
        } catch let error as RecorderError {
            switch error {
            case .unreachable, .unauthorized: throw error
            default: break
            }
            sid = nil                                     // oturum düşmüş olabilir: bir kez yeniden giriş
            return try await body(try await session())
        }
    }

    private func session() async throws -> String {
        if let sid { return sid }
        let data = try await http.get("/login", query: [("username", username), ("password", password)])
        let value = try RecorderParsers.trassirValue(try RecorderParsers.trassirJSON(data), key: "sid")
        sid = value
        return value
    }
}
