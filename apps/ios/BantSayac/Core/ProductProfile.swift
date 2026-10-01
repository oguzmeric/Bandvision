import Foundation
import CoreGraphics

/// Ürünün görüntüde aktığı yön (portre, işlenmiş görüntü koordinatlarında).
enum FlowDirection: String, Codable, CaseIterable, Identifiable {
    case down, up, right, left

    var id: String { rawValue }

    var title: String {
        switch self {
        case .down: return "Yukarıdan aşağı"
        case .up: return "Aşağıdan yukarı"
        case .right: return "Soldan sağa"
        case .left: return "Sağdan sola"
        }
    }

    var arrow: String {
        switch self {
        case .down: return "↓"
        case .up: return "↑"
        case .right: return "→"
        case .left: return "←"
        }
    }

    var isVertical: Bool { self == .down || self == .up }
    /// Akış ekseninde ilerleme yönü: +1 (aşağı/sağa) ya da -1 (yukarı/sola).
    var sign: Double { (self == .down || self == .right) ? 1 : -1 }
}

/// Bir ürün tipi için tüm kalibrasyon ve algılama parametreleri.
/// Konum/alan değerleri normalize: 0...1 (görüntü boyutu ya da toplam alan oranı).
struct ProductProfile: Codable, Identifiable, Equatable {
    var id = UUID()
    var name: String
    /// İlgi alanı (ROI), normalize.
    var roi: CGRect
    /// Sayım çizgisi; akış eksenindeki normalize konum.
    var linePosition: CGFloat
    var direction: FlowDirection
    /// Arka plandan gri seviye farkı eşiği (0-255).
    var diffThreshold: Int
    /// Tek ürünün normalize alanı. 0 = örnek kalibrasyonu yapılmadı.
    var expectedArea: Double
    /// Bir lekenin ürün sayılması için min alan = expectedArea * minAreaFactor.
    var minAreaFactor: Double
    /// Örnek kalibrasyonu yokken kullanılan min alan.
    var minAreaAbs: Double
    /// Birbirine değen ürünleri alan oranıyla ayır.
    var splitTouching: Bool
    var maxMultiplicity: Int
    /// Morfolojik kapama tekrar sayısı (parçalı görünen ürünleri birleştirir).
    var closeIterations: Int
    /// İşleme genişliği (piksel). Küçük = hızlı, büyük = küçük üründe hassas.
    var processingWidth: Int
    /// Bir izin sayılması için minimum görülme sayısı (kare).
    var minHits: Int
    /// Kareler arası eşleştirme mesafesi (normalize).
    var maxMatchDistance: Double
    /// Arka planın ışık değişimlerine uyum hızı.
    var backgroundRate: Double
}

extension ProductProfile {
    static func egg() -> ProductProfile {
        ProductProfile(name: "Yumurta",
                       roi: CGRect(x: 0.05, y: 0.1, width: 0.9, height: 0.8),
                       linePosition: 0.5, direction: .down,
                       diffThreshold: 28, expectedArea: 0,
                       minAreaFactor: 0.35, minAreaAbs: 0.0008,
                       splitTouching: true, maxMultiplicity: 6,
                       closeIterations: 0, processingWidth: 240,
                       minHits: 2, maxMatchDistance: 0.10, backgroundRate: 0.02)
    }

    static func flourSack() -> ProductProfile {
        ProductProfile(name: "Un torbası",
                       roi: CGRect(x: 0.05, y: 0.05, width: 0.9, height: 0.9),
                       linePosition: 0.5, direction: .down,
                       diffThreshold: 22, expectedArea: 0,
                       minAreaFactor: 0.45, minAreaAbs: 0.01,
                       splitTouching: true, maxMultiplicity: 3,
                       closeIterations: 2, processingWidth: 160,
                       minHits: 2, maxMatchDistance: 0.20, backgroundRate: 0.02)
    }

    static func generic() -> ProductProfile {
        ProductProfile(name: "Genel ürün",
                       roi: CGRect(x: 0.05, y: 0.1, width: 0.9, height: 0.8),
                       linePosition: 0.5, direction: .down,
                       diffThreshold: 25, expectedArea: 0,
                       minAreaFactor: 0.4, minAreaAbs: 0.002,
                       splitTouching: false, maxMultiplicity: 4,
                       closeIterations: 1, processingWidth: 240,
                       minHits: 2, maxMatchDistance: 0.15, backgroundRate: 0.02)
    }
}
