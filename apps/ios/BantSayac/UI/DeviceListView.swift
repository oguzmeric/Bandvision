import SwiftUI

/// Ayarlar → Görüntü kaynağı → Cihazlar: kamera ve kayıt cihazları (ekle, düzenle, sil).
struct DeviceListView: View {
    @ObservedObject var vm: CountingViewModel
    @ObservedObject var devices: DeviceStore
    @State private var adding: NetworkDeviceKind?
    @State private var pendingDelete: NetworkDevice?

    init(vm: CountingViewModel) {
        _vm = ObservedObject(wrappedValue: vm)
        _devices = ObservedObject(wrappedValue: vm.devices)
    }

    var body: some View {
        List {
            Section {
                ForEach(devices.devices) { device in
                    NavigationLink {
                        NetworkCameraForm(vm: vm, device: device)
                    } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(device.name)
                            Text(device.summary).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        }
                    }
                    .accessibilityIdentifier("device.\(device.name)")
                    .swipeActions {
                        Button("Sil", role: .destructive) { pendingDelete = device }
                    }
                }
                if devices.devices.isEmpty {
                    Text("Henüz cihaz yok.").foregroundStyle(.secondary)
                }
            } footer: {
                if let problem = devices.problem {
                    Text(problem).foregroundStyle(.red)
                }
            }
            Section {
                Button { adding = .camera } label: {
                    Label("Kamera ekle", systemImage: "web.camera")
                }
                .accessibilityIdentifier("addCamera")
                Button { adding = .recorder } label: {
                    Label("Kayıt cihazı ekle (NVR/XVR)", systemImage: "externaldrive.connected.to.line.below")
                }
                .accessibilityIdentifier("addRecorder")
            } footer: {
                Text("Kayıt cihazı bir kez eklenir; kameraları (kanalları) sayım ve İzleme için listeden seçilir. Silmek için satırı sola kaydır.")
            }
        }
        .navigationTitle("Cihazlar")
        .navigationBarTitleDisplayMode(.inline)
        .navigationDestination(item: $adding) { kind in
            NetworkCameraForm(vm: vm, device: nil, initialKind: kind)
        }
        .alert("Cihaz silinsin mi?", isPresented: deleteShown, presenting: pendingDelete) { device in
            Button("Sil", role: .destructive) { vm.deleteDevice(device.id) }
            Button("Vazgeç", role: .cancel) {}
        } message: { device in
            Text("\(device.name) ve şifresi bu iPhone'dan silinir. Bu cihazı kullanan İzleme kutuları \"Kamera silinmiş\" gösterir.")
        }
    }

    private var deleteShown: Binding<Bool> {
        Binding(get: { pendingDelete != nil }, set: { if !$0 { pendingDelete = nil } })
    }
}
