import SwiftUI

/// Cihaz listesinden kamera seçimi (sayım ve İzleme şablonu). Kayıt cihazlarında kanallar küçük resimle.
struct CameraPickerView: View {
    @ObservedObject var devices: DeviceStore
    let selected: CameraRef?
    /// Seçilemeyen kameralar (şablonda başka kutuda olanlar)
    var unavailable: Set<CameraRef> = []
    /// "Boş bırak" satırı (şablon kutusu)
    var allowsEmpty = false
    let onPick: (CameraRef?) -> Void

    var body: some View {
        List {
            if allowsEmpty {
                Button { onPick(nil) } label: {
                    Label("Boş bırak", systemImage: "square.dashed")
                }
                .accessibilityIdentifier("pickEmpty")
            }
            if devices.devices.isEmpty {
                Text("Henüz cihaz yok. Ayarlar → Görüntü kaynağı → Cihazlar'dan kamera ya da kayıt cihazı ekle.")
                    .foregroundStyle(.secondary)
            }
            ForEach(devices.devices) { device in
                DeviceCamerasSection(devices: devices, device: device, selected: selected,
                                     unavailable: unavailable, onPick: onPick)
            }
        }
    }
}

/// Bir cihazın kameraları: doğrudan kamerada tek satır, kayıt cihazında kanallar (+ listeyi yenile)
private struct DeviceCamerasSection: View {
    @ObservedObject var devices: DeviceStore
    let device: NetworkDevice
    let selected: CameraRef?
    let unavailable: Set<CameraRef>
    let onPick: (CameraRef?) -> Void
    @StateObject private var thumbnails = ChannelThumbnailLoader()
    @State private var listing = false
    @State private var error: String?

    var body: some View {
        Section {
            if device.kind == .camera {
                row(CameraRef(sourceId: device.id, channelId: nil), title: device.name, subtitle: device.summary,
                    channel: nil)
            } else {
                ForEach(channelList) { channel in
                    row(CameraRef(sourceId: device.id, channelId: channel.id), title: channel.title,
                        subtitle: channel.subtitle, channel: channel)
                }
                refreshButton
                if let error {
                    Label(error, systemImage: "xmark.octagon.fill")
                        .foregroundStyle(.red)
                        .accessibilityElement(children: .combine)
                }
            }
        } header: {
            Text(device.name)
        }
    }

    private var channelList: [RecorderChannel] { devices.channels[device.id] ?? [] }

    private var refreshButton: some View {
        Button {
            refresh()
        } label: {
            HStack {
                Label(channelList.isEmpty ? "Kanalları listele" : "Kanalları yenile", systemImage: "arrow.clockwise")
                if listing { Spacer(); ProgressView() }
            }
        }
        .disabled(listing)
        .accessibilityIdentifier("refreshChannels.\(device.name)")
    }

    private func row(_ ref: CameraRef, title: String, subtitle: String?, channel: RecorderChannel?) -> some View {
        let blocked = unavailable.contains(ref)
        return Button {
            onPick(ref)
        } label: {
            HStack(spacing: 12) {
                if let channel {
                    ChannelThumbnail(image: thumbnails.images[channel.id], failed: thumbnails.failed.contains(channel.id))
                } else {
                    Image(systemName: "web.camera").font(.title2).frame(width: 96, height: 54)
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).foregroundStyle(blocked ? .secondary : .primary).lineLimit(2)
                    if let subtitle {
                        Text(subtitle).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    }
                    if blocked {
                        Text("Bu şablonda zaten var").font(.caption).foregroundStyle(.orange)
                    }
                }
                Spacer()
                if selected == ref {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(.tint)
                }
            }
        }
        .disabled(blocked)
        .accessibilityIdentifier("camera.\(title)")
        .accessibilityAddTraits(selected == ref ? .isSelected : [])
        .task(id: channel?.id) {
            guard let channel, let client = devices.recorderClient(for: device.id) else { return }
            await thumbnails.load(channel, client: client, username: device.config.recorderUsername,
                                  password: devices.password(for: device.id))
        }
    }

    private func refresh() {
        guard let client = devices.recorderClient(for: device.id) else { return }
        listing = true
        error = nil
        Task { @MainActor in
            do {
                devices.setChannels(try await client.channels(), for: device.id)
            } catch {
                self.error = error.localizedDescription
            }
            listing = false
        }
    }
}
