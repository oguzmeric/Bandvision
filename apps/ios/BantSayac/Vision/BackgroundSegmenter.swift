import Foundation
import CoreGraphics

/// Bir karede bulunan ürün adayı (leke). Koordinatlar ve alan normalize.
struct Blob {
    var cx: Double
    var cy: Double
    var bbox: CGRect
    var area: Double
    var multiplicity: Int = 1
}

struct PixelRect {
    let x0: Int, y0: Int, x1: Int, y1: Int
}

/// Sabit kamera + bant için arka plan çıkarımı:
/// fark → eşik → açma/kapama → bağlı bileşenler.
final class BackgroundSegmenter {
    private(set) var width = 0
    private(set) var height = 0
    private var bg: [Float] = []
    private var mask: [UInt8] = []
    private var tmp: [UInt8] = []
    private(set) var lastMask: [UInt8]?
    // §2.0 ROI maskesi önbelleği (ROI ya da boyut değişince yeniden)
    private var roiMaskKey: RoiMaskKey?
    private var roiMaskCache: [UInt8] = []

    private struct RoiMaskKey: Equatable {
        let width: Int, height: Int
        let roi: CGRect
        let polygon: [NormPoint]?
    }

    var hasBackground: Bool { !bg.isEmpty }

    func reset() {
        bg = []
        lastMask = nil
    }

    private func ensureSize(_ w: Int, _ h: Int) {
        guard w != width || h != height else { return }
        width = w
        height = h
        bg = []
        mask = [UInt8](repeating: 0, count: w * h)
        tmp = mask
        lastMask = nil
    }

    func pixelRect(_ r: CGRect) -> PixelRect {
        Self.pixelRect(r, width: width, height: height)
    }

    static func pixelRect(_ r: CGRect, width: Int, height: Int) -> PixelRect {
        let w = Double(width), h = Double(height)
        let x0 = max(0, min(width - 1, Int(Double(r.minX) * w)))
        let y0 = max(0, min(height - 1, Int(Double(r.minY) * h)))
        let x1 = max(x0 + 1, min(width, Int(Double(r.maxX) * w)))
        let y1 = max(y0 + 1, min(height, Int(Double(r.maxY) * h)))
        return PixelRect(x0: x0, y0: y0, x1: x1, y1: y1)
    }

    /// §2.0 ROI maskesi (1 = içeride): dikdörtgen ∩ çokgen. Çokgen: piksel merkezi, çift-tek kuralı.
    /// İşlem sırası dokümandaki ve Python `roi_mask` ile aynı (aynı pikseller seçilir).
    static func roiMask(roi: CGRect, polygon: [NormPoint]?, width w: Int, height h: Int) -> [UInt8] {
        var m = [UInt8](repeating: 0, count: w * h)
        let r = pixelRect(roi, width: w, height: h)
        let poly = polygon ?? []
        let n = poly.count
        for y in r.y0..<r.y1 {
            let py = (Double(y) + 0.5) / Double(h)
            for x in r.x0..<r.x1 {
                guard n > 0 else { m[y * w + x] = 1; continue }
                let px = (Double(x) + 0.5) / Double(w)
                var inside = false
                for k in 0..<n {
                    let a = poly[k], b = poly[k == 0 ? n - 1 : k - 1]
                    if (a.y > py) != (b.y > py) {
                        let xc = (b.x - a.x) * (py - a.y) / (b.y - a.y) + a.x
                        if px < xc { inside.toggle() }
                    }
                }
                if inside { m[y * w + x] = 1 }
            }
        }
        return m
    }

    private func roiMask(_ roi: CGRect, _ polygon: [NormPoint]?) -> [UInt8] {
        let key = RoiMaskKey(width: width, height: height, roi: roi, polygon: polygon)
        if key != roiMaskKey || roiMaskCache.count != width * height {
            roiMaskCache = Self.roiMask(roi: roi, polygon: polygon, width: width, height: height)
            roiMaskKey = key
        }
        return roiMaskCache
    }

    /// Kalibrasyon: arka planı koşulsuz öğren. rate >= 1 → sıfırdan başlat.
    func learn(_ f: GrayFrame, rate: Float) {
        ensureSize(f.width, f.height)
        if bg.isEmpty || rate >= 1 {
            bg = f.pixels.map { Float($0) }
            return
        }
        let n = width * height
        f.pixels.withUnsafeBufferPointer { src in
            bg.withUnsafeMutableBufferPointer { b in
                for i in 0..<n { b[i] += rate * (Float(src[i]) - b[i]) }
            }
        }
    }

    /// ROI maskesi içinde |kare - arka plan| dağılımının yüzdelik değeri (gürültü ölçümü, §5).
    func diffPercentile(_ f: GrayFrame, roi: CGRect, polygon: [NormPoint]? = nil, percentile: Double) -> Int {
        guard !bg.isEmpty, f.width == width, f.height == height else { return 0 }
        let r = pixelRect(roi)
        let inside = roiMask(roi, polygon)
        var hist = [Int](repeating: 0, count: 256)
        var total = 0
        let w = width
        let px = f.pixels
        let b = bg
        for y in r.y0..<r.y1 {
            for x in r.x0..<r.x1 {
                let i = y * w + x
                if inside[i] == 0 { continue }
                let d = min(255, Int(abs(Float(px[i]) - b[i])))
                hist[d] += 1
                total += 1
            }
        }
        guard total > 0 else { return 0 }
        let target = Int(Double(total) * percentile)
        var acc = 0
        for v in 0..<256 {
            acc += hist[v]
            if acc >= target { return v }
        }
        return 255
    }

    func segment(_ f: GrayFrame, roi: CGRect, polygon: [NormPoint]? = nil, threshold: Int, closeIterations: Int,
                 backgroundRate: Float, keepMask: Bool) -> [Blob] {
        ensureSize(f.width, f.height)
        if bg.isEmpty {
            bg = f.pixels.map { Float($0) }
            return []
        }
        let w = width, n = width * height
        let r = pixelRect(roi)
        let th = Float(threshold)
        let inside = roiMask(roi, polygon)

        // 1) Fark + eşik (yalnızca ROI maskesi, §2.0)
        f.pixels.withUnsafeBufferPointer { src in
            bg.withUnsafeBufferPointer { b in
                inside.withUnsafeBufferPointer { roiM in
                    mask.withUnsafeMutableBufferPointer { m in
                        for i in 0..<n { m[i] = 0 }
                        for y in r.y0..<r.y1 {
                            var i = y * w + r.x0
                            for _ in r.x0..<r.x1 {
                                m[i] = roiM[i] != 0 && abs(Float(src[i]) - b[i]) > th ? 1 : 0
                                i += 1
                            }
                        }
                    }
                }
            }
        }

        // 2) Açma (gürültü temizliği) + kapama (parçalı ürünü birleştirme)
        morph(dilate: false)
        morph(dilate: true)
        for _ in 0..<max(0, closeIterations) {
            morph(dilate: true)
            morph(dilate: false)
        }

        // 3) Seçici arka plan güncellemesi (ürün altındaki pikseller çok yavaş)
        let rate = backgroundRate
        // §2.4: ürün altında çok yavaş; 0.05 yoğun akışta arka planı ürüne kaydırıp sayımı durduruyordu
        let fgRate = backgroundRate * 0.002
        f.pixels.withUnsafeBufferPointer { src in
            mask.withUnsafeBufferPointer { m in
                bg.withUnsafeMutableBufferPointer { b in
                    for i in 0..<n {
                        b[i] += (m[i] == 0 ? rate : fgRate) * (Float(src[i]) - b[i])
                    }
                }
            }
        }

        lastMask = keepMask ? mask : nil
        return components(in: r)
    }

    /// 3x3 erozyon / genişleme, sonuç mask'e yazılır.
    private func morph(dilate: Bool) {
        let w = width, h = height
        mask.withUnsafeBufferPointer { s in
            tmp.withUnsafeMutableBufferPointer { d in
                for y in 0..<h {
                    let ya = max(0, y - 1), yb = min(h - 1, y + 1)
                    for x in 0..<w {
                        let xa = max(0, x - 1), xb = min(w - 1, x + 1)
                        var v: UInt8 = dilate ? 0 : 1
                        scan: for yy in ya...yb {
                            let row = yy * w
                            for xx in xa...xb {
                                let p = s[row + xx]
                                if dilate {
                                    if p != 0 { v = 1; break scan }
                                } else if p == 0 {
                                    v = 0; break scan
                                }
                            }
                        }
                        d[y * w + x] = v
                    }
                }
            }
        }
        (mask, tmp) = (tmp, mask)
    }

    /// 8-komşuluk bağlı bileşen etiketleme.
    private func components(in r: PixelRect) -> [Blob] {
        let w = width, h = height, n = w * h
        let m = mask
        var visited = [UInt8](repeating: 0, count: n)
        var stack: [Int] = []
        stack.reserveCapacity(2048)
        var blobs: [Blob] = []
        let fw = Double(w), fh = Double(h)

        for y in r.y0..<r.y1 {
            for x in r.x0..<r.x1 {
                let start = y * w + x
                if m[start] == 0 || visited[start] != 0 { continue }
                visited[start] = 1
                stack.append(start)
                var area = 0, sx = 0, sy = 0
                var minX = x, maxX = x, minY = y, maxY = y

                while let p = stack.popLast() {
                    let px = p % w, py = p / w
                    area += 1; sx += px; sy += py
                    if px < minX { minX = px }
                    if px > maxX { maxX = px }
                    if py < minY { minY = py }
                    if py > maxY { maxY = py }
                    for dy in -1...1 {
                        let ny = py + dy
                        if ny < 0 || ny >= h { continue }
                        for dx in -1...1 {
                            let nx = px + dx
                            if nx < 0 || nx >= w || (dx == 0 && dy == 0) { continue }
                            let q = ny * w + nx
                            if m[q] != 0 && visited[q] == 0 {
                                visited[q] = 1
                                stack.append(q)
                            }
                        }
                    }
                }

                blobs.append(Blob(
                    cx: Double(sx) / Double(area) / fw,
                    cy: Double(sy) / Double(area) / fh,
                    bbox: CGRect(x: Double(minX) / fw, y: Double(minY) / fh,
                                 width: Double(maxX - minX + 1) / fw,
                                 height: Double(maxY - minY + 1) / fh),
                    area: Double(area) / Double(n)))
            }
        }
        return blobs
    }
}
