import SwiftUI

/// Kişi sayımı (§4.10) arayüz parçaları: Giriş/Çıkış sayaçları ve giriş yönü düğmesi.

/// Büyük sayaç kutucuğu ("Giriş 12")
struct CounterTile: View {
    let title: String
    let value: Int
    let icon: String
    let color: Color
    var compact = false
    var identifier: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Label(title, systemImage: icon)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(color)
            Text("\(value)")
                .font(.system(size: compact ? 40 : 52, weight: .bold, design: .rounded))
                .monospacedDigit()
                .lineLimit(1)
                .minimumScaleFactor(0.5)
                .contentTransition(.numericText())
                .animation(.snappy, value: value)
                .accessibilityIdentifier(identifier)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 14)
        .padding(.vertical, compact ? 8 : 10)
        .background(RoundedRectangle(cornerRadius: 16).fill(color.opacity(0.12)))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(color.opacity(0.35), lineWidth: 1))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(title): \(value)")
    }
}

/// Giriş ve çıkış sayaçları yan yana
struct PeopleCounters: View {
    @ObservedObject var vm: CountingViewModel
    var compact = false

    var body: some View {
        VStack(spacing: 6) {
            HStack(spacing: 10) {
                CounterTile(title: "Giriş", value: vm.total, icon: "figure.walk.arrival", color: .green,
                            compact: compact, identifier: "countIn")
                CounterTile(title: "Çıkış", value: vm.totalOut, icon: "figure.walk.departure", color: .orange,
                            compact: compact, identifier: "countOut")
            }
            if !(vm.profile.staffColors ?? []).isEmpty {
                Text("Personel geçişi: \(vm.staffIn + vm.staffOut)")
                    .font(.caption).foregroundStyle(.secondary)
                    .accessibilityIdentifier("staffCount")
            }
        }
    }
}

/// Giriş yönünü gösterir; dokununca çevirir (giriş ↔ çıkış)
struct EntryDirectionButton: View {
    @ObservedObject var vm: CountingViewModel

    var body: some View {
        Button { vm.flipEntryDirection() } label: {
            HStack(spacing: 8) {
                Image(systemName: "arrow.up.arrow.down")
                Text("Giriş yönü: \(vm.entryDirectionText)")
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
                Spacer(minLength: 4)
                Text("Çevir").fontWeight(.semibold)
            }
            .font(.callout)
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .frame(maxWidth: .infinity)
            .background(RoundedRectangle(cornerRadius: 12).fill(Color.white.opacity(0.07)))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("flipEntry")
        .accessibilityHint("Giriş ve çıkış yönünü tersine çevirir")
    }
}
