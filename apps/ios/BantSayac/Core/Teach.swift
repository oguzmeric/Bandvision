import Foundation
import Vision

/// Örnekle öğretme (docs/09-ml-roadmap.md §4b, A aşaması): her profil için iyi ve kusurlu ürün örnekleri.
/// Karar cihazda, Apple Vision görüntü benzerliğiyle (feature print) en yakın örneklere bakılarak verilir;
/// model eğitimi yoktur, işaretlenen örnek hemen etkili olur.

enum TeachLabel {
    static let good = "İyi"
    static let anomaly = "Beklenmedik"
}

struct TeachExample: Codable, Identifiable, Sendable, Equatable {
    var id: UUID
    var label: String
    var created: Date
}

/// Kalite kararı. `label`: "İyi", kusur adı ya da "Beklenmedik" (yalnızca iyi örnek varken).
struct AppearanceVerdict: Sendable, Equatable {
    let pass: Bool
    let label: String
    /// 0...1
    let confidence: Double
}

/// Örnek bankası + sınıflandırıcı. Vision nesneleri yalnızca kendi kuyruğunda kullanılır.
final class AppearanceClassifier: @unchecked Sendable {
    private let queue = DispatchQueue(label: "bantsayac.teach", qos: .utility)
    private var bank: [(id: UUID, label: String, print: VNFeaturePrintObservation)] = []
    /// Yalnızca iyi örnek varken: iyi örneklerin birbirine en yakın uzaklıklarının medyanı (ölçek).
    private var goodScale: Float = 0

    static let minGoodForAnomaly = 5
    static let k = 5

    /// Bankayı diskteki feature print arşivleriyle yeniden kurar.
    func load(_ items: [(UUID, String, Data)]) {
        queue.async { [self] in
            bank = items.compactMap { id, label, data in
                guard let p = try? NSKeyedUnarchiver.unarchivedObject(ofClass: VNFeaturePrintObservation.self,
                                                                      from: data) else { return nil }
                return (id: id, label: label, print: p)
            }
            recomputeScale()
        }
    }

    /// Görüntünün feature print'ini hesaplar, bankaya ekler; arşivini (diske yazmak için) döndürür.
    func add(id: UUID, label: String, jpeg: Data, completion: @escaping @Sendable (Data?) -> Void) {
        queue.async { [self] in
            guard let p = Self.featurePrint(jpeg),
                  let archive = try? NSKeyedArchiver.archivedData(withRootObject: p, requiringSecureCoding: true)
            else { completion(nil); return }
            bank.append((id: id, label: label, print: p))
            recomputeScale()
            completion(archive)
        }
    }

    func remove(id: UUID) {
        queue.async { [self] in
            bank.removeAll { $0.id == id }
            recomputeScale()
        }
    }

    func relabel(id: UUID, to label: String) {
        queue.async { [self] in
            if let i = bank.firstIndex(where: { $0.id == id }) { bank[i].label = label }
            recomputeScale()
        }
    }

    /// Karar: en yakın k örneğin 1/uzaklık ağırlıklı oyu. Yalnızca iyi örnek varsa anomali modu:
    /// en yakın iyi örneğe uzaklık, iyi örneklerin kendi aralarındaki tipik uzaklığın 1,8 katını aşarsa kalır.
    /// Örnek yetersizse nil (karar yok).
    func classify(jpeg: Data, completion: @escaping @Sendable (AppearanceVerdict?) -> Void) {
        queue.async { [self] in
            guard !bank.isEmpty, let q = Self.featurePrint(jpeg) else { completion(nil); return }
            var dists: [(label: String, d: Float)] = []
            for item in bank {
                var d: Float = 0
                if (try? q.computeDistance(&d, to: item.print)) != nil { dists.append((item.label, d)) }
            }
            let labels = Set(dists.map(\.label))
            if labels == [TeachLabel.good] {
                guard dists.count >= Self.minGoodForAnomaly, goodScale > 0,
                      let nearest = dists.map(\.d).min() else { completion(nil); return }
                let score = Double(nearest / goodScale)
                let limit = 1.8
                let pass = score <= limit
                let conf = pass ? 1 - 0.5 * score / limit : min(1, 0.5 + 0.5 * (score - limit) / limit)
                completion(AppearanceVerdict(pass: pass, label: pass ? TeachLabel.good : TeachLabel.anomaly,
                                             confidence: max(0.5, min(0.99, conf))))
                return
            }
            let nearest = dists.sorted { $0.d < $1.d }.prefix(Self.k)
            var votes: [String: Double] = [:]
            for n in nearest { votes[n.label, default: 0] += 1 / Double(n.d + 1e-4) }
            let total = votes.values.reduce(0, +)
            guard let (label, w) = votes.max(by: { $0.value < $1.value }), total > 0 else { completion(nil); return }
            completion(AppearanceVerdict(pass: label == TeachLabel.good, label: label,
                                         confidence: min(0.99, w / total)))
        }
    }

    private func recomputeScale() {
        let goods = bank.filter { $0.label == TeachLabel.good }.map(\.print)
        guard goods.count >= 2 else { goodScale = 0; return }
        var nn: [Float] = []
        for (i, a) in goods.enumerated() {
            var best = Float.greatestFiniteMagnitude
            for (j, b) in goods.enumerated() where i != j {
                var d: Float = 0
                if (try? a.computeDistance(&d, to: b)) != nil { best = min(best, d) }
            }
            if best < .greatestFiniteMagnitude { nn.append(best) }
        }
        nn.sort()
        goodScale = nn.isEmpty ? 0 : nn[nn.count / 2]
    }

    private static func featurePrint(_ jpeg: Data) -> VNFeaturePrintObservation? {
        let request = VNGenerateImageFeaturePrintRequest()
        let handler = VNImageRequestHandler(data: jpeg, options: [:])
        do {
            try handler.perform([request])
            return request.results?.first
        } catch {
            return nil
        }
    }
}

/// Seçili profilin kusur türleri ve örnekleri. Disk: Application Support/teach/<profil-id>/
/// (index.json, <örnek-id>.jpg, <örnek-id>.fp). A aşamasında cihaza özeldir; sözleşmeye F1.1/B'de girer.
@MainActor
final class TeachStore: ObservableObject {
    @Published private(set) var profileID: UUID?
    @Published private(set) var defects: [String] = []
    @Published private(set) var examples: [TeachExample] = []
    @Published var enabled = true {
        didSet { save() }
    }

    let classifier = AppearanceClassifier()

    private struct Index: Codable {
        var defects: [String]
        var examples: [TeachExample]
        var enabled: Bool
    }

    static let minGood = 3
    static let minPerDefect = 2

    func count(_ label: String) -> Int { examples.filter { $0.label == label }.count }

    /// Karar verebilecek kadar örnek var mı: iyi + en az bir kusur türü, ya da yalnızca iyi (anomali modu).
    var isReady: Bool {
        let good = count(TeachLabel.good)
        let taughtDefects = defects.filter { count($0) >= Self.minPerDefect }
        if good >= Self.minGood && !taughtDefects.isEmpty { return true }
        return good >= AppearanceClassifier.minGoodForAnomaly
    }

    var readinessText: String {
        let good = count(TeachLabel.good)
        if isReady {
            let taught = defects.filter { count($0) >= Self.minPerDefect }
            return taught.isEmpty
                ? "Hazır (yalnızca iyi örnekler: iyiye benzemeyen ürünler kalır)"
                : "Hazır: İyi + \(taught.joined(separator: ", "))"
        }
        if good < Self.minGood { return "En az \(Self.minGood) iyi örnek gerekli (şu an \(good))" }
        return "Bir kusur türüne en az \(Self.minPerDefect) örnek ya da toplam "
            + "\(AppearanceClassifier.minGoodForAnomaly) iyi örnek gerekli"
    }

    func image(for example: TeachExample) -> Data? {
        guard let dir = directory else { return nil }
        return try? Data(contentsOf: dir.appendingPathComponent("\(example.id.uuidString).jpg"))
    }

    func load(profileID id: UUID) {
        guard id != profileID else { return }
        profileID = id
        defects = []
        examples = []
        guard let dir = directory,
              let data = try? Data(contentsOf: dir.appendingPathComponent("index.json")),
              let index = try? JSONDecoder().decode(Index.self, from: data) else {
            enabled = true
            classifier.load([])
            return
        }
        defects = index.defects
        examples = index.examples
        enabled = index.enabled
        let items: [(UUID, String, Data)] = index.examples.compactMap { ex in
            guard let fp = try? Data(contentsOf: dir.appendingPathComponent("\(ex.id.uuidString).fp")) else { return nil }
            return (ex.id, ex.label, fp)
        }
        classifier.load(items)
    }

    func addDefect(_ name: String) {
        let n = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !n.isEmpty, n != TeachLabel.good, n != TeachLabel.anomaly, !defects.contains(n) else { return }
        defects.append(n)
        save()
    }

    /// Kusur türünü ve ona ait örnekleri siler.
    func removeDefect(_ name: String) {
        defects.removeAll { $0 == name }
        for ex in examples where ex.label == name { deleteFiles(ex.id); classifier.remove(id: ex.id) }
        examples.removeAll { $0.label == name }
        save()
    }

    func addExample(jpeg: Data, label: String) {
        guard let dir = directory else { return }
        if label != TeachLabel.good && !defects.contains(label) { addDefect(label) }
        let ex = TeachExample(id: UUID(), label: label, created: Date())
        try? jpeg.write(to: dir.appendingPathComponent("\(ex.id.uuidString).jpg"))
        examples.append(ex)
        save()
        let fpURL = dir.appendingPathComponent("\(ex.id.uuidString).fp")
        classifier.add(id: ex.id, label: label, jpeg: jpeg) { archive in
            if let archive { try? archive.write(to: fpURL) }
        }
    }

    func deleteExample(_ ex: TeachExample) {
        examples.removeAll { $0.id == ex.id }
        deleteFiles(ex.id)
        classifier.remove(id: ex.id)
        save()
    }

    // MARK: - Disk

    /// Profil silinince örneklerini de sil.
    nonisolated static func deleteData(profileID id: UUID) {
        guard let base = try? FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                                      appropriateFor: nil, create: false) else { return }
        try? FileManager.default.removeItem(at: base.appendingPathComponent("teach/\(id.uuidString)", isDirectory: true))
    }

    private var directory: URL? {
        guard let id = profileID,
              let base = try? FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                                      appropriateFor: nil, create: true) else { return nil }
        let dir = base.appendingPathComponent("teach/\(id.uuidString)", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    private func deleteFiles(_ id: UUID) {
        guard let dir = directory else { return }
        for ext in ["jpg", "fp"] {
            try? FileManager.default.removeItem(at: dir.appendingPathComponent("\(id.uuidString).\(ext)"))
        }
    }

    private func save() {
        guard let dir = directory else { return }
        let index = Index(defects: defects, examples: examples, enabled: enabled)
        if let data = try? JSONEncoder().encode(index) {
            try? data.write(to: dir.appendingPathComponent("index.json"), options: .atomic)
        }
    }
}
