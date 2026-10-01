import SwiftUI
import CoreTransferable
import UniformTypeIdentifiers

/// Fotoğraflar'dan seçilen videoyu geçici klasöre kopyalar (seçici dosyayı yalnızca kısa süre erişilebilir tutar).
struct PickedVideo: Transferable, Sendable {
    let url: URL

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(contentType: .movie) { video in
            SentTransferredFile(video.url)
        } importing: { received in
            try Self(url: copyToTemporary(received.file))
        }
    }

    /// Güvenlik kapsamlı ya da geçici bir dosyayı uygulamanın geçici klasörüne kopyalar.
    static func copyToTemporary(_ src: URL) throws -> URL {
        let ext = src.pathExtension.isEmpty ? "mov" : src.pathExtension
        let dst = FileManager.default.temporaryDirectory
            .appendingPathComponent("video-\(UUID().uuidString).\(ext)")
        try FileManager.default.copyItem(at: src, to: dst)
        return dst
    }
}

/// Video modunda alt panel: ilerleme, hız, sayı; bitince sonuç ve isteğe bağlı doğruluk hesabı.
struct VideoPanel: View {
    @ObservedObject var vm: CountingViewModel
    @State private var truthText = ""

    var body: some View {
        if let run = vm.video {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Label(run.name, systemImage: "film")
                        .font(.caption)
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text(run.finished ? "Bitti" : "%\(Int(run.progress * 100))")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(run.finished ? .green : .secondary)
                }
                ProgressView(value: run.progress)

                HStack(alignment: .lastTextBaseline) {
                    Text("\(vm.total)")
                        .font(.system(size: 64, weight: .bold, design: .rounded))
                        .monospacedDigit()
                        .lineLimit(1)
                        .minimumScaleFactor(0.5)
                    Text("adet").foregroundStyle(.secondary)
                    Spacer()
                    if let acc = accuracy(count: vm.total) {
                        VStack(alignment: .trailing, spacing: 0) {
                            Text(String(format: "%%%.1f", acc))
                                .font(.title2.bold())
                                .monospacedDigit()
                                .foregroundStyle(acc >= 98 ? .green : .orange)
                            Text("doğruluk").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }

                if let err = run.error {
                    Text(err).font(.callout).foregroundStyle(.red)
                }

                HStack(spacing: 10) {
                    Text("Doğru adet").font(.callout)
                    TextField("isteğe bağlı", text: $truthText)
                        .keyboardType(.numberPad)
                        .textFieldStyle(.roundedBorder)
                        .frame(maxWidth: 120)
                    Spacer()
                    Picker("Hız", selection: $vm.videoSpeed) {
                        Text("1×").tag(1.0)
                        Text("2×").tag(2.0)
                        Text("Hızlı").tag(0.0)
                    }
                    .pickerStyle(.segmented)
                    .frame(maxWidth: 170)
                }

                HStack(spacing: 10) {
                    if run.finished {
                        Button { vm.beginCalibration() } label: {
                            Label("Kalibre", systemImage: "scope").frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
                    } else {
                        Button { vm.stopVideo() } label: {
                            Label("Durdur", systemImage: "stop.fill").frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
                        .tint(.orange)
                        Button { vm.beginCalibration() } label: {
                            Label("Kalibre", systemImage: "scope").frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
                    }
                    Button { vm.exitVideo() } label: {
                        Label("Kameraya dön", systemImage: "camera").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                }
                .controlSize(.large)
            }
            .padding()
        }
    }

    private func accuracy(count: Int) -> Double? {
        guard let truth = Int(truthText.trimmingCharacters(in: .whitespaces)), truth > 0 else { return nil }
        return max(0, 100 * (1 - Double(abs(count - truth)) / Double(truth)))
    }
}
