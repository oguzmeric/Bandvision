import Foundation
import Security

/// Akış niteliği: ızgarada alt akış, tek kamerada ana akış
enum TileQuality: String, Sendable {
    case sub, main
}

/// Ağdaki bir cihaz: doğrudan IP kamera ya da kayıt cihazı (NVR/XVR). Şifresi Keychain'de (`device.<id>`).
struct NetworkDevice: Codable, Identifiable, Equatable, Sendable {
    var id: String
    var name: String
    /// Bağlantı ayarı; `recorderChannel` cihazda tutulmaz (kanallar `DeviceStore.channels`'ta)
    var config: NetworkCameraConfig

    var kind: NetworkDeviceKind { config.kind }

    /// "Hikvision · 192.168.1.64" (listelerde)
    var summary: String {
        switch kind {
        case .camera: return config.summary
        case .recorder:
            return config.recorderReady ? "\(config.recorderBrand.title) · \(config.cleanRecorderHost)" : "Ayarlanmadı"
        }
    }

    static func newID() -> String { UUID().uuidString.lowercased() }
}

/// Şifre deposu (gerçeği Keychain; testlerde bellek)
protocol CredentialStore: Sendable {
    func password(account: String) -> String
    /// Boş şifre kaydı siler. Dönüş: Keychain durum kodu (sessizce yutulmaz).
    @discardableResult func setPassword(_ password: String, account: String) -> OSStatus
}

/// Ağ cihazı şifreleri iPhone Keychain'de (cihaz kilidi açıldıktan sonra erişilebilir, yedekle taşınmaz).
/// Hesaplar: `device.<id>`; eski sürümlerin hesapları "camera" ve "recorder" (geçişte okunur, silinmez).
struct KeychainCredentials: CredentialStore {
    private static let service = "com.oguzmeric.bantsayac.netcam"

    func password(account: String) -> String {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: Self.service, kSecAttrAccount as String: account,
                                    kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return "" }
        return String(data: data, encoding: .utf8) ?? ""
    }

    @discardableResult
    func setPassword(_ password: String, account: String) -> OSStatus {
        let base: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                   kSecAttrService as String: Self.service, kSecAttrAccount as String: account]
        SecItemDelete(base as CFDictionary)
        guard !password.isEmpty else { return errSecSuccess }
        var add = base
        add[kSecValueData as String] = Data(password.utf8)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        return SecItemAdd(add as CFDictionary, nil)
    }
}

/// Bir kameranın bağlantı ayarı ya da neden bulunamadığı
enum CameraLookup: Equatable {
    case ok(NetworkCameraConfig)
    case deleted
    case channelMissing
}

/// Kamera ve kayıt cihazları (sayım ve İzleme ortak listesi). Liste `devices.json`'da (atomik; bozuksa kenara alınır),
/// şifreler Keychain'de. Kayıt cihazının kanal listesi önbellekte: kutu adları ve seçim çevrimdışı da görünür.
@MainActor
final class DeviceStore: ObservableObject {
    static let nameLimit = 40
    static let migratedKey = "bs.devicesMigrated"

    @Published private(set) var devices: [NetworkDevice] = []
    /// Kayıt cihazlarının kanal listesi (cihaz kimliği → kanallar)
    @Published private(set) var channels: [String: [RecorderChannel]] = [:]
    /// Dosya bozuktu ya da yazılamadı: Cihazlar ekranında gösterilir
    @Published private(set) var problem: String?

    private struct Stored: Codable {
        var version = 1
        var devices: [NetworkDevice]
        var channels: [String: [RecorderChannel]]
    }

    private let file: JSONFile
    private let credentials: CredentialStore
    /// Bozuk dosya kenara alınamadı: üzerine yazılmaz
    private var readOnly = false
    /// Bu oturumda girilen ya da Keychain'den bir kez okunan şifreler: Keychain yazılamasa da (imzasız simülatör)
    /// bağlantı çalışır, İzleme her kutuda Keychain'e gitmez
    private var sessionPasswords: [String: String] = [:]
    /// Kayıt cihazı istemcisi cihaz başına bir tane (TRASSIR: tek oturum); ayar ya da şifre değişince yenilenir
    private var clients: [String: (identity: String, client: RecorderClient)] = [:]

    init(directory: URL = AppFiles.directory, credentials: CredentialStore = KeychainCredentials()) {
        file = JSONFile(url: directory.appendingPathComponent("devices.json"))
        self.credentials = credentials
        switch file.load(Stored.self) {
        case .missing:
            break
        case .loaded(let stored):
            // Geçersiz kayıt (adresi eksik kamera, ayarsız kayıt cihazı) sessizce atılmaz: dosyanın kopyası
            // kenara alınır, sonra geçerli kayıtlar yüklenir (sonraki kayıt dosyayı yeniden yazar).
            let valid = stored.devices.filter(Self.isValid)
            devices = valid
            channels = stored.channels
            let invalid = stored.devices.count - valid.count
            if invalid > 0 {
                if let copy = file.backupCopy() {
                    problem = "\(invalid) cihaz okunamadı; dosyanın kopyası kenara alındı (\(copy))."
                } else {
                    readOnly = true
                    problem = "\(invalid) cihaz okunamadı; değişiklikler kaydedilmeyecek."
                }
            }
        case .corrupt(let moved):
            if let moved {
                problem = "Cihaz listesi okunamadı; kenara alındı (\(moved)). Cihazları yeniden ekle."
            } else {
                readOnly = true
                problem = "Cihaz listesi okunamadı; değişiklikler kaydedilmeyecek."
            }
        }
    }

    static func account(_ id: String) -> String { "device.\(id)" }

    /// Bağlantı bilgisi kullanılabilir mi: kameranın RTSP adresi çıkıyor, kayıt cihazının adresi ve portları geçerli
    private static func isValid(_ device: NetworkDevice) -> Bool {
        switch device.kind {
        case .camera: return device.config.rtspURL != nil
        case .recorder: return device.config.recorderReady
        }
    }

    func device(_ id: String) -> NetworkDevice? { devices.first { $0.id == id } }

    /// Kayıtlı şifre: önce bu oturumda girilen, yoksa Keychain (ilk okuma önbelleğe alınır: İzleme her kutu açılışında
    /// sorar; `save` üzerine yazar, `delete` siler)
    func password(for id: String) -> String {
        if let cached = sessionPasswords[id] { return cached }
        let stored = credentials.password(account: Self.account(id))
        sessionPasswords[id] = stored
        return stored
    }

    /// Ekler ya da günceller. Ad kırpılır (en çok 40); boşsa "Kamera 1" / "NVR 1"; başka cihazda varsa " (2)".
    /// Dönüş: kaydedilen cihaz ve şifre güvenli depoya yazılamadıysa kullanıcıya gösterilecek uyarı.
    @discardableResult
    func save(_ device: NetworkDevice, password: String) -> (device: NetworkDevice, warning: String?) {
        var d = device
        d.config.recorderChannel = nil
        let cleaned = d.name.trimmingCharacters(in: .whitespacesAndNewlines)
        d.name = UniqueName.make(cleaned.isEmpty ? defaultName(for: d.kind) : cleaned, limit: Self.nameLimit,
                                 taken: Set(devices.filter { $0.id != d.id }.map(\.name)))
        if let i = devices.firstIndex(where: { $0.id == d.id }) {
            devices[i] = d
        } else {
            devices.append(d)
        }
        if d.kind == .camera { channels[d.id] = nil }
        persist()
        sessionPasswords[d.id] = password
        clients[d.id] = nil
        let status = credentials.setPassword(password, account: Self.account(d.id))
        let warning = status == errSecSuccess ? nil
            : "Şifre güvenli depoya kaydedilemedi (kod \(status)). Bu oturumda kullanılır; uygulama yeniden açılınca tekrar girmen gerekebilir."
        return (d, warning)
    }

    func setChannels(_ list: [RecorderChannel], for id: String) {
        guard device(id)?.kind == .recorder else { return }
        channels[id] = list
        persist()
    }

    /// Cihaz, kanal listesi ve şifresi silinir
    func delete(_ id: String) {
        devices.removeAll { $0.id == id }
        channels[id] = nil
        sessionPasswords[id] = nil
        clients[id] = nil
        credentials.setPassword("", account: Self.account(id))
        persist()
    }

    /// Kameranın bağlantı ayarı. `substream` nil: cihazın kendi ayarı (sayım); ızgara alt, tek kamera ana akış ister.
    func lookup(_ ref: CameraRef, substream: Bool? = nil) -> CameraLookup {
        guard let d = device(ref.sourceId) else { return .deleted }
        var config = d.config
        if let substream { config.substream = substream }
        switch d.kind {
        case .camera:
            return ref.channelId == nil ? .ok(config) : .channelMissing
        case .recorder:
            guard let cid = ref.channelId, let channel = channels[d.id]?.first(where: { $0.id == cid }) else {
                return .channelMissing
            }
            config.recorderChannel = channel
            return .ok(config)
        }
    }

    /// Kutu ve seçicide gösterilen ad
    func title(for ref: CameraRef) -> String {
        guard let d = device(ref.sourceId) else { return "Kamera silinmiş" }
        guard d.kind == .recorder, let cid = ref.channelId else { return d.name }
        return channels[d.id]?.first { $0.id == cid }?.title ?? "Kanal \(cid)"
    }

    /// Sayım kaynağı özeti: "Ofis NVR · Bant 1"
    func summary(for ref: CameraRef?) -> String {
        guard let ref else { return "Seçilmedi" }
        guard let d = device(ref.sourceId) else { return "Kamera silinmiş" }
        return d.kind == .recorder ? "\(d.name) · \(title(for: ref))" : d.name
    }

    /// Kayıt cihazının istemcisi; aynı ayar ve şifreyle hep aynısı (TRASSIR'da tek oturum, kanal başına jeton)
    func recorderClient(for id: String) -> RecorderClient? {
        guard let d = device(id), d.kind == .recorder else { return nil }
        let pw = password(for: id)
        let c = d.config
        let identity = [c.recorderBrand.rawValue, c.cleanRecorderHost, String(c.effectiveHTTPPort),
                        String(c.effectiveRTSPPort), c.recorderUsername, pw].joined(separator: "|")
        if let cached = clients[id], cached.identity == identity { return cached.client }
        let client = NetworkStreamPlan.recorderClient(c, password: pw)
        clients[id] = (identity, client)
        return client
    }

    /// Eski sürümlerin tek kamera/NVR ayarını (`bs.netcam` + Keychain "camera"/"recorder") listeye taşır.
    /// Bir kez çalışır (`bs.devicesMigrated`); eski anahtarlar bir sürüm boyunca silinmez.
    /// Cihaz dosyası salt okunursa (bozuk dosya kenara alınamadı) bayrak konmadan nil döner: cihaz kaydedilemeyeceği
    /// için taşıma sonraki açılışta, dosya sorunu geçince denenir.
    /// Dönüş: sayımın kullanacağı kamera (eski ayarda seçili olan).
    func migrateLegacy(defaults: UserDefaults = .standard) -> CameraRef? {
        guard !defaults.bool(forKey: Self.migratedKey) else { return nil }
        guard !readOnly else { return nil }
        defaults.set(true, forKey: Self.migratedKey)
        guard let data = defaults.data(forKey: "bs.netcam"),
              let legacy = try? JSONDecoder().decode(NetworkCameraConfig.self, from: data) else { return nil }
        guard legacy.kind == .camera ? legacy.rtspURL != nil : legacy.recorderReady else { return nil }
        let pw = credentials.password(account: legacy.kind.rawValue)
        let saved = save(NetworkDevice(id: NetworkDevice.newID(), name: "", config: legacy), password: pw).device
        guard legacy.kind == .recorder else { return CameraRef(sourceId: saved.id, channelId: nil) }
        guard let channel = legacy.recorderChannel else { return nil }
        setChannels([channel], for: saved.id)
        return CameraRef(sourceId: saved.id, channelId: channel.id)
    }

    #if DEBUG || UITEST
    /// UI testi: her test boş listeyle başlar
    func removeAll() {
        for d in devices { delete(d.id) }
    }
    #endif

    // MARK: - İç

    private func defaultName(for kind: NetworkDeviceKind) -> String {
        let prefix = kind == .camera ? "Kamera" : "NVR"
        let names = Set(devices.map(\.name))
        var n = 1
        while names.contains("\(prefix) \(n)") { n += 1 }
        return "\(prefix) \(n)"
    }

    private func persist() {
        guard !readOnly else { return }
        do {
            try file.save(Stored(devices: devices, channels: channels))
        } catch {
            problem = "Cihaz listesi kaydedilemedi: \(error.localizedDescription)"
        }
    }
}
