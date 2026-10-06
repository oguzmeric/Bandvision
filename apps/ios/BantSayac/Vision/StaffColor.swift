import Foundation

/// Öğretilen personel üniforma rengi: CIE Lab (D65). Sözleşme `staffColors` öğesi (algoritma §4.10 eki).
struct LabColor: Codable, Equatable, Hashable, Sendable {
    var L: Double
    var a: Double
    var b: Double
}
