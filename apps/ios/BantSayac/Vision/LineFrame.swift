import Foundation
import CoreGraphics

/// Açılı sayım çizgisi çerçevesi — docs/03-algorithm.md §4.8. Python `bantvision.core.lineframe.LineFrame` ile
/// birebir aynı işlem sırası (eşdeğerlik: BantSayacTests/LineFrameTests ↔ services/edge/tests/test_angled_line.py).
/// `v` çizgi boyunca, `u` akış yönünde (çizgi `u = 0`); birim kare yüksekliği.
struct LineFrame: Equatable {
    let alpha: Double          // w / h
    let ax: Double, ay: Double // A (eş ölçekli)
    let dx: Double, dy: Double // çizgi yönü (birim)
    /// Silme sınırı (v0, v1, u0, u1), ±0.1 dahil
    let bounds: (v0: Double, v1: Double, u0: Double, u1: Double)

    var nx: Double { -dy }
    var ny: Double { dx }

    static func == (l: LineFrame, r: LineFrame) -> Bool {
        l.alpha == r.alpha && l.ax == r.ax && l.ay == r.ay && l.dx == r.dx && l.dy == r.dy
    }

    static func build(a: NormPoint, b: NormPoint, width w: Int, height h: Int) -> LineFrame? {
        guard w > 0, h > 0 else { return nil }
        let alpha = Double(w) / Double(h)
        let ax = a.x * alpha, ay = a.y
        let bx = b.x * alpha, by = b.y
        let length = hypot(bx - ax, by - ay)
        guard length >= 1e-6 else { return nil }
        let dx = (bx - ax) / length, dy = (by - ay) / length
        let partial = LineFrame(alpha: alpha, ax: ax, ay: ay, dx: dx, dy: dy, bounds: (0, 0, 0, 0))
        let corners = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)].map { partial.toFrame($0.0, $0.1) }
        let vs = corners.map(\.v), us = corners.map(\.u)
        return LineFrame(alpha: alpha, ax: ax, ay: ay, dx: dx, dy: dy,
                         bounds: (vs.min()! - 0.1, vs.max()! + 0.1, us.min()! - 0.1, us.max()! + 0.1))
    }

    func toFrame(_ x: Double, _ y: Double) -> (v: Double, u: Double) {
        let rx = x * alpha - ax, ry = y - ay
        return (rx * dx + ry * dy, rx * nx + ry * ny)
    }

    func toImage(_ v: Double, _ u: Double) -> (x: Double, y: Double) {
        let qx = ax + v * dx + u * nx
        let qy = ay + v * dy + u * ny
        return (qx / alpha, qy)
    }

    /// Leke çerçeveye: merkez (v, u); kutu piksellerden (`frameBBox`), yoksa görüntü kutusunun köşelerinden.
    /// Görüntüdeki özgün kutu `sourceBBox`'ta kalır (sayım olayının kırpıntısı için).
    func blob(_ b: Blob) -> Blob {
        let c = toFrame(b.cx, b.cy)
        var box: CGRect
        if let fb = b.frameBBox {
            box = fb
        } else {
            let r = b.bbox
            let pts = [(r.minX, r.minY), (r.maxX, r.minY), (r.minX, r.maxY), (r.maxX, r.maxY)]
                .map { toFrame(Double($0.0), Double($0.1)) }
            let v0 = pts.map(\.v).min()!, v1 = pts.map(\.v).max()!
            let u0 = pts.map(\.u).min()!, u1 = pts.map(\.u).max()!
            box = CGRect(x: v0, y: u0, width: v1 - v0, height: u1 - u0)
        }
        var out = Blob(cx: c.v, cy: c.u, bbox: box, area: b.area, multiplicity: b.multiplicity)
        out.sourceBBox = b.bbox
        return out
    }

    /// Akış vektörüne (a→b'nin sağ eli) en yakın eksen yönü; uyumluluk için `direction`'a yazılır.
    static func nearestDirection(a: NormPoint, b: NormPoint, aspect: Double) -> FlowDirection {
        let dx = (b.x - a.x) * aspect, dy = b.y - a.y
        let fx = -dy, fy = dx
        if abs(fy) >= abs(fx) { return fy > 0 ? .down : .up }
        return fx > 0 ? .right : .left
    }
}
