import Foundation

/// Düzenlenen şablon (kaydedilmeden önce)
struct TemplateDraft: Identifiable, Equatable {
    var id: String
    var isNew: Bool
    var name: String
    var layout: String
    var tiles: [CameraRef?]
}

extension TemplateDraft {
    static func new() -> TemplateDraft {
        TemplateDraft(id: UUID().uuidString, isNew: true, name: "", layout: "4", tiles: Array(repeating: nil, count: 4))
    }

    init(_ template: ViewTemplate) {
        self.init(id: template.id, isNew: false, name: template.name, layout: template.layout, tiles: template.tiles)
    }
}

/// Izgaradaki bir kutu (ya da tek kamera): hub aboneliği, durum ve kare sayacı.
@MainActor
final class TileModel: ObservableObject, Identifiable {
    let id: Int
    let ref: CameraRef?
    let quality: TileQuality
    let title: String
    let sink = TileSink()
    @Published private(set) var status: TileStatus = .idle
    /// Son saniyedeki kare sayısı (teşhis)
    @Published private(set) var fps = 0
    /// Toplam gelen kare (arayüz testi; saniyede bir güncellenir)
    @Published private(set) var frames = 0
    private var subscribed = false

    var key: HubKey? { ref.map { HubKey(ref: $0, quality: quality) } }

    init(id: Int, ref: CameraRef?, title: String, quality: TileQuality = .sub) {
        self.id = id
        self.ref = ref
        self.title = title
        self.quality = quality
        sink.setStatusHandler { [weak self] status in
            guard let model = self else { return }
            Task { @MainActor in model.status = status }
        }
    }

    func subscribe(_ hub: CameraHub) {
        guard !subscribed, let key else { return }
        subscribed = true
        hub.subscribe(key, sink)
        // Durum hemen alınır: sink'ten gelen durum ana iş parçacığına sonradan atlar, o ana dek `.idle` görünmesin
        status = hub.status(key) ?? status
    }

    func unsubscribe(_ hub: CameraHub) {
        guard subscribed, let key else { return }
        subscribed = false
        hub.unsubscribe(key, sink)
        // Hub kendi son karesini tutar ve yeniden aboneliğe verir; bırakılan kutu bellek tutmasın
        sink.clearLast()
    }

    func collectStats() {
        let n = sink.takeFrameCount()
        if n != fps { fps = n }
        if n > 0 { frames += n }
    }
}

/// İzleme sekmesi: seçili şablon, kutular, tek kamera, görünürlük (sekme + ön plan) ve ısı uyarısı.
/// Kutular yalnızca sekme görünür ve uygulama ön plandayken abonedir; ayrılınca hub 5 sn sonra kapatır.
@MainActor
final class WatchModel: ObservableObject {
    let templates: TemplateStore
    let devices: DeviceStore
    let hub: CameraHub
    @Published private(set) var currentID: String?
    @Published private(set) var tiles: [TileModel] = []
    /// Tam ekran tek kamera (ana akış); açıkken ızgara kutuları bırakılır
    @Published private(set) var single: TileModel?
    @Published var diagnostics = false
    @Published private(set) var thermalWarning = false
    /// Açık bağlantı sayısı (teşhis satırı; saniyede bir güncellenir)
    @Published private(set) var openCount: (sub: Int, main: Int) = (0, 0)

    private var visible = false
    private var foreground = true
    private let defaults: UserDefaults
    private let thermal: () -> ProcessInfo.ThermalState
    private var ticker: Task<Void, Never>?
    private static let currentKey = "bs.watch.current"

    init(templates: TemplateStore, devices: DeviceStore, hub: CameraHub, defaults: UserDefaults = .standard,
         thermal: @escaping () -> ProcessInfo.ThermalState = { ProcessInfo.processInfo.thermalState }) {
        self.templates = templates
        self.devices = devices
        self.hub = hub
        self.defaults = defaults
        self.thermal = thermal
        #if DEBUG || UITEST
        if ProcessInfo.processInfo.environment["BS_TEST_FORMS"] != nil { templates.removeAll() }
        #endif
        let saved = defaults.string(forKey: Self.currentKey)
        select(templates.template(saved)?.id ?? templates.templates.first?.id)
        // Saniyede bir: hub temizliği (sekmeden çıkınca da sürer), kare hızı, ısı
        ticker = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                guard let self else { return }
                self.tick()
            }
        }
    }

    var current: ViewTemplate? { templates.template(currentID) }
    var layout: ViewLayout? { current.flatMap { ViewLayouts.layout($0.layout) } }

    func select(_ id: String?) {
        let template = templates.template(id)
        currentID = template?.id
        defaults.set(template?.id, forKey: Self.currentKey)
        rebuildTiles()
    }

    /// Kutular şablonun güncel haliyle kurulur; ortak kameraların bağlantısı sürer (hub aynı okuyucuyu verir).
    /// Sıra önemli: önce ortak kameraların yeni kutuları abone olur (okuyucu boşta kalmaz, sınırda çıkarılmaz),
    /// sonra eski kutular bırakılır, en son kalan yeni kutular abone olur (boşalan yerleri kullanır).
    func rebuildTiles() {
        let old = tiles
        let fresh = (current?.tiles ?? []).enumerated().map { index, ref in
            TileModel(id: index, ref: ref, title: ref.map { devices.title(for: $0) } ?? "")
        }
        tiles = fresh
        if visible && foreground && single == nil {
            let oldKeys = Set(old.compactMap(\.key))
            for tile in fresh {
                if let key = tile.key, oldKeys.contains(key) { tile.subscribe(hub) }
            }
        }
        for tile in old { tile.unsubscribe(hub) }
        applyActive()
    }

    /// Sekme göründü/gizlendi. Görününce adlar ve kutular yenilenir (cihaz adı değişmiş olabilir).
    func setVisible(_ on: Bool) {
        guard on != visible else { return }
        visible = on
        if on { rebuildTiles() } else { applyActive() }
    }

    /// Uygulama ön planda mı. Arka plana geçince bağlantılar hemen kapanır (iOS uygulamayı askıya alır).
    func setForeground(_ on: Bool) {
        guard on != foreground else { return }
        foreground = on
        applyActive()
        if !on { hub.closeIdle() }
    }

    func tick() {
        hub.sweep()
        for tile in tiles { tile.collectStats() }
        single?.collectStats()
        let counts = hub.openCount
        if counts.sub != openCount.sub || counts.main != openCount.main { openCount = counts }
        let warm = thermal().rawValue >= ProcessInfo.ThermalState.serious.rawValue
        if warm != thermalWarning { thermalWarning = warm }
    }

    /// Kutuya dokunuş: şifre hatası ya da NVR reddinde yeniden dener, yoksa tek kamerayı açar.
    func tapped(_ tile: TileModel) {
        switch tile.status {
        case .authFailed, .nvrLimit: retry(tile)
        default: openSingle(tile)
        }
    }

    func retry(_ tile: TileModel) {
        if let key = tile.key { hub.retry(key) }
    }

    /// Tek kamera: ana akış (ilk karesi gelene dek alt akışın son karesi görünür); ızgara kutuları bırakılır.
    func openSingle(_ tile: TileModel) {
        guard let ref = tile.ref, single == nil else { return }
        single = TileModel(id: -1, ref: ref, title: tile.title, quality: .main)
        applyActive()
    }

    func closeSingle() {
        single?.unsubscribe(hub)
        single = nil
        applyActive()
    }

    /// Kayıt cihazının kanallarından şablon (kanal listesi yoksa önce cihazdan alınır). Dönüş: kanal sayısı.
    func createFromRecorder(_ device: NetworkDevice) async throws -> Int {
        var list = devices.channels[device.id] ?? []
        if list.isEmpty {
            guard let client = devices.recorderClient(for: device.id) else { throw RecorderError.noChannels }
            list = try await client.channels()
            guard !list.isEmpty else { throw RecorderError.noChannels }
            devices.setChannels(list, for: device.id)
        }
        let template = try templates.createFromRecorder(name: device.name, deviceId: device.id, channels: list)
        select(template.id)
        return list.count
    }

    func saveTemplate(_ draft: TemplateDraft) throws {
        let saved: ViewTemplate
        if draft.isNew {
            saved = try templates.create(name: draft.name, layout: draft.layout, tiles: draft.tiles)
        } else {
            saved = try templates.update(ViewTemplate(id: draft.id, name: draft.name, layout: draft.layout,
                                                      tiles: draft.tiles, createdAt: 0, updatedAt: 0))
        }
        select(saved.id)
    }

    /// Verilen şablonu siler; silinen seçiliyse ilk kalan şablon seçilir, değilse seçim değişmez.
    func deleteTemplate(_ id: String) throws {
        let wasCurrent = id == currentID
        try templates.delete(id)
        if wasCurrent { select(templates.templates.first?.id) }
    }

    func deleteCurrent() throws {
        guard let id = currentID else { return }
        try deleteTemplate(id)
    }

    // MARK: - İç

    private func applyActive() {
        let gridActive = visible && foreground && single == nil
        for tile in tiles {
            if gridActive { tile.subscribe(hub) } else { tile.unsubscribe(hub) }
        }
        if let single {
            if visible && foreground { single.subscribe(hub) } else { single.unsubscribe(hub) }
        }
    }
}
