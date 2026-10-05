import Foundation

@MainActor
final class ProfileStore: ObservableObject {
    @Published private(set) var profiles: [ProductProfile]
    @Published private(set) var selectedID: UUID

    private static let profilesKey = "bs.profiles"
    private static let selectedKey = "bs.selectedProfile"

    init() {
        let d = UserDefaults.standard
        var loaded: [ProductProfile] = []
        if let data = d.data(forKey: Self.profilesKey),
           let decoded = try? JSONDecoder().decode([ProductProfile].self, from: data),
           !decoded.isEmpty {
            loaded = decoded
        } else {
            loaded = [.egg(), .flourSack(), .box(), .generic()]
        }
        profiles = loaded
        if let s = d.string(forKey: Self.selectedKey), let id = UUID(uuidString: s),
           loaded.contains(where: { $0.id == id }) {
            selectedID = id
        } else {
            selectedID = loaded[0].id
        }
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
        let d = UserDefaults.standard
        if let data = try? JSONEncoder().encode(profiles) {
            d.set(data, forKey: Self.profilesKey)
        }
        d.set(selectedID.uuidString, forKey: Self.selectedKey)
    }
}
