import SwiftUI

/// ROI, sayım çizgisi, lekeler ve izleri çizer. Kalibrasyonda sürüklenebilir.
struct OverlayView: View {
    @Binding var profile: ProductProfile
    let snapshot: EngineSnapshot
    let fitRect: CGRect
    let editable: Bool
    /// İz kimliği → kalite kararı (ürünün yanında etiket)
    var verdicts: [Int: AppearanceVerdict] = [:]

    @State private var activeHandle: Handle?
    /// vertex: çokgen köşesi; midpoint(i): i ile i+1 arasındaki kenarın ortası (sürükleyince köşe eklenir)
    private enum Handle: Equatable { case topLeft, bottomRight, line, vertex(Int), midpoint(Int) }

    var body: some View {
        Canvas { ctx, _ in
            let roi = viewRect(profile.roi)
            let area = roiPath()

            // ROI dışını karart
            var outside = Path(fitRect)
            outside.addPath(area)
            ctx.fill(outside, with: .color(.black.opacity(0.35)), style: FillStyle(eoFill: true))
            ctx.stroke(area, with: .color(.yellow), lineWidth: 2)

            // Sayım çizgisi
            let (a, b) = lineEndpoints(roi)
            var line = Path()
            line.move(to: a)
            line.addLine(to: b)
            ctx.stroke(line, with: .color(.orange), lineWidth: 4)

            // Lekeler
            for blob in snapshot.blobs {
                let r = viewRect(blob.bbox)
                ctx.stroke(Path(roundedRect: r, cornerRadius: 3), with: .color(.green), lineWidth: 2)
                if blob.multiplicity > 1 {
                    ctx.draw(Text("×\(blob.multiplicity)").font(.caption.bold()).foregroundColor(.green),
                             at: CGPoint(x: r.midX, y: max(fitRect.minY + 8, r.minY - 10)))
                }
            }

            // İzler: beyaz = henüz sayılmadı, camgöbeği = sayıldı
            for t in snapshot.tracks {
                let p = viewPoint(t.x, t.y)
                ctx.fill(Path(ellipseIn: CGRect(x: p.x - 4, y: p.y - 4, width: 8, height: 8)),
                         with: .color(t.counted ? .cyan : .white))
                ctx.draw(Text(hexID(t.id)).font(.caption2.monospacedDigit())
                            .foregroundColor(t.counted ? .cyan : .white),
                         at: CGPoint(x: p.x + 8, y: p.y - 8), anchor: .bottomLeading)
                if let v = verdicts[t.id] {
                    let color: Color = v.pass ? .green : .red
                    if !v.pass {
                        ctx.stroke(Path(ellipseIn: CGRect(x: p.x - 16, y: p.y - 16, width: 32, height: 32)),
                                   with: .color(.red), lineWidth: 3)
                    }
                    let text = v.pass ? "OK \(Int(v.confidence * 100))" : "NOK · \(v.label)"
                    let resolved = ctx.resolve(Text(text).font(.caption2.bold()).foregroundColor(.white))
                    let size = resolved.measure(in: CGSize(width: 220, height: 40))
                    let tag = CGRect(x: p.x - size.width / 2 - 6, y: p.y + 10,
                                     width: size.width + 12, height: size.height + 4)
                    ctx.fill(Path(roundedRect: tag, cornerRadius: tag.height / 2), with: .color(color.opacity(0.85)))
                    ctx.draw(resolved, at: CGPoint(x: tag.midX, y: tag.midY))
                }
            }

            // Akış yönü
            ctx.draw(Text(profile.direction.arrow).font(.system(size: 28, weight: .bold)).foregroundColor(.yellow),
                     at: CGPoint(x: roi.minX + 22, y: roi.minY + 22))

            // Tutamaçlar
            if editable {
                for (_, p) in handleCandidates() {
                    let c = CGRect(x: p.x - 12, y: p.y - 12, width: 24, height: 24)
                    ctx.fill(Path(ellipseIn: c), with: .color(.white))
                    ctx.stroke(Path(ellipseIn: c), with: .color(.black), lineWidth: 2)
                }
                // Kenar ortaları: sürükleyince yeni köşe
                for (_, p) in midpointCandidates() {
                    let c = CGRect(x: p.x - 9, y: p.y - 9, width: 18, height: 18)
                    ctx.fill(Path(ellipseIn: c), with: .color(.yellow.opacity(0.75)))
                    ctx.draw(Text("+").font(.caption.bold()).foregroundColor(.black), at: p)
                }
            }
        }
        .contentShape(Rectangle())
        .gesture(dragGesture)
        .simultaneousGesture(SpatialTapGesture(count: 2).onEnded { value in removeVertex(near: value.location) })
        .allowsHitTesting(editable)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(profile.roiPolygon == nil ? "İlgi alanı: dikdörtgen" : "İlgi alanı: \(profile.roiPolygon?.count ?? 0) köşeli çokgen")
        .accessibilityIdentifier("roiOverlay")
    }

    /// İlgi alanının ekrandaki şekli: çokgen ya da dikdörtgen
    private func roiPath() -> Path {
        guard let poly = profile.roiPolygon, poly.count >= 3 else { return Path(viewRect(profile.roi)) }
        var path = Path()
        path.addLines(poly.map { viewPoint($0.x, $0.y) })
        path.closeSubpath()
        return path
    }

    /// Sürüklenebilir tutamaçlar ve ekrandaki yerleri
    private func handleCandidates() -> [(Handle, CGPoint)] {
        let roi = viewRect(profile.roi)
        let (a, b) = lineEndpoints(roi)
        let line = (Handle.line, CGPoint(x: (a.x + b.x) / 2, y: (a.y + b.y) / 2))
        guard let poly = profile.roiPolygon else {
            return [(.topLeft, CGPoint(x: roi.minX, y: roi.minY)),
                    (.bottomRight, CGPoint(x: roi.maxX, y: roi.maxY)), line]
        }
        return poly.enumerated().map { (Handle.vertex($0.offset), viewPoint($0.element.x, $0.element.y)) } + [line]
    }

    private func midpointCandidates() -> [(Handle, CGPoint)] {
        guard let poly = profile.roiPolygon, poly.count < ProductProfile.maxPolygonPoints else { return [] }
        return poly.indices.map { i in
            let a = poly[i], b = poly[(i + 1) % poly.count]
            return (Handle.midpoint(i), viewPoint((a.x + b.x) / 2, (a.y + b.y) / 2))
        }
    }

    /// Köşeye çift dokunma: köşeyi sil (en az 3 kalır)
    private func removeVertex(near pt: CGPoint) {
        guard editable, var poly = profile.roiPolygon, poly.count > 3 else { return }
        let nearest = poly.indices.min { dist(viewPoint(poly[$0].x, poly[$0].y), pt) < dist(viewPoint(poly[$1].x, poly[$1].y), pt) }
        guard let i = nearest, dist(viewPoint(poly[i].x, poly[i].y), pt) < 30 else { return }
        poly.remove(at: i)
        profile.setPolygon(poly)
    }

    // MARK: - Sürükleme

    private var dragGesture: some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { value in
                if activeHandle == nil { activeHandle = pickHandle(value.startLocation) }
                guard let h = activeHandle else { return }
                let p = normPoint(value.location)
                var r = profile.roi
                switch h {
                case .vertex(let i):
                    guard var poly = profile.roiPolygon, poly.indices.contains(i) else { return }
                    poly[i] = NormPoint(x: Double(p.x), y: Double(p.y))
                    profile.setPolygon(poly)
                    return
                case .midpoint(let i):
                    // Kenar ortasından tutunca yeni köşe eklenir ve sürükleme o köşeyle sürer
                    guard var poly = profile.roiPolygon, poly.indices.contains(i),
                          poly.count < ProductProfile.maxPolygonPoints else { return }
                    poly.insert(NormPoint(x: Double(p.x), y: Double(p.y)), at: i + 1)
                    profile.setPolygon(poly)
                    activeHandle = .vertex(i + 1)
                    return
                case .topLeft:
                    let nx = min(p.x, r.maxX - 0.05), ny = min(p.y, r.maxY - 0.05)
                    r = CGRect(x: nx, y: ny, width: r.maxX - nx, height: r.maxY - ny)
                case .bottomRight:
                    let nx = max(p.x, r.minX + 0.05), ny = max(p.y, r.minY + 0.05)
                    r = CGRect(x: r.minX, y: r.minY, width: nx - r.minX, height: ny - r.minY)
                case .line:
                    let pos = profile.direction.isVertical ? p.y : p.x
                    let lo = profile.direction.isVertical ? r.minY : r.minX
                    let hi = profile.direction.isVertical ? r.maxY : r.maxX
                    profile.linePosition = clamp(pos, lo + 0.02, hi - 0.02)
                    return
                }
                profile.roi = r
                // Çizgi ROI içinde kalsın
                let lo = profile.direction.isVertical ? r.minY : r.minX
                let hi = profile.direction.isVertical ? r.maxY : r.maxX
                profile.linePosition = clamp(profile.linePosition, lo + 0.02, hi - 0.02)
            }
            .onEnded { _ in activeHandle = nil }
    }

    private func pickHandle(_ pt: CGPoint) -> Handle? {
        let roi = viewRect(profile.roi)
        let (a, b) = lineEndpoints(roi)
        // En yakın tutamaç: köşe, sayım çizgisi ya da kenar ortası (yeni köşe)
        let candidates = handleCandidates() + midpointCandidates()
        let best = candidates.min { dist($0.1, pt) < dist($1.1, pt) }
        if let best, dist(best.1, pt) < 44 { return best.0 }
        // Çizginin görünen parçasının herhangi bir yerinden tutmak
        let onLine = profile.direction.isVertical
            ? abs(pt.y - a.y) < 30 && pt.x >= min(a.x, b.x) - 20 && pt.x <= max(a.x, b.x) + 20
            : abs(pt.x - a.x) < 30 && pt.y >= min(a.y, b.y) - 20 && pt.y <= max(a.y, b.y) + 20
        return onLine ? .line : nil
    }

    // MARK: - Koordinat dönüşümleri

    private func viewRect(_ r: CGRect) -> CGRect {
        CGRect(x: fitRect.minX + r.minX * fitRect.width,
               y: fitRect.minY + r.minY * fitRect.height,
               width: r.width * fitRect.width,
               height: r.height * fitRect.height)
    }

    private func viewPoint(_ x: Double, _ y: Double) -> CGPoint {
        CGPoint(x: fitRect.minX + CGFloat(x) * fitRect.width,
                y: fitRect.minY + CGFloat(y) * fitRect.height)
    }

    private func normPoint(_ p: CGPoint) -> CGPoint {
        guard fitRect.width > 0, fitRect.height > 0 else { return .zero }
        return CGPoint(x: clamp((p.x - fitRect.minX) / fitRect.width, 0, 1),
                       y: clamp((p.y - fitRect.minY) / fitRect.height, 0, 1))
    }

    /// Sayım çizgisinin ekrandaki uçları. Çokgende çizgi yalnızca çokgenin içinde kalan parçadır (tutamaç onun ortası);
    /// çizgi çokgeni kesmiyorsa sınır kutusu boyunca çizilir.
    private func lineEndpoints(_ roi: CGRect) -> (CGPoint, CGPoint) {
        let pos = Double(profile.linePosition)
        if let span = polygonSpan(at: pos) {
            return profile.direction.isVertical
                ? (viewPoint(span.lo, pos), viewPoint(span.hi, pos))
                : (viewPoint(pos, span.lo), viewPoint(pos, span.hi))
        }
        if profile.direction.isVertical {
            let y = fitRect.minY + profile.linePosition * fitRect.height
            return (CGPoint(x: roi.minX, y: y), CGPoint(x: roi.maxX, y: y))
        } else {
            let x = fitRect.minX + profile.linePosition * fitRect.width
            return (CGPoint(x: x, y: roi.minY), CGPoint(x: x, y: roi.maxY))
        }
    }

    /// Çizgi (akış eksenine dik) ile çokgen kenarlarının kesişimlerinin en küçüğü ve en büyüğü (normalize).
    private func polygonSpan(at pos: Double) -> (lo: Double, hi: Double)? {
        guard let poly = profile.roiPolygon, poly.count >= 3 else { return nil }
        let vertical = profile.direction.isVertical      // çizgi yatay: y = pos; değilse x = pos
        var hits: [Double] = []
        for k in poly.indices {
            let a = poly[k], b = poly[(k + 1) % poly.count]
            let (ua, ub) = vertical ? (a.y, b.y) : (a.x, b.x)   // çizgiye dik eksen
            let (va, vb) = vertical ? (a.x, b.x) : (a.y, b.y)   // çizgi boyunca eksen
            guard (ua <= pos && pos <= ub) || (ub <= pos && pos <= ua), ua != ub else { continue }
            hits.append(va + (vb - va) * (pos - ua) / (ub - ua))
        }
        guard let lo = hits.min(), let hi = hits.max(), hi - lo > 1e-6 else { return nil }
        return (lo, hi)
    }

    private func dist(_ a: CGPoint, _ b: CGPoint) -> CGFloat { hypot(a.x - b.x, a.y - b.y) }
    private func clamp(_ v: CGFloat, _ lo: CGFloat, _ hi: CGFloat) -> CGFloat { min(max(v, lo), max(lo, hi)) }
}
