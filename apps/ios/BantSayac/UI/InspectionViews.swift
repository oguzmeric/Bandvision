import SwiftUI
import UIKit

/// Menü öğesinden pencere (alert/sheet) açarken: menünün kapanma animasyonu bitmeden sunum başlatılırsa
/// SwiftUI zaman zaman yok sayıyor (video menüsünde yaşandı). Sunumu menü kapandıktan sonra yapar.
@MainActor
func presentAfterMenuCloses(_ action: @escaping @MainActor () -> Void) {
    Task { @MainActor in
        try? await Task.sleep(for: .milliseconds(350))
        action()
    }
}

/// JPEG küçük resim (kart ve örnek ızgaraları).
struct JPEGThumb: View {
    let jpeg: Data?
    var size: CGFloat = 64

    var body: some View {
        Group {
            if let data = jpeg, let ui = UIImage(data: data) {
                Image(uiImage: ui).resizable().scaledToFill()
            } else {
                Color.gray.opacity(0.3)
            }
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

/// "OK %96", "NOK %88 · Kırık", bekliyor ya da yalnızca sayıldı.
struct VerdictBadge: View {
    let record: InspectionRecord

    var body: some View {
        if record.pending {
            ProgressView().controlSize(.small)
        } else if let v = record.verdict {
            Text(v.pass ? "OK %\(Int(v.confidence * 100))" : "NOK %\(Int(v.confidence * 100))")
                .font(.caption.bold().monospacedDigit())
                .padding(.horizontal, 8).padding(.vertical, 4)
                .background((v.pass ? Color.green : Color.red).opacity(0.2))
                .foregroundStyle(v.pass ? .green : .red)
                .clipShape(Capsule())
        } else {
            Text("öğretilmedi")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }
}

struct InspectionCard: View {
    let record: InspectionRecord

    var body: some View {
        HStack(spacing: 12) {
            JPEGThumb(jpeg: record.jpeg)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(title).font(.headline).foregroundStyle(titleColor)
                    if record.delta > 1 {
                        Text("×\(record.delta)").font(.caption.bold()).foregroundStyle(.secondary)
                    }
                }
                Text("\(record.time.formatted(date: .omitted, time: .standard)) · \(record.shortID)")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
                if let v = record.verdict, !v.pass {
                    Text(v.label).font(.caption).foregroundStyle(.red)
                }
            }
            Spacer()
            VerdictBadge(record: record)
        }
        .padding(10)
        .background(Color(white: 0.11))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private var title: String {
        guard let v = record.verdict else { return record.pending ? "İnceleniyor" : "Sayıldı" }
        return v.pass ? "Geçti" : "Kaldı"
    }

    private var titleColor: Color {
        guard let v = record.verdict else { return .primary }
        return v.pass ? .green : .red
    }
}

/// Kartın ayrıntısı: büyük görüntü, karar ve bu ürünü örnek olarak öğretme.
struct InspectionDetailView: View {
    @ObservedObject var vm: CountingViewModel
    @ObservedObject var teach: TeachStore
    let record: InspectionRecord
    @Environment(\.dismiss) private var dismiss
    @State private var taughtAs: String?
    @State private var askNewDefect = false
    @State private var newDefect = ""

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let ui = UIImage(data: record.jpeg) {
                        Image(uiImage: ui).resizable().scaledToFit()
                            .frame(maxWidth: .infinity)
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                    }
                    HStack {
                        InspectionCard(record: record)
                    }
                    if let v = record.verdict {
                        Text(v.pass
                             ? "Öğretilen iyi örneklere benziyor (güven %\(Int(v.confidence * 100)))."
                             : "\(v.label) olarak değerlendirildi (güven %\(Int(v.confidence * 100))).")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    }

                    Text("Bu ürünü örnek olarak öğret").font(.headline)
                    if let label = taughtAs {
                        Label("Öğretildi: \(label)", systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                    }
                    HStack(spacing: 10) {
                        Button { teachAs(TeachLabel.good) } label: {
                            Label("İyi", systemImage: "checkmark").frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(.green)
                        Menu {
                            ForEach(teach.defects, id: \.self) { d in
                                Button(d) { teachAs(d) }
                            }
                            Button("Yeni kusur türü…") { presentAfterMenuCloses { askNewDefect = true } }
                        } label: {
                            Label("Kusurlu", systemImage: "xmark").frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(.red)
                    }
                    .controlSize(.large)
                    .disabled(taughtAs != nil)
                    Text("Öğretilen örnek \(vm.profile.name) profilinde saklanır ve sonraki ürünlerin kararında hemen kullanılır.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding()
            }
            .navigationTitle(record.shortID)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Kapat") { dismiss() } }
            }
            .alert("Yeni kusur türü", isPresented: $askNewDefect) {
                TextField("ör. Kırık, Kir, Yırtık", text: $newDefect)
                Button("Vazgeç", role: .cancel) { newDefect = "" }
                Button("Ekle ve öğret") {
                    let name = newDefect.trimmingCharacters(in: .whitespacesAndNewlines)
                    newDefect = ""
                    if !name.isEmpty { teachAs(name) }
                }
            }
        }
    }

    private func teachAs(_ label: String) {
        vm.teachExample(record, as: label)
        taughtAs = label
    }
}
