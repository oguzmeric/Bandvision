import Foundation
import CoreGraphics

struct TrackMarker {
    let id: Int
    let x: Double
    let y: Double
    let counted: Bool
}

struct CountEvent {
    let delta: Int
    /// true: iz çizgiyi ilk kez geçti. false: geçtikten sonra birleşme ile çarpan arttı.
    let isFirstCrossing: Bool
    let medianArea: Double
    let trackId: Int
    /// Sayımın olduğu karedeki lekenin kutusu (normalize); ürün kırpıntısı için.
    let bbox: CGRect
}

/// Ekranda ve kartlarda gösterilen kısa kimlik (ardışık iz numaralarında bile ayırt edilebilir).
/// Python `bantvision.video._hex_id` ile aynı.
func hexID(_ id: Int) -> String {
    String(format: "%04X", (UInt64(truncatingIfNeeded: id) &* 2_654_435_761) & 0xFFFF)
}

func median(_ a: [Double]) -> Double {
    guard !a.isEmpty else { return 0 }
    let s = a.sorted()
    let c = s.count
    return c % 2 == 1 ? s[c / 2] : (s[c / 2 - 1] + s[c / 2]) / 2
}

/// Python referansıyla aynı yuvarlama (en yakın çift: 2,5 → 2). docs/03-algorithm.md §4.
@inline(__always) func roundHalfEven(_ v: Double) -> Int { Int(v.rounded(.toNearestOrEven)) }

/// §4.0: izin tahmini konumu lekenin kutusunun bu oranı kadar dışına taşsa da "içinde" sayılır.
let mergeMargin = 0.05

/// Bant tek yönde aktığı için: konum + sabit hız tahmini, açgözlü eşleştirme, çizgi geçişinde sayım.
/// Birbirine değen ürünler için birleşik grup (§4.0) ve bölünme (§4.5) kuralları, yeni izlere bant hızı (§4.7).
/// Davranış `services/edge/bantvision/core/tracker.py` ile birebir aynıdır.
final class BlobTracker {
    private struct Track {
        let id: Int
        var x: Double
        var y: Double
        var vx: Double
        var vy: Double
        var hits: Int
        var missed: Int
        var startedBefore: Bool
        var countedSoFar: Int
        var multHistory: [Int]
        var areaHistory: [Double]
        var bbox: CGRect
        var lastMult: Int
    }

    private var tracks: [Track] = []
    private var nextID = 1

    func reset() { tracks.removeAll() }

    var markers: [TrackMarker] {
        tracks.map { TrackMarker(id: $0.id, x: $0.x, y: $0.y, counted: $0.countedSoFar > 0) }
    }

    func update(blobs: [Blob], direction: FlowDirection, line: Double,
                maxDistance: Double, minHits: Int, maxMissed: Int = 6) -> [CountEvent] {
        let s = direction.sign
        func axis(_ x: Double, _ y: Double) -> Double { direction.isVertical ? y : x }
        var events: [CountEvent] = []

        func observe(_ ti: Int, mult: Int, area: Double, blob: Blob) {
            var t = tracks[ti]
            t.bbox = blob.bbox
            t.lastMult = mult
            t.hits += 1
            t.missed = 0
            t.multHistory.append(mult)
            if t.multHistory.count > 5 { t.multHistory.removeFirst(t.multHistory.count - 5) }
            t.areaHistory.append(area)
            if t.areaHistory.count > 9 { t.areaHistory.removeFirst(t.areaHistory.count - 9) }
            if t.countedSoFar == 0 {
                if t.startedBefore && t.hits >= minHits && s * (axis(t.x, t.y) - line) >= 0 {
                    let mean = Double(t.multHistory.reduce(0, +)) / Double(t.multHistory.count)
                    let m = max(1, roundHalfEven(mean))
                    t.countedSoFar = m
                    events.append(CountEvent(delta: m, isFirstCrossing: true, medianArea: median(t.areaHistory),
                                             trackId: t.id, bbox: blob.bbox))
                }
            } else {
                let recent = t.multHistory.suffix(3)
                if recent.count == 3, let low = recent.min(), low > t.countedSoFar {
                    events.append(CountEvent(delta: low - t.countedSoFar, isFirstCrossing: false, medianArea: 0,
                                             trackId: t.id, bbox: blob.bbox))
                    t.countedSoFar = low
                }
            }
            tracks[ti] = t
        }

        var usedT = Set<Int>(), usedB = Set<Int>()
        let preds = tracks.map { (x: $0.x + $0.vx, y: $0.y + $0.vy) }

        // §4.0 Birleşik gruplar
        var owner: [Int: (d: Double, b: Int)] = [:]
        for (bi, b) in blobs.enumerated() {
            let mx = mergeMargin * Double(b.bbox.width), my = mergeMargin * Double(b.bbox.height)
            let bx = Double(b.bbox.minX), by = Double(b.bbox.minY)
            let bw = Double(b.bbox.width), bh = Double(b.bbox.height)
            let inside = preds.indices.filter {
                preds[$0].x >= bx - mx && preds[$0].x <= bx + bw + mx &&
                preds[$0].y >= by - my && preds[$0].y <= by + bh + my
            }
            if inside.count < 2 { continue }
            for ti in inside {
                let d = hypot(b.cx - preds[ti].x, b.cy - preds[ti].y)
                if let o = owner[ti], o.d <= d { continue }
                owner[ti] = (d: d, b: bi)
            }
        }
        var groups: [Int: [Int]] = [:]
        for ti in owner.keys.sorted() { groups[owner[ti]!.b, default: []].append(ti) }
        for bi in groups.keys.sorted() {
            guard var members = groups[bi], members.count >= 2 else { continue }
            let b = blobs[bi]
            members.sort { -s * axis(preds[$0].x, preds[$0].y) < -s * axis(preds[$1].x, preds[$1].y) }
            let n = members.count
            let total = max(b.multiplicity, n)
            let dx = b.cx - members.reduce(0.0) { $0 + preds[$1].x } / Double(n)
            let dy = b.cy - members.reduce(0.0) { $0 + preds[$1].y } / Double(n)
            for (k, ti) in members.enumerated() {
                let nx = preds[ti].x + dx, ny = preds[ti].y + dy
                tracks[ti].vx = 0.6 * tracks[ti].vx + 0.4 * (nx - tracks[ti].x)
                tracks[ti].vy = 0.6 * tracks[ti].vy + 0.4 * (ny - tracks[ti].y)
                tracks[ti].x = nx
                tracks[ti].y = ny
                observe(ti, mult: total / n + (k < total % n ? 1 : 0), area: b.area / Double(n), blob: b)
                usedT.insert(ti)
            }
            usedB.insert(bi)
        }

        // §4.1–4.3 Aday eşleşmeler ve açgözlü atama
        var prev = tracks.map { (bbox: $0.bbox, mult: $0.lastMult) }
        var greedy = Set<Int>()
        var pairs: [(d: Double, t: Int, b: Int)] = []
        for (ti, t) in tracks.enumerated() where !usedT.contains(ti) {
            for (bi, b) in blobs.enumerated() where !usedB.contains(bi) {
                if s * (axis(b.cx, b.cy) - axis(t.x, t.y)) < -0.03 { continue }
                let d = hypot(b.cx - preds[ti].x, b.cy - preds[ti].y)
                if d <= maxDistance { pairs.append((d: d, t: ti, b: bi)) }
            }
        }
        pairs.sort { $0.d < $1.d }
        for pair in pairs {
            if usedT.contains(pair.t) || usedB.contains(pair.b) { continue }
            usedT.insert(pair.t)
            usedB.insert(pair.b)
            greedy.insert(pair.t)
            let b = blobs[pair.b]
            tracks[pair.t].vx = 0.6 * tracks[pair.t].vx + 0.4 * (b.cx - tracks[pair.t].x)
            tracks[pair.t].vy = 0.6 * tracks[pair.t].vy + 0.4 * (b.cy - tracks[pair.t].y)
            tracks[pair.t].x = b.cx
            tracks[pair.t].y = b.cy
            observe(pair.t, mult: b.multiplicity, area: b.area, blob: b)
        }

        // §4.5 Bölünme
        var children: [Track] = []
        for (bi, b) in blobs.enumerated() where !usedB.contains(bi) {
            var best: (d: Double, t: Int)?
            for ti in greedy.sorted() {
                let pb = prev[ti].bbox
                let pw = Double(pb.width), ph = Double(pb.height)
                if prev[ti].mult < 2 || pw <= 0 { continue }
                let ox = Double(pb.minX) + tracks[ti].vx - mergeMargin * pw
                let oy = Double(pb.minY) + tracks[ti].vy - mergeMargin * ph
                if b.cx >= ox && b.cx <= ox + pw * (1 + 2 * mergeMargin) &&
                   b.cy >= oy && b.cy <= oy + ph * (1 + 2 * mergeMargin) {
                    let d = hypot(b.cx - tracks[ti].x, b.cy - tracks[ti].y)
                    if best == nil || d < best!.d { best = (d: d, t: ti) }
                }
            }
            guard let parentIndex = best?.t else { continue }
            let parent = tracks[parentIndex]
            let keep = min(parent.countedSoFar, parent.lastMult)
            children.append(Track(id: nextID, x: b.cx, y: b.cy, vx: parent.vx, vy: parent.vy,
                                  hits: parent.hits, missed: 0, startedBefore: parent.startedBefore,
                                  countedSoFar: min(parent.countedSoFar - keep, b.multiplicity),
                                  multHistory: [b.multiplicity], areaHistory: [b.area],
                                  bbox: b.bbox, lastMult: b.multiplicity))
            nextID += 1
            tracks[parentIndex].countedSoFar = keep
            tracks[parentIndex].multHistory = [parent.lastMult]
            prev[parentIndex] = (bbox: parent.bbox, mult: parent.lastMult)
            usedB.insert(bi)
        }

        // §4.6 Eşleşmeyen izler: hız ile ilerlet (kısa kayıplara dayanıklılık)
        for i in tracks.indices where !usedT.contains(i) {
            tracks[i].missed += 1
            tracks[i].x += tracks[i].vx
            tracks[i].y += tracks[i].vy
        }
        tracks.removeAll {
            $0.missed > maxMissed || $0.x < -0.1 || $0.x > 1.1 || $0.y < -0.1 || $0.y > 1.1
        }

        // §4.7 Yeni izler: bant hızıyla başlar
        let settled = tracks.filter { $0.hits >= 3 && $0.missed == 0 }
        let vx0 = median(settled.map { $0.vx }), vy0 = median(settled.map { $0.vy })
        for (bi, b) in blobs.enumerated() where !usedB.contains(bi) {
            tracks.append(Track(id: nextID, x: b.cx, y: b.cy, vx: vx0, vy: vy0,
                                hits: 1, missed: 0,
                                startedBefore: s * (axis(b.cx, b.cy) - line) < 0,
                                countedSoFar: 0,
                                multHistory: [b.multiplicity],
                                areaHistory: [b.area],
                                bbox: b.bbox, lastMult: b.multiplicity))
            nextID += 1
        }
        tracks.append(contentsOf: children)
        return events
    }
}
