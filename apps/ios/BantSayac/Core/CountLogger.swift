import Foundation
import UIKit

/// İki yönlü sayımda olayın yönü (sözleşme `count.direction`: in / out)
enum CountDirection: String, Codable, Sendable {
    case entry = "in"
    case exit = "out"
}

struct CountEventRecord: Codable, Sendable {
    let ts: Date
    let delta: Int
    let total: Int
    let profile: String
    /// İki yönlü sayım (kişi): giriş/çıkış; tek yönlü sayımda yok
    var direction: CountDirection? = nil
}

struct WebhookPayload: Codable {
    let device: String
    let line: String
    let events: [CountEventRecord]
}

/// Sayım olaylarını tutar: dakikalık özet (CSV), anlık hız ve webhook gönderimi.
@MainActor
final class CountLogger: ObservableObject {
    @Published private(set) var ratePerMinute = 0

    var webhookURL = ""
    var lineName = "Hat-1"
    var profileName = ""

    private var minuteBuckets: [Date: Int] = [:]
    private var minuteBucketsOut: [Date: Int] = [:]
    private var recent: [(date: Date, delta: Int)] = []
    private var pending: [CountEventRecord] = []
    private var sending = false
    private let totalKey = "bs.sessionTotal"
    private let totalOutKey = "bs.sessionTotalOut"
    private let deviceID: String
    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        return e
    }()

    var restoredTotal: Int { UserDefaults.standard.integer(forKey: totalKey) }
    var restoredTotalOut: Int { UserDefaults.standard.integer(forKey: totalOutKey) }

    init() {
        deviceID = UIDevice.current.identifierForVendor?.uuidString ?? "unknown"
        Task { [weak self] in
            while true {
                try? await Task.sleep(nanoseconds: 5_000_000_000)
                guard let self else { return }
                self.updateRate()
                self.flush()
            }
        }
    }

    /// `direction`: iki yönlü sayımda giriş/çıkış (çıkışlar dakikalık ayrı sütunda; hız yalnızca girişlerden)
    func record(delta: Int, total: Int, direction: CountDirection? = nil) {
        let now = Date()
        let minute = Date(timeIntervalSince1970: floor(now.timeIntervalSince1970 / 60) * 60)
        if direction == .exit {
            minuteBucketsOut[minute, default: 0] += delta
            UserDefaults.standard.set(total, forKey: totalOutKey)
        } else {
            minuteBuckets[minute, default: 0] += delta
            recent.append((date: now, delta: delta))
            UserDefaults.standard.set(total, forKey: totalKey)
        }
        pending.append(CountEventRecord(ts: now, delta: delta, total: total, profile: profileName, direction: direction))
        if pending.count > 5000 { pending.removeFirst(pending.count - 5000) }
        updateRate()
    }

    func resetSession() {
        minuteBuckets.removeAll()
        minuteBucketsOut.removeAll()
        recent.removeAll()
        pending.removeAll()
        UserDefaults.standard.set(0, forKey: totalKey)
        UserDefaults.standard.set(0, forKey: totalOutKey)
        updateRate()
    }

    func makeCSV() -> URL? {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HH:mm"
        f.locale = Locale(identifier: "tr_TR")
        var s: String
        if minuteBucketsOut.isEmpty {
            s = "dakika;adet\n"
            for k in minuteBuckets.keys.sorted() {
                s += "\(f.string(from: k));\(minuteBuckets[k] ?? 0)\n"
            }
        } else {                                       // iki yönlü sayım: giriş ve çıkış ayrı sütunlar
            s = "dakika;giriş;çıkış\n"
            for k in Set(minuteBuckets.keys).union(minuteBucketsOut.keys).sorted() {
                s += "\(f.string(from: k));\(minuteBuckets[k] ?? 0);\(minuteBucketsOut[k] ?? 0)\n"
            }
        }
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("bant-sayim-\(Int(Date().timeIntervalSince1970)).csv")
        do {
            try s.write(to: url, atomically: true, encoding: .utf8)
            return url
        } catch {
            return nil
        }
    }

    private func updateRate() {
        let cutoff = Date().addingTimeInterval(-60)
        recent.removeAll { $0.date < cutoff }
        ratePerMinute = recent.reduce(0) { $0 + $1.delta }
    }

    private func flush() {
        guard !sending, !pending.isEmpty else { return }
        let trimmed = webhookURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let url = URL(string: trimmed),
              let scheme = url.scheme, scheme.hasPrefix("http") else {
            pending.removeAll()   // webhook tanımlı değil: biriktirme
            return
        }
        let batch = pending
        pending.removeAll()
        sending = true

        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = 10
        req.httpBody = try? encoder.encode(WebhookPayload(device: deviceID, line: lineName, events: batch))

        Task { [weak self] in
            var ok = false
            if let result = try? await URLSession.shared.data(for: req),
               let http = result.1 as? HTTPURLResponse {
                ok = (200..<300).contains(http.statusCode)
            }
            guard let self else { return }
            self.sending = false
            if !ok {
                // Başarısızsa geri koy; ağ gelince tekrar denenir.
                self.pending = Array((batch + self.pending).suffix(5000))
            }
        }
    }
}
