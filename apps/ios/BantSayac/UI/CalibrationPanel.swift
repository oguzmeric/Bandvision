import SwiftUI

struct CalibrationPanel: View {
    @ObservedObject var vm: CountingViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Kalibrasyon").font(.headline)
                Spacer()
                if vm.profile.countLine == nil {
                    Picker("Akış yönü", selection: $vm.profile.direction) {
                        ForEach(FlowDirection.allCases) { d in
                            Text("\(d.arrow) \(d.title)").tag(d)
                        }
                    }
                    .pickerStyle(.menu)
                } else {
                    Button {
                        if let cl = vm.profile.countLine {
                            vm.profile.setCountLine(CountLine(a: cl.b, b: cl.a), aspect: imageAspect)
                        }
                    } label: {
                        Label("Yönü çevir", systemImage: "arrow.left.arrow.right")
                    }
                    .accessibilityIdentifier("flipLine")
                }
            }

            areaShapePicker
            lineModePicker

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

    /// Görüntünün genişlik / yükseklik oranı (açılı çizginin akış yönü için)
    private var imageAspect: Double {
        let s = vm.snapshot.frameSize
        return s.height > 0 ? Double(s.width / s.height) : 9.0 / 16.0
    }

    /// Sayım çizgisi: düz (akış eksenine dik) ya da açılı (iki ucu sürüklenir, akış çizgiye dik) — §4.8
    private var lineModePicker: some View {
        VStack(alignment: .leading, spacing: 4) {
            Picker("Sayım çizgisi", selection: Binding(
                get: { vm.profile.countLine != nil },
                set: { angled in
                    vm.profile.setCountLine(angled ? vm.profile.straightCountLine : nil, aspect: imageAspect)
                }
            )) {
                Text("Düz çizgi").tag(false)
                Text("Açılı çizgi").tag(true)
            }
            .pickerStyle(.segmented)
            .accessibilityIdentifier("lineMode")
            Text(vm.profile.countLine == nil
                 ? "Turuncu çizgiyi ortasındaki tutamaçla akış yönünde kaydır."
                 : "Çizginin uçlarını sürükle · ortasından tutup taşı · ok akış yönünü gösterir (gerekirse \"Yönü çevir\")")
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
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
