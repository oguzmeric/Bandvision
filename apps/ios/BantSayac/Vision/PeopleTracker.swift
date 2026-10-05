import Foundation

/// Kişi/araç/hayvan takibi ve iki yönlü çizgi geçişi (algoritma §4.10).
/// Python referansı: services/edge/bantvision/core/people_track.py — davranış birebir aynı olmalı
/// (BantSayacTests/PeopleTrackerTests: Python'un ürettiği senaryolarda aynı karede aynı iz kimliğiyle aynı olaylar).

/// Normalize kutu (x1, y1, x2, y2)
struct NBox: Equatable {
    var x1: Double, y1: Double, x2: Double, y2: Double

    var area: Double { max(0, x2 - x1) * max(0, y2 - y1) }
    var center: (x: Double, y: Double) { ((x1 + x2) / 2, (y1 + y2) / 2) }

    static func + (a: NBox, b: NBox) -> NBox { NBox(x1: a.x1 + b.x1, y1: a.y1 + b.y1, x2: a.x2 + b.x2, y2: a.y2 + b.y2) }
    static let zero = NBox(x1: 0, y1: 0, x2: 0, y2: 0)
}

/// Tanıyıcıdan gelen kutu ve güveni
struct Detection: Equatable {
    var box: NBox
    var score: Double
}

/// Çizgiye göre konum noktası (sözleşme `countAnchor`)
enum CountAnchor: String, Codable, CaseIterable, Identifiable {
    /// Kutu merkezi: tepeden bakan kamera (hareket desteği açık)
    case center
    /// Alt orta, ayak: yatık/yandan kamera (çizgi zemine çizilir)
    case bottom

    var id: String { rawValue }
    var title: String {
        switch self {
        case .center: return "Tepeden"
        case .bottom: return "Yandan"
        }
    }
}

struct MotParams {
    var high = 0.45
    var low = 0.15
    var iouMatch = 0.2
    var iouLow = 0.3
    var centerGate = 0.8
    var tentativeAge = 2
    var gateGrow = 0.5
    var gateMax = 1.6
    var velWindow = 10
    var minHits = 3
    var maxAge = 30
    var band = 0.02
    var bandRel = 0.1
    var sideFrames = 2
    var contain = 0.85
    var partArea = 0.75
    var motionGate = 1.0
    var groupArea = 1.8
    var groupMargin = 1.0
    var dupIou = 0.3
    var motionLife = 1.5
    var unverifiedLife = 3.0
}

final class MotTrack {
    let id: Int
    /// Tahmin edilen (gözlenen karede: gözlenen) kutu
    var box: NBox
    var vel: NBox
    /// Son gözlenen kutu
    var last: NBox
    var score: Double
    var hits = 1
    var misses = 0
    var confirmed = false
    /// Son kesin yan: −1, +1; 0 bilinmiyor
    var side = 0
    /// Yan teyidi: aday yeni yan ve art arda görülme sayısı
    var cand = 0
    var candN = 0
    /// Onaydan önce olan geçişler (+1 giriş, −1 çıkış)
    var pending: [Int] = []
    var trail: [(x: Double, y: Double)] = []
    /// (kare, gözlenen kutu): uzun tabanlı hız
    var hist: [(frame: Int, box: NBox)] = []
    var entries = 0
    var exits = 0
    /// En az bir yüksek güvenli tanımayla eşleşti (hareket lekesinden doğan iz: false)
    var verified: Bool
    /// Doğduğu ve son tanımayla eşleştiği kare
    let born: Int
    var lastDet: Int

    init(id: Int, box: NBox, vel: NBox, last: NBox, score: Double, verified: Bool, born: Int) {
        self.id = id
        self.box = box
        self.vel = vel
        self.last = last
        self.score = score
        self.verified = verified
        self.born = born
        self.lastDet = born
    }
}

func iou(_ a: NBox, _ b: NBox) -> Double {
    let x1 = max(a.x1, b.x1), y1 = max(a.y1, b.y1)
    let x2 = min(a.x2, b.x2), y2 = min(a.y2, b.y2)
    let inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    let ua = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter
    return ua > 0 ? inter / ua : 0.0
}

/// Çizgiye göre konum noktası
func anchorPoint(_ b: NBox, _ mode: CountAnchor) -> (x: Double, y: Double) {
    let cx = (b.x1 + b.x2) / 2
    return mode == .bottom ? (cx, b.y2) : (cx, (b.y1 + b.y2) / 2)
}

/// Başka bir kutunun içinde kalan parça kutuları atar; kapsayan kutu ikisinin yüksek güvenini alır.
/// Dönüş sırası alana göre büyükten küçüğe (Python `sorted`, eşitlikte giriş sırası).
func suppressParts(_ dets: [Detection], contain: Double, partArea: Double) -> [Detection] {
    let order = dets.indices.sorted { i, j in
        let ai = dets[i].box.area, aj = dets[j].box.area
        return ai != aj ? ai > aj : i < j
    }
    var kept: [Detection] = []
    for i in order {
        let b = dets[i].box, s = dets[i].score
        let a = b.area
        var absorbed = false
        for k in kept.indices {
            let c = kept[k].box
            let inter = max(0.0, min(b.x2, c.x2) - max(b.x1, c.x1)) * max(0.0, min(b.y2, c.y2) - max(b.y1, c.y1))
            if a > 0 && inter / a >= contain && a <= partArea * c.area {
                kept[k].score = max(kept[k].score, s)
                absorbed = true
                break
            }
        }
        if !absorbed { kept.append(Detection(box: b, score: s)) }
    }
    return kept
}

/// `b` kutusunun merkezi `c` kutusunun içinde mi?
private func centerIn(_ b: NBox, _ c: NBox) -> Bool {
    let (x, y) = b.center
    return c.x1 <= x && x <= c.x2 && c.y1 <= y && y <= c.y2
}

/// `size` boyunda, merkezi `c` olan kutu
private func boxAt(_ size: NBox, _ c: (x: Double, y: Double)) -> NBox {
    let hw = (size.x2 - size.x1) / 2, hh = (size.y2 - size.y1) / 2
    return NBox(x1: c.x - hw, y1: c.y - hh, x2: c.x + hw, y2: c.y + hh)
}

/// Merkezler arası uzaklık, `size` kutusunun en ve boyuna göre normalize (elips kapı)
private func gateDist(_ a: NBox, _ size: NBox, _ b: NBox) -> Double {
    let w = max(size.x2 - size.x1, 1e-6)
    let h = max(size.y2 - size.y1, 1e-6)
    return hypot((a.x1 + a.x2 - b.x1 - b.x2) / 2 / w, (a.y1 + a.y2 - b.y1 - b.y2) / 2 / h)
}

final class MotTracker {
    var p: MotParams
    private(set) var tracks: [MotTrack] = []
    private(set) var nextId = 1
    private(set) var frame = 0

    init(params: MotParams = MotParams()) {
        p = params
    }

    func reset() {
        tracks.removeAll()
    }

    /// Bir kare. `sideOf(x, y)`: çizgiye işaretli uzaklık (giriş yönü pozitif); `motion`: hareket lekeleri;
    /// `bounds`: sayım alanı (ROI) — tahmini merkezi dışına çıkan iz silinir. Dönüş: (girenler, çıkanlar)
    func update(_ input: [Detection], sideOf: (Double, Double) -> Double, anchor: CountAnchor = .center,
                motion: [NBox]? = nil, bounds: NBox = NBox(x1: 0, y1: 0, x2: 1, y2: 1))
        -> (entered: [MotTrack], exited: [MotTrack]) {
        for t in tracks { t.box = t.box + t.vel }                       // tahmin
        let dets = suppressParts(input, contain: p.contain, partArea: p.partArea)
        let high = dets.indices.filter { dets[$0].score >= p.high }
        let low = dets.indices.filter { dets[$0].score >= p.low && dets[$0].score < p.high }

        var matchedT = Set<Int>()
        var matchedD: [Int: Int] = [:]                                  // iz indeksi → tespit indeksi
        var usedD = Set<Int>()
        var pairs: [(negOv: Double, dc: Double, ti: Int, di: Int)] = []
        for (ti, t) in tracks.enumerated() {
            for di in high + low {
                let b = dets[di].box
                let ov = max(iou(t.box, b), iou(t.last, b))
                let dc = min(gateDist(t.box, t.last, b), gateDist(t.last, t.last, b))
                let gate = min(p.gateMax, p.centerGate + grow(t))
                let ok = dets[di].score >= p.high ? (ov >= p.iouMatch || dc < gate) : ov >= p.iouLow
                if ok { pairs.append((-ov, dc, ti, di)) }
            }
        }
        pairs.sort { a, b in
            if a.negOv != b.negOv { return a.negOv < b.negOv }
            if a.dc != b.dc { return a.dc < b.dc }
            if a.ti != b.ti { return a.ti < b.ti }
            return a.di < b.di
        }
        for pr in pairs {                                               // açgözlü: en iyi örtüşen önce
            if matchedT.contains(pr.ti) || usedD.contains(pr.di) { continue }
            matchedT.insert(pr.ti)
            usedD.insert(pr.di)
            matchedD[pr.ti] = pr.di
        }

        // Hareket desteği: tanımayla eşleşmeyen onaylı ya da doğrulanmamış izler lekeyle sürer
        let mboxes = motion ?? []
        var claim: [Int: Int] = [:]                                     // iz indeksi → leke indeksi
        for (ti, t) in tracks.enumerated() {
            // Tanımadan doğmuş onaysız iz lekeyle sürmez (birleşik/yarım kutudan doğan hayali iz yaşamasın)
            if matchedD[ti] != nil || mboxes.isEmpty || (t.verified && !t.confirmed) { continue }
            // Yaşam sınırı: kapı/ekran/gölge hareketiyle süresiz yaşayan hayalet iz olmasın
            if t.verified && Double(frame - t.lastDet) > p.motionLife * Double(p.maxAge) { continue }
            if !t.verified && Double(frame - t.born) > p.unverifiedLife * Double(p.maxAge) { continue }
            let gate = min(p.gateMax, p.motionGate + grow(t))
            var best: (dc: Double, mi: Int)?
            for (mi, m) in mboxes.enumerated() {
                let dc = gateDist(t.box, t.last, m)
                if (dc < gate || centerIn(t.box, m)) && (best == nil || dc < best!.dc) { best = (dc, mi) }
            }
            if let best { claim[ti] = best.mi }
        }
        // Lekeyi açıklayan kişi sayısı: talep eden izler + tanıma kutusunun merkezi lekede olanlar. Birden çoksa
        // (ya da leke tek kişiden büyükse) grup lekesi: tahmini merkez lekeye yakınsa lekeye kısıtlanır, uzaksa
        // eşleşmez (sürüklenmez); tek sahibi olan leke izi merkezine taşır.
        var owners = [Int](repeating: 0, count: mboxes.count)
        for mi in claim.values { owners[mi] += 1 }
        for di in matchedD.values {
            for (mi, m) in mboxes.enumerated() where centerIn(dets[di].box, m) { owners[mi] += 1 }
        }
        var matchedM: [Int: NBox] = [:]
        for (ti, mi) in claim {
            let t = tracks[ti], m = mboxes[mi]
            if owners[mi] > 1 || m.area > p.groupArea * t.last.area {
                let pc = t.box.center
                let hw = p.groupMargin * (t.last.x2 - t.last.x1), hh = p.groupMargin * (t.last.y2 - t.last.y1)
                if m.x1 - hw <= pc.x && pc.x <= m.x2 + hw && m.y1 - hh <= pc.y && pc.y <= m.y2 + hh {
                    matchedM[ti] = boxAt(t.last, (min(max(pc.x, m.x1), m.x2), min(max(pc.y, m.y1), m.y2)))
                }
            } else {
                matchedM[ti] = boxAt(t.last, m.center)
            }
        }

        var entered: [MotTrack] = []
        var exited: [MotTrack] = []
        for (ti, t) in tracks.enumerated() {
            if let di = matchedD[ti] {
                t.score = dets[di].score
                if dets[di].score >= p.high && !t.verified {
                    t.verified = true
                    t.hist = []                                         // hız artık tanıma gözlemlerinden
                }
                t.lastDet = frame
                observeUpdate(t, dets[di].box, fromDet: true, sideOf, anchor, &entered, &exited)
            } else if let mb = matchedM[ti] {
                observeUpdate(t, mb, fromDet: false, sideOf, anchor, &entered, &exited)
            } else {
                t.misses += 1
            }
        }
        let used = Set(matchedD.values)
        for di in high where !used.contains(di) {
            newTrack(dets[di].box, dets[di].score, verified: true, sideOf, anchor, &entered, &exited)
        }
        for m in mboxes {                                               // hiçbir izin açıklamadığı leke: doğrulanmamış iz
            if !tracks.contains(where: { iou($0.box, m) > 0 || centerIn(m, $0.box) }) {
                newTrack(m, 0.0, verified: false, sideOf, anchor, &entered, &exited)
            }
        }
        let verifiedTracks = tracks.filter(\.verified)
        tracks = tracks.filter { t in
            t.misses <= (t.confirmed ? p.maxAge : p.tentativeAge)
                && centerIn(t.box, bounds)                              // alandan çıktı: kimliği yeni gelene geçmesin
                && (t.verified || !verifiedTracks.contains { v in
                    iou(t.box, v.box) >= p.dupIou || centerIn(t.box, v.box)
                })
        }
        frame += 1
        return (entered, exited)
    }

    /// Kayıptaki izin kapı büyümesi: kayıp kare × hız (kutu en/boyuna göre); duran iz büyümez
    private func grow(_ t: MotTrack) -> Double {
        let w = max(t.last.x2 - t.last.x1, 1e-6)
        let h = max(t.last.y2 - t.last.y1, 1e-6)
        return p.gateGrow * Double(t.misses) * hypot(t.vel.x1 / w, t.vel.y1 / h)
    }

    private func newTrack(_ box: NBox, _ score: Double, verified: Bool, _ sideOf: (Double, Double) -> Double,
                          _ anchor: CountAnchor, _ entered: inout [MotTrack], _ exited: inout [MotTrack]) {
        let t = MotTrack(id: nextId, box: box, vel: .zero, last: box, score: score, verified: verified, born: frame)
        t.hist.append((frame, box))
        nextId += 1
        tracks.append(t)
        observe(t, sideOf, anchor, &entered, &exited)
    }

    private func observeUpdate(_ t: MotTrack, _ box: NBox, fromDet: Bool, _ sideOf: (Double, Double) -> Double,
                               _ anchor: CountAnchor, _ entered: inout [MotTrack], _ exited: inout [MotTrack]) {
        let f = frame
        if fromDet || !t.verified {
            // Doğrulanmış izin hızı yalnızca tanıma gözlemlerinden (grup lekesine kısıtlanan konum hızı bozmasın)
            t.hist = t.hist.filter { $0.frame >= f - p.velWindow }
            if let first = t.hist.first {                               // uzun tabanlı hız (merkezden)
                let c = box.center, c0 = first.box.center
                let n = Double(f - first.frame)
                let vx = (c.x - c0.x) / n, vy = (c.y - c0.y) / n
                t.vel = NBox(x1: vx, y1: vy, x2: vx, y2: vy)
            }
            t.hist.append((f, box))
        }
        t.box = box
        t.last = box
        t.hits += 1
        t.misses = 0
        observe(t, sideOf, anchor, &entered, &exited)
    }

    private func observe(_ t: MotTrack, _ sideOf: (Double, Double) -> Double, _ anchor: CountAnchor,
                         _ entered: inout [MotTrack], _ exited: inout [MotTrack]) {
        let a = anchorPoint(t.box, anchor)
        t.trail.append(a)
        if t.trail.count > 30 { t.trail.removeFirst(t.trail.count - 30) }
        let s = sideOf(a.x, a.y)
        let band = max(p.band, p.bandRel * (t.box.y2 - t.box.y1))
        let d = s > band ? 1 : (s < -band ? -1 : 0)
        if d != 0 {
            if t.side == 0 || d == t.side {
                t.side = d
                t.cand = 0
                t.candN = 0
            } else {                                                    // yan teyidi: art arda sideFrames gözlem
                t.candN = t.cand == d ? t.candN + 1 : 1
                t.cand = d
                if t.candN >= p.sideFrames {
                    t.pending.append(d)                                 // −1→+1 giriş, +1→−1 çıkış
                    t.side = d
                    t.cand = 0
                    t.candN = 0
                }
            }
        }
        if !t.confirmed && t.verified && t.hits >= p.minHits { t.confirmed = true }
        if t.confirmed && !t.pending.isEmpty {
            for x in t.pending {
                if x > 0 {
                    t.entries += 1
                    entered.append(t)
                } else {
                    t.exits += 1
                    exited.append(t)
                }
            }
            t.pending = []
        }
    }
}
