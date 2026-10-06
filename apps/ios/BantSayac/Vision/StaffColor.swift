import Foundation

/// Öğretilen personel üniforma rengi: CIE Lab (D65). Sözleşme `staffColors` öğesi (algoritma §4.10 eki).
struct LabColor: Codable, Equatable, Hashable, Sendable {
    var L: Double
    var a: Double
    var b: Double
}

/// Personel rengi (algoritma §4.10 eki). Python referansı: services/edge/bantvision/core/staff_color.py —
/// davranış birebir aynı (BantSayacTests/StaffColorTests + staff_parity.json).
enum StaffColor {
    static let grid = 12
    static let matchDist = 20.0
    static let minFraction = 0.25
    static let minPoints = 36
    static let darkL = 8.0
    static let minVotes = 3
    static let achromaticC = 15.0
    static let commonDarkL = 30.0
    static let teachPatch = 0.06
    static let maxColors = 3
    static let minBoxPx = (w: 8.0, h: 16.0)

    private static func lin(_ v: UInt8) -> Double {
        let c = Double(v) / 255
        return c <= 0.04045 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4)
    }

    private static func f(_ t: Double) -> Double { t > 0.008856 ? cbrt(t) : 7.787 * t + 16.0 / 116.0 }

    static func lab(_ r: UInt8, _ g: UInt8, _ b: UInt8) -> LabColor {
        let R = lin(r), G = lin(g), B = lin(b)
        let x = (R * 0.4124564 + G * 0.3575761 + B * 0.1804375) / 0.95047
        let y = (R * 0.2126729 + G * 0.7151522 + B * 0.0721750) / 1.0
        let z = (R * 0.0193339 + G * 0.1191920 + B * 0.9503041) / 1.08883
        let fx = f(x), fy = f(y), fz = f(z)
        return LabColor(L: 116 * fy - 16, a: 500 * (fx - fy), b: 200 * (fy - fz))
    }

    /// Lab → sRGB (0–1), yalnızca ekranda örnek göstermek için
    static func srgb(from c: LabColor) -> (r: Double, g: Double, b: Double) {
        let fy = (c.L + 16) / 116, fx = fy + c.a / 500, fz = fy - c.b / 200
        func inv(_ t: Double) -> Double { t * t * t > 0.008856 ? t * t * t : (t - 16.0 / 116.0) / 7.787 }
        let X = 0.95047 * inv(fx), Y = inv(fy), Z = 1.08883 * inv(fz)
        func gamma(_ v: Double) -> Double { min(1, max(0, v <= 0.0031308 ? 12.92 * v : 1.055 * pow(v, 1 / 2.4) - 0.055)) }
        return (gamma(3.2404542 * X - 1.5371385 * Y - 0.4985314 * Z),
                gamma(-0.969266 * X + 1.8760108 * Y + 0.041556 * Z),
                gamma(0.0556434 * X - 0.2040259 * Y + 1.0572252 * Z))
    }

    static func torsoRegion(_ box: NBox, _ anchor: CountAnchor) -> NBox {
        let w = box.x2 - box.x1, h = box.y2 - box.y1
        let (t0, t1) = anchor == .bottom ? (0.15, 0.45) : (0.30, 0.70)
        return NBox(x1: box.x1 + 0.30 * w, y1: box.y1 + t0 * h, x2: box.x1 + 0.70 * w, y2: box.y1 + t1 * h)
    }

    static func gridPoints(_ r: NBox) -> [(x: Double, y: Double)] {
        let rw = r.x2 - r.x1, rh = r.y2 - r.y1, n = Double(grid)
        var out: [(x: Double, y: Double)] = []
        out.reserveCapacity(grid * grid)
        for j in 0..<grid {
            let y = r.y1 + (Double(j) + 0.5) / n * rh
            for i in 0..<grid { out.append((r.x1 + (Double(i) + 0.5) / n * rw, y)) }
        }
        return out
    }

    static func pixel(_ x: Double, _ y: Double, width: Int, height: Int) -> (Int, Int) {
        (min(max(Int(floor(x * Double(width))), 0), width - 1), min(max(Int(floor(y * Double(height))), 0), height - 1))
    }

    static func distance(_ p: LabColor, _ q: LabColor) -> Double {
        let dl = 0.5 * (p.L - q.L), da = p.a - q.a, db = p.b - q.b
        return (dl * dl + da * da + db * db).squareRoot()
    }

    static func voteLabs(_ labs: [LabColor], colors: [LabColor]) -> Bool? {
        guard labs.count >= minPoints, !colors.isEmpty else { return nil }
        let hits = labs.filter { p in p.L >= darkL && colors.contains { distance(p, $0) < matchDist } }.count
        return Double(hits) >= minFraction * Double(labs.count)
    }

    private static func inside(_ o: NBox, _ x: Double, _ y: Double) -> Bool { o.x1 <= x && x <= o.x2 && o.y1 <= y && y <= o.y2 }

    /// Bu karede tanımayla gözlenen kutunun oyu; `others`: aynı karedeki diğer tanıma kutuları (noktaları dışlanır)
    static func vote(box: NBox, others: [NBox], anchor: CountAnchor, colors: [LabColor], width: Int, height: Int,
                     rgbAt: (Int, Int) -> (UInt8, UInt8, UInt8)) -> Bool? {
        guard (box.x2 - box.x1) * Double(width) >= minBoxPx.w, (box.y2 - box.y1) * Double(height) >= minBoxPx.h else { return nil }
        let pts = gridPoints(torsoRegion(box, anchor)).filter { p in !others.contains { inside($0, p.x, p.y) } }
        guard pts.count >= minPoints else { return nil }
        let labs = pts.map { p -> LabColor in
            let (px, py) = pixel(p.x, p.y, width: width, height: height)
            let c = rgbAt(px, py)
            return lab(c.0, c.1, c.2)
        }
        return voteLabs(labs, colors: colors)
    }

    static func isStaff(votes: Int, staffVotes: Int) -> Bool { votes >= minVotes && 2 * staffVotes >= votes }

    /// Müşterilerde sık görülen renk: akromatik (siyah, beyaz, gri) ya da koyu (lacivert, koyu kahve) — yalnızca uyarı
    static func isAchromatic(_ c: LabColor) -> Bool { hypot(c.a, c.b) < achromaticC || c.L < commonDarkL }

    private static func median(_ v: [Double]) -> Double {
        let s = v.sorted(), n = s.count
        return n % 2 == 1 ? s[n / 2] : (s[n / 2 - 1] + s[n / 2]) / 2
    }

    /// (⌊a/8⌋, ⌊b/8⌋) kutucuklarından en kalabalığı (eşitlikte ilk görülen); o kutucuğun L, a, b medyanı
    static func dominant(_ labs: [LabColor]) -> LabColor? {
        guard !labs.isEmpty else { return nil }
        var order: [[Int]] = []
        var bins: [[Int]: [Int]] = [:]
        for (k, c) in labs.enumerated() {
            let key = [Int(floor(c.a / 8)), Int(floor(c.b / 8))]
            if bins[key] == nil { order.append(key) }
            bins[key, default: []].append(k)
        }
        var best = order[0]
        for key in order where bins[key]!.count > bins[best]!.count { best = key }
        let sel = bins[best]!.map { labs[$0] }
        let c = LabColor(L: median(sel.map(\.L)), a: median(sel.map(\.a)), b: median(sel.map(\.b)))
        return c.L < darkL ? nil : c
    }

    /// Tıklanan noktayı içeren en küçük kutunun gövdesi; kutu yoksa tıklanan yer çevresi. Çok karanlıksa nil
    static func teach(boxes: [NBox], point: (x: Double, y: Double), anchor: CountAnchor, width: Int, height: Int,
                      rgbAt: (Int, Int) -> (UInt8, UInt8, UInt8)) -> LabColor? {
        let containing = boxes.filter { inside($0, point.x, point.y) }
        let region: NBox
        if let b = containing.min(by: { $0.area < $1.area }) {
            region = torsoRegion(b, anchor)
        } else {
            let hx = teachPatch / 2, hy = teachPatch / 2 * Double(width) / Double(height)
            region = NBox(x1: max(0, point.x - hx), y1: max(0, point.y - hy), x2: min(1, point.x + hx), y2: min(1, point.y + hy))
        }
        let labs = gridPoints(region).map { p -> LabColor in
            let (px, py) = pixel(p.x, p.y, width: width, height: height)
            let c = rgbAt(px, py)
            return lab(c.0, c.1, c.2)
        }
        return dominant(labs)
    }
}
