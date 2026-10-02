import SwiftUI

/// Öğret: seçili profilin kusur türleri ve örnekleri; son ürünlerden hızlı işaretleme.
struct TeachView: View {
    @ObservedObject var vm: CountingViewModel
    @ObservedObject var teach: TeachStore
    @State private var askNewDefect = false
    @State private var newDefect = ""
    @State private var pendingRecord: InspectionRecord?
    @State private var confirmRemove: String?

    private let grid = [GridItem(.adaptive(minimum: 72), spacing: 8)]

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack {
                        Image(systemName: teach.isReady ? "checkmark.seal.fill" : "hourglass")
                            .foregroundStyle(teach.isReady ? .green : .orange)
                        Text(teach.readinessText).font(.callout)
                    }
                    Toggle("Kalite kontrol açık", isOn: $teach.enabled)
                } header: {
                    Text("Profil: \(vm.profile.name)")
                } footer: {
                    Text("Ürün sayım çizgisini geçerken fotoğrafı alınır ve öğretilen örneklere en çok benzeyen sınıfa göre Geçti/Kaldı kararı verilir. Model eğitimi yoktur; işaretlediğin örnek hemen etkili olur.")
                }

                Section {
                    if vm.inspections.isEmpty {
                        Text("Henüz ürün yok. Canlı sekmesinde sayım başlat ya da video ile test et; geçen ürünler burada görünür.")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    } else {
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 10) {
                                ForEach(vm.inspections.prefix(20)) { record in
                                    QuickTeachTile(record: record, defects: teach.defects,
                                                   onGood: { vm.teachExample(record, as: TeachLabel.good) },
                                                   onDefect: { vm.teachExample(record, as: $0) },
                                                   onNewDefect: { pendingRecord = record; askNewDefect = true })
                                }
                            }
                            .padding(.vertical, 4)
                        }
                    }
                } header: {
                    Text("Son ürünlerden öğret")
                } footer: {
                    Text("✓ iyi, ✗ kusurlu. Önce birkaç iyi ürün, sonra her kusur türünden birkaç örnek işaretle.")
                }

                examplesSection(TeachLabel.good, color: .green)
                ForEach(teach.defects, id: \.self) { defect in
                    examplesSection(defect, color: .red)
                }

                Section {
                    Button { pendingRecord = nil; askNewDefect = true } label: {
                        Label("Kusur türü ekle", systemImage: "plus")
                    }
                } footer: {
                    Text("Örnek: yumurtada Kırık, Kir, Kan lekesi; torbada Yırtık, Leke; pakette Etiket yok.")
                }
            }
            .navigationTitle("Öğret")
            .alert("Yeni kusur türü", isPresented: $askNewDefect) {
                TextField("ör. Kırık, Kir, Yırtık", text: $newDefect)
                Button("Vazgeç", role: .cancel) { newDefect = ""; pendingRecord = nil }
                Button(pendingRecord == nil ? "Ekle" : "Ekle ve öğret") {
                    let name = newDefect.trimmingCharacters(in: .whitespacesAndNewlines)
                    newDefect = ""
                    guard !name.isEmpty else { return }
                    if let record = pendingRecord {
                        vm.teachExample(record, as: name)
                    } else {
                        teach.addDefect(name)
                    }
                    pendingRecord = nil
                }
            }
            .confirmationDialog("Kusur türü silinsin mi?",
                                isPresented: Binding(get: { confirmRemove != nil }, set: { if !$0 { confirmRemove = nil } }),
                                titleVisibility: .visible) {
                Button("\(confirmRemove ?? "") ve örneklerini sil", role: .destructive) {
                    if let d = confirmRemove { teach.removeDefect(d) }
                    confirmRemove = nil
                }
            }
        }
    }

    @ViewBuilder
    private func examplesSection(_ label: String, color: Color) -> some View {
        let items = teach.examples.filter { $0.label == label }
        Section {
            if items.isEmpty {
                Text("Henüz örnek yok").font(.callout).foregroundStyle(.secondary)
            } else {
                LazyVGrid(columns: grid, spacing: 8) {
                    ForEach(items) { ex in
                        ExampleThumb(teach: teach, example: ex)
                            .contextMenu {
                                Button(role: .destructive) { teach.deleteExample(ex) } label: {
                                    Label("Örneği sil", systemImage: "trash")
                                }
                            }
                    }
                }
                .padding(.vertical, 4)
            }
            if label != TeachLabel.good {
                Button(role: .destructive) { confirmRemove = label } label: {
                    Label("Bu kusur türünü sil", systemImage: "trash")
                }
                .font(.callout)
            }
        } header: {
            HStack {
                Circle().fill(color).frame(width: 8, height: 8)
                Text("\(label) · \(items.count)")
            }
        } footer: {
            if !items.isEmpty { Text("Silmek için örneğe basılı tut.") }
        }
    }
}

private struct ExampleThumb: View {
    let teach: TeachStore
    let example: TeachExample
    @State private var jpeg: Data?

    var body: some View {
        JPEGThumb(jpeg: jpeg, size: 72)
            .task(id: example.id) { jpeg = teach.image(for: example) }
    }
}

private struct QuickTeachTile: View {
    let record: InspectionRecord
    let defects: [String]
    let onGood: () -> Void
    let onDefect: (String) -> Void
    let onNewDefect: () -> Void
    @State private var done: String?

    var body: some View {
        VStack(spacing: 6) {
            ZStack(alignment: .topTrailing) {
                JPEGThumb(jpeg: record.jpeg, size: 84)
                if let done {
                    Text(done == TeachLabel.good ? "✓" : "✗")
                        .font(.caption.bold())
                        .padding(4)
                        .background((done == TeachLabel.good ? Color.green : Color.red))
                        .clipShape(Circle())
                        .padding(4)
                }
            }
            Text(record.shortID).font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
            HStack(spacing: 6) {
                Button { onGood(); done = TeachLabel.good } label: {
                    Image(systemName: "checkmark").frame(width: 28, height: 24)
                }
                .buttonStyle(.bordered)
                .tint(.green)
                Menu {
                    ForEach(defects, id: \.self) { d in
                        Button(d) { onDefect(d); done = d }
                    }
                    Button("Yeni kusur türü…") { onNewDefect() }
                } label: {
                    Image(systemName: "xmark").frame(width: 28, height: 24)
                }
                .buttonStyle(.bordered)
                .tint(.red)
            }
            .disabled(done != nil)
        }
    }
}
