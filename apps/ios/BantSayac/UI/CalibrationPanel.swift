import SwiftUI

struct CalibrationPanel: View {
    @ObservedObject var vm: CountingViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Kalibrasyon").font(.headline)
                Spacer()
                Picker("Akış yönü", selection: $vm.profile.direction) {
                    ForEach(FlowDirection.allCases) { d in
                        Text("\(d.arrow) \(d.title)").tag(d)
                    }
                }
                .pickerStyle(.menu)
            }

            Text(vm.calibrationMessage)
                .font(.callout)
                .foregroundStyle(.yellow)
                .frame(maxWidth: .infinity, alignment: .leading)

            HStack(spacing: 10) {
                Button { vm.learnBackground() } label: {
                    Label("1. Boş bandı öğren", systemImage: "rectangle.dashed")
                        .frame(maxWidth: .infinity)
                }
                Button { vm.learnSample() } label: {
                    Label("2. Örnek geçir (8)", systemImage: "shippingbox")
                        .frame(maxWidth: .infinity)
                }
            }
            .buttonStyle(.bordered)

            VStack(alignment: .leading, spacing: 2) {
                Text("Hassasiyet eşiği: \(vm.profile.diffThreshold)  (düşük = daha hassas)")
                    .font(.caption)
                Slider(value: Binding(
                    get: { Double(vm.profile.diffThreshold) },
                    set: { vm.profile.diffThreshold = Int($0) }
                ), in: 5...120, step: 1)
            }

            Toggle("Bitişik ürünleri ayır (alan oranıyla)", isOn: $vm.profile.splitTouching)
                .font(.callout)

            Text(vm.profile.expectedArea > 0
                 ? String(format: "Tek ürün alanı: %.4f", vm.profile.expectedArea)
                 : "Tek ürün alanı: henüz öğrenilmedi")
                .font(.caption)
                .foregroundStyle(.secondary)

            HStack {
                Button("İptal", role: .cancel) { vm.cancelCalibration() }
                Spacer()
                Button { vm.saveCalibration() } label: {
                    Label("Kaydet", systemImage: "checkmark")
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .padding()
        .background(Color(white: 0.08))
    }
}
