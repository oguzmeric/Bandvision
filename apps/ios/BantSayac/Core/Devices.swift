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
