import SwiftUI
import PhotosUI
import CoreTransferable
import UniformTypeIdentifiers

/// Seçilen videoyu uygulamanın geçici klasörüne kopyalar (seçiciler dosyayı yalnızca kısa süre erişilebilir tutar).
struct PickedVideo: Transferable, Sendable {
    let url: URL

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(contentType: .movie) { video in
            SentTransferredFile(video.url)
        } importing: { received in
            try Self(url: copyToTemporary(received.file))
        }
    }

    static func copyToTemporary(_ src: URL) throws -> URL {
        let ext = src.pathExtension.isEmpty ? "mov" : src.pathExtension
        let dst = FileManager.default.temporaryDirectory
            .appendingPathComponent("video-\(UUID().uuidString).\(ext)")
        try FileManager.default.copyItem(at: src, to: dst)
        return dst
    }
}

/// "Video ile test" sayfası: kaynak seçimi ve oynatma öncesi ayar. Seçiciler bu sayfaya bağlıdır
/// (ana ekrandaki menüden açmak, menü kapanırken sunum çakıştığı için zaman zaman tepkisiz kalıyordu).
struct VideoPickerSheet: View {
    @ObservedObject var vm: CountingViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var photoItem: PhotosPickerItem?
    @State private var showFiles = false
    @State private var preparing = false
    @State private var errorText: String?

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 18) {
                Text("Bant videosunu kamera yerine sayar. Sonuçta doğru adedi girip doğruluğu görebilirsin.")
                    .font(.callout)
                    .foregroundStyle(.secondary)

                PhotosPicker(selection: $photoItem, matching: .videos, preferredItemEncoding: .current) {
                    Label("Fotoğraflar'dan seç", systemImage: "photo.on.rectangle")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)

                Button { showFiles = true } label: {
                    Label("Dosyalar'dan seç", systemImage: "folder")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)

                Toggle(isOn: $vm.videoLearnBackground) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Videonun başında bant boş")
                        Text("Açıksa arka plan (boş bant) videonun ilk saniyesinden otomatik öğrenilir. "
                             + "Video ürünle başlıyorsa kapat; oynarken bant boş göründüğünde "
                             + "Kalibre → Boş bandı öğren'i kullan.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                if preparing {
                    HStack(spacing: 10) {
                        ProgressView()
                        Text("Video hazırlanıyor…").foregroundStyle(.secondary)
                    }
                }
                if let errorText {
                    Text(errorText).font(.callout).foregroundStyle(.red)
                }
                Spacer()
            }
            .controlSize(.large)
            .padding()
            .disabled(preparing)
            .navigationTitle("Video ile test")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Kapat") { dismiss() }
                }
            }
            .onChange(of: photoItem) { _, item in
                guard let item else { return }
                photoItem = nil
                prepare { try await item.loadTransferable(type: PickedVideo.self)?.url }
            }
            .fileImporter(isPresented: $showFiles, allowedContentTypes: [.movie]) { result in
                guard let picked = try? result.get() else { return }
                prepare {
                    try await Task.detached {
                        let scoped = picked.startAccessingSecurityScopedResource()
                        defer { if scoped { picked.stopAccessingSecurityScopedResource() } }
                        return try PickedVideo.copyToTemporary(picked)
                    }.value
                }
            }
        }
    }

    /// Dosyayı hazırlar (kopyalar), videoyu açar ve sayfayı kapatır; bu sırada gösterge görünür.
    private func prepare(_ load: @escaping @MainActor @Sendable () async throws -> URL?) {
        preparing = true
        errorText = nil
        Task { @MainActor in
            defer { preparing = false }
            do {
                guard let url = try await load() else { return }
                try await vm.openVideo(url: url)
                dismiss()
            } catch {
                errorText = "Video açılamadı: \(error.localizedDescription)"
            }
        }
    }
}

/// Oynatıcı kontrolleri: baştan, oynat/duraklat, sürüklenebilir zaman çubuğu.
struct VideoTransportBar: View {
    @ObservedObject var vm: CountingViewModel
    @State private var scrub: Double?

    var body: some View {
        if let run = vm.video {
            HStack(spacing: 12) {
                Button { vm.seekVideo(to: 0) } label: {
                    Image(systemName: "backward.end.fill")
                }
                .accessibilityLabel("Baştan oynat")
                Button { vm.toggleVideoPlayback() } label: {
                    Image(systemName: run.playing ? "pause.fill" : "play.fill")
                        .frame(width: 22)
                }
                .accessibilityLabel(run.playing ? "Duraklat" : "Oynat")
                Text(timeText(scrub ?? run.position))
                    .font(.caption.monospacedDigit())
                Slider(value: Binding(get: { scrub ?? run.position }, set: { scrub = $0 }),
                       in: 0...max(run.duration, 0.1)) { editing in
                    if !editing, let t = scrub {
                        vm.seekVideo(to: t)
                        scrub = nil
                    }
                }
                Text(timeText(run.duration))
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
            .font(.title3)
        }
    }

    private func timeText(_ t: Double) -> String {
        let s = max(0, Int(t.rounded(.down)))
        return String(format: "%d:%02d", s / 60, s % 60)
    }
}

/// Video modunda alt panel: oynatıcı, sayı, doğruluk, hız.
struct VideoPanel: View {
    @ObservedObject var vm: CountingViewModel
    var onPickVideo: () -> Void
    @State private var truthText = ""
    /// Sayısal klavyede "Tamam" tuşu yok: kapatmak için alanın yanında ve klavyenin üstünde düğme var.
    @FocusState private var truthFocused: Bool

    var body: some View {
        if let run = vm.video {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Label(run.name, systemImage: "film")
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Spacer()
                    if run.finished {
                        Text("Bitti").foregroundStyle(.green).accessibilityIdentifier("videoFinished")
                    }
                }
                .font(.caption)
                .foregroundStyle(.secondary)

                VideoTransportBar(vm: vm)

                if vm.profile.isTwoWay {
                    PeopleCounters(vm: vm, compact: true)
                } else {
                    beltCount(run)
                }

                if let err = run.error {
                    Text(err).font(.callout).foregroundStyle(.red)
                }

                if !vm.profile.isTwoWay { RecentInspectionStrip(vm: vm) }

                HStack(spacing: 10) {
                    Text(vm.profile.isTwoWay ? "Doğru giriş" : "Doğru adet").font(.callout)
                    TextField("isteğe bağlı", text: $truthText)
                        .keyboardType(.numberPad)
                        .textFieldStyle(.roundedBorder)
                        .frame(maxWidth: 110)
                        .focused($truthFocused)
                    Spacer()
                    if truthFocused {
                        Button("Tamam") { truthFocused = false }
                            .buttonStyle(.borderedProminent)
                    } else {
                        Picker("Hız", selection: $vm.videoSpeed) {
                            Text("1×").tag(1.0)
                            Text("2×").tag(2.0)
                            Text("Hızlı").tag(0.0)
                        }
                        .pickerStyle(.segmented)
                        .frame(maxWidth: 170)
                    }
                }

                HStack(spacing: 10) {
                    Button { vm.beginCalibration() } label: {
                        Label(vm.profile.isTwoWay ? "Ayarla" : "Kalibre", systemImage: "scope").lineLimit(1).minimumScaleFactor(0.7).frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    Button(action: onPickVideo) {
                        Label("Başka video", systemImage: "film.stack").lineLimit(1).minimumScaleFactor(0.7).frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    Button { vm.exitVideo() } label: {
                        Label("Kamera", systemImage: "camera").lineLimit(1).minimumScaleFactor(0.7).frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                }
                .controlSize(.large)
            }
            .padding()
            .contentShape(Rectangle())
            .onTapGesture { truthFocused = false }     // panelde boş bir yere dokununca klavye kapanır
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Tamam") { truthFocused = false }
                }
            }
        }
    }

    private func timeText(_ t: Double) -> String {
        let s = max(0, Int(t.rounded(.down)))
        return String(format: "%d:%02d", s / 60, s % 60)
    }

    /// Tek yönlü sayım: büyük sayı + doğruluk
    private func beltCount(_ run: VideoRun) -> some View {
        HStack(alignment: .lastTextBaseline) {
            Text("\(vm.total)")
                .accessibilityIdentifier("videoCount")
                .font(.system(size: 48, weight: .bold, design: .rounded))
                .monospacedDigit()
                .lineLimit(1)
                .minimumScaleFactor(0.5)
            VStack(alignment: .leading, spacing: 0) {
                Text("adet").foregroundStyle(.secondary)
                if run.countFrom > 0 {
                    Text("sayım başlangıcı \(timeText(run.countFrom))")
                        .font(.caption2)
                        .foregroundStyle(.orange)
                }
            }
            Spacer()
            if let acc = accuracy(count: vm.total), run.countFrom == 0 {
                VStack(alignment: .trailing, spacing: 0) {
                    Text(String(format: "%%%.1f", acc))
                        .font(.title2.bold())
                        .monospacedDigit()
                        .foregroundStyle(acc >= 98 ? .green : .orange)
                    Text("doğruluk").font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func accuracy(count: Int) -> Double? {
        guard let truth = Int(truthText.trimmingCharacters(in: .whitespaces)), truth > 0 else { return nil }
        return max(0, 100 * (1 - Double(abs(count - truth)) / Double(truth)))
    }
}
