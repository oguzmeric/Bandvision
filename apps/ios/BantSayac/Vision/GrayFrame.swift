import CoreVideo

/// Küçültülmüş gri seviye kare (Y düzleminden kutu-ortalama ile).
struct GrayFrame {
    let width: Int
    let height: Int
    let sourceWidth: Int
    let sourceHeight: Int
    let pixels: [UInt8]

    static func make(from pb: CVPixelBuffer, targetWidth: Int) -> GrayFrame? {
        guard CVPixelBufferIsPlanar(pb) else { return nil }
        CVPixelBufferLockBaseAddress(pb, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pb, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddressOfPlane(pb, 0) else { return nil }

        let srcW = CVPixelBufferGetWidthOfPlane(pb, 0)
        let srcH = CVPixelBufferGetHeightOfPlane(pb, 0)
        let stride = CVPixelBufferGetBytesPerRowOfPlane(pb, 0)
        let f = max(1, srcW / max(64, targetWidth))
        let w = srcW / f
        let h = srcH / f
        let area = f * f
        let src = base.assumingMemoryBound(to: UInt8.self)

        var out = [UInt8](repeating: 0, count: w * h)
        out.withUnsafeMutableBufferPointer { dst in
            for y in 0..<h {
                let sy = y * f
                for x in 0..<w {
                    let sx = x * f
                    var sum = 0
                    for dy in 0..<f {
                        let row = src + (sy + dy) * stride + sx
                        for dx in 0..<f { sum += Int(row[dx]) }
                    }
                    dst[y * w + x] = UInt8(sum / area)
                }
            }
        }
        return GrayFrame(width: w, height: h, sourceWidth: srcW, sourceHeight: srcH, pixels: out)
    }
}
