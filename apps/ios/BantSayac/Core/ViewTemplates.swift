import Foundation

/// Bir kamera: sözleşmedeki şablon kutusu `{sourceId, channelId}`. iPhone'da `sourceId` cihaz kimliği,
/// `channelId` kayıt cihazının kanal kimliği (doğrudan kamerada nil).
struct CameraRef: Codable, Hashable, Sendable {
    var sourceId: String
    var channelId: String?

    init(sourceId: String, channelId: String?) {
        self.sourceId = sourceId
        self.channelId = channelId
    }

    private enum CodingKeys: String, CodingKey { case sourceId, channelId }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        sourceId = try c.decode(String.self, forKey: .sourceId)
        channelId = try c.decodeIfPresent(String.self, forKey: .channelId)
    }

    /// Sözleşme `channelId`'yi her zaman yazar (kanalsız kamerada null)
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(sourceId, forKey: .sourceId)
        try c.encode(channelId, forKey: .channelId)
    }
}

/// Çoklu izleme şablonu (contracts/view-template.schema.json)
struct ViewTemplate: Codable, Identifiable, Equatable, Sendable {
    var id: String
    var name: String
    var layout: String
    var tiles: [CameraRef?]
    var createdAt: Double
    var updatedAt: Double
}

enum TemplateError: LocalizedError, Equatable {
    case emptyName, unknownLayout, tileCount, duplicateCamera, notFound, readOnly

    var errorDescription: String? {
        switch self {
        case .emptyName: return "Şablon adı boş olamaz."
        case .unknownLayout: return "Bilinmeyen düzen."
        case .tileCount: return "Kutu sayısı düzenle uyuşmuyor."
        case .duplicateCamera: return "Aynı kamera bir şablonda yalnızca bir kez yer alabilir."
        case .notFound: return "Şablon bulunamadı."
        case .readOnly: return "Şablon dosyası okunamadığı için değişiklik kaydedilmiyor."
        }
    }
}

/// Şablonlar telefonda (`views.json`, atomik); web ile eşitlenmez. Kurallar: ad 1–60 karakter (çakışmada " (2)"),
/// düzen katalogda, kutu sayısı düzenle aynı, aynı kamera en fazla bir kez.
@MainActor
final class TemplateStore: ObservableObject {
    static let nameLimit = 60

    @Published private(set) var templates: [ViewTemplate] = []
    /// Dosya bozuktu ya da yazılamadı: İzleme ekranında gösterilir
    @Published private(set) var problem: String?

    private struct Stored: Codable {
        var version = 1
        var templates: [ViewTemplate]
    }

    private let file: JSONFile
    private let now: () -> Double
    /// Bozuk dosya kenara alınamadı: üzerine yazılmaz
    private var readOnly = false

    init(directory: URL = AppFiles.directory, now: @escaping () -> Double = { Date().timeIntervalSince1970 }) {
        file = JSONFile(url: directory.appendingPathComponent("views.json"))
        self.now = now
        switch file.load(Stored.self) {
        case .missing:
            break
        case .loaded(let stored):
            templates = stored.templates.filter { t in
                ViewLayouts.layout(t.layout).map { $0.tileCount == t.tiles.count } ?? false
            }
        case .corrupt(let moved):
            if let moved {
                problem = "Şablon dosyası okunamadı; kenara alındı (\(moved)). Şablonları yeniden oluştur."
            } else {
                readOnly = true
                problem = "Şablon dosyası okunamadı; değişiklikler kaydedilmeyecek."
            }
        }
    }

    func template(_ id: String?) -> ViewTemplate? {
        guard let id else { return nil }
        return templates.first { $0.id == id }
    }

    @discardableResult
    func create(name: String, layout: String, tiles: [CameraRef?]) throws -> ViewTemplate {
        let t = now()
        var template = ViewTemplate(id: Self.newID(), name: "", layout: layout, tiles: tiles, createdAt: t, updatedAt: t)
        template.name = try uniqueName(name, excluding: template.id)
        try validate(template)
        try commit(templates + [template])
        return template
    }

    @discardableResult
    func update(_ template: ViewTemplate) throws -> ViewTemplate {
        guard let i = templates.firstIndex(where: { $0.id == template.id }) else { throw TemplateError.notFound }
        var t = template
        t.name = try uniqueName(template.name, excluding: t.id)
        t.createdAt = templates[i].createdAt
        t.updatedAt = now()
        try validate(t)
        var list = templates
        list[i] = t
        try commit(list)
        return t
    }

    func delete(_ id: String) throws {
        try commit(templates.filter { $0.id != id })
    }

    /// Kayıt cihazının kanallarından şablon: kanal sayısına uyan en küçük düzen, en fazla 16 kanal (sırayla).
    @discardableResult
    func createFromRecorder(name: String, deviceId: String, channels: [RecorderChannel]) throws -> ViewTemplate {
        guard let layout = ViewLayouts.smallestFor(channels.count) else { throw TemplateError.unknownLayout }
        let refs: [CameraRef?] = channels.prefix(layout.tileCount).map { CameraRef(sourceId: deviceId, channelId: $0.id) }
        return try create(name: name, layout: layout.id,
                          tiles: refs + Array(repeating: nil, count: layout.tileCount - refs.count))
    }

    /// Düzen değişince kameralar sırasıyla yeni kutulara taşınır; sığmayanların sayısı döner.
    static func retile(_ tiles: [CameraRef?], to layout: ViewLayout) -> (tiles: [CameraRef?], dropped: Int) {
        let cameras = tiles.compactMap { $0 }
        let kept: [CameraRef?] = cameras.prefix(layout.tileCount).map { $0 }
        return (kept + Array(repeating: nil, count: layout.tileCount - kept.count), cameras.count - kept.count)
    }

    #if DEBUG || UITEST
    /// UI testi: her test boş şablonla başlar
    func removeAll() {
        do { try commit([]) } catch { problem = error.localizedDescription }
    }
    #endif

    // MARK: - İç

    static func newID() -> String { UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased() }

    private func uniqueName(_ raw: String, excluding id: String) throws -> String {
        let base = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !base.isEmpty else { throw TemplateError.emptyName }
        return UniqueName.make(base, limit: Self.nameLimit, taken: Set(templates.filter { $0.id != id }.map(\.name)))
    }

    private func validate(_ t: ViewTemplate) throws {
        guard let layout = ViewLayouts.layout(t.layout) else { throw TemplateError.unknownLayout }
        guard t.tiles.count == layout.tileCount else { throw TemplateError.tileCount }
        let cameras = t.tiles.compactMap { $0 }
        guard Set(cameras).count == cameras.count else { throw TemplateError.duplicateCamera }
    }

    private func commit(_ list: [ViewTemplate]) throws {
        guard !readOnly else { throw TemplateError.readOnly }
        do {
            try file.save(Stored(templates: list))
        } catch {
            problem = "Şablonlar kaydedilemedi: \(error.localizedDescription)"
            throw error
        }
        templates = list
        problem = nil
    }
}
