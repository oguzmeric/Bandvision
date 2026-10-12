import SwiftUI

/// Tam ekran tek kamera (ana akış). İzleme sekmesinin içinde katman: sekme görünür kalır.
struct SingleCameraView: View {
    @ObservedObject var tile: TileModel
    let onClose: () -> Void
    let onCount: () -> Void

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            TileVideoView(sink: tile.sink)
                .ignoresSafeArea()
                .accessibilityElement()
                .accessibilityLabel(tile.title)
                .accessibilityValue("\(tile.status.text ?? "canlı") · kare \(tile.frames)")
                .accessibilityIdentifier("singleVideo")
            if let text = tile.status.text {
                Text(text)
                    .font(.callout.bold())
                    .padding(10)
                    .background(.black.opacity(0.6))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            }
            VStack {
                HStack {
                    Text(tile.title)
                        .font(.headline)
                        .padding(.horizontal, 10).padding(.vertical, 6)
                        .background(.black.opacity(0.5))
                        .clipShape(Capsule())
                    Spacer()
                    Button(action: onClose) {
                        Image(systemName: "xmark.circle.fill").font(.title).symbolRenderingMode(.hierarchical)
                    }
                    .accessibilityLabel("Kapat")
                    .accessibilityIdentifier("closeSingle")
                }
                Spacer()
                Button(action: onCount) {
                    Label("Bu kamerayı say", systemImage: "number")
                }
                .buttonStyle(.borderedProminent)
                .accessibilityIdentifier("countThisCamera")
            }
            .padding()
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("singleCamera")
    }
}
