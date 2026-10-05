import SwiftUI

/// Genel bakış: sayım ve kalite özeti, son ürün kartları (dokununca ayrıntı ve öğretme).
struct OverviewView: View {
    @ObservedObject var vm: CountingViewModel
    @ObservedObject var teach: TeachStore
    @State private var selected: InspectionRecord?

    var body: some View {
        NavigationStack {
            ScrollView {
                if vm.profile.isTwoWay {
                    peopleOverview.padding()
                } else {
                    beltOverview.padding()
                }
            }
            .navigationTitle("Genel bakış")
            .sheet(item: $selected) { record in
                InspectionDetailView(vm: vm, teach: teach, record: record)
            }
        }
    }

    /// Kişi sayımı: giriş, çıkış, dakikadaki giriş; görüntü saklanmaz
    private var peopleOverview: some View {
        VStack(alignment: .leading, spacing: 16) {
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                StatTile(title: "Giriş", value: "\(vm.total)", color: .green)
                StatTile(title: "Çıkış", value: "\(vm.totalOut)", color: .orange)
                RateTile(logger: vm.logger, title: "Giriş / dk")
            }
            Label("Kişi sayımında görüntü kaydedilmez ve cihazdan çıkmaz; yalnızca giriş ve çıkış sayıları tutulur.",
                  systemImage: "lock.shield")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
    }

    private var beltOverview: some View {
        VStack(alignment: .leading, spacing: 16) {
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                StatTile(title: "Sayılan", value: "\(vm.total)", color: .primary)
                RateTile(logger: vm.logger)
                StatTile(title: "Geçti", value: "\(vm.inspectionStats.pass)", color: .green)
                StatTile(title: "Kaldı", value: "\(vm.inspectionStats.fail)", color: .red)
                StatTile(title: "Kusur oranı",
                         value: vm.inspectionStats.failRate.map { String(format: "%%%.1f", $0 * 100) } ?? "—",
                         color: .orange)
                StatTile(title: "Öğretilmeden sayılan", value: "\(vm.inspectionStats.unknown)",
                         color: .secondary)
            }

            HStack(spacing: 8) {
                Image(systemName: teach.isReady && teach.enabled ? "checkmark.seal.fill" : "info.circle")
                    .foregroundStyle(teach.isReady && teach.enabled ? .green : .orange)
                Text(teach.enabled ? "\(vm.profile.name): \(teach.readinessText)"
                                   : "\(vm.profile.name): kalite kontrol kapalı")
                    .font(.footnote)
            }

            VStack(alignment: .leading, spacing: 2) {
                Text("Son ürünler").font(.title3.bold())
                Text("Son \(InspectionLog.capacity) ürün cihazda tutulur. Öğretmek için bir ürüne dokun.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if vm.inspections.isEmpty {
                Text("Henüz ürün sayılmadı. Canlı sekmesinde Başlat'a bas ya da film simgesiyle video ile test et.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .padding(.vertical, 24)
            } else {
                LazyVStack(spacing: 8) {
                    ForEach(vm.inspections) { record in
                        Button { selected = record } label: { InspectionCard(record: record) }
                            .buttonStyle(.plain)
                    }
                }
            }
        }
    }
}

struct StatTile: View {
    let title: String
    let value: String
    let color: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title.uppercased(with: Locale(identifier: "tr_TR")))
                .font(.caption2.bold())
                .foregroundStyle(.secondary)
            Text(value)
                .font(.title.bold().monospacedDigit())
                .foregroundStyle(color)
                .lineLimit(1)
                .minimumScaleFactor(0.5)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Color(white: 0.11))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }
}

private struct RateTile: View {
    @ObservedObject var logger: CountLogger
    var title = "Adet / dk"

    var body: some View {
        StatTile(title: title, value: "\(logger.ratePerMinute)", color: .primary)
    }
}
