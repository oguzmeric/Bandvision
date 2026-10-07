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
    /// Ters yön (kişi sayımında giriş ↔ çıkış)
    var opposite: FlowDirection {
        switch self {
        case .down: return .up
        case .up: return .down
        case .right: return .left
        case .left: return .right
        }
    }
    /// Akış ekseninde ilerleme yönü: +1 (aşağı/sağa) ya da -1 (yukarı/sola).
    var sign: Double { (self == .down || self == .right) ? 1 : -1 }
}

/// Normalize nokta (0...1). Sözleşmedeki `{x, y}` biçimiyle kodlanır (CGPoint dizi olarak kodlanırdı).
struct NormPoint: Codable, Equatable, Hashable {
    var x: Double
    var y: Double
}

/// Açılı sayım çizgisi (algoritma §4.8): akış, a'dan b'ye yürürken sağ el tarafıdır.
struct CountLine: Codable, Equatable, Hashable {
    var a: NormPoint
    var b: NormPoint
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
    /// İsteğe bağlı açılı sayım çizgisi (§4.8). Varsa `direction`/`linePosition` sayımda kullanılmaz.
    var countLine: CountLine? = nil
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
    /// Sayım yöntemi (§4.9). nil = leke (eski kayıtlar). İsteğe bağlı: eski kayıtlar sorunsuz açılır.
    var countMode: CountMode? = nil
    /// Şerit tarama: tek ürünün akış boyunca boyu, ROI'nin akış uzunluğuna oranla. nil/0 = otomatik öğren.
    var productLength: Double? = nil
    /// Tanıma (§4.10): sayılan sınıflar (COCO adları; iPhone'da şimdilik yalnızca "person")
    var detectClasses: [String]? = nil
    /// Tanıma: yeni iz başlatan en düşük güven (nil = 0,35)
    var detectConfidence: Double? = nil
    /// Tanıma: çizgiye göre konum noktası (nil = merkez / tepeden)
    var countAnchor: CountAnchor? = nil
    /// Tanıma (kişi): personel üniforma renkleri (en çok 3). nil/boş = kapalı; bu renkteki kişinin geçişi müşteri sayılmaz
    var staffColors: [LabColor]? = nil
    /// Güvenlik (poz alarmı, `countMode == .safety`): yalnızca bilgisayardaki analiz sunucusunda çalışır. iPhone alanı
    /// yalnızca taşır (kaydedilince kaybolmasın); bu cihazda işlenmez.
    var safety: SafetyConfig? = nil
}

/// Poz güvenlik alarmı ayarları (sözleşme `safety`; yalnızca bilgisayardaki analiz sunucusunda çalışır)
struct SafetyConfig: Codable, Equatable, Sendable {
    struct Rule: Codable, Equatable, Sendable { var enabled: Bool; var seconds: Double }
    var handsUp: Rule
    var lying: Rule
    var sendImage: Bool
}

/// Sayım yöntemi (sözleşme `countMode`).
enum CountMode: String, Codable, CaseIterable, Identifiable {
    /// Arka plan farkı + izleme: ayrık ürünler (yumurta, meyve...)
    case blob
    /// Şerit tarama: tek sıra gelen bitişik/aralıklı hacimli ürünler (torba, koli)
    case linescan
    /// Nesne tanıma + iki yönlü geçiş (kişi): giriş ve çıkış ayrı sayılır
    case detect
    /// Poz güvenlik alarmı (eller yukarı, yerde yatan kişi): yalnızca bilgisayarda; iPhone yalnızca görüntüler
    case safety

    var id: String { rawValue }
    var title: String {
        switch self {
        case .blob: return "Ayrık ürün"
        case .linescan: return "Bitişik / hacimli"
        case .detect: return "Kişi (giriş/çıkış)"
        case .safety: return "Güvenlik (yalnızca bilgisayar)"
        }
    }

    /// Bant üstü ürün yöntemleri (kalibrasyondaki yöntem seçicisi); tanıma ayrı bir sayım türüdür
    static let beltModes: [CountMode] = [.blob, .linescan]
}

extension ProductProfile {
    static let maxPolygonPoints = 12

    var mode: CountMode { countMode ?? .blob }
    /// Tanıma: çizgiye göre konum noktası
    var anchor: CountAnchor { countAnchor ?? .center }
    /// İki yönlü sayım mı (giriş/çıkış)
    var isTwoWay: Bool { mode == .detect }
    /// Şerit taramada kullanılan ürün boyu (0 = öğrenilecek)
    var lineProductLength: Double { max(0, productLength ?? 0) }

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
        fitCountLineToArea()
    }

    /// Açılı çizgiyi açısını ve konumunu koruyarak alanın kenarından kenarına uzatır/kısaltır (alan büyüyünce çizgi
    /// de büyür). Yalnızca çizimi değiştirir: sayım çizginin doğrusuna bağlıdır, uçlarına değil. Ortası alanın
    /// dışındaysa dokunulmaz. Python `Profile.fit_count_line_to_area` ve paneldeki `fitCountLine` ile aynı.
    mutating func fitCountLineToArea() {
        guard let cl = countLine else { return }
        let pts = roiPolygon ?? roiCorners
        let mx = (cl.a.x + cl.b.x) / 2, my = (cl.a.y + cl.b.y) / 2
        let dx = cl.b.x - cl.a.x, dy = cl.b.y - cl.a.y
        guard hypot(dx, dy) > 1e-9, pts.count >= 3 else { return }
        var lo: Double?, hi: Double?
        for i in pts.indices {
            let p = pts[i], q = pts[(i + 1) % pts.count]
            let ex = q.x - p.x, ey = q.y - p.y
            let den = dx * ey - dy * ex
            if abs(den) < 1e-12 { continue }
            let wx = p.x - mx, wy = p.y - my
            let t = (wx * ey - wy * ex) / den                 // çizgi üzerindeki konum (orta 0, uçlar ±0,5)
            let s = (wx * dy - wy * dx) / den                 // kenar üzerindeki konum (0…1)
            guard s >= 0, s <= 1 else { continue }
            if t <= 0 { lo = max(lo ?? -.infinity, t) }
            if t >= 0 { hi = min(hi ?? .infinity, t) }
        }
        guard let lo, let hi, hi - lo > 1e-6 else { return }
        countLine = CountLine(a: NormPoint(x: mx + lo * dx, y: my + lo * dy), b: NormPoint(x: mx + hi * dx, y: my + hi * dy))
    }

    /// Açılı çizgiyi ayarlar; `direction` akışa en yakın eksene güncellenir (uyumluluk, ekrandaki ok).
    /// `aspect`: görüntü genişliği / yüksekliği. nil → düz çizgiye dön (çizginin ortası `linePosition` olur).
    mutating func setCountLine(_ line: CountLine?, aspect: Double) {
        guard let line else {
            if let old = countLine {
                let mid = direction.isVertical ? (old.a.y + old.b.y) / 2 : (old.a.x + old.b.x) / 2
                let lo = direction.isVertical ? roi.minY : roi.minX
                let hi = direction.isVertical ? roi.maxY : roi.maxX
                linePosition = min(max(CGFloat(mid), lo + 0.02), max(lo + 0.02, hi - 0.02))
            }
            countLine = nil
            return
        }
        let clamp = { (p: NormPoint) in NormPoint(x: min(max(p.x, 0), 1), y: min(max(p.y, 0), 1)) }
        countLine = CountLine(a: clamp(line.a), b: clamp(line.b))
        direction = LineFrame.nearestDirection(a: line.a, b: line.b, aspect: aspect)
    }

    /// Düz çizgiden açılı çizgiye geçerken başlangıç: aynı çizgi, aynı akış yönü (sağ el kuralıyla).
    var straightCountLine: CountLine {
        let p = Double(linePosition)
        switch direction {
        case .down: return CountLine(a: NormPoint(x: roi.minX, y: p), b: NormPoint(x: roi.maxX, y: p))
        case .up: return CountLine(a: NormPoint(x: roi.maxX, y: p), b: NormPoint(x: roi.minX, y: p))
        case .right: return CountLine(a: NormPoint(x: p, y: roi.maxY), b: NormPoint(x: p, y: roi.minY))
        case .left: return CountLine(a: NormPoint(x: p, y: roi.minY), b: NormPoint(x: p, y: roi.maxY))
        }
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
                       closeIterations: 2, processingWidth: 240,
                       minHits: 2, maxMatchDistance: 0.20, backgroundRate: 0.02,
                       countMode: .linescan)
    }

    /// Koli/kutu: tek sıra, çoğu zaman bitişik — şerit tarama (§4.9)
    static func box() -> ProductProfile {
        ProductProfile(name: "Koli / kutu",
                       roi: CGRect(x: 0.05, y: 0.05, width: 0.9, height: 0.9),
                       linePosition: 0.5, direction: .down,
                       diffThreshold: 22, expectedArea: 0,
                       minAreaFactor: 0.45, minAreaAbs: 0.01,
                       splitTouching: true, maxMultiplicity: 3,
                       closeIterations: 2, processingWidth: 240,
                       minHits: 2, maxMatchDistance: 0.20, backgroundRate: 0.02,
                       countMode: .linescan)
    }

    /// Mağaza girişi: kişi sayımı, iki yönlü (giriş = `direction` yönünde geçen). Python `Profile.people` ile aynı.
    static func people() -> ProductProfile {
        ProductProfile(name: "Mağaza girişi",
                       roi: CGRect(x: 0, y: 0, width: 1, height: 1),
                       linePosition: 0.55, direction: .down,
                       diffThreshold: 25, expectedArea: 0,
                       minAreaFactor: 0.4, minAreaAbs: 0.002,
                       splitTouching: false, maxMultiplicity: 4,
                       closeIterations: 1, processingWidth: 640,
                       minHits: 3, maxMatchDistance: 0.15, backgroundRate: 0.02,
                       countMode: .detect, detectClasses: ["person"], detectConfidence: 0.35, countAnchor: .center)
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
