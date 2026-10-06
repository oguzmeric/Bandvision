import SwiftUI

struct ProfilesView: View {
    @ObservedObject var vm: CountingViewModel
    @ObservedObject var store: ProfileStore
    @Environment(\.dismiss) private var dismiss
    @State private var editing: ProductProfile?

    var body: some View {
        NavigationStack {
            List {
                // Sayım türüne göre gruplu (bant üstü ürün, kişi sayımı)
                ForEach(ProductCatalog.categories.filter(\.available)) { cat in
                    let list = store.profiles.filter(cat.contains)
                    if !list.isEmpty {
                        Section {
                            ForEach(list) { p in row(p) }
                        } header: {
                            Label(cat.title, systemImage: cat.icon)
                        }
                    }
                }
            }
            .navigationTitle("Profiller")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Kapat") { dismiss() }
                }
                ToolbarItem(placement: .primaryAction) {
                    addMenu
                }
            }
            .sheet(item: $editing) { p in
                ProfileEditView(profile: p) { vm.saveEditedProfile($0) }
            }
        }
    }

    private func row(_ p: ProductProfile) -> some View {
        Button {
            vm.selectProfile(p.id)
            dismiss()
        } label: {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(p.name).foregroundStyle(.primary)
                    Text(Self.status(p))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if p.id == store.selectedID {
                    Image(systemName: "checkmark").foregroundStyle(.tint)
                }
            }
        }
        .swipeActions(edge: .trailing) {
            if store.profiles.count > 1 {
                Button(role: .destructive) { vm.deleteProfile(p.id) } label: {
                    Label("Sil", systemImage: "trash")
                }
            }
            Button { editing = p } label: {
                Label("Düzenle", systemImage: "slider.horizontal.3")
            }
            .tint(.blue)
            Button { vm.duplicateProfile(p) } label: {
                Label("Kopyala", systemImage: "plus.square.on.square")
            }
            .tint(.gray)
        }
    }

    /// Profilin altındaki kısa durum yazısı
    static func status(_ p: ProductProfile) -> String {
        switch p.mode {
        case .detect: return "Giriş / çıkış sayımı"
        case .linescan: return "Bitişik / hacimli ürün"
        case .blob: return p.expectedArea > 0 ? "Kalibre edildi" : "Kalibre edilmedi"
        }
    }

    /// Hazır profilden ekle: sayım türüne göre (yakında olanlar görünür ama seçilemez)
    private var addMenu: some View {
        Menu {
            ForEach(ProductCatalog.categories) { cat in
                Section(cat.available ? cat.title : "\(cat.title) · yakında") {
                    if cat.available {
                        ForEach(cat.presets) { preset in
                            Button(preset.name) { store.add(preset.make()) }
                        }
                    } else {
                        Button {} label: { Label(cat.subtitle, systemImage: cat.icon) }
                            .disabled(true)
                    }
                }
            }
        } label: {
            Image(systemName: "plus")
        }
        .accessibilityLabel("Profil ekle")
    }
}

struct ProfileEditView: View {
    @State private var draft: ProductProfile
    let onSave: (ProductProfile) -> Void
    @Environment(\.dismiss) private var dismiss

    init(profile: ProductProfile, onSave: @escaping (ProductProfile) -> Void) {
        _draft = State(initialValue: profile)
        self.onSave = onSave
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Genel") {
                    TextField("Profil adı", text: $draft.name)
                    Picker("Akış yönü", selection: $draft.direction) {
                        ForEach(FlowDirection.allCases) { d in
                            Text("\(d.arrow) \(d.title)").tag(d)
                        }
                    }
                }

                Section {
                    Stepper("Hassasiyet eşiği: \(draft.diffThreshold)", value: $draft.diffThreshold, in: 5...120)
                    Picker("İşleme çözünürlüğü", selection: $draft.processingWidth) {
                        Text("Hızlı (160)").tag(160)
                        Text("Dengeli (240)").tag(240)
                        Text("Detaylı (360)").tag(360)
                    }
                    Stepper("Birleştirme (kapama): \(draft.closeIterations)", value: $draft.closeIterations, in: 0...4)
                    VStack(alignment: .leading) {
                        Text("Min. alan oranı: \(draft.minAreaFactor, specifier: "%.2f")")
                        Slider(value: $draft.minAreaFactor, in: 0.1...0.9)
                    }
                } header: {
                    Text("Algılama")
                } footer: {
                    Text("Küçük ürünlerde (yumurta) Dengeli/Detaylı, büyük ürünlerde (torba) Hızlı yeterlidir. Parçalı görünen ürünlerde birleştirmeyi artırın.")
                }

                Section("Sayım") {
                    Toggle("Bitişik ürünleri ayır", isOn: $draft.splitTouching)
                    Stepper("Maks. çarpan: \(draft.maxMultiplicity)", value: $draft.maxMultiplicity, in: 1...12)
                    Stepper("Min. görülme (kare): \(draft.minHits)", value: $draft.minHits, in: 1...6)
                    VStack(alignment: .leading) {
                        Text("Eşleştirme mesafesi: \(draft.maxMatchDistance, specifier: "%.2f")")
                        Slider(value: $draft.maxMatchDistance, in: 0.03...0.3)
                    }
                    VStack(alignment: .leading) {
                        Text("Arka plan uyum hızı: \(draft.backgroundRate, specifier: "%.3f")")
                        Slider(value: $draft.backgroundRate, in: 0.002...0.1)
                    }
                }

                Section("Kalibrasyon") {
                    LabeledContent("Tek ürün alanı",
                                   value: draft.expectedArea > 0 ? String(format: "%.4f", draft.expectedArea) : "yok")
                    Button("Örnek kalibrasyonunu sıfırla", role: .destructive) {
                        draft.expectedArea = 0
                    }
                }
            }
            .navigationTitle(draft.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Vazgeç") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Kaydet") {
                        onSave(draft)
                        dismiss()
                    }
                }
            }
        }
    }
}
