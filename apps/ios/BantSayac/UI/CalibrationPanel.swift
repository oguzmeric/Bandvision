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

            areaShapePicker

            Text(vm.calibrationMessage)
                .font(.callout)
                .foregroundStyle(.yellow)
                .fixedSize(horizontal: false, vertical: true)      // dar ekranda kırpılmasın, alt satıra geçsin
                .frame(maxWidth: .infinity, alignment: .leading)

            HStack(spacing: 10) {
                Button { vm.learnBackground() } label: {
                    Label("1. Boş bandı öğren", systemImage: "rectangle.dashed")
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                        .minimumScaleFactor(0.85)
                        .frame(maxWidth: .infinity)
                }
                Button { vm.learnSample() } label: {
                    Label("2. Örnek geçir (8)", systemImage: "shippingbox")
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                        .minimumScaleFactor(0.85)
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

    /// İlgi alanı biçimi: dikdörtgen ya da banda göre çizilen çokgen (algoritma §2.0)
    private var areaShapePicker: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Picker("Alan", selection: Binding(
                    get: { vm.profile.roiPolygon != nil },
                    set: { polygon in vm.profile.setPolygon(polygon ? vm.profile.roiCorners : nil) }
                )) {
                    Text("Dikdörtgen").tag(false)
                    Text("Çokgen").tag(true)
                }
                .pickerStyle(.segmented)
                .accessibilityIdentifier("roiShape")
                if vm.profile.roiPolygon != nil {
                    Button("Köşeleri sıfırla") { vm.profile.setPolygon(vm.profile.roiCorners) }
                        .font(.caption)
                        .accessibilityIdentifier("resetPolygon")
                }
            }
            Text(vm.profile.roiPolygon == nil
                 ? "Köşelerden sürükleyerek alanı ayarla."
                 : "Köşeleri sürükle · sarı + ile köşe ekle (en çok 12) · köşeye çift dokun: sil")
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}
