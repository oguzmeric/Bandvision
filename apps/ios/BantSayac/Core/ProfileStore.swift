import Foundation

/// Kayıtlı profil listesinin bozuk kayda dayanıklı okunması: tek bir okunamayan kayıt (ör. bilinmeyen gelecek sürüm
/// yöntemi) tüm listeyi silmesin.
enum ProfileListCodec {
    private struct Lossy: Decodable {
        let profile: ProductProfile?
        init(from decoder: Decoder) throws { profile = try? ProductProfile(from: decoder) }
    }

    /// nil: veri bir dizi olarak okunamadı. Aksi hâlde sırayla okunabilen profiller ve atlanan kayıt sayısı.
    static func decode(_ data: Data) -> (profiles: [ProductProfile], skipped: Int)? {
        guard let items = try? JSONDecoder().decode([Lossy].self, from: data) else { return nil }
        let profiles = items.compactMap(\.profile)
        return (profiles, items.count - profiles.count)
    }
}

@MainActor
final class ProfileStore: ObservableObject {
    @Published private(set) var profiles: [ProductProfile]
    @Published private(set) var selectedID: UUID

    private let defaults: UserDefaults
    static let profilesKey = "bs.profiles"
    /// Okunamayan kayıtlı profil verisinin ham kopyası (varsayılana dönmeden önce; kayıtlar kurtarılabilsin)
    static let backupKey = "bs.profiles.backup"
    private static let selectedKey = "bs.selectedProfile"
    /// Yeni sayım türü hazır profili mevcut kullanıcının listesine bir kez eklendi mi (kişi sayımı: derleme 23)
    private static let peopleAddedKey = "bs.peopleProfileAdded"

    init(defaults d: UserDefaults = .standard) {
        defaults = d
        var loaded: [ProductProfile] = []
        if let data = d.data(forKey: Self.profilesKey) {
            // Okunamayan ya da atlanan kayıt varsa ham veri önce yedeklenir: aşağıdaki persist() listeyi yeniden yazar
            if let result = ProfileListCodec.decode(data) {
                loaded = result.profiles
                if result.skipped > 0 { d.set(data, forKey: Self.backupKey) }
            } else {
                d.set(data, forKey: Self.backupKey)
            }
        }
        if loaded.isEmpty {
            loaded = [.egg(), .flourSack(), .box(), .generic(), .people()]
        }
        // Güncellemeyle gelen kişi sayımı: önceden kurulmuş uygulamada profil listesi kayıtlı olduğundan hazır
        // profil görünmüyordu. Bir kez eklenir; kullanıcı silerse geri gelmez.
        if !d.bool(forKey: Self.peopleAddedKey) {
            if !loaded.contains(where: { $0.mode == .detect }) { loaded.append(.people()) }
            d.set(true, forKey: Self.peopleAddedKey)
        }
        profiles = loaded
        if let s = d.string(forKey: Self.selectedKey), let id = UUID(uuidString: s),
           loaded.contains(where: { $0.id == id }) {
            selectedID = id
        } else {
            selectedID = loaded[0].id
        }
        persist()
    }

    var selectedProfile: ProductProfile {
        profiles.first { $0.id == selectedID } ?? profiles[0]
    }

    func select(_ id: UUID) {
        guard profiles.contains(where: { $0.id == id }) else { return }
        selectedID = id
        persist()
    }

    func update(_ p: ProductProfile) {
        if let i = profiles.firstIndex(where: { $0.id == p.id }) {
            profiles[i] = p
        } else {
            profiles.append(p)
        }
        persist()
    }

    func add(_ p: ProductProfile) {
        profiles.append(p)
        persist()
    }

    func delete(_ id: UUID) {
        guard profiles.count > 1 else { return }
        profiles.removeAll { $0.id == id }
        if selectedID == id { selectedID = profiles[0].id }
        persist()
    }

    private func persist() {
        let d = defaults
        if let data = try? JSONEncoder().encode(profiles) {
            d.set(data, forKey: Self.profilesKey)
        }
        d.set(selectedID.uuidString, forKey: Self.selectedKey)
    }
}
