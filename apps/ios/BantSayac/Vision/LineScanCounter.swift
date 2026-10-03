import Foundation
import CoreGraphics

/// §4.9 Şerit tarama sayımı: tek sıra gelen hacimli ürünler (torba, koli). Arka plan kullanmaz; sayım çizgisi
/// çevresinde bandın kaymasını ölçer, çizgiden geçen satırların parlaklığını "geçen mesafe" ekseninde bir sinyale
/// ekler ve sinyaldeki çukurlardan (ek yeri, boşluk) ürünleri ayırır.
/// Python başvurusu: services/edge/bantvision/core/linescan.py — davranış birebir aynıdır.
/// Yalnızca tek kuyrukta (FrameProcessor.queue) kullanılır.
final class LineScanCounter {
    struct Event: Equatable {
        let id: Int
        let delta: Int
    }

    struct Marker {
        let id: Int
        let x: Double          // normalize görüntü koordinatı
        let y: Double
        let counted: Bool
    }

    static let minRoiLen = 8
    static let minContrast = 6.0
    static let seamProminence = 0.25
    static let lowLevel = 0.25
    static let confMin = 0.05
    static let loQ = 0.02
    static let reliableSegments = 4
    static let activeFrames = 10
    static let activeFraction = 0.25
    static let motionMin = 1.0

    private struct Stats {
        var lo: [Double]
        var med: [Double]
        var hi: [Double]
    }

    private struct Seg {
        let id: Int
        let centers: [Double]
    }

    /// Bekletilen kısa parça (§4.9.7)
    private struct Carry {
        let a: Int?
        let b: Int
        let ia: Int
        let ib: Int
        let id: Int
        let k: Int
    }

    private struct MaskKey: Equatable {
        let roi: CGRect
        let polygon: [NormPoint]?
        let width: Int
        let height: Int
        let vertical: Bool
    }

    private var maskKey: MaskKey?
    private var mask: [UInt8] = []

    // Durum (Python `reset` ile aynı alanlar)
    private var prev: [Double]?
    private var prevStats: Stats?
    private var line = 0
    private var n = 0
    private var acc = 0.0
    private var key: [Double]?
    private var base = 0.0
    private var dist = 0.0
    private var vel = 0.0
    private var sig: [Double] = []
    private var pend: [(Double, Double)] = []
    private var carry: Carry?
    private var oId = 0
    private var oIa: Int?
    private var oIb = 0
    private var oK = 0
    private var low: Double?
    private var off = 0
    private var start = 0
    private var end: Int?
    private var scan = 0
    private var lastSeam: Int?
    private var pPitch = 0.0
    private var pLen = 0.0
    private var learnAt = 0
    private var tryAt = 0
    private var nextId = 1
    private var segs: [Seg] = []
    private(set) var failed = false
    private var polarity = 0
    private var votes = 0
    private var lastShift = 0.0
    // §4.9.0 Hareketli bölge (tam sıfırlamada yeniden seçilir)
    private var active: [UInt8]?
    private var bounds: PixelRect?
    private var wPrev: GrayFrame?
    private var wMaps: [[Double]] = []
    private var wFrames: [GrayFrame] = []

    init() { reset() }

    /// Tam sıfırlama: hareketli bölge de yeniden seçilir.
    func reset() {
        active = nil
        bounds = nil
        wPrev = nil
        wMaps = []
        wFrames = []
        resetScan()
    }

    private func resetScan() {
        prev = nil; prevStats = nil; line = 0; n = 0; acc = 0
        key = nil; base = 0; dist = 0; vel = 0
        sig = []; pend = []; carry = nil
        oId = 0; oIa = nil; oIb = 0; oK = 0; low = nil
        off = 0; start = 0; end = nil; scan = 0; lastSeam = nil
        pPitch = 0; pLen = 0; learnAt = 0; tryAt = 0; nextId = 1; segs = []
        failed = false; polarity = 0; votes = 0; lastShift = 0
    }

    // MARK: - Dış arayüz

    /// Öğrenilen/kullanılan ürün boyu (hareketli bölgenin akış uzunluğuna oranla; 0 = henüz yok)
    var productLength: Double { n > 0 && pLen > 0 ? pLen / Double(n) : 0 }

    /// Son karede bant hareket etti mi (§8)
    var moving: Bool { lastShift > 0.05 }

    func process(_ f: GrayFrame, profile: ProductProfile) -> [Event] {
        let k = MaskKey(roi: profile.roi, polygon: profile.roiPolygon, width: f.width, height: f.height,
                        vertical: profile.direction.isVertical)
        if k != maskKey {
            maskKey = k
            mask = BackgroundSegmenter.roiMask(roi: profile.roi, polygon: profile.roiPolygon,
                                               width: f.width, height: f.height)
            reset()
        }
        if active != nil { return processActive(f, profile: profile) }
        // §4.9.0 Önce hangi sütunların hareket ettiğini öğren. İlk kare ve hareketli kareler saklanır; bölge
        // bulununca baştan işlenir (öğrenme sırasında çizgiyi geçen ürün kaçmaz).
        if let wp = wPrev {
            if wp.width == f.width && wp.height == f.height {
                let mm = Self.motionMap(f, wp, mask: mask)
                if Self.frameMoving(mm, width: f.width, height: f.height, profile: profile) {
                    wMaps.append(mm)
                    wFrames.append(f)
                }
            }
        } else {
            wFrames.append(f)
        }
        wPrev = f
        guard wMaps.count >= Self.activeFrames else { return [] }
        // Piksel başına alt medyan: siyah kare, sahne geçişi gibi tek tük kareler seçimi bozmasın
        let count = wMaps[0].count
        var med = [Double](repeating: 0, count: count)
        var col = [Double](repeating: 0, count: wMaps.count)
        for i in 0..<count {
            for j in 0..<wMaps.count { col[j] = wMaps[j][i] }
            col.sort()
            med[i] = col[(Self.activeFrames - 1) / 2]
        }
        guard let region = Self.activeRegion(med, width: f.width, height: f.height, profile: profile, mask: mask) else {
            wMaps = []
            wFrames = [f]
            return []
        }
        active = region.mask
        bounds = region.bounds
        let frames = wFrames
        wFrames = []
        wMaps = []
        var events: [Event] = []
        for fr in frames { events += processActive(fr, profile: profile) }
        return events
    }

    private func processActive(_ f: GrayFrame, profile: ProductProfile) -> [Event] {
        guard let act = active, let bd = bounds else { return [] }
        guard let fp = Self.flowProfile(f, profile: profile, mask: act, bounds: bd) else { return [] }
        let stats = fp.stats, ln = fp.line
        let prof = stats.med
        if polarity == 0 {
            votes += Self.polarityVote(f, profile: profile, mask: act, line: ln, bounds: bd)
        }
        guard let prevProf = prev, prevProf.count == prof.count, ln == line else {
            begin(stats, line: ln, profile: profile)
            return []
        }
        // Anahtar kareye göre ölç: kare kare yuvarlama hataları birikmez (tekrarlanan karelerde artış 0)
        let d: Double
        if let keyProf = key, let m = Self.matchShift(key: keyProf, cur: prof, line: ln) {
            d = base + m.s
            if m.s >= Double(m.smax) / 2 {
                key = prof
                base = d
            }
        } else {
            d = dist + vel
            key = prof
            base = d
        }
        let inc = max(0, d - dist)
        vel = inc
        dist = max(dist, d)
        lastShift = inc
        acc += inc
        var q = Int(acc.rounded(.down))
        acc -= Double(q)
        q = min(q, n - ln)
        if q > 0 {
            for j in 0..<q {                       // bu karede çizgiyi geçen q satır, önce geçen önce
                let r = ln + q - 1 - j
                push(stats.lo[r], stats.hi[r])
            }
        }
        prev = prof
        prevStats = stats
        return advance(profile, final: false)
    }

    /// Video sonu: son karede çizgiye henüz varmamış kısım eklenir, merkezi geçmiş ürünler sayılır.
    func flush(profile: ProductProfile) -> [Event] {
        guard prev != nil, end == nil, let st = prevStats else { return [] }
        end = total
        var k = line - 1
        while k >= 0 {
            push(st.lo[k], st.hi[k])
            k -= 1
        }
        return advance(profile, final: true)
    }

    /// Son sayılan ürünlerin şimdiki konumu (çizgiden geçtikleri mesafe kadar ileride).
    func markers(width w: Int, height h: Int, profile: ProductProfile) -> [Marker] {
        guard prev != nil else { return [] }
        let r = bounds ?? BackgroundSegmenter.pixelRect(profile.roi, width: w, height: h)
        let emitted = Double(end ?? total)
        let forward = profile.direction == .down || profile.direction == .right
        var items: [(Int, Double, Bool)] = []
        for seg in segs {
            for (q, c) in seg.centers.enumerated() { items.append((seg.id * 16 + q, c, inRange(c))) }
        }
        if let c = carry, c.k > 0 {
            for q in 0..<c.k { items.append((c.id * 16 + q, Double(c.ia) + (Double(q) + 0.5) * pLen, true)) }
        }
        if let ia = oIa, oK > 0 {
            for q in 0..<oK { items.append((oId * 16 + q, Double(ia) + (Double(q) + 0.5) * pLen, true)) }
        }
        var out: [Marker] = []
        for (mid, c, counted) in items {
            let k = Double(line) + (emitted - c)
            guard k >= 0, k < Double(n) else { continue }
            if profile.direction.isVertical {
                let yy = forward ? Double(r.y0) + k + 0.5 : Double(r.y1 - 1) - k + 0.5
                out.append(Marker(id: mid, x: Double(r.x0 + r.x1) / 2 / Double(w), y: yy / Double(h), counted: counted))
            } else {
                let xx = forward ? Double(r.x0) + k + 0.5 : Double(r.x1 - 1) - k + 0.5
                out.append(Marker(id: mid, x: xx / Double(w), y: Double(r.y0 + r.y1) / 2 / Double(h), counted: counted))
            }
        }
        return out
    }

    // MARK: - Hareketli bölge (§4.9.0)

    /// |kare − önceki kare|, ROI maskesi dışı 0
    private static func motionMap(_ f: GrayFrame, _ prev: GrayFrame, mask: [UInt8]) -> [Double] {
        var out = [Double](repeating: 0, count: f.pixels.count)
        for i in 0..<out.count where mask[i] != 0 {
            out[i] = Double(abs(Int(f.pixels[i]) - Int(prev.pixels[i])))
        }
        return out
    }

    /// Kare hareketli mi: ROI içinde akışa dik en hareketli konumun ortalama farkı ≥ motionMin
    /// (Python: ROI dikdörtgenindeki tüm satırlar/sütunlar üzerinden ortalama)
    private static func frameMoving(_ m: [Double], width w: Int, height h: Int, profile: ProductProfile) -> Bool {
        let r = BackgroundSegmenter.pixelRect(profile.roi, width: w, height: h)
        var best = 0.0
        if profile.direction.isVertical {
            for x in r.x0..<r.x1 {
                var s = 0.0
                for y in r.y0..<r.y1 { s += m[y * w + x] }
                best = max(best, s / Double(max(1, r.y1 - r.y0)))
            }
        } else {
            for y in r.y0..<r.y1 {
                var s = 0.0
                for x in r.x0..<r.x1 { s += m[y * w + x] }
                best = max(best, s / Double(max(1, r.x1 - r.x0)))
            }
        }
        return best >= motionMin
    }

    /// Hareketli bölge: ROI içinde akışa dik konumlar (dikey akışta sütunlar), ortalama hareketi en hareketlinin
    /// activeFraction'ı kadar olanlar. Akış ekseninde kırpılmaz.
    private static func activeRegion(_ motion: [Double], width w: Int, height h: Int, profile: ProductProfile,
                                     mask: [UInt8]) -> (mask: [UInt8], bounds: PixelRect)? {
        let r = BackgroundSegmenter.pixelRect(profile.roi, width: w, height: h)
        let vertical = profile.direction.isVertical
        let len = vertical ? r.x1 - r.x0 : r.y1 - r.y0
        var cross = [Double](repeating: 0, count: len)
        for i in 0..<len {
            var s = 0.0, c = 0
            if vertical {
                let x = r.x0 + i
                for y in r.y0..<r.y1 where mask[y * w + x] != 0 { s += motion[y * w + x]; c += 1 }
            } else {
                let y = r.y0 + i
                for x in r.x0..<r.x1 where mask[y * w + x] != 0 { s += motion[y * w + x]; c += 1 }
            }
            cross[i] = c > 0 ? s / Double(c) : 0
        }
        guard let mx = cross.max(), mx > 0 else { return nil }
        let sel = cross.map { $0 >= activeFraction * mx }
        guard let c0 = sel.firstIndex(of: true), let cl = sel.lastIndex(of: true) else { return nil }
        var out = [UInt8](repeating: 0, count: w * h)
        for y in r.y0..<r.y1 {
            for x in r.x0..<r.x1 where mask[y * w + x] != 0 && sel[vertical ? x - r.x0 : y - r.y0] {
                out[y * w + x] = 1
            }
        }
        let b = vertical
            ? PixelRect(x0: r.x0 + c0, y0: r.y0, x1: r.x0 + cl + 1, y1: r.y1)
            : PixelRect(x0: r.x0, y0: r.y0 + c0, x1: r.x1, y1: r.y0 + cl + 1)
        return (out, b)
    }

    // MARK: - Profil, kayma, oy (§4.9.1, .2, .4)

    private static func flowProfile(_ f: GrayFrame, profile: ProductProfile, mask: [UInt8], bounds r: PixelRect)
        -> (stats: Stats, line: Int)? {
        let w = f.width, h = f.height
        let vertical = profile.direction.isVertical
        let lo = vertical ? r.y0 : r.x0
        let hi = vertical ? r.y1 : r.x1
        let count = hi - lo
        guard count >= minRoiLen else { return nil }
        var sLo = [Double](repeating: 0, count: count)
        var sMed = sLo, sHi = sLo
        var last = (0.0, 0.0, 0.0)
        var hist = [Int](repeating: 0, count: 256)
        f.pixels.withUnsafeBufferPointer { px in
            mask.withUnsafeBufferPointer { mk in
                for i in 0..<count {
                    for b in 0..<256 { hist[b] = 0 }
                    var cnt = 0
                    if vertical {
                        let row = (lo + i) * w
                        for x in r.x0..<r.x1 where mk[row + x] != 0 {
                            hist[Int(px[row + x])] += 1
                            cnt += 1
                        }
                    } else {
                        let x = lo + i
                        for y in r.y0..<r.y1 where mk[y * w + x] != 0 {
                            hist[Int(px[y * w + x])] += 1
                            cnt += 1
                        }
                    }
                    if cnt > 0 {
                        let m = cnt - 1
                        last = (Self.kth(hist, m / 4), Self.kth(hist, m / 2), Self.kth(hist, (3 * m) / 4))
                    }
                    sLo[i] = last.0
                    sMed[i] = last.1
                    sHi[i] = last.2
                }
            }
        }
        let forward = profile.direction == .down || profile.direction == .right
        if !forward {
            sLo.reverse(); sMed.reverse(); sHi.reverse()
        }
        let b = Int((Double(profile.linePosition) * Double(vertical ? h : w) + 0.5).rounded(.down))
        var ln = forward ? b - lo : hi - b
        ln = min(max(ln, 2), count - 2)
        return (Stats(lo: sLo, med: sMed, hi: sHi), ln)
    }

    /// Histogramda sıralı dizinin `k`. elemanı (0 tabanlı)
    private static func kth(_ hist: [Int], _ k: Int) -> Double {
        var c = 0
        for v in 0..<256 {
            c += hist[v]
            if c > k { return Double(v) }
        }
        return 255
    }

    private static func matchShift(key: [Double], cur: [Double], line: Int) -> (s: Double, smax: Int)? {
        let count = cur.count
        let win = max(4, count / 8)
        let smax = max(2, count / 6)
        let ka = max(smax, line - win), kb = min(count, line + win)
        guard kb - ka >= 4 else { return nil }
        var errs = [Double](repeating: 0, count: smax + 1)
        for s in 0...smax {
            var sum = 0.0
            for k in ka..<kb {
                let d = cur[k] - key[k - s]
                sum += d * d
            }
            errs[s] = sum / Double(kb - ka)
        }
        var k = 0
        for s in 1...smax where errs[s] < errs[k] { k = s }
        let meanE = errs.reduce(0, +) / Double(errs.count)
        if (meanE - errs[k]) / (meanE + 1e-6) < confMin { return nil }
        var s = Double(k)
        if k > 0 && k < smax {
            let a = errs[k - 1], b = errs[k], c = errs[k + 1]
            let d = a - 2 * b + c
            if d > 1e-9 { s = Double(k) + 0.5 * (a - c) / d }
        }
        return (s, smax)
    }

    private static func lowerMedian(_ v: [Double]) -> Double {
        let s = v.sorted()
        return s[(s.count - 1) / 2]
    }

    /// Ürün banttan açık mı (+1) koyu mu (−1)? ROI ortası (%30–%70) ile kenarları (%15'er), çizgi çevresi 5 satır.
    private static func polarityVote(_ f: GrayFrame, profile: ProductProfile, mask: [UInt8], line: Int,
                                     bounds r: PixelRect) -> Int {
        let w = f.width
        let forward = profile.direction == .down || profile.direction == .right
        var center: [Double] = [], sides: [Double] = []
        if profile.direction.isVertical {
            let c = forward ? r.y0 + line : r.y1 - 1 - line
            let r0 = max(r.y0, c - 2), r1 = min(r.y1, c + 3)
            let wd = r.x1 - r.x0
            let side = max(1, (15 * wd) / 100)
            let c0 = (3 * wd) / 10, c1 = wd - (3 * wd) / 10
            guard c1 > c0, r1 > r0 else { return 0 }
            for y in r0..<r1 {
                for i in 0..<wd {
                    let idx = y * w + r.x0 + i
                    guard mask[idx] != 0 else { continue }
                    if i >= c0 && i < c1 { center.append(Double(f.pixels[idx])) }
                    if i < side || i >= wd - side { sides.append(Double(f.pixels[idx])) }
                }
            }
        } else {
            let c = forward ? r.x0 + line : r.x1 - 1 - line
            let r0 = max(r.x0, c - 2), r1 = min(r.x1, c + 3)
            let wd = r.y1 - r.y0
            let side = max(1, (15 * wd) / 100)
            let c0 = (3 * wd) / 10, c1 = wd - (3 * wd) / 10
            guard c1 > c0, r1 > r0 else { return 0 }
            for x in r0..<r1 {
                for i in 0..<wd {
                    let idx = (r.y0 + i) * w + x
                    guard mask[idx] != 0 else { continue }
                    if i >= c0 && i < c1 { center.append(Double(f.pixels[idx])) }
                    if i < side || i >= wd - side { sides.append(Double(f.pixels[idx])) }
                }
            }
        }
        guard !center.isEmpty, !sides.isEmpty else { return 0 }
        let diff = lowerMedian(center) - lowerMedian(sides)
        return abs(diff) <= 15 ? 0 : (diff > 0 ? 1 : -1)
    }

    // MARK: - Sinyal

    private func begin(_ stats: Stats, line ln: Int, profile: ProductProfile) {
        let count = stats.med.count
        let keepLen = n == count ? pLen : 0
        let keepPol = n == count ? polarity : 0
        resetScan()
        prev = stats.med
        prevStats = stats
        line = ln
        n = count
        key = stats.med
        if keepLen > 0 && profile.lineProductLength <= 0 {
            pLen = keepLen
            pPitch = keepLen
        }
        polarity = keepPol
        // Başlangıçta çizgiyi zaten geçmiş kısım (en uzaktaki en önce geçmiştir)
        var k = count - 1
        while k >= ln {
            push(stats.lo[k], stats.hi[k])
            k -= 1
        }
        start = total
        learnAt = start + 2 * n
    }

    private func push(_ lo: Double, _ hi: Double) {
        if polarity == 0 {
            pend.append((lo, hi))
        } else {
            sig.append(polarity > 0 ? hi : 255 - lo)
        }
    }

    private var total: Int { off + sig.count + pend.count }

    private func sm(_ i: Int, _ r: Int) -> Double {
        let a = max(off, i - r) - off
        let b = min(off + sig.count, i + r + 1) - off
        var s = 0.0
        for j in a..<b { s += sig[j] }
        return s / Double(b - a)
    }

    private func inRange(_ c: Double) -> Bool {
        c >= Double(start) && (end == nil || c < Double(end!))
    }

    // MARK: - Yön kararı ve ürün boyu (§4.9.4, .5)

    private func ensurePeriod(_ profile: ProductProfile, final: Bool) -> Bool {
        let tot = total
        let known = profile.lineProductLength > 0
        if polarity == 0 {
            // En erken bir alan boyu bant aktıktan sonra; boy bilinmiyorsa iki alan boyuna kadar yalnızca
            // güvenilir sonuç (≥ 4 tam ürün, tutarlı boylar) kabul edilir
            if tot < start + n && !final { return false }
            if known || final || tot >= start + 2 * n {
                _ = decidePolarity(profile, strict: false)
            } else {
                if tot < tryAt { return false }
                tryAt = tot + max(4, n / 2)
                if !decidePolarity(profile, strict: true) { return false }
            }
        }
        if known {
            pLen = profile.lineProductLength * Double(n)
            pPitch = pLen
            return true
        }
        if pLen > 0 { return true }
        if tot < learnAt && !final { return false }
        guard let r = learn() else {
            learnAt = tot + n
            if final { failed = true }
            return false
        }
        pLen = r.p
        pPitch = r.p
        return true
    }

    @discardableResult
    private func decidePolarity(_ profile: ProductProfile, strict: Bool) -> Bool {
        let pd = pend
        pend = []
        func reliable(_ r: (p: Double, res: Double, count: Int)?) -> Bool {
            guard let r else { return false }
            return r.count >= Self.reliableSegments && r.res <= 0.15
        }
        func rollback() -> Bool {
            pend = pd
            sig = []
            polarity = 0
            return false
        }
        let forced = Self.spreadPolarity(pd)
        if forced != 0 {
            // Kesin ipucu: ürün satırında kenarlarda bant görünür (satır içi yayılım büyük), boş bant satırı düzdür
            sig = pd.map { forced > 0 ? $0.1 : 255 - $0.0 }
            if profile.lineProductLength <= 0 {
                let r = learn()
                if strict && !reliable(r) { return rollback() }
                if let r {
                    pLen = r.p
                    pPitch = r.p
                }
            }
            polarity = forced
            return true
        }
        var best: (res: Double, pol: Int, p: Double, count: Int)?
        for pol in [1, -1] {
            sig = pd.map { pol > 0 ? $0.1 : 255 - $0.0 }
            var r: (p: Double, res: Double, count: Int)?
            if profile.lineProductLength > 0 {
                let plen = profile.lineProductLength * Double(n)
                if let res = residual(max(4, Self.roundEven(plen)), off + sig.count) { r = (plen, res, 0) }
            } else {
                r = learn()
            }
            guard let rr = r else { continue }
            if best == nil || rr.res < best!.res - 0.03 {
                best = (rr.res, pol, rr.p, rr.count)
            } else if abs(rr.res - best!.res) <= 0.03 {
                let votePol = votes < 0 ? -1 : 1
                if pol == votePol { best = (rr.res, pol, rr.p, rr.count) }
            }
        }
        if strict {
            guard let b = best, reliable((b.p, b.res, b.count)) else { return rollback() }
        }
        polarity = best?.pol ?? (votes < 0 ? -1 : 1)
        sig = pd.map { polarity > 0 ? $0.1 : 255 - $0.0 }
        if let b = best, profile.lineProductLength <= 0 {
            pLen = b.p
            pPitch = b.p
        }
        return true
    }

    private func residual(_ pp: Int, _ tot: Int) -> Double? {
        let lens = segLengths(pp, tot)
        guard lens.count >= 2 else { return nil }
        var s = 0.0
        for v in lens {
            let x = Double(v) / Double(pp)
            s += abs(x - Double(max(1, Self.roundEven(x))))
        }
        return s / Double(lens.count)
    }

    private func learn() -> (p: Double, res: Double, count: Int)? {
        let x = sig
        let cnt = x.count
        let pmin = max(4, n / 10)
        let pmax = min(n, cnt / 2)
        var cands: [Double] = []
        let mean = x.reduce(0, +) / Double(max(1, cnt))
        var bestAc: (lag: Double, power: Double)?
        for s in [x.map { $0 - mean }, Self.highpass(x, max(2, pmin / 2))] {
            if let r = Self.autocorrPeak(s, pmin, pmax), bestAc == nil || r.power > bestAc!.power { bestAc = r }
        }
        if let b = bestAc { cands.append(b.lag) }
        if let run = Self.runMedian(x, pmin) { cands.append(run) }
        guard !cands.isEmpty else { return nil }
        let tot = off + cnt
        for c in cands {
            let lens = segLengths(max(4, Self.roundEven(c)), tot)
            if lens.count >= 2 { cands.append(Double(lens[(lens.count - 1) / 2])) }
        }
        var scored: [Int: Double] = [:]
        for c in cands {
            let q = max(4, Self.roundEven(c))
            if q < pmin { continue }                 // alanın onda birinden kısa "ürün" kıvrım/etiket parçasıdır
            if scored[q] == nil { scored[q] = residual(q, tot) ?? 1.0 }
        }
        guard !scored.isEmpty else { return nil }
        let good = scored.filter { $0.value <= 0.15 }.map(\.key)
        let q: Int
        if let g = good.max() {
            q = g
        } else {
            q = scored.min { ($0.value, $0.key) < ($1.value, $1.key) }!.key
        }
        return (Double(q), scored[q]!, segLengths(q, tot).count)
    }

    private func segLengths(_ pp: Int, _ tot: Int) -> [Int] {
        let parts = detect(pp, off, tot)
        guard parts.count > 2 else { return [] }
        return parts[1..<(parts.count - 1)]
            .map { $0.ib - $0.ia }
            .filter { Double($0) >= 0.3 * Double(pp) }
            .sorted()
    }

    // MARK: - Ek yeri taraması ve parçalar (§4.9.6–.9)

    /// §4.9.6 (lo, kontrast, ürün eşiği): lo = %2'lik, kontrast = %90'lık − lo, eşik = lo + 0,25·kontrast
    private static func levels(_ window: [Double]) -> (lo: Double, contrast: Double, low: Double) {
        let lo = percentileLower(window, loQ)
        let contrast = percentileLower(window, 0.90) - lo
        return (lo, contrast, lo + lowLevel * contrast)
    }

    /// i ek yeri mi? (a) dar çukur: yerel en küçük, derinliği ≥ 0,25·kontrast; (b) düşen kenar: sinyal ürün
    /// eşiğinin altına iner (aralıklı ürünlerde uzun boş bant). Yeterli ileri veri yoksa nil.
    private func seamAt(_ i: Int, _ pp: Int, _ tot: Int, final: Bool) -> (ok: Bool, low: Double, contrast: Double)? {
        let r = pp / 50
        let half = max(1, pp / 3)
        let hp = max(1, pp / 2)
        if !final && i + hp + r >= tot { return nil }
        let v = sm(i, r)
        let vPrev: Double? = i - 1 >= off ? sm(i - 1, r) : nil
        let loI = max(off, i - half), hiI = min(tot - 1, i + half)
        var localMin = true
        for j in loI...hiI {
            let sj = sm(j, r)
            if sj < v || (j < i && sj <= v) {
                localMin = false
                break
            }
        }
        if !localMin && (vPrev == nil || v >= vPrev!) { return (false, 0, 0) }
        let wa = max(off, i - 4 * pp), wb = min(tot, i + hp + 1)
        var window: [Double] = []
        window.reserveCapacity(wb - wa)
        for j in wa..<wb { window.append(sm(j, r)) }
        let lv = Self.levels(window)
        if lv.contrast < Self.minContrast { return (false, lv.low, lv.contrast) }
        if let vp = vPrev, v <= lv.low && lv.low < vp { return (true, lv.low, lv.contrast) }   // (b) düşen kenar
        if !localMin { return (false, lv.low, lv.contrast) }
        var lmax = -Double.infinity, rmax = -Double.infinity
        for j in max(off, i - hp)...i { lmax = max(lmax, sm(j, r)) }
        for j in i...min(tot - 1, i + hp) { rmax = max(rmax, sm(j, r)) }
        return (min(lmax, rmax) - v >= Self.seamProminence * lv.contrast, lv.low, lv.contrast)
    }

    private func detect(_ pp: Int, _ a0: Int, _ tot: Int) -> [(a: Int, b: Int, ia: Int, ib: Int)] {
        let half = max(1, pp / 3)
        var seams: [Int] = []
        var out: [(a: Int, b: Int, ia: Int, ib: Int)] = []
        var prevSeam = a0
        var i = a0
        while i < tot {
            defer { i += 1 }
            guard let res = seamAt(i, pp, tot, final: true), res.ok else { continue }
            if let last = seams.last, i - last < half { continue }
            if let br = bright(prevSeam, i, pp, res.low) {
                out.append((prevSeam, i, br.ia, br.ib))
            }
            seams.append(i)
            prevSeam = i
        }
        return out
    }

    /// Ürün kısmı: [a, b) içinde eşiğin üstündeki, en az max(2, 0,15·pp) uzunluktaki koşuların ilk ve son indeksi
    private func bright(_ a: Int, _ b: Int, _ pp: Int, _ lowThr: Double) -> (ia: Int, ib: Int)? {
        let r = pp / 50
        let minRun = max(2, Self.roundEven(0.15 * Double(pp)))
        var first: Int?, last = 0
        var runStart: Int?
        var j = a
        while j <= b {
            let above = j < b && sm(j, r) > lowThr
            if above && runStart == nil {
                runStart = j
            } else if !above, let rs = runStart {
                if j - rs >= minRun {
                    if first == nil { first = rs }
                    last = j
                }
                runStart = nil
            }
            j += 1
        }
        guard let f = first else { return nil }
        return (f, last)
    }

    private func advance(_ profile: ProductProfile, final: Bool) -> [Event] {
        guard ensurePeriod(profile, final: final) else { return [] }
        let pp = max(4, Self.roundEven(pPitch))
        let half = max(1, pp / 3)
        let r = pp / 50
        let tot = off + sig.count
        var events: [Event] = []
        var lastLow = 0.0, lastC = 0.0
        while scan < tot {
            let i = scan
            guard let res = seamAt(i, pp, tot, final: final) else { break }
            scan += 1
            if res.contrast > 0 {
                lastLow = res.low
                lastC = res.contrast
                low = res.low
            }
            if res.ok && (lastSeam == nil || i - lastSeam! >= half) {
                events += close(lastSeam, i, pp, res.low, profile, rightSeam: true)
                lastSeam = i
                oIa = nil
                oK = 0
            } else if let lowThr = low, sm(i, r) > lowThr {
                if oIa == nil {
                    oIa = i
                    oId = nextId
                    nextId += 1
                }
                oIb = i + 1
                events += provisional(profile)
            }
        }
        if final {
            if lastC <= 0 {
                var window: [Double] = []
                for j in max(off, tot - 4 * pp)..<tot { window.append(sm(j, r)) }
                if !window.isEmpty {
                    let lv = Self.levels(window)
                    lastC = lv.contrast
                    lastLow = lv.low
                }
            }
            if lastC >= Self.minContrast {
                events += close(lastSeam, tot, pp, lastLow, profile, rightSeam: false)
            }
            events += flushCarry(profile)
            oIa = nil
            oK = 0
        }
        trim(pp)
        return events
    }

    /// Ön sayım: açık parçanın ürün kısmı 0,5·P'yi geçince ilk ürün hemen sayılır (fazlası geri alınmaz).
    private func provisional(_ profile: ProductProfile) -> [Event] {
        guard let ia = oIa, ia >= start else { return [] }
        let plen = pLen
        let a = lastSeam ?? off
        if let c = carry, Double(ia - a) <= 0.15 * plen, Double(oIb - c.ia) <= 1.35 * plen { return [] }
        // Yalnızca parçanın ilk ürünü; sonrakiler kapanışta kesin olarak (fazla sayım geri alınamaz)
        let target = min(1, Int((Double(oIb - ia) / plen + 0.5).rounded(.down)))
        var out: [Event] = []
        while oK < target {
            let c = Double(ia) + (Double(oK) + 0.5) * plen
            if let e = end, c >= Double(e) { break }
            out.append(Event(id: oId * 16 + oK, delta: 1))
            oK += 1
        }
        return out
    }

    private func close(_ a0: Int?, _ b: Int, _ pp: Int, _ lowThr: Double, _ profile: ProductProfile,
                       rightSeam: Bool) -> [Event] {
        var out: [Event] = []
        let startIdx = a0 ?? off
        var sid = oIa != nil ? oId : 0
        var k = oIa != nil ? oK : 0
        guard let br = bright(startIdx, b, pp, lowThr) else {     // yalnızca boş bant
            out += flushCarry(profile)
            return out
        }
        if sid == 0 {
            sid = nextId
            nextId += 1
        }
        var a = a0
        var ia = br.ia
        let ib = br.ib
        let plen = pLen
        let tight = 0.15 * plen
        var isolated = a0 == nil || Double(ia - startIdx) > tight      // önünde gerçek boşluk var
        if let c = carry {
            if Double(ia - startIdx) <= tight && Double(ib - c.ia) <= 1.35 * plen {
                a = c.a
                ia = c.ia
                sid = c.id
                k += c.k
                carry = nil
                isolated = false
            } else {
                out += flushCarry(profile)
            }
        }
        if Double(ib - ia) < 0.75 * plen && rightSeam && Double(b - ib) <= tight && sm(b, pp / 50) > lowThr {
            carry = Carry(a: a, b: b, ia: ia, ib: ib, id: sid, k: k)
            return out
        }
        out += emit(a, b, ia, ib, rightSeam: rightSeam, profile, sid: sid, k: k, isolated: isolated)
        return out
    }

    private func flushCarry(_ profile: ProductProfile) -> [Event] {
        guard let c = carry else { return [] }
        carry = nil
        return emit(c.a, c.b, c.ia, c.ib, rightSeam: true, profile, sid: c.id, k: c.k)
    }

    /// Kesin karar: n ürün; ilk k'sı ön sayımla zaten sayıldı. Önünde boşluk olan tek başına parça ≥ 0,25·P ise
    /// bir üründür (perspektifte uzak/sivri görünen torba).
    private func emit(_ a: Int?, _ b: Int, _ ia: Int, _ ib: Int, rightSeam: Bool, _ profile: ProductProfile,
                      sid: Int, k: Int, isolated: Bool = false) -> [Event] {
        var cnt = min(profile.maxMultiplicity, Int((Double(ib - ia) / pLen + 0.5).rounded(.down)))
        if cnt == 0 && isolated && Double(ib - ia) >= 0.25 * pLen { cnt = 1 }
        guard cnt > 0 else { return [] }
        let e = 0.1 * pLen
        let ca = a.map { max(Double($0), Double(ia) - e) } ?? Double(ia) - e
        let cb = rightSeam ? min(Double(b), Double(ib) + e) : Double(ib) + e
        let centers = (0..<cnt).map { ca + (Double($0) + 0.5) * (cb - ca) / Double(cnt) }
        segs = Array((segs + [Seg(id: sid, centers: centers)]).suffix(8))
        guard k < cnt else { return [] }
        return (k..<cnt).filter { inRange(centers[$0]) }.map { Event(id: sid * 16 + $0, delta: 1) }
    }

    /// Bir daha okunmayacak eski sinyali at (sonucu değiştirmez).
    private func trim(_ pp: Int) {
        let keepFrom = min(scan - 4 * pp - pp, lastSeam ?? off)
        let drop = keepFrom - off - pp / 50 - 2
        if drop > 4096 {
            sig.removeFirst(drop)
            off += drop
        }
    }

    // MARK: - Yardımcılar

    private static func pearson(_ a: [Double], _ b: [Double]) -> Double {
        let n = Double(a.count)
        let ma = a.reduce(0, +) / n, mb = b.reduce(0, +) / n
        var sab = 0.0, saa = 0.0, sbb = 0.0
        for i in 0..<a.count {
            let da = a[i] - ma, db = b[i] - mb
            sab += da * db
            saa += da * da
            sbb += db * db
        }
        let den = (saa * sbb).squareRoot()
        return den > 1e-9 ? sab / den : 0
    }

    /// §4.9.4 Yayılım ipucu: s = üst − alt çeyrek. Açık üründe üst çeyrek s ile pozitif, koyu ürün yorumu
    /// (255 − alt çeyrek) negatif ilişkili (ya da tersi) ise kesin karar; değilse 0.
    private static func spreadPolarity(_ pd: [(Double, Double)]) -> Int {
        guard pd.count >= 8 else { return 0 }
        let lo = pd.map { $0.0 }, hi = pd.map { $0.1 }
        let spread = zip(hi, lo).map { $0 - $1 }
        let cn = pearson(hi, spread), ci = pearson(lo.map { 255 - $0 }, spread)
        if cn > 0.3 && ci < 0 { return 1 }
        if ci > 0.3 && cn < 0 { return -1 }
        return 0
    }

    static func roundEven(_ x: Double) -> Int { Int(x.rounded(.toNearestOrEven)) }

    /// İnterpolasyonsuz yüzdelik: sıralı dizide floor(q·(n−1)) indeksli eleman
    static func percentileLower(_ v: [Double], _ q: Double) -> Double {
        let s = v.sorted()
        return s[Int((q * Double(s.count - 1)).rounded(.down))]
    }

    /// x − kayan ortalama (pencere 2w+1, uçlarda kırpılır)
    private static func highpass(_ x: [Double], _ w: Int) -> [Double] {
        let cnt = x.count
        var c = [Double](repeating: 0, count: cnt + 1)
        for i in 0..<cnt { c[i + 1] = c[i] + x[i] }
        return (0..<cnt).map { i in
            let a = max(0, i - w), b = min(cnt, i + w + 1)
            return x[i] - (c[b] - c[a]) / Double(b - a)
        }
    }

    private static func autocorrPeak(_ x: [Double], _ pmin: Int, _ pmax: Int) -> (lag: Double, power: Double)? {
        let cnt = x.count
        var den = 0.0
        for v in x { den += v * v }
        guard pmax > pmin + 1, den > 1e-9 else { return nil }
        var ac = [Double](repeating: 0, count: pmax + 1)
        for lag in 0...pmax {
            var s = 0.0
            for i in 0..<(cnt - lag) { s += x[i] * x[i + lag] }
            ac[lag] = s / den
        }
        let peaks = (pmin..<pmax).filter { ac[$0] > ac[$0 - 1] && ac[$0] >= ac[$0 + 1] }
        guard let best = peaks.map({ ac[$0] }).max(), best >= 0.1 else { return nil }
        guard let lag = peaks.first(where: { ac[$0] >= 0.6 * best }) else { return nil }
        return (Double(lag), best)
    }

    private static func runMedian(_ x: [Double], _ pmin: Int) -> Double? {
        let cnt = x.count
        guard cnt > 0 else { return nil }
        let r = max(1, pmin / 8)
        var c = [Double](repeating: 0, count: cnt + 1)
        for i in 0..<cnt { c[i + 1] = c[i] + x[i] }
        let smv = (0..<cnt).map { i -> Double in
            let a = max(0, i - r), b = min(cnt, i + r + 1)
            return (c[b] - c[a]) / Double(b - a)
        }
        let lo = percentileLower(smv, 0.05)
        let mid = lo + 0.5 * (percentileLower(smv, 0.90) - lo)
        var runs: [Int] = []
        var k = 0
        while k < cnt {
            if smv[k] > mid {
                var j = k
                while j < cnt && smv[j] > mid { j += 1 }
                if k > 0 && j < cnt && j - k >= pmin { runs.append(j - k) }
                k = j
            } else {
                k += 1
            }
        }
        guard runs.count >= 2 else { return nil }
        runs.sort()
        return Double(runs[(runs.count - 1) / 2])
    }
}
