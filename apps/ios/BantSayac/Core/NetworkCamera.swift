import Foundation
import Security

/// Görüntü kaynağı: iPhone'un kendi kamerası ya da ağdaki IP kamera (RTSP).
enum VideoSourceKind: String, Codable, CaseIterable, Identifiable {
    case phone
    case network

    var id: String { rawValue }
    var title: String { self == .phone ? "iPhone kamerası" : "Ağ kamerası (IP)" }
}

/// Marka bazında RTSP yol şablonları (docs/10-field-setup.md §3b). Model ve yazılım sürümüne göre değişebilir;
/// uymazsa "Diğer" ile tam adres girilir.
enum CameraBrand: String, Codable, CaseIterable, Identifiable {
    case hikvision, dahua, axis, vivotek, milesight, custom

    var id: String { rawValue }

    var title: String {
        switch self {
        case .hikvision: return "Hikvision"
        case .dahua: return "Dahua"
        case .axis: return "Axis"
        case .vivotek: return "Vivotek"
        case .milesight: return "Milesight"
        case .custom: return "Diğer (tam RTSP adresi)"
        }
    }

    func path(channel: Int, substream: Bool) -> String {
        switch self {
        case .hikvision: return "/Streaming/Channels/\(channel)0\(substream ? 2 : 1)"
        case .dahua: return "/cam/realmonitor?channel=\(channel)&subtype=\(substream ? 1 : 0)"
        case .axis: return "/axis-media/media.amp" + (substream ? "?resolution=640x360&fps=25" : "")
        case .vivotek: return "/live\(channel)s\(substream ? 2 : 1).sdp"
        case .milesight: return substream ? "/sub" : "/main"
        case .custom: return ""
        }
    }
}

struct NetworkCameraConfig: Codable, Equatable {
    /// Doğrudan kamera ya da kayıt cihazı (NVR/XVR)
    var kind: NetworkDeviceKind = .camera

    // Kamera
    var brand: CameraBrand = .hikvision
    var host = ""
    var port = 554
    var channel = 1
    /// Alt akış: sayım için yeterli (640×360 / 25 fps), ağ ve işlemci dostu. Kayıt cihazında da kullanılır.
    var substream = true
    var username = "admin"
    /// Yalnızca `.custom` markada: rtsp://… tam adres
    var customURL = ""

    // Kayıt cihazı
    var recorderBrand: RecorderBrand = .trassir
    var recorderHost = ""
    /// nil: markanın varsayılanı (TRASSIR 8080/555, Hikvision/Dahua 80/554)
    var recorderHTTPPort: Int?
    var recorderRTSPPort: Int?
    var recorderUsername = "admin"
    /// Seçilen kamera (kanal)
    var recorderChannel: RecorderChannel?

    init() {}

    /// Eski sürümlerin kaydında yeni alanlar yok: eksik alan varsayılanla okunur (kayıtlı kamera kaybolmasın).
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let d = NetworkCameraConfig()
        kind = try c.decodeIfPresent(NetworkDeviceKind.self, forKey: .kind) ?? d.kind
        brand = try c.decodeIfPresent(CameraBrand.self, forKey: .brand) ?? d.brand
        host = try c.decodeIfPresent(String.self, forKey: .host) ?? d.host
        port = try c.decodeIfPresent(Int.self, forKey: .port) ?? d.port
        channel = try c.decodeIfPresent(Int.self, forKey: .channel) ?? d.channel
        substream = try c.decodeIfPresent(Bool.self, forKey: .substream) ?? d.substream
        username = try c.decodeIfPresent(String.self, forKey: .username) ?? d.username
        customURL = try c.decodeIfPresent(String.self, forKey: .customURL) ?? d.customURL
        recorderBrand = try c.decodeIfPresent(RecorderBrand.self, forKey: .recorderBrand) ?? d.recorderBrand
        recorderHost = try c.decodeIfPresent(String.self, forKey: .recorderHost) ?? d.recorderHost
        recorderHTTPPort = try c.decodeIfPresent(Int.self, forKey: .recorderHTTPPort)
        recorderRTSPPort = try c.decodeIfPresent(Int.self, forKey: .recorderRTSPPort)
        recorderUsername = try c.decodeIfPresent(String.self, forKey: .recorderUsername) ?? d.recorderUsername
        recorderChannel = try c.decodeIfPresent(RecorderChannel.self, forKey: .recorderChannel)
    }

    /// Kayıt cihazının temizlenmiş adresi
    var cleanRecorderHost: String { Self.clean(recorderHost) }
    var effectiveHTTPPort: Int { recorderHTTPPort ?? recorderBrand.defaultHTTPPort }
    var effectiveRTSPPort: Int { recorderRTSPPort ?? recorderBrand.defaultRTSPPort }

    /// Kayıt cihazına bağlanmak için gereken bilgiler tamam mı (kanal seçimi hariç)
    var recorderReady: Bool {
        !cleanRecorderHost.isEmpty && (1...65535).contains(effectiveHTTPPort) && (1...65535).contains(effectiveRTSPPort)
    }

    /// Bağlanılabilir mi: kamera adresi geçerli ya da kayıt cihazında kamera seçilmiş
    var isComplete: Bool {
        kind == .camera ? rtspURL != nil : recorderReady && recorderChannel != nil
    }

    /// Kullanıcının yazdığı adresten şema, kimlik ve boşlukları ayıklar ("http://192.168.1.64/" → "192.168.1.64").
    var cleanHost: String { Self.clean(host) }

    private static func clean(_ text: String) -> String {
        var h = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if let r = h.range(of: "://") { h = String(h[r.upperBound...]) }
        if let at = h.lastIndex(of: "@") { h = String(h[h.index(after: at)...]) }
        if let slash = h.firstIndex(of: "/") { h = String(h[..<slash]) }
        if let colon = h.firstIndex(of: ":") { h = String(h[..<colon]) }
        return h
    }

    /// Şifresiz RTSP adresi; ayar eksikse nil.
    var rtspURL: URL? {
        if brand == .custom {
            let s = customURL.trimmingCharacters(in: .whitespacesAndNewlines)
            guard s.lowercased().hasPrefix("rtsp://"), let url = URL(string: s), url.host != nil else { return nil }
            return url
        }
        guard !cleanHost.isEmpty, (1...65535).contains(port) else { return nil }
        return URL(string: "rtsp://\(cleanHost):\(port)\(brand.path(channel: channel, substream: substream))")
    }

    /// Ekranda gösterilecek özet
    var summary: String {
        if kind == .recorder {
            guard recorderReady, let ch = recorderChannel else { return "Ayarlanmadı" }
            return "\(recorderBrand.title) · \(cleanRecorderHost) · \(ch.title)"
        }
        guard let url = rtspURL else { return "Ayarlanmadı" }
        return "\(brand == .custom ? "RTSP" : brand.title) · \(url.host ?? "")"
    }

    private static let key = "bs.netcam"

    static func load() -> NetworkCameraConfig {
        guard let data = UserDefaults.standard.data(forKey: key),
              let config = try? JSONDecoder().decode(NetworkCameraConfig.self, from: data) else { return .init() }
        return config
    }

    func save() {
        if let data = try? JSONEncoder().encode(self) { UserDefaults.standard.set(data, forKey: Self.key) }
    }
}

/// Ağ kamerası ve kayıt cihazı şifreleri iPhone Keychain'de (cihaz kilidi açıldıktan sonra erişilebilir,
/// yedekle taşınmaz). Hesap: "camera" (doğrudan kamera, eski sürümlerle aynı) ve "recorder".
enum CameraCredentialStore {
    private static let service = "com.oguzmeric.bantsayac.netcam"

    static func password(for kind: NetworkDeviceKind = .camera) -> String {
        let account = kind.rawValue
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service, kSecAttrAccount as String: account,
                                    kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return "" }
        return String(data: data, encoding: .utf8) ?? ""
    }

    /// Kaydeder; başarısızsa Keychain durum kodunu döndürür (sessizce yutulmaz).
    @discardableResult
    static func setPassword(_ password: String, for kind: NetworkDeviceKind = .camera) -> OSStatus {
        let account = kind.rawValue
        let base: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                   kSecAttrService as String: service, kSecAttrAccount as String: account]
        SecItemDelete(base as CFDictionary)
        guard !password.isEmpty else { return errSecSuccess }
        var add = base
        add[kSecValueData as String] = Data(password.utf8)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        return SecItemAdd(add as CFDictionary, nil)
    }
}
