import Foundation
import Network
import CryptoKit

/// Ağ kamerası için RTSP istemcisi (RFC 2326), dış kütüphanesiz.
///
/// - Taşıma: RTP/AVP/TCP interleaved (tek TCP bağlantısı; NAT/güvenlik duvarı dostu, UDP kaybı yok).
/// - Kimlik doğrulama: Basic ve Digest (MD5, qop=auth dahil).
/// - Codec: H.264 (RFC 6184: tekil NAL, STAP-A, FU-A) ve H.265 (RFC 7798: tekil NAL, AP, FU).
/// - Çıktı: erişim birimi = başlangıç kodsuz NAL listesi + RTP zaman damgası.
/// Tüm durum kendi kuyruğunda değişir.
final class RTSPClient: @unchecked Sendable {
    enum Codec: String, Sendable {
        case h264 = "H.264"
        case h265 = "H.265"
    }

    struct StreamInfo: Sendable {
        let codec: Codec
        /// SDP'deki parametre setleri (H.264: SPS, PPS; H.265: VPS, SPS, PPS), başlangıç kodsuz
        let parameterSets: [Data]
    }

    enum Failure: LocalizedError, Equatable {
        case badURL
        case connection(String)
        case unauthorized
        case status(Int, String)
        case noVideo
        case unsupportedCodec(String)
        case protocolError(String)
        case closed

        var errorDescription: String? {
            switch self {
            case .badURL: return "Kamera adresi geçersiz."
            case .connection(let why): return "Kameraya bağlanılamadı (\(why))."
            case .unauthorized: return "Kullanıcı adı ya da şifre hatalı."
            case .status(let code, let text): return "Kamera isteği reddetti: \(code) \(text)."
            case .noVideo: return "Akışta video bulunamadı."
            case .unsupportedCodec(let c): return "Desteklenmeyen video biçimi: \(c). H.264 ya da H.265 seçin."
            case .protocolError(let why): return "Kamera yanıtı anlaşılamadı (\(why))."
            case .closed: return "Kamera bağlantıyı kapattı."
            }
        }
    }

    private struct Response {
        let code: Int
        let reason: String
        let headers: [String: String]     // anahtarlar küçük harf
        let body: Data
    }

    private struct DigestChallenge {
        let realm: String
        let nonce: String
        let qop: String?
        let opaque: String?
        /// "MD5" (varsayılan) ya da "SHA-256" (RFC 7616)
        let algorithm: String
    }

    private let url: URL
    private let requestURL: String           // kimlik bilgisi çıkarılmış adres
    private let username: String
    private let password: String
    private let queue = DispatchQueue(label: "bantsayac.rtsp")
    private var connection: NWConnection?
    private var inbox = [UInt8]()
    private var cseq = 0
    private var session: String?
    private var sessionTimeout = 60
    private var basicAuth = false
    private var digest: DigestChallenge?
    private var digestCount = 0
    private var pending: ((Result<Response, Failure>) -> Void)?
    private var depacketizer: Depacketizer?
    private var keepAlive: DispatchSourceTimer?
    private var finished = false

    /// Akış başlayınca bir kez (kendi kuyruğunda)
    var onStreamInfo: (@Sendable (StreamInfo) -> Void)?
    /// Her erişim birimi (kendi kuyruğunda)
    var onAccessUnit: (@Sendable ([Data], UInt32) -> Void)?
    /// Bağlantı bittiğinde ya da hata olduğunda bir kez (kendi kuyruğunda). nil: istenerek durduruldu.
    var onClose: (@Sendable (Failure?) -> Void)?

    init(url: URL, username: String, password: String) {
        self.url = url
        var c = URLComponents(url: url, resolvingAgainstBaseURL: false)
        c?.user = nil
        c?.password = nil
        requestURL = c?.string ?? url.absoluteString
        self.username = username
        self.password = password
    }

    func start() {
        queue.async { [self] in
            guard let host = url.host, !host.isEmpty else { finish(.badURL); return }
            let port = NWEndpoint.Port(rawValue: UInt16(url.port ?? 554)) ?? 554
            let conn = NWConnection(host: NWEndpoint.Host(host), port: port, using: .tcp)
            connection = conn
            conn.stateUpdateHandler = { [weak self] state in
                guard let self else { return }
                switch state {
                case .ready:
                    self.receive()
                    self.handshake()
                case .waiting(let error):
                    self.finish(.connection(error.localizedDescription))
                case .failed(let error):
                    self.finish(.connection(error.localizedDescription))
                default:
                    break
                }
            }
            conn.start(queue: queue)
            // Bağlantı ya da el sıkışma 10 sn'de tamamlanmazsa vazgeç
            queue.asyncAfter(deadline: .now() + 10) { [weak self] in
                guard let self, !self.finished, self.depacketizer == nil else { return }
                self.finish(.connection("zaman aşımı"))
            }
        }
    }

    func stop() {
        queue.async { [self] in
            guard !finished else { return }
            if let session { send(method: "TEARDOWN", url: requestURL, headers: ["Session": session]) { _ in } }
            finish(nil)
        }
    }

    // MARK: - El sıkışma

    private func handshake() {
        request(method: "OPTIONS", url: requestURL) { [self] _ in
            request(method: "DESCRIBE", url: requestURL, headers: ["Accept": "application/sdp"]) { [self] result in
                switch result {
                case .failure(let e): finish(e)
                case .success(let r): describeDone(r)
                }
            }
        }
    }

    private func describeDone(_ r: Response) {
        guard let sdp = String(data: r.body, encoding: .utf8) else { finish(.protocolError("SDP")); return }
        guard let media = SDP.video(in: sdp) else { finish(.noVideo); return }
        let codec: Codec
        switch media.encoding.uppercased() {
        case "H264": codec = .h264
        case "H265", "HEVC": codec = .h265
        default: finish(.unsupportedCodec(media.encoding)); return
        }
        let base = r.headers["content-base"] ?? r.headers["content-location"] ?? requestURL
        let control = SDP.resolve(control: media.control, base: base)
        let transport = "RTP/AVP/TCP;unicast;interleaved=0-1"
        request(method: "SETUP", url: control, headers: ["Transport": transport]) { [self] result in
            switch result {
            case .failure(let e): finish(e)
            case .success(let r):
                guard let s = r.headers["session"] else { finish(.protocolError("Session yok")); return }
                let parts = s.split(separator: ";").map { $0.trimmingCharacters(in: .whitespaces) }
                session = parts.first
                if let t = parts.first(where: { $0.lowercased().hasPrefix("timeout=") }),
                   let v = Int(t.dropFirst("timeout=".count)), v > 0 { sessionTimeout = v }
                let playURL = SDP.resolve(control: SDP.sessionControl(in: sdp), base: base)
                request(method: "PLAY", url: playURL, headers: ["Range": "npt=0.000-"]) { [self] result in
                    switch result {
                    case .failure(let e): finish(e)
                    case .success:
                        depacketizer = Depacketizer(codec: codec)
                        onStreamInfo?(StreamInfo(codec: codec, parameterSets: media.parameterSets))
                        startKeepAlive()
                    }
                }
            }
        }
    }

    private func startKeepAlive() {
        let timer = DispatchSource.makeTimerSource(queue: queue)
        let interval = Double(max(10, sessionTimeout / 2))
        timer.schedule(deadline: .now() + interval, repeating: interval)
        timer.setEventHandler { [weak self] in
            guard let self, let session = self.session else { return }
            // OPTIONS her kamerada desteklenir; yanıtı önemsiz
            self.send(method: "OPTIONS", url: self.requestURL, headers: ["Session": session]) { _ in }
        }
        timer.resume()
        keepAlive = timer
    }

    // MARK: - İstek / yanıt

    /// Yetkisiz yanıtta kimlik doğrulamayı bir kez kurup isteği tekrarlar.
    private func request(method: String, url: String, headers: [String: String] = [:],
                         completion: @escaping (Result<Response, Failure>) -> Void) {
        send(method: method, url: url, headers: headers) { [self] result in
            if case .success(let r) = result, r.code == 401 {
                guard !username.isEmpty, digest == nil, !basicAuth,
                      let header = r.headers["www-authenticate"] else { completion(.failure(.unauthorized)); return }
                let challenges = header.components(separatedBy: "\n")
                // Sunucu birden çok Digest önerebilir (ör. SHA-256 ve MD5): MD5'i tercih et, yoksa SHA-256
                let digests = challenges.filter { $0.lowercased().hasPrefix("digest") }.compactMap(Self.parseDigest)
                if let d = digests.first(where: { $0.algorithm == "MD5" })
                    ?? digests.first(where: { $0.algorithm == "SHA-256" }) {
                    digest = d
                } else if challenges.contains(where: { $0.lowercased().hasPrefix("basic") }) {
                    basicAuth = true
                } else {
                    completion(.failure(.unauthorized))
                    return
                }
                send(method: method, url: url, headers: headers) { result in
                    if case .success(let r) = result, r.code == 401 { completion(.failure(.unauthorized)); return }
                    completion(Self.checked(result))
                }
                return
            }
            completion(Self.checked(result))
        }
    }

    private static func checked(_ result: Result<Response, Failure>) -> Result<Response, Failure> {
        if case .success(let r) = result, !(200..<300).contains(r.code) {
            return .failure(r.code == 401 ? .unauthorized : .status(r.code, r.reason))
        }
        return result
    }

    private func send(method: String, url: String, headers: [String: String],
                      completion: @escaping (Result<Response, Failure>) -> Void) {
        guard let connection, !finished else { completion(.failure(.closed)); return }
        cseq += 1
        var lines = ["\(method) \(url) RTSP/1.0", "CSeq: \(cseq)", "User-Agent: BantSayac"]
        for (k, v) in headers { lines.append("\(k): \(v)") }
        if let session, headers["Session"] == nil, method != "SETUP" { lines.append("Session: \(session)") }
        if let auth = authorization(method: method, uri: url) { lines.append("Authorization: \(auth)") }
        let text = lines.joined(separator: "\r\n") + "\r\n\r\n"
        pending = completion
        connection.send(content: Data(text.utf8), completion: .contentProcessed { [weak self] error in
            if let error { self?.finish(.connection(error.localizedDescription)) }
        })
    }

    private func authorization(method: String, uri: String) -> String? {
        guard !username.isEmpty else { return nil }
        if let d = digest {
            let h: (String) -> String = d.algorithm == "SHA-256" ? Self.sha256 : Self.md5
            let ha1 = h("\(username):\(d.realm):\(password)")
            let ha2 = h("\(method):\(uri)")
            var fields = ["username=\"\(username)\"", "realm=\"\(d.realm)\"", "nonce=\"\(d.nonce)\"",
                          "uri=\"\(uri)\""]
            if let qop = d.qop?.split(separator: ",").map({ $0.trimmingCharacters(in: .whitespaces) })
                .first(where: { $0 == "auth" }) {
                digestCount += 1
                let nc = String(format: "%08x", digestCount)
                let cnonce = String(UUID().uuidString.prefix(8)).lowercased()
                let response = h("\(ha1):\(d.nonce):\(nc):\(cnonce):\(qop):\(ha2)")
                fields += ["qop=\(qop)", "nc=\(nc)", "cnonce=\"\(cnonce)\"", "response=\"\(response)\""]
            } else {
                fields.append("response=\"\(h("\(ha1):\(d.nonce):\(ha2)"))\"")
            }
            fields.append("algorithm=\(d.algorithm)")
            if let opaque = d.opaque { fields.append("opaque=\"\(opaque)\"") }
            return "Digest " + fields.joined(separator: ", ")
        }
        if basicAuth {
            return "Basic " + Data("\(username):\(password)".utf8).base64EncodedString()
        }
        return nil
    }

    private static func md5(_ s: String) -> String {
        Insecure.MD5.hash(data: Data(s.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private static func sha256(_ s: String) -> String {
        SHA256.hash(data: Data(s.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private static func parseDigest(_ header: String) -> DigestChallenge? {
        var params: [String: String] = [:]
        let body = header.dropFirst("Digest".count)
        // anahtar="değer" ya da anahtar=değer, virgülle ayrılmış (değer içinde virgül olabilir)
        var rest = Substring(body)
        while let eq = rest.firstIndex(of: "=") {
            let key = rest[..<eq].trimmingCharacters(in: CharacterSet(charactersIn: " ,")).lowercased()
            rest = rest[rest.index(after: eq)...]
            var value: String
            if rest.first == "\"" {
                rest = rest.dropFirst()
                let end = rest.firstIndex(of: "\"") ?? rest.endIndex
                value = String(rest[..<end])
                rest = end < rest.endIndex ? rest[rest.index(after: end)...] : ""
            } else {
                let end = rest.firstIndex(of: ",") ?? rest.endIndex
                value = rest[..<end].trimmingCharacters(in: .whitespaces)
                rest = rest[end...]
            }
            value = value.trimmingCharacters(in: .whitespaces)
            params[key] = value
        }
        guard let realm = params["realm"], let nonce = params["nonce"] else { return nil }
        let algorithm = (params["algorithm"] ?? "MD5").uppercased()
        guard algorithm == "MD5" || algorithm == "SHA-256" else { return nil }   // -sess türleri desteklenmez
        return DigestChallenge(realm: realm, nonce: nonce, qop: params["qop"], opaque: params["opaque"],
                               algorithm: algorithm)
    }

    // MARK: - Alım

    private func receive() {
        connection?.receive(minimumIncompleteLength: 1, maximumLength: 256 * 1024) { [weak self] data, _, isComplete, error in
            guard let self else { return }
            if let data, !data.isEmpty {
                self.inbox.append(contentsOf: data)
                self.parseInbox()
            }
            if let error {
                self.finish(.connection(error.localizedDescription))
            } else if isComplete {
                self.finish(.closed)
            } else if !self.finished {
                self.receive()
            }
        }
    }

    private func parseInbox() {
        var offset = 0
        defer { if offset > 0 { inbox.removeFirst(offset) } }
        while offset < inbox.count, !finished {
            if inbox[offset] == 0x24 {                         // '$' kanal len RTP
                guard inbox.count - offset >= 4 else { return }
                let channel = inbox[offset + 1]
                let length = Int(inbox[offset + 2]) << 8 | Int(inbox[offset + 3])
                guard inbox.count - offset >= 4 + length else { return }
                if channel == 0 {
                    handleRTP(Array(inbox[(offset + 4)..<(offset + 4 + length)]))
                }
                offset += 4 + length
            } else if inbox.count - offset >= 8, inbox[offset] == 0x52,
                      String(bytes: inbox[offset..<offset + 8], encoding: .ascii) == "RTSP/1.0" {
                guard let consumed = parseResponse(at: offset) else { return }
                offset += consumed
            } else {
                offset += 1                                     // eşzamanlamayı yeniden yakala
            }
        }
    }

    /// Yanıt tamamsa işler ve tükettiği bayt sayısını döndürür; eksikse nil.
    private func parseResponse(at offset: Int) -> Int? {
        let separator: [UInt8] = [13, 10, 13, 10]
        var end = -1
        var i = offset
        while i + 4 <= inbox.count {
            if inbox[i] == 13, Array(inbox[i..<i + 4]) == separator { end = i; break }
            i += 1
        }
        guard end >= 0, let head = String(bytes: inbox[offset..<end], encoding: .utf8) else { return nil }
        let lines = head.components(separatedBy: "\r\n")
        var headers: [String: String] = [:]
        for line in lines.dropFirst() {
            guard let colon = line.firstIndex(of: ":") else { continue }
            let key = line[..<colon].trimmingCharacters(in: .whitespaces).lowercased()
            let value = line[line.index(after: colon)...].trimmingCharacters(in: .whitespaces)
            // Aynı başlık birden çok kez gelebilir (ör. Digest ve Basic): satır sonuyla birleştir
            headers[key] = headers[key].map { $0 + "\n" + value } ?? value
        }
        let length = Int(headers["content-length"] ?? "0") ?? 0
        let bodyStart = end + 4
        guard inbox.count >= bodyStart + length else { return nil }
        let status = lines.first?.split(separator: " ", maxSplits: 2).map(String.init) ?? []
        let code = status.count > 1 ? Int(status[1]) ?? 0 : 0
        let reason = status.count > 2 ? status[2] : ""
        let response = Response(code: code, reason: reason, headers: headers,
                                body: Data(inbox[bodyStart..<(bodyStart + length)]))
        let handler = pending
        pending = nil
        handler?(.success(response))
        return bodyStart + length - offset
    }

    private func handleRTP(_ packet: [UInt8]) {
        guard packet.count >= 12, packet[0] >> 6 == 2, let depacketizer else { return }
        let hasPadding = packet[0] & 0x20 != 0
        let hasExtension = packet[0] & 0x10 != 0
        let csrcCount = Int(packet[0] & 0x0F)
        let marker = packet[1] & 0x80 != 0
        let sequence = UInt16(packet[2]) << 8 | UInt16(packet[3])
        let timestamp = UInt32(packet[4]) << 24 | UInt32(packet[5]) << 16 | UInt32(packet[6]) << 8 | UInt32(packet[7])
        var start = 12 + 4 * csrcCount
        if hasExtension {
            guard packet.count >= start + 4 else { return }
            start += 4 + 4 * (Int(packet[start + 2]) << 8 | Int(packet[start + 3]))
        }
        var end = packet.count
        if hasPadding, let pad = packet.last { end -= Int(pad) }
        guard start < end else { return }
        for unit in depacketizer.push(Array(packet[start..<end]), sequence: sequence, timestamp: timestamp,
                                      marker: marker) {
            onAccessUnit?(unit.nalus, unit.timestamp)
        }
    }

    private func finish(_ failure: Failure?) {
        guard !finished else { return }
        finished = true
        keepAlive?.cancel()
        keepAlive = nil
        let handler = pending
        pending = nil
        handler?(.failure(failure ?? .closed))
        connection?.cancel()
        connection = nil
        onClose?(failure)
    }
}

// MARK: - SDP

enum SDP {
    struct VideoMedia {
        let encoding: String
        let control: String?
        let parameterSets: [Data]
    }

    static func video(in sdp: String) -> VideoMedia? {
        let lines = sdp.components(separatedBy: CharacterSet.newlines).filter { !$0.isEmpty }
        var inVideo = false
        var payloadType: String?
        var encoding: String?
        var control: String?
        var fmtp: String?
        for line in lines {
            if line.hasPrefix("m=") {
                if inVideo { break }                           // ilk video bölümü bitti
                inVideo = line.hasPrefix("m=video")
                if inVideo { payloadType = line.split(separator: " ").dropFirst(3).first.map(String.init) }
                continue
            }
            guard inVideo else { continue }
            if line.hasPrefix("a=rtpmap:") {
                let v = line.dropFirst("a=rtpmap:".count).split(separator: " ", maxSplits: 1)
                if v.count == 2, String(v[0]) == payloadType || payloadType == nil {
                    encoding = v[1].split(separator: "/").first.map(String.init)
                }
            } else if line.hasPrefix("a=control:") {
                control = String(line.dropFirst("a=control:".count))
            } else if line.hasPrefix("a=fmtp:") {
                fmtp = String(line.dropFirst("a=fmtp:".count))
            }
        }
        guard inVideo || encoding != nil, let encoding else { return nil }
        return VideoMedia(encoding: encoding, control: control, parameterSets: parameterSets(fmtp))
    }

    /// Oturum düzeyindeki a=control (ilk m= satırından önce); yoksa "*".
    static func sessionControl(in sdp: String) -> String? {
        for line in sdp.components(separatedBy: CharacterSet.newlines) {
            if line.hasPrefix("m=") { break }
            if line.hasPrefix("a=control:") { return String(line.dropFirst("a=control:".count)) }
        }
        return nil
    }

    static func resolve(control: String?, base: String) -> String {
        guard let control, !control.isEmpty, control != "*" else { return base }
        if control.lowercased().hasPrefix("rtsp://") || control.lowercased().hasPrefix("rtsps://") { return control }
        return base.hasSuffix("/") ? base + control : base + "/" + control
    }

    private static func parameterSets(_ fmtp: String?) -> [Data] {
        guard let fmtp else { return [] }
        let params = fmtp.split(separator: " ", maxSplits: 1).last.map(String.init) ?? fmtp
        var out: [Data] = []
        for kv in params.split(separator: ";") {
            let pair = kv.split(separator: "=", maxSplits: 1).map { $0.trimmingCharacters(in: .whitespaces) }
            guard pair.count == 2 else { continue }
            switch pair[0].lowercased() {
            case "sprop-parameter-sets":
                out += pair[1].split(separator: ",").compactMap { Data(base64Encoded: String($0)) }
            case "sprop-vps", "sprop-sps", "sprop-pps":
                out += pair[1].split(separator: ",").compactMap { Data(base64Encoded: String($0)) }
            default:
                break
            }
        }
        return out
    }
}

// MARK: - RTP → erişim birimi

/// RTP yüklerinden NAL birimlerini çıkarır, aynı zaman damgalı NAL'ları bir erişim biriminde toplar.
/// Paket kaybında yarım kalan parçalı NAL atılır.
final class Depacketizer {
    struct AccessUnit {
        let nalus: [Data]
        let timestamp: UInt32
    }

    private let codec: RTSPClient.Codec
    private var current: [Data] = []
    private var currentTS: UInt32?
    private var fragment = [UInt8]()
    private var lastSequence: UInt16?

    init(codec: RTSPClient.Codec) {
        self.codec = codec
    }

    /// Tamamlanan erişim birimleri (genelde 0 ya da 1; işaret biti kaçmışsa 2).
    func push(_ payload: [UInt8], sequence: UInt16, timestamp: UInt32, marker: Bool) -> [AccessUnit] {
        var out: [AccessUnit] = []
        if let last = lastSequence, sequence != last &+ 1 { fragment.removeAll() }   // kayıp: yarım NAL'ı at
        lastSequence = sequence
        if let ts = currentTS, ts != timestamp, !current.isEmpty {   // işaret biti kaçtıysa zaman damgası değişimi
            out.append(AccessUnit(nalus: current, timestamp: ts))
            current.removeAll()
        }
        currentTS = timestamp
        switch codec {
        case .h264: pushH264(payload)
        case .h265: pushH265(payload)
        }
        if marker, !current.isEmpty {
            out.append(AccessUnit(nalus: current, timestamp: timestamp))
            current.removeAll()
            currentTS = nil
        }
        return out
    }

    private func pushH264(_ p: [UInt8]) {
        guard let first = p.first else { return }
        let type = first & 0x1F
        switch type {
        case 1...23:
            current.append(Data(p))
        case 24:                                                       // STAP-A
            var i = 1
            while i + 2 <= p.count {
                let size = Int(p[i]) << 8 | Int(p[i + 1])
                i += 2
                guard size > 0, i + size <= p.count else { break }
                current.append(Data(p[i..<(i + size)]))
                i += size
            }
        case 28:                                                       // FU-A
            guard p.count > 2 else { return }
            let header = p[1]
            if header & 0x80 != 0 {
                fragment = [(first & 0xE0) | (header & 0x1F)] + p[2...]
            } else if !fragment.isEmpty {
                fragment += p[2...]
            }
            if header & 0x40 != 0, !fragment.isEmpty {
                current.append(Data(fragment))
                fragment.removeAll()
            }
        default:
            break
        }
    }

    private func pushH265(_ p: [UInt8]) {
        guard p.count > 2 else { return }
        let type = (p[0] >> 1) & 0x3F
        switch type {
        case 0...47:
            current.append(Data(p))
        case 48:                                                       // AP
            var i = 2
            while i + 2 <= p.count {
                let size = Int(p[i]) << 8 | Int(p[i + 1])
                i += 2
                guard size > 0, i + size <= p.count else { break }
                current.append(Data(p[i..<(i + size)]))
                i += size
            }
        case 49:                                                       // FU
            guard p.count > 3 else { return }
            let fu = p[2]
            if fu & 0x80 != 0 {
                fragment = [(p[0] & 0x81) | ((fu & 0x3F) << 1), p[1]] + p[3...]
            } else if !fragment.isEmpty {
                fragment += p[3...]
            }
            if fu & 0x40 != 0, !fragment.isEmpty {
                current.append(Data(fragment))
                fragment.removeAll()
            }
        default:
            break
        }
    }
}
