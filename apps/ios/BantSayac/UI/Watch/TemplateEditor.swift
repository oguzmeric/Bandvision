import SwiftUI

/// Şablon düzenleyici: ad, düzen (9 seçenek), kutulara kamera (dokun: seç; basılı tut: değiştir/boşalt), sil.
struct TemplateEditor: View {
    @ObservedObject var model: WatchModel
    @State var draft: TemplateDraft
    @Environment(\.dismiss) private var dismiss
    @State private var picking: Int?
    @State private var error: String?
    @State private var dropped = 0
    @State private var confirmDelete = false

    private struct Slot: Identifiable {
        let index: Int
        var id: Int { index }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Ad") {
                    TextField("Şablon adı (ör. Giriş katı)", text: $draft.name)
                        .accessibilityIdentifier("templateName")
                }
                Section("Düzen") {
                    layoutPicker
                }
                Section {
                    tilesPreview
                } header: {
                    Text("Kutular")
                } footer: {
                    Text(footerText)
                }
                if let error {
                    Section {
                        Text(error).foregroundStyle(.red)
                    }
                }
                if !draft.isNew {
                    Section {
                        Button("Şablonu sil", role: .destructive) { confirmDelete = true }
                            .accessibilityIdentifier("deleteTemplate")
                    }
                }
            }
            .navigationTitle(draft.isNew ? "Yeni şablon" : "Şablonu düzenle")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Vazgeç") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Kaydet") { save() }
                        .accessibilityIdentifier("saveTemplate")
                }
            }
            .sheet(item: pickingSlot) { slot in
                NavigationStack {
                    CameraPickerView(devices: model.devices, selected: draft.tiles[slot.index],
                                     unavailable: unavailable(except: slot.index), allowsEmpty: true) { ref in
                        draft.tiles[slot.index] = ref
                        picking = nil
                    }
                    .navigationTitle("Kutu \(slot.index + 1)")
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar {
                        ToolbarItem(placement: .cancellationAction) {
                            Button("Kapat") { picking = nil }
                        }
                    }
                }
            }
            .alert("Şablon silinsin mi?", isPresented: $confirmDelete) {
                Button("Sil", role: .destructive) { delete() }
                Button("Vazgeç", role: .cancel) {}
            } message: {
                Text("\(draft.name) şablonu bu iPhone'dan silinir; kameralar ve cihazlar silinmez.")
            }
        }
    }

    private var footerText: String {
        let hint = "Kutuya dokun: kamera seç. Basılı tut: değiştir ya da boşalt."
        return dropped > 0 ? "\(hint)\n\(dropped) kamera yeni düzene sığmadı." : hint
    }

    private var pickingSlot: Binding<Slot?> {
        Binding(get: { picking.map(Slot.init(index:)) }, set: { picking = $0?.index })
    }

    private var layoutPicker: some View {
        LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 5), spacing: 10) {
            ForEach(ViewLayouts.catalog) { layout in
                Button {
                    setLayout(layout)
                } label: {
                    VStack(spacing: 4) {
                        LayoutIcon(layout: layout).frame(width: 44, height: 28)
                        Text(layout.id).font(.caption2)
                    }
                    .padding(4)
                    .background(RoundedRectangle(cornerRadius: 6)
                        .stroke(draft.layout == layout.id ? Color.accentColor : .clear, lineWidth: 2))
                }
                .buttonStyle(.plain)
                .accessibilityLabel(layout.name)
                .accessibilityAddTraits(draft.layout == layout.id ? .isSelected : [])
                .accessibilityIdentifier("layout.\(layout.id)")
            }
        }
    }

    private var tilesPreview: some View {
        let layout = ViewLayouts.layout(draft.layout)
        return GeometryReader { geo in
            if let layout {
                let rects = layout.rects(in: geo.size, gap: 4)
                ZStack(alignment: .topLeading) {
                    ForEach(Array(rects.enumerated()), id: \.offset) { index, rect in
                        slotView(index)
                            .frame(width: rect.width, height: rect.height)
                            .position(x: rect.midX, y: rect.midY)
                    }
                }
            }
        }
        .aspectRatio(layout?.aspectRatio ?? 16.0 / 9.0, contentMode: .fit)
    }

    private func slotView(_ index: Int) -> some View {
        let ref = index < draft.tiles.count ? draft.tiles[index] : nil
        return Button {
            picking = index
        } label: {
            ZStack {
                RoundedRectangle(cornerRadius: 4).fill(Color.secondary.opacity(ref == nil ? 0.15 : 0.35))
                if let ref {
                    Text(model.devices.title(for: ref))
                        .font(.caption2)
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                        .padding(2)
                } else {
                    Image(systemName: "plus").foregroundStyle(.secondary)
                }
            }
        }
        .buttonStyle(.plain)
        .contextMenu {
            if ref != nil {
                Button("Değiştir") { picking = index }
                Button("Boşalt", role: .destructive) { draft.tiles[index] = nil }
            }
        }
        .accessibilityIdentifier("slot.\(index)")
    }

    private func setLayout(_ layout: ViewLayout) {
        guard layout.id != draft.layout else { return }
        let result = TemplateStore.retile(draft.tiles, to: layout)
        draft.layout = layout.id
        draft.tiles = result.tiles
        dropped = result.dropped
    }

    private func unavailable(except index: Int) -> Set<CameraRef> {
        Set(draft.tiles.enumerated().compactMap { i, ref in i == index ? nil : ref })
    }

    private func save() {
        do {
            try model.saveTemplate(draft)
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func delete() {
        do {
            try model.deleteCurrent()
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// Düzenin küçük simgesi (düzen seçicide)
struct LayoutIcon: View {
    let layout: ViewLayout

    var body: some View {
        GeometryReader { geo in
            ForEach(Array(layout.rects(in: geo.size, gap: 2).enumerated()), id: \.offset) { _, rect in
                Rectangle()
                    .fill(Color.secondary.opacity(0.5))
                    .frame(width: rect.width, height: rect.height)
                    .position(x: rect.midX, y: rect.midY)
            }
        }
    }
}
