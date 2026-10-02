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

/// Normalize nokta (0...1). Sözleşmedeki `{x, y}` biçimiyle kodlanır (CGPoint dizi olarak kodlanırdı).
struct NormPoint: Codable, Equatable, Hashable {
    var x: Double
    var y: Double
}

/// Bir ürün tipi için tüm kalibrasyon ve algılama parametreleri.
/// Konum/alan değerleri normalize: 0...1 (görüntü boyutu ya da toplam alan oranı).
struct ProductProfile: Codable, Identifiable, Equatable {
    var id = UUID()
    var name: String
    /// İlgi alanı (ROI), normalize. Çokgen varsa onun sınır kutusu.
    var roi: CGRect
    /// İsteğe bağlı çokgen ROI (algoritma §2.0, 3–12 köşe). nil = dikdörtgen. Eski kayıtlarda yok → nil.
    var roiPolygon: [NormPoint]? = nil
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
    static let maxPolygonPoints = 12

    /// Çokgeni ayarlar; roi çokgenin sınır kutusu olur, sayım çizgisi kutunun içinde kalır. nil → dikdörtgene dön.
    mutating func setPolygon(_ points: [NormPoint]?) {
        guard let points, points.count >= 3 else {
            roiPolygon = nil
            return
        }
        let pts = points.prefix(Self.maxPolygonPoints).map {
            NormPoint(x: min(max($0.x, 0), 1), y: min(max($0.y, 0), 1))
        }
        roiPolygon = Array(pts)
        let xs = pts.map(\.x), ys = pts.map(\.y)
        let minX = xs.min() ?? 0, maxX = xs.max() ?? 1, minY = ys.min() ?? 0, maxY = ys.max() ?? 1
        roi = CGRect(x: minX, y: minY, width: max(maxX - minX, 0.01), height: max(maxY - minY, 0.01))
        let lo = direction.isVertical ? roi.minY : roi.minX
        let hi = direction.isVertical ? roi.maxY : roi.maxX
        linePosition = min(max(linePosition, lo + 0.02), max(lo + 0.02, hi - 0.02))
    }

    /// Dikdörtgenin dört köşesi (çokgen düzenlemeye başlangıç)
    var roiCorners: [NormPoint] {
        [NormPoint(x: roi.minX, y: roi.minY), NormPoint(x: roi.maxX, y: roi.minY),
         NormPoint(x: roi.maxX, y: roi.maxY), NormPoint(x: roi.minX, y: roi.maxY)]
    }

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
