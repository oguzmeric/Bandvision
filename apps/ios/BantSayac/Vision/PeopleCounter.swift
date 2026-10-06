import Foundation
import CoreVideo
import CoreGraphics
import Vision

/// İki yönlü geçiş sayımı (algoritma §4.10): tanıyıcı + hareket lekeleri + `MotTracker`.
/// Python referansı: services/edge/bantvision/core/detect_count.py

/// Profilin ilgi alanında mı (§2.0: dikdörtgen ∩ çokgen, çift-tek kuralı; Python `inside_roi` ile aynı)
func insideRoi(_ p: ProductProfile, _ x: Double, _ y: Double) -> Bool {
    let r = p.roi
    guard x >= Double(r.minX), x < Double(r.maxX), y >= Double(r.minY), y < Double(r.maxY) else { return false }
    guard let poly = p.roiPolygon, poly.count >= 3 else { return true }
    var inside = false
    let n = poly.count
    for k in 0..<n {
        let a = poly[k], b = poly[(k - 1 + n) % n]
        if (a.y > y) != (b.y > y) && x < (b.x - a.x) * (y - a.y) / (b.y - a.y) + a.x { inside.toggle() }
    }
    return inside
}

/// Çapa noktasının çizgiye işaretli uzaklığı (giriş yönü pozitif) ve çizimlik çizgi uçları (Python `side_function`)
func peopleSideFunction(_ p: ProductProfile, width: Int, height: Int)
    -> (side: (Double, Double) -> Double, line: (NormPoint, NormPoint)) {
    if let cl = p.countLine, let lf = LineFrame.build(a: cl.a, b: cl.b, width: width, height: height) {
        return ({ x, y in lf.toFrame(x, y).u }, (cl.a, cl.b))
    }
    let lp = Double(p.linePosition), r = p.roi, sign = p.direction.sign
    if p.direction.isVertical {
        return ({ _, y in sign * (y - lp) },
                (NormPoint(x: Double(r.minX), y: lp), NormPoint(x: Double(r.maxX), y: lp)))
    }
    return ({ x, _ in sign * (x - lp) },
            (NormPoint(x: lp, y: Double(r.minY)), NormPoint(x: lp, y: Double(r.maxY))))
}

/// Hareket lekeleri: küçük gri karede, yalnızca hareketsiz yerlerde güncellenen arka plana göre fark
/// (Python `MotionDetector`: eşik 22, açma 3×3, kapama 5×5, arka plan 0,05 / her yerde 0,002, en küçük alan %0,2).
final class MotionDetector {
    static let width = 160
    private let threshold: Float = 22
    private let minArea = 0.002
    private var bg: [Float] = []
    private var size = (w: 0, h: 0)

    func reset() { bg = [] }

    func detect(_ f: GrayFrame, profile: ProductProfile) -> [NBox] {
        let w = f.width, h = f.height, n = w * h
        let g = Self.blur5(f.pixels, w, h)
        if bg.count != n || size != (w, h) {
            bg = g
            size = (w, h)
            return []
        }
        var m = [UInt8](repeating: 0, count: n)
        for i in 0..<n where abs(g[i] - bg[i]) > threshold { m[i] = 1 }
        m = Self.morph(m, w, h, dilate: false, times: 1)        // açma 3×3
        m = Self.morph(m, w, h, dilate: true, times: 1)
        m = Self.morph(m, w, h, dilate: true, times: 2)         // kapama 5×5 (3×3 iki kez)
        m = Self.morph(m, w, h, dilate: false, times: 2)
        for i in 0..<n {
            if m[i] == 0 { bg[i] += 0.05 * (g[i] - bg[i]) }
            bg[i] += 0.002 * (g[i] - bg[i])
        }
        return Self.components(m, w, h, minPixels: minArea * Double(n)).filter {
            insideRoi(profile, ($0.x1 + $0.x2) / 2, ($0.y1 + $0.y2) / 2)
        }
    }

    /// 5×5 Gauss yaklaşığı (ayrılabilir 1-4-6-4-1, kenarda yansıtma)
    static func blur5(_ p: [UInt8], _ w: Int, _ h: Int) -> [Float] {
        let k: [Float] = [1, 4, 6, 4, 1]
        func ref(_ i: Int, _ n: Int) -> Int { i < 0 ? -i : (i >= n ? 2 * n - 2 - i : i) }
        var tmp = [Float](repeating: 0, count: w * h)
        for y in 0..<h {
            for x in 0..<w {
                var s: Float = 0
                for d in -2...2 { s += k[d + 2] * Float(p[y * w + ref(x + d, w)]) }
                tmp[y * w + x] = s / 16
            }
        }
        var out = [Float](repeating: 0, count: w * h)
        for y in 0..<h {
            for x in 0..<w {
                var s: Float = 0
                for d in -2...2 { s += k[d + 2] * tmp[ref(y + d, h) * w + x] }
                out[y * w + x] = s / 16
            }
        }
        return out
    }

    static func morph(_ src: [UInt8], _ w: Int, _ h: Int, dilate: Bool, times: Int) -> [UInt8] {
        var s = src
        for _ in 0..<times {
            var d = [UInt8](repeating: 0, count: w * h)
            for y in 0..<h {
                let ya = max(0, y - 1), yb = min(h - 1, y + 1)
                for x in 0..<w {
                    let xa = max(0, x - 1), xb = min(w - 1, x + 1)
                    var v: UInt8 = dilate ? 0 : 1
                    scan: for yy in ya...yb {
                        for xx in xa...xb {
                            let q = s[yy * w + xx]
                            if dilate, q != 0 { v = 1; break scan }
                            if !dilate, q == 0 { v = 0; break scan }
                        }
                    }
                    d[y * w + x] = v
                }
            }
            s = d
        }
        return s
    }

    static func components(_ m: [UInt8], _ w: Int, _ h: Int, minPixels: Double) -> [NBox] {
        var seen = [UInt8](repeating: 0, count: w * h)
        var out: [NBox] = []
        var stack: [Int] = []
        for start in 0..<(w * h) where m[start] != 0 && seen[start] == 0 {
            seen[start] = 1
            stack.append(start)
            var area = 0, minX = w, maxX = 0, minY = h, maxY = 0
            while let p = stack.popLast() {
                let px = p % w, py = p / w
                area += 1
                minX = min(minX, px); maxX = max(maxX, px); minY = min(minY, py); maxY = max(maxY, py)
                for dy in -1...1 {
                    let ny = py + dy
                    if ny < 0 || ny >= h { continue }
                    for dx in -1...1 {
                        let nx = px + dx
                        if nx < 0 || nx >= w || (dx == 0 && dy == 0) { continue }
                        let q = ny * w + nx
                        if m[q] != 0 && seen[q] == 0 { seen[q] = 1; stack.append(q) }
                    }
                }
            }
            if Double(area) >= minPixels {
                out.append(NBox(x1: Double(minX) / Double(w), y1: Double(minY) / Double(h),
                                x2: Double(maxX + 1) / Double(w), y2: Double(maxY + 1) / Double(h)))
            }
        }
        return out
    }
}

/// Apple Vision insan dikdörtgeni (cihaz üstünde, model indirmesi yok). Yalnızca ROI + %5 pay kesitinde arar.
final class HumanDetector {
    private let request: VNDetectHumanRectanglesRequest = {
        let r = VNDetectHumanRectanglesRequest()
        r.upperBodyOnly = false
        return r
    }()

    func detect(_ pb: CVPixelBuffer, profile: ProductProfile) -> [Detection] {
        let r = profile.roi
        let mx = 0.05 * r.width, my = 0.05 * r.height
        let x0 = max(0, r.minX - mx), y0 = max(0, r.minY - my)
        let x1 = min(1, r.maxX + mx), y1 = min(1, r.maxY + my)
        // Vision: sol alt köşe başlangıçlı normalize koordinat; sonuçlar ilgi alanına göre normalize
        let roiV = CGRect(x: x0, y: 1 - y1, width: x1 - x0, height: y1 - y0)
        request.regionOfInterest = roiV
        let handler = VNImageRequestHandler(cvPixelBuffer: pb, orientation: .up, options: [:])
        guard (try? handler.perform([request])) != nil, let results = request.results else { return [] }
        var out: [Detection] = []
        for o in results {
            let b = o.boundingBox
            let bx1 = Double(roiV.minX + b.minX * roiV.width)
            let bx2 = Double(roiV.minX + b.maxX * roiV.width)
            let by1 = Double(1 - (roiV.minY + b.maxY * roiV.height))
            let by2 = Double(1 - (roiV.minY + b.minY * roiV.height))
            let box = NBox(x1: bx1, y1: by1, x2: bx2, y2: by2)
            if insideRoi(profile, (bx1 + bx2) / 2, (by1 + by2) / 2) { out.append(Detection(box: box, score: Double(o.confidence))) }
        }
        return out
    }
}

/// Kare başına sonuç (çizim ve sayım)
struct PeopleFrame {
    var tracks: [MotTrack]
    var entered: [MotTrack]
    var exited: [MotTrack]
    var line: (NormPoint, NormPoint)
}

final class PeopleCounter {
    let tracker = MotTracker()
    private let motion = MotionDetector()
    private let detector = HumanDetector()

    func reset() {
        tracker.reset()
        motion.reset()
    }

    func process(_ pb: CVPixelBuffer, profile: ProductProfile, fps: Double) -> PeopleFrame? {
        guard let small = GrayFrame.make(from: pb, targetWidth: MotionDetector.width) else { return nil }
        tracker.p.minHits = max(1, profile.minHits)
        tracker.p.maxAge = max(5, roundHalfEven(fps * 1.0))
        tracker.p.high = max(profile.detectConfidence ?? 0.35, tracker.p.low + 0.05)
        let dets = detector.detect(pb, profile: profile)
        // Hareket desteği yalnızca tepeden kamerada (Python detect_count.py ile aynı): yatık/yandan kamerada tanıyıcı
        // kişiyi zaten bulur; kapı, ekran, gölge hareketi hayalet iz üretir.
        let blobs: [NBox]? = profile.anchor == .center ? motion.detect(small, profile: profile) : nil
        let (side, line) = peopleSideFunction(profile, width: small.sourceWidth, height: small.sourceHeight)
        let r = profile.roi
        let (ins, outs) = tracker.update(dets, sideOf: side, anchor: profile.anchor, motion: blobs,
                                         bounds: NBox(x1: Double(r.minX), y1: Double(r.minY),
                                                      x2: Double(r.maxX), y2: Double(r.maxY)))
        let seen = tracker.tracks.filter { $0.confirmed && $0.misses == 0 }
        return PeopleFrame(tracks: seen, entered: ins, exited: outs, line: line)
    }
}
