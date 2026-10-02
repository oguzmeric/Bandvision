import SwiftUI

/// ROI, sayım çizgisi, lekeler ve izleri çizer. Kalibrasyonda sürüklenebilir.
struct OverlayView: View {
    @Binding var profile: ProductProfile
    let snapshot: EngineSnapshot
    let fitRect: CGRect
    let editable: Bool

    @State private var activeHandle: Handle?
    private enum Handle { case topLeft, bottomRight, line }

    var body: some View {
        Canvas { ctx, _ in
            let roi = viewRect(profile.roi)

            // ROI dışını karart
            var outside = Path(fitRect)
            outside.addRect(roi)
            ctx.fill(outside, with: .color(.black.opacity(0.35)), style: FillStyle(eoFill: true))
            ctx.stroke(Path(roi), with: .color(.yellow), lineWidth: 2)

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
            }

            // Akış yönü
            ctx.draw(Text(profile.direction.arrow).font(.system(size: 28, weight: .bold)).foregroundColor(.yellow),
                     at: CGPoint(x: roi.minX + 22, y: roi.minY + 22))

            // Tutamaçlar
            if editable {
                let handles = [CGPoint(x: roi.minX, y: roi.minY),
                               CGPoint(x: roi.maxX, y: roi.maxY),
                               CGPoint(x: (a.x + b.x) / 2, y: (a.y + b.y) / 2)]
                for p in handles {
                    let c = CGRect(x: p.x - 12, y: p.y - 12, width: 24, height: 24)
                    ctx.fill(Path(ellipseIn: c), with: .color(.white))
                    ctx.stroke(Path(ellipseIn: c), with: .color(.black), lineWidth: 2)
                }
            }
        }
        .contentShape(Rectangle())
        .gesture(dragGesture)
        .allowsHitTesting(editable)
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
        let candidates: [(Handle, CGPoint)] = [
            (.topLeft, CGPoint(x: roi.minX, y: roi.minY)),
            (.bottomRight, CGPoint(x: roi.maxX, y: roi.maxY)),
            (.line, CGPoint(x: (a.x + b.x) / 2, y: (a.y + b.y) / 2))
        ]
        let best = candidates.min { dist($0.1, pt) < dist($1.1, pt) }
        if let best, dist(best.1, pt) < 44 { return best.0 }
        // Çizginin herhangi bir yerinden tutmak
        let onLine = profile.direction.isVertical
            ? abs(pt.y - a.y) < 30 && pt.x >= roi.minX && pt.x <= roi.maxX
            : abs(pt.x - a.x) < 30 && pt.y >= roi.minY && pt.y <= roi.maxY
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

    private func lineEndpoints(_ roi: CGRect) -> (CGPoint, CGPoint) {
        if profile.direction.isVertical {
            let y = fitRect.minY + profile.linePosition * fitRect.height
            return (CGPoint(x: roi.minX, y: y), CGPoint(x: roi.maxX, y: y))
        } else {
            let x = fitRect.minX + profile.linePosition * fitRect.width
            return (CGPoint(x: x, y: roi.minY), CGPoint(x: x, y: roi.maxY))
        }
    }

    private func dist(_ a: CGPoint, _ b: CGPoint) -> CGFloat { hypot(a.x - b.x, a.y - b.y) }
    private func clamp(_ v: CGFloat, _ lo: CGFloat, _ hi: CGFloat) -> CGFloat { min(max(v, lo), max(lo, hi)) }
}
