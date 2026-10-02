import Foundation

/// Sayılan bir ürünün muayene kaydı (Genel bakış kartı). Son `InspectionLog.capacity` kayıt bellekte tutulur.
struct InspectionRecord: Identifiable, Equatable {
    let id = UUID()
    let trackId: Int
    /// Bu leke kaç ürün sayıldı (bitişik ürünlerde > 1)
    let delta: Int
    let time: Date
    let jpeg: Data
    /// nil: öğretme kapalı ya da örnek yetersiz (yalnızca sayıldı)
    var verdict: AppearanceVerdict?
    /// Karar bekleniyor
    var pending = false

    var shortID: String { "#" + hexID(trackId) }
}

struct InspectionStats: Equatable {
    var counted = 0
    var pass = 0
    var fail = 0
    var unknown = 0

    var failRate: Double? {
        let judged = pass + fail
        return judged > 0 ? Double(fail) / Double(judged) : nil
    }
}

enum InspectionLog {
    static let capacity = 50
}
