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
        let w = Double(width), h = Double(height)
        let x0 = max(0, min(width - 1, Int(Double(r.minX) * w)))
        let y0 = max(0, min(height - 1, Int(Double(r.minY) * h)))
        let x1 = max(x0 + 1, min(width, Int(Double(r.maxX) * w)))
        let y1 = max(y0 + 1, min(height, Int(Double(r.maxY) * h)))
        return PixelRect(x0: x0, y0: y0, x1: x1, y1: y1)
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

    /// ROI içinde |kare - arka plan| dağılımının yüzdelik değeri (gürültü ölçümü).
    func diffPercentile(_ f: GrayFrame, roi: CGRect, percentile: Double) -> Int {
        guard !bg.isEmpty, f.width == width, f.height == height else { return 0 }
        let r = pixelRect(roi)
        var hist = [Int](repeating: 0, count: 256)
        var total = 0
        let w = width
        let px = f.pixels
        let b = bg
        for y in r.y0..<r.y1 {
            for x in r.x0..<r.x1 {
                let i = y * w + x
                let d = min(255, Int(abs(Float(px[i]) - b[i])))
                hist[d] += 1
                total += 1
            }
        }
        let target = Int(Double(total) * percentile)
        var acc = 0
        for v in 0..<256 {
            acc += hist[v]
            if acc >= target { return v }
        }
        return 255
    }

    func segment(_ f: GrayFrame, roi: CGRect, threshold: Int, closeIterations: Int,
                 backgroundRate: Float, keepMask: Bool) -> [Blob] {
        ensureSize(f.width, f.height)
        if bg.isEmpty {
            bg = f.pixels.map { Float($0) }
            return []
        }
        let w = width, n = width * height
        let r = pixelRect(roi)
        let th = Float(threshold)

        // 1) Fark + eşik (yalnızca ROI)
        f.pixels.withUnsafeBufferPointer { src in
            bg.withUnsafeBufferPointer { b in
                mask.withUnsafeMutableBufferPointer { m in
                    for i in 0..<n { m[i] = 0 }
                    for y in r.y0..<r.y1 {
                        var i = y * w + r.x0
                        for _ in r.x0..<r.x1 {
                            m[i] = abs(Float(src[i]) - b[i]) > th ? 1 : 0
                            i += 1
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
        let fgRate = backgroundRate * 0.05
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
