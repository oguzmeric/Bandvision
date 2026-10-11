import Foundation
import CoreGraphics

/// Çoklu izleme düzeni (contracts/view-layouts.json, docs/02-contracts.md §8). Hücre `[x, y, w, h]` birim ızgarada;
/// hücre sırası kutu sırasıdır.
struct ViewLayout: Codable, Identifiable, Equatable, Sendable {
    let id: String
    let name: String
    let cols: Int
    let rows: Int
    let cells: [[Int]]

    var tileCount: Int { cells.count }

    /// Kutuları 16:9 kabul eden tuval oranı (genişlik / yükseklik)
    var aspectRatio: CGFloat { CGFloat(cols * 16) / CGFloat(rows * 9) }

    /// Kutu dikdörtgenleri: hücreler `size` tuvaline oranlanır, kutular arasında `gap` boşluk kalır.
    func rects(in size: CGSize, gap: CGFloat = 2) -> [CGRect] {
        guard cols > 0, rows > 0 else { return [] }
        let cw = size.width / CGFloat(cols), ch = size.height / CGFloat(rows)
        return cells.map { c in
            CGRect(x: CGFloat(c[0]) * cw, y: CGFloat(c[1]) * ch, width: CGFloat(c[2]) * cw, height: CGFloat(c[3]) * ch)
                .insetBy(dx: gap / 2, dy: gap / 2)
        }
    }
}

enum ViewLayouts {
    static let maxTiles = 16

    /// Uygulama paketindeki sözleşme dosyası (project.yml: contracts/view-layouts.json, kopya değil)
    static let catalog: [ViewLayout] = load(from: .main)

    private struct Catalog: Decodable {
        let version: Int
        let layouts: [ViewLayout]
    }

    static func load(from bundle: Bundle) -> [ViewLayout] {
        guard let url = bundle.url(forResource: "view-layouts", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let catalog = try? JSONDecoder().decode(Catalog.self, from: data),
              catalog.version == 1 else { return [] }
        return catalog.layouts.filter { layout in layout.cells.allSatisfy { $0.count == 4 } }
    }

    static func layout(_ id: String) -> ViewLayout? { catalog.first { $0.id == id } }

    /// `n` kameranın sığdığı en küçük düzen; 16'dan fazlası için 16'lı (web'deki `smallest_for` ile aynı).
    static func smallestFor(_ n: Int) -> ViewLayout? {
        catalog.first { $0.tileCount >= n } ?? catalog.last
    }
}
