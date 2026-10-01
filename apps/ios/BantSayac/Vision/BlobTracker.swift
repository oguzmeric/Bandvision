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
}

func median(_ a: [Double]) -> Double {
    guard !a.isEmpty else { return 0 }
    let s = a.sorted()
    let c = s.count
    return c % 2 == 1 ? s[c / 2] : (s[c / 2 - 1] + s[c / 2]) / 2
}

/// Bant tek yönde aktığı için: konum + sabit hız tahmini, açgözlü eşleştirme,
/// çizgi geçişinde sayım. Çizgiden önce doğmayan izler sayılmaz (çift sayım koruması).
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

        // Aday eşleşmeler (tahmini konuma uzaklık; geriye gitme yasak)
        var pairs: [(d: Double, t: Int, b: Int)] = []
        for (ti, t) in tracks.enumerated() {
            let px = t.x + t.vx, py = t.y + t.vy
            for (bi, b) in blobs.enumerated() {
                let progress = s * (axis(b.cx, b.cy) - axis(t.x, t.y))
                if progress < -0.03 { continue }
                let d = hypot(b.cx - px, b.cy - py)
                if d <= maxDistance { pairs.append((d: d, t: ti, b: bi)) }
            }
        }
        pairs.sort { $0.d < $1.d }

        var usedT = Set<Int>(), usedB = Set<Int>()
        var events: [CountEvent] = []

        for pair in pairs {
            if usedT.contains(pair.t) || usedB.contains(pair.b) { continue }
            usedT.insert(pair.t)
            usedB.insert(pair.b)
            let b = blobs[pair.b]
            var t = tracks[pair.t]

            t.vx = 0.6 * t.vx + 0.4 * (b.cx - t.x)
            t.vy = 0.6 * t.vy + 0.4 * (b.cy - t.y)
            t.x = b.cx
            t.y = b.cy
            t.hits += 1
            t.missed = 0
            t.multHistory.append(b.multiplicity)
            if t.multHistory.count > 5 { t.multHistory.removeFirst() }
            t.areaHistory.append(b.area)
            if t.areaHistory.count > 9 { t.areaHistory.removeFirst() }

            if t.countedSoFar == 0 {
                if t.startedBefore && t.hits >= minHits && s * (axis(t.x, t.y) - line) >= 0 {
                    let mean = Double(t.multHistory.reduce(0, +)) / Double(t.multHistory.count)
                    let m = max(1, Int(mean.rounded()))
                    t.countedSoFar = m
                    events.append(CountEvent(delta: m, isFirstCrossing: true,
                                             medianArea: median(t.areaHistory)))
                }
            } else {
                // Sayıldıktan sonra arkadaki ürün bu leke ile birleştiyse farkı ekle
                let recent = t.multHistory.suffix(3)
                if recent.count == 3, let low = recent.min(), low > t.countedSoFar {
                    events.append(CountEvent(delta: low - t.countedSoFar, isFirstCrossing: false, medianArea: 0))
                    t.countedSoFar = low
                }
            }
            tracks[pair.t] = t
        }

        // Eşleşmeyen izler: hız ile ilerlet (kısa kayıplara dayanıklılık)
        for i in tracks.indices where !usedT.contains(i) {
            tracks[i].missed += 1
            tracks[i].x += tracks[i].vx
            tracks[i].y += tracks[i].vy
        }
        tracks.removeAll {
            $0.missed > maxMissed || $0.x < -0.1 || $0.x > 1.1 || $0.y < -0.1 || $0.y > 1.1
        }

        // Yeni izler
        for (bi, b) in blobs.enumerated() where !usedB.contains(bi) {
            tracks.append(Track(id: nextID, x: b.cx, y: b.cy, vx: 0, vy: 0,
                                hits: 1, missed: 0,
                                startedBefore: s * (axis(b.cx, b.cy) - line) < 0,
                                countedSoFar: 0,
                                multHistory: [b.multiplicity],
                                areaHistory: [b.area]))
            nextID += 1
        }
        return events
    }
}
