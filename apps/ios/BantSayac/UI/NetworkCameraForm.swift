import SwiftUI
import ImageIO

/// Ayarlar → Görüntü kaynağı bölümü.
struct VideoSourceSection: View {
    @ObservedObject var vm: CountingViewModel

    var body: some View {
        Section {
            Picker("Kaynak", selection: Binding(get: { vm.sourceKind }, set: { vm.setSource($0) })) {
                ForEach(VideoSourceKind.allCases) { Text($0.title).tag($0) }
            }
            NavigationLink {
                NetworkCameraForm(vm: vm)
            } label: {
                HStack {
                    Text("Ağ kamerası")
                    Spacer()
                    Text(vm.networkConfig.summary).foregroundStyle(.secondary).lineLimit(1)
                }
            }
            .accessibilityIdentifier("networkCameraLink")
            if vm.sourceKind == .network, let state = vm.networkState {
                Text(state.text).font(.caption).foregroundStyle(state.isPlaying ? .green : .orange)
            }
        } header: {
            Text("Görüntü kaynağı")
        } footer: {
            Text("Ağ kamerası: telefon, IP kameranın ya da kayıt cihazındaki (NVR/XVR) bir kameranın yayınını alır ve aynı sayım/kalite kontrolünü yapar. Telefon cihaza ağ üzerinden ulaşabilmeli (aynı yerel ağ ya da VPN). Uygulama açık ve telefon şarjda kalmalı.")
        }
    }
}

/// Ağ kamerası ya da kayıt cihazı ayarları, kamera seçimi, bağlantı sınaması ve kaydetme.
struct NetworkCameraForm: View {
    @ObservedObject var vm: CountingViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var config: NetworkCameraConfig
    @State private var cameraPassword: String
    @State private var recorderPassword: String
    @State private var portText: String
    @State private var httpPortText: String
    @State private var rtspPortText: String
    @State private var testing = false
    @State private var result: NetworkCameraSource.ProbeResult?
    @State private var errorText: String?
    @State private var saveWarning: String?
    // Kayıt cihazı kamera listesi
    @State private var channels: [RecorderChannel] = []
    @State private var listing = false
    @State private var channelError: String?
    @State private var search = ""
    @State private var listClient: RecorderClient?
    @StateObject private var thumbnails = ChannelThumbnailLoader()
    @FocusState private var focused: Bool

    init(vm: CountingViewModel) {
        _vm = ObservedObject(wrappedValue: vm)
        // Başlangıç değerleri burada: onAppear'da atansaydı "cihaz değişti" kuralı kayıtlı kamera seçimini silerdi.
        let c = vm.networkConfig
        _config = State(initialValue: c)
        _cameraPassword = State(initialValue: vm.storedPassword(for: .camera))
        _recorderPassword = State(initialValue: vm.storedPassword(for: .recorder))
        _portText = State(initialValue: String(c.port))
        _httpPortText = State(initialValue: c.recorderHTTPPort.map(String.init) ?? "")
        _rtspPortText = State(initialValue: c.recorderRTSPPort.map(String.init) ?? "")
    }

    // Gövde küçük parçalara bölünür: tek büyük ifade derleyicinin tip denetimini zaman aşımına uğratıyordu.
    var body: some View {
        observingChanges(formContent)
            .alert("Şifre", isPresented: warningShown) {
                Button("Tamam") { saveWarning = nil; dismiss() }
            } message: {
                Text(saveWarning ?? "")
            }
            .navigationTitle("Ağ kamerası")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Tamam") { focused = false }
                }
            }
    }

    private var warningShown: Binding<Bool> {
        Binding(get: { saveWarning != nil }, set: { if !$0 { saveWarning = nil } })
    }

    private var formContent: some View {
        Form {
            kindSection
            if config.kind == .camera {
                cameraSections
            } else {
                recorderSections
            }
            substreamSection
            testSection
            saveSection
        }
    }

    private func observingChanges<Content: View>(_ content: Content) -> some View {
        content
            .onChange(of: portText) { _, text in
                config.port = Int(text.filter(\.isNumber)) ?? 0
            }
            .onChange(of: httpPortText) { _, text in
                config.recorderHTTPPort = Int(text.filter(\.isNumber))
            }
            .onChange(of: rtspPortText) { _, text in
                config.recorderRTSPPort = Int(text.filter(\.isNumber))
            }
            .onChange(of: config) { _, _ in
                result = nil
                errorText = nil
            }
            .onChange(of: recorderIdentity) { _, _ in
                recorderChanged()
            }
    }

    /// Başka bir cihaz: eski liste ve seçim geçersiz
    private func recorderChanged() {
        channels = []
        channelError = nil
        listClient = nil
        config.recorderChannel = nil
        thumbnails.reset()
    }

    private var kindSection: some View {
        Section {
            Picker("Cihaz türü", selection: $config.kind) {
                ForEach(NetworkDeviceKind.allCases) { Text($0.title).tag($0) }
            }
            .pickerStyle(.segmented)
            .accessibilityIdentifier("deviceKind")
        } footer: {
            Text(kindFooter)
        }
    }

    private var kindFooter: String {
        config.kind == .camera
            ? "Kamera ağa doğrudan bağlıysa."
            : "Kameralar bir kayıt cihazına (NVR/XVR) bağlıysa: cihazı bir kez ekle, kamerayı listeden seç."
    }

    private var substreamSection: some View {
        Section {
            Toggle("Alt akış (önerilir)", isOn: $config.substream)
        } footer: {
            Text("Sayım için alt akış (ör. 640×360) yeterli; ağı, pili ve ısınmayı azaltır.")
        }
    }

    private var saveSection: some View {
        Section {
            Button {
                save()
            } label: {
                Label("Kaydet ve bu kamerayı kullan", systemImage: "checkmark")
            }
            .disabled(!config.isComplete)
            .accessibilityIdentifier("saveNetworkCamera")
        }
    }

    // MARK: - Kamera

    @ViewBuilder private var cameraSections: some View {
        Section {
            Picker("Marka", selection: $config.brand) {
                ForEach(CameraBrand.allCases) { Text($0.title).tag($0) }
            }
            if config.brand == .custom {
                TextField("rtsp://192.168.1.64:554/…", text: $config.customURL)
                    .keyboardType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .focused($focused)
            } else {
                LabeledContent("IP adresi") {
                    TextField("192.168.1.64", text: $config.host)
                        .keyboardType(.numbersAndPunctuation)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .multilineTextAlignment(.trailing)
                        .focused($focused)
                }
                LabeledContent("Port") {
                    TextField("554", text: $portText)
                        .keyboardType(.numbersAndPunctuation)
                        .multilineTextAlignment(.trailing)
                        .focused($focused)
                }
                Stepper("Kanal: \(config.channel)", value: $config.channel, in: 1...64)
            }
        } header: {
            Text("Kamera")
        } footer: {
            if let url = config.rtspURL {
                Text("Adres: \(url.absoluteString)").textSelection(.enabled)
            } else {
                Text(config.brand == .custom ? "rtsp:// ile başlayan tam adresi girin."
                                             : "Kameranın IP adresini girin (ör. 192.168.1.64).")
            }
        }

        Section {
            TextField("Kullanıcı adı", text: $config.username)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .focused($focused)
            SecureField("Şifre", text: $cameraPassword)
                .focused($focused)
        } header: {
            Text("Giriş")
        } footer: {
            Text("Şifre yalnızca bu iPhone'un güvenli anahtar deposunda (Keychain) saklanır.")
        }
    }

    // MARK: - Kayıt cihazı

    /// Değişince kamera listesi ve seçim sıfırlanır
    private var recorderIdentity: String {
        "\(config.recorderBrand.rawValue)|\(config.cleanRecorderHost)|\(config.effectiveHTTPPort)|\(config.effectiveRTSPPort)|\(config.recorderUsername)"
    }

    @ViewBuilder private var recorderSections: some View {
        recorderDeviceSection
        recorderLoginSection
        channelsSection
    }

    private var recorderDeviceSection: some View {
        Section {
            Picker("Marka", selection: $config.recorderBrand) {
                ForEach(RecorderBrand.allCases) { Text($0.title).tag($0) }
            }
            .pickerStyle(.segmented)
            .accessibilityIdentifier("recorderBrand")
            LabeledContent("IP adresi") {
                TextField("192.168.1.10", text: $config.recorderHost)
                    .keyboardType(.numbersAndPunctuation)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .multilineTextAlignment(.trailing)
                    .focused($focused)
                    .accessibilityIdentifier("recorderHost")
            }
            portsGroup
        } header: {
            Text("Kayıt cihazı")
        } footer: {
            Text(recorderFooter)
        }
    }

    private var portsGroup: some View {
        DisclosureGroup("Portlar") {
            LabeledContent(config.recorderBrand == .trassir ? "SDK portu" : "Web portu") {
                TextField(String(config.recorderBrand.defaultHTTPPort), text: $httpPortText)
                    .keyboardType(.numberPad)
                    .multilineTextAlignment(.trailing)
                    .focused($focused)
                    .accessibilityIdentifier("recorderHTTPPort")
            }
            LabeledContent("Görüntü portu") {
                TextField(String(config.recorderBrand.defaultRTSPPort), text: $rtspPortText)
                    .keyboardType(.numberPad)
                    .multilineTextAlignment(.trailing)
                    .focused($focused)
                    .accessibilityIdentifier("recorderRTSPPort")
            }
        }
    }

    private var recorderFooter: String {
        switch config.recorderBrand {
        case .trassir:
            return "TRASSIR'da Ayarlar → Web sunucusu (SDK) açık olmalı. Varsayılan portlar: SDK 8080, görüntü 555."
        case .hikvision, .dahua:
            return "Kayıt cihazının web arayüzüne girdiğin kullanıcı ile. Varsayılan portlar: web 80, görüntü 554."
        }
    }

    private var recorderLoginSection: some View {
        Section {
            TextField("Kullanıcı adı", text: $config.recorderUsername)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .focused($focused)
                .accessibilityIdentifier("recorderUser")
            SecureField("Şifre", text: $recorderPassword)
                .focused($focused)
                .accessibilityIdentifier("recorderPassword")
        } header: {
            Text("Giriş")
        } footer: {
            Text("Şifre yalnızca bu iPhone'un güvenli anahtar deposunda (Keychain) saklanır.")
        }
    }

    private var channelsSection: some View {
        Section {
            listButton
            channelStatusRows
            ForEach(filteredChannels) { channel in
                channelRow(channel)
            }
        } header: {
            Text(channels.isEmpty ? "Kamera" : "Kameralar (\(channels.count))")
        } footer: {
            Text(channels.isEmpty ? "" : "Bantı gören kameraya dokun.")
        }
    }

    private var listButton: some View {
        Button {
            listChannels()
        } label: {
            HStack {
                Label(channels.isEmpty ? "Kameraları listele" : "Listeyi yenile", systemImage: "list.bullet.rectangle")
                if listing {
                    Spacer()
                    ProgressView()
                }
            }
        }
        .disabled(listing || !config.recorderReady)
        .accessibilityIdentifier("listChannels")
    }

    @ViewBuilder private var channelStatusRows: some View {
        if let channelError {
            Label(channelError, systemImage: "xmark.octagon.fill")
                .foregroundStyle(.red)
                .accessibilityIdentifier("channelError")
            Text(recorderHelp).font(.caption).foregroundStyle(.secondary)
        }
        if channels.isEmpty, let selected = config.recorderChannel {
            Label("Seçili: \(selected.title)", systemImage: "checkmark.circle.fill")
                .foregroundStyle(.green)
        }
        if channels.count > 8 {
            TextField("Kamera ara (ad ya da kanal no)", text: $search)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .focused($focused)
        }
    }

    private var filteredChannels: [RecorderChannel] {
        let q = search.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else { return channels }
        return channels.filter { ch in
            ch.title.lowercased().contains(q) || ch.number.map { String($0) == q } == true
        }
    }

    private func channelRow(_ channel: RecorderChannel) -> some View {
        Button {
            config.recorderChannel = channel
        } label: {
            HStack(spacing: 12) {
                ChannelThumbnail(image: thumbnails.images[channel.id], failed: thumbnails.failed.contains(channel.id))
                VStack(alignment: .leading, spacing: 2) {
                    Text(channel.title).foregroundStyle(.primary).lineLimit(2)
                    if let subtitle = channel.subtitle {
                        Text(subtitle).font(.caption).foregroundStyle(.secondary)
                    }
                }
                Spacer()
                if config.recorderChannel?.id == channel.id {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(.tint)
                }
            }
        }
        .accessibilityIdentifier("channel.\(channel.title)")
        .accessibilityAddTraits(config.recorderChannel?.id == channel.id ? .isSelected : [])
        .task(id: channel.id) {
            // Yalnızca ekranda görünen satırlar yükler; aynı anda en fazla 3 istek (64–128 kanallı cihazlar)
            guard let client = listClient else { return }
            await thumbnails.load(channel, client: client, username: config.recorderUsername,
                                  password: recorderPassword)
        }
    }

    private var recorderHelp: String {
        switch config.recorderBrand {
        case .trassir:
            return "Kontrol et: IP adresi · telefon aynı ağda mı · TRASSIR'da Ayarlar → Web sunucusu (SDK) açık mı, port 8080 mi · kullanıcının kameraları izleme yetkisi var mı."
        case .hikvision, .dahua:
            return "Kontrol et: IP adresi · telefon aynı ağda mı · web portu (varsayılan 80) · kullanıcı adı/şifre (kayıt cihazının web arayüzündeki ile aynı)."
        }
    }

    private func listChannels() {
        focused = false
        listing = true
        channelError = nil
        search = ""
        thumbnails.reset()
        let client = NetworkStreamPlan.recorderClient(config, password: recorderPassword)
        listClient = client
        Task { @MainActor in
            do {
                let list = try await client.channels()
                channels = list
                // Seçili kamera hâlâ var mı (ad değişmiş olabilir)
                if let selected = config.recorderChannel {
                    config.recorderChannel = list.first { $0.id == selected.id }
                }
            } catch {
                channels = []
                channelError = error.localizedDescription
            }
            listing = false
        }
    }

    // MARK: - Sınama ve kayıt

    private var testSection: some View {
        Section {
            Button {
                test()
            } label: {
                HStack {
                    Label("Bağlantıyı test et", systemImage: "antenna.radiowaves.left.and.right")
                    if testing { Spacer(); ProgressView() }
                }
            }
            .disabled(testing || !config.isComplete)
            .accessibilityIdentifier("testConnection")
            if let result {
                if let thumb = result.thumbnail {
                    Image(decorative: thumb, scale: 1).resizable().scaledToFit()
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                }
                Label("Bağlandı · \(result.width)×\(result.height) · \(result.codec)",
                      systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                    .accessibilityIdentifier("testResult")
                if result.width > 1280 {
                    Text("Sayım için alt akış (ör. 640×360) yeterli ve daha az pil/ısı demek.")
                        .font(.caption).foregroundStyle(.orange)
                }
            }
            if let errorText {
                Label(errorText, systemImage: "xmark.octagon.fill").foregroundStyle(.red)
                    .accessibilityIdentifier("testError")
                Text(config.kind == .camera
                     ? "Kontrol et: IP adresi doğru mu · telefon kamerayla aynı ağda mı (misafir Wi-Fi çoğu zaman kameralara erişemez) · kamerada RTSP açık mı, port 554 mü · kullanıcı adı/şifre · marka/kanal doğru mu (olmazsa \"Diğer\" ile tam adres). iPhone \"Yerel ağ\" izni istediyse izin ver."
                     : recorderHelp)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var password: String { config.kind == .camera ? cameraPassword : recorderPassword }

    private func test() {
        guard let plan = NetworkStreamPlan.make(config, password: password) else { return }
        focused = false
        testing = true
        result = nil
        errorText = nil
        Task { @MainActor in
            switch await NetworkCameraSource.probe(resolver: plan.resolver, username: plan.username,
                                                   password: plan.password) {
            case .success(let r): result = r
            case .failure(let e): errorText = e.localizedDescription
            }
            testing = false
        }
    }

    private func save() {
        focused = false
        let warning = vm.saveNetworkConfig(config, password: password)
        vm.setSource(.network)
        if let warning {
            saveWarning = warning                    // sessizce geçme: kullanıcıya göster, sonra kapat
        } else {
            dismiss()
        }
    }
}

// MARK: - Kamera listesi küçük resimleri

private struct ChannelThumbnail: View {
    let image: CGImage?
    let failed: Bool

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 6).fill(Color.secondary.opacity(0.15))
            if let image {
                Image(decorative: image, scale: 1).resizable().scaledToFill()
            } else if failed {
                Image(systemName: "video.slash").foregroundStyle(.secondary)
            } else {
                ProgressView().controlSize(.small)
            }
        }
        .frame(width: 96, height: 54)
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }
}

/// Küçük resimleri sırayla ve sınırlı eşzamanlılıkla yükler: önce cihazın anlık görüntü API'si,
/// olmazsa akışın ilk karesi (RTSP). Görüntü vermeyen kanal (boş kanal) "görüntü yok" olarak işaretlenir.
@MainActor
final class ChannelThumbnailLoader: ObservableObject {
    @Published private(set) var images: [String: CGImage] = [:]
    @Published private(set) var failed: Set<String> = []
    private var inFlight: Set<String> = []
    private var generation = 0
    private let limiter = AsyncLimiter(limit: 3)

    func reset() {
        images = [:]
        failed = []
        inFlight = []
        generation += 1
    }

    func load(_ channel: RecorderChannel, client: RecorderClient, username: String, password: String) async {
        let id = channel.id
        guard images[id] == nil, !failed.contains(id), !inFlight.contains(id) else { return }
        inFlight.insert(id)
        let mine = generation
        await limiter.acquire()
        let image: CGImage?
        if Task.isCancelled {
            image = nil                                   // satır ekrandan çıktı: sonra yeniden denenir
        } else {
            image = await Self.fetch(channel, client: client, username: username, password: password)
        }
        await limiter.release()
        guard mine == generation else { return }
        inFlight.remove(id)
        if let image {
            images[id] = image
        } else if !Task.isCancelled {
            failed.insert(id)
        }
    }

    private nonisolated static func fetch(_ channel: RecorderChannel, client: RecorderClient,
                                          username: String, password: String) async -> CGImage? {
        if let data = try? await client.snapshot(channel), let image = downscale(data) {
            return image
        }
        guard let url = try? await client.streamURL(channel, substream: true) else { return nil }
        if case .success(let probe) = await NetworkCameraSource.probe(url: url, username: username,
                                                                      password: password, timeout: 8) {
            return probe.thumbnail
        }
        return nil
    }

    private nonisolated static func downscale(_ data: Data) -> CGImage? {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil) else { return nil }
        let options: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true,
                                        kCGImageSourceThumbnailMaxPixelSize: 320,
                                        kCGImageSourceCreateThumbnailWithTransform: true]
        return CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary)
    }
}

/// En fazla `limit` iş aynı anda.
actor AsyncLimiter {
    private var available: Int
    private var waiters: [CheckedContinuation<Void, Never>] = []

    init(limit: Int) { available = limit }

    func acquire() async {
        if available > 0 {
            available -= 1
            return
        }
        await withCheckedContinuation { waiters.append($0) }
    }

    func release() {
        if waiters.isEmpty {
            available += 1
        } else {
            waiters.removeFirst().resume()
        }
    }
}
