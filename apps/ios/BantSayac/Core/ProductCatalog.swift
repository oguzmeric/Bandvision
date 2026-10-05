import Foundation

/// Hazır profil (katalogdaki bir seçenek).
struct ProfilePreset: Identifiable {
    var id: String { name }
    let name: String
    let make: () -> ProductProfile
}

/// Sayım türü: arayüzde hazır profilleri gruplar ("Ne sayacaksın?"). Bant üstü ürün ve kişi sayımı çalışır;
/// diğerleri yol haritasını gösterir ("Yakında", seçilemez). Yeni tür çalışır hale gelince önce sözleşme (profil
/// şeması) güncellenir, sonra burada `available` açılır.
struct CountCategory: Identifiable {
    let id: String
    let title: String
    let subtitle: String
    /// SF Symbol adı
    let icon: String
    let available: Bool
    let presets: [ProfilePreset]

    /// Bu türe ait kayıtlı profil mi (bant üstü: ayrık/bitişik; kişi: iki yönlü tanıma)
    func contains(_ p: ProductProfile) -> Bool {
        switch id {
        case "people": return p.mode == .detect
        case "belt": return p.mode != .detect
        default: return false
        }
    }
}

enum ProductCatalog {
    static var categories: [CountCategory] {
        [
            CountCategory(id: "belt", title: "Bant üstü ürün", subtitle: "Banttan geçen ürünleri sayar ve kontrol eder",
                          icon: "shippingbox", available: true,
                          presets: [
                              ProfilePreset(name: "Yumurta", make: { .egg() }),
                              ProfilePreset(name: "Un torbası", make: { .flourSack() }),
                              ProfilePreset(name: "Koli / kutu", make: { .box() }),
                              ProfilePreset(name: "Genel ürün", make: { .generic() }),
                          ]),
            CountCategory(id: "people", title: "Kişi sayımı", subtitle: "Mağaza girişi: giren ve çıkan kişi sayısı",
                          icon: "person.2", available: true,
                          presets: [ProfilePreset(name: "Mağaza girişi", make: { .people() })]),
            CountCategory(id: "vehicle", title: "Araç sayımı", subtitle: "Giriş/çıkış ve otopark doluluğu",
                          icon: "car", available: false, presets: []),
            CountCategory(id: "animal", title: "Hayvan sayımı", subtitle: "Koridor geçişi ve ağıl doluluğu",
                          icon: "pawprint", available: false, presets: []),
            CountCategory(id: "stock", title: "Stok sayımı", subtitle: "Sera ve depo: sabit kamerayla saksı/ürün sayımı",
                          icon: "leaf", available: false, presets: []),
        ]
    }
}
