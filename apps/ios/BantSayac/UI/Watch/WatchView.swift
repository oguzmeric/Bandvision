import AVFoundation
import SwiftUI

/// İzleme sekmesi: şablonlu ızgarada canlı kameralar (docs/superpowers/specs/2026-10-11-iphone-izleme-design.md §2).
/// Yan çevirince ızgara tam ekran; kutuya dokununca tek kamera (ana akış).
struct WatchView: View {
    let vm: CountingViewModel
    let onCountCamera: () -> Void
    let onOpenSettings: () -> Void
    @StateObject private var model: WatchModel
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.verticalSizeClass) private var verticalSizeClass
    @State private var editing: TemplateDraft?
    @State private var notice: String?
    @State private var pickingRecorder = false
    @State private var confirmCount: TileModel?
    /// NVR'dan şablon oluşturuluyor (çift dokunuşta ikinci kez başlamasın)
    @State private var creating = false

    init(vm: CountingViewModel, onCountCamera: @escaping () -> Void, onOpenSettings: @escaping () -> Void) {
        self.vm = vm
        self.onCountCamera = onCountCamera
        self.onOpenSettings = onOpenSettings
        _model = StateObject(wrappedValue: WatchModel(templates: TemplateStore(), devices: vm.devices, hub: vm.hub))
    }

    private var isLandscape: Bool { verticalSizeClass == .compact }
    private var barsHidden: Bool { isLandscape || model.single != nil }

    var body: some View {
        NavigationStack {
            ZStack {
                Color.black.ignoresSafeArea()
                content
                if let single = model.single {
                    SingleCameraView(tile: single, onClose: { model.closeSingle() },
                                     onCount: { countRequested(single) })
                        .zIndex(1)
                }
            }
            .navigationTitle("İzleme")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { toolbarItems }
            .toolbar(barsHidden ? .hidden : .visible, for: .navigationBar)
            .toolbar(barsHidden ? .hidden : .visible, for: .tabBar)
            .statusBarHidden(isLandscape)
        }
        .sheet(item: $editing) { draft in
            TemplateEditor(model: model, draft: draft)
        }
        .confirmationDialog("Hangi kayıt cihazı?", isPresented: $pickingRecorder, titleVisibility: .visible) {
            ForEach(recorders) { device in
                Button(device.name) { createFromRecorder(device) }
            }
            Button("Vazgeç", role: .cancel) {}
        }
        .alert("Sayım bu kameraya geçsin mi?", isPresented: confirmShown, presenting: confirmCount) { tile in
            Button("Geç") { if let ref = tile.ref { switchCounting(to: ref) } }
            Button("Vazgeç", role: .cancel) {}
        } message: { tile in
            Text("Süren sayım \(tile.title) kamerasıyla devam eder.")
        }
        .onAppear {
            OrientationLock.allowLandscape(true)
            model.setVisible(true)
        }
        .onDisappear {
            OrientationLock.allowLandscape(false)
            model.setVisible(false)
        }
        .onChange(of: scenePhase) { _, phase in
            model.setForeground(phase != .background)
        }
    }

    // MARK: - İçerik

    private var showsGrid: Bool { !model.devices.devices.isEmpty && model.current != nil }

    /// Uyarılar (ısı, bozuk şablon dosyası, bilgi) her durumda görünür: cihaz yok, şablon yok ya da ızgara
    @ViewBuilder private var content: some View {
        VStack(spacing: 6) {
            if showsGrid && !isLandscape { header }
            banners
            if model.devices.devices.isEmpty {
                emptyDevices
            } else if model.current == nil {
                emptyTemplates
            } else {
                grid
            }
        }
    }

    @ViewBuilder private var banners: some View {
        if model.thermalWarning { banner("Telefon ısındı, daha küçük bir şablon önerilir.", icon: "thermometer.high", color: .orange) }
        if let problem = model.templates.problem { banner(problem, icon: "exclamationmark.triangle", color: .red) }
        if let notice { banner(notice, icon: "info.circle", color: .blue) }
    }

    private var header: some View {
        HStack {
            Text(model.current?.name ?? "")
                .font(.headline)
                .foregroundStyle(.white)
                .lineLimit(1)
            Spacer()
            if model.diagnostics {
                Text(diagnosticsText)
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal)
        .contentShape(Rectangle())
        .onLongPressGesture { model.diagnostics.toggle() }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("watchHeader")
    }

    private var diagnosticsText: String {
        let open = model.openCount
        let heat: String
        switch ProcessInfo.processInfo.thermalState {
        case .nominal: heat = "normal"
        case .fair: heat = "ılık"
        case .serious: heat = "ciddi"
        case .critical: heat = "kritik"
        @unknown default: heat = "?"
        }
        return "bağlantı \(open.sub)+\(open.main) · ısı \(heat)"
    }

    private func banner(_ text: String, icon: String, color: Color) -> some View {
        HStack {
            Label(text, systemImage: icon).font(.caption)
            Spacer()
            if text == notice {
                Button { notice = nil } label: { Image(systemName: "xmark") }
                    .accessibilityLabel("Kapat")
            }
        }
        .padding(8)
        .foregroundStyle(.white)
        .background(color.opacity(0.75))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .padding(.horizontal)
    }

    private var grid: some View {
        GeometryReader { geo in
            if let layout = model.layout {
                let canvas = AVMakeRect(aspectRatio: CGSize(width: layout.aspectRatio, height: 1),
                                        insideRect: CGRect(origin: .zero, size: geo.size))
                let rects = layout.rects(in: canvas.size)
                ZStack(alignment: .topLeading) {
                    ForEach(model.tiles) { tile in
                        if tile.id < rects.count {
                            let rect = rects[tile.id]
                            TileView(tile: tile, vm: vm, diagnostics: model.diagnostics)
                                .frame(width: rect.width, height: rect.height)
                                .position(x: canvas.minX + rect.midX, y: canvas.minY + rect.midY)
                                .onTapGesture { model.tapped(tile) }
                        }
                    }
                }
            }
        }
        .ignoresSafeArea(edges: isLandscape ? .all : [])
    }

    private var emptyDevices: some View {
        ContentUnavailableView {
            Label("Cihaz yok", systemImage: "video.slash")
        } description: {
            Text("Önce Ayarlar → Görüntü kaynağı → Cihazlar'dan kamera ya da NVR ekle.")
        } actions: {
            Button("Ayarlar'a git") { onOpenSettings() }
                .buttonStyle(.borderedProminent)
        }
    }

    private var emptyTemplates: some View {
        ContentUnavailableView {
            Label("Şablon yok", systemImage: "square.grid.2x2")
        } description: {
            Text("Kameraları birlikte izlemek için bir şablon oluştur.")
        } actions: {
            Button("Yeni şablon") { editing = TemplateDraft.new() }
                .buttonStyle(.borderedProminent)
                .accessibilityIdentifier("emptyNewTemplate")
            Button("NVR'dan şablon") { startFromRecorder() }
                .disabled(creating)
                .accessibilityIdentifier("emptyFromRecorder")
        }
    }

    // MARK: - Araç çubuğu

    @ToolbarContentBuilder private var toolbarItems: some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) {
            Menu {
                ForEach(model.templates.templates) { template in
                    Button {
                        notice = nil
                        model.select(template.id)
                    } label: {
                        if template.id == model.currentID {
                            Label(template.name, systemImage: "checkmark")
                        } else {
                            Text(template.name)
                        }
                    }
                }
            } label: {
                Label("Şablonlar", systemImage: "rectangle.grid.2x2")
            }
            .disabled(model.templates.templates.isEmpty)
            .accessibilityIdentifier("templatePicker")
        }
        ToolbarItemGroup(placement: .topBarTrailing) {
            if let current = model.current {
                Button("Düzenle") { editing = TemplateDraft(current) }
                    .accessibilityIdentifier("editTemplate")
            }
            Menu {
                Button("Yeni şablon") { editing = TemplateDraft.new() }
                Button("NVR'dan şablon") { startFromRecorder() }
                    .disabled(creating)
            } label: {
                Image(systemName: "plus")
            }
            .accessibilityLabel("Şablon ekle")
            .accessibilityIdentifier("addTemplate")
        }
    }

    // MARK: - İşler

    private var recorders: [NetworkDevice] { model.devices.devices.filter { $0.kind == .recorder } }

    private func startFromRecorder() {
        switch recorders.count {
        case 0: notice = "Önce bir kayıt cihazı ekle (Ayarlar → Görüntü kaynağı → Cihazlar)."
        case 1: createFromRecorder(recorders[0])
        default: pickingRecorder = true
        }
    }

    private func createFromRecorder(_ device: NetworkDevice) {
        guard !creating else { return }
        creating = true
        Task {
            do {
                let total = try await model.createFromRecorder(device)
                notice = total > ViewLayouts.maxTiles ? "\(total) kanaldan \(ViewLayouts.maxTiles)'sı eklendi." : nil
            } catch {
                notice = error.localizedDescription
            }
            creating = false
        }
    }

    private var confirmShown: Binding<Bool> {
        Binding(get: { confirmCount != nil }, set: { if !$0 { confirmCount = nil } })
    }

    private func countRequested(_ tile: TileModel) {
        guard let ref = tile.ref else { return }
        // Süren sayım başka bir kamerada ya da başka bir kaynakta (telefon kamerası, video) ise önce sorulur
        if vm.isRunning && (vm.sourceKind != .network || vm.isVideoMode || vm.countCamera != ref) {
            confirmCount = tile
        } else {
            switchCounting(to: ref)
        }
    }

    private func switchCounting(to ref: CameraRef) {
        vm.selectCountCamera(ref)
        vm.setSource(.network)
        model.closeSingle()
        onCountCamera()
    }
}

/// Izgaradaki kutu: görüntü, ad, durum metni, sayaç rozeti, (teşhiste) kare hızı
private struct TileView: View {
    @ObservedObject var tile: TileModel
    let vm: CountingViewModel
    let diagnostics: Bool

    var body: some View {
        ZStack {
            Color(white: 0.12)
            if tile.ref != nil {
                TileVideoView(sink: tile.sink)
            }
            if tile.ref == nil {
                Image(systemName: "plus").foregroundStyle(.secondary)
            } else if let text = tile.status.text {
                Text(text)
                    .font(.caption.bold())
                    .foregroundStyle(.white)
                    .padding(6)
                    .background(.black.opacity(0.6))
                    .clipShape(RoundedRectangle(cornerRadius: 6))
            }
            VStack {
                Spacer()
                HStack {
                    Text(tile.title)
                        .font(.caption2)
                        .foregroundStyle(.white)
                        .lineLimit(1)
                        .padding(.horizontal, 4).padding(.vertical, 2)
                        .background(.black.opacity(0.5))
                    Spacer()
                    if diagnostics && tile.ref != nil {
                        Text("\(tile.fps) kare/sn")
                            .font(.caption2.monospacedDigit())
                            .foregroundStyle(.white)
                            .padding(.horizontal, 4).padding(.vertical, 2)
                            .background(.black.opacity(0.5))
                    }
                }
            }
            .padding(4)
        }
        .clipped()
        .contentShape(Rectangle())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(tile.ref == nil ? "Boş kutu" : tile.title)
        .accessibilityValue("\(tile.status.text ?? "canlı") · kare \(tile.frames)")
        .accessibilityAddTraits(.isButton)
        .accessibilityIdentifier("tile.\(tile.id)")
        // Rozet kutunun erişilebilirlik öğesinin dışında: `countBadge` ayrı bir öğe olarak sorgulanabilir
        .overlay(alignment: .topTrailing) {
            CountBadge(vm: vm, ref: tile.ref).padding(4)
        }
    }
}

/// Sayılan kameranın kutusunda sayaç (ağ sayımı bu kameradayken)
private struct CountBadge: View {
    @ObservedObject var vm: CountingViewModel
    let ref: CameraRef?

    var body: some View {
        if let ref, ref == vm.countCamera, vm.sourceKind == .network, !vm.isVideoMode {
            Text(vm.profile.mode == .detect ? "Giriş \(vm.total) · Çıkış \(vm.totalOut)" : "Toplam \(vm.total)")
                .font(.caption2.bold())
                .foregroundStyle(.white)
                .padding(.horizontal, 6).padding(.vertical, 3)
                .background(Color.blue.opacity(0.85))
                .clipShape(Capsule())
                .accessibilityIdentifier("countBadge")
        }
    }
}
