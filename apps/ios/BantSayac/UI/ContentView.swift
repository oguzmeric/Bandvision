import SwiftUI
import AVFoundation

struct ContentView: View {
    @ObservedObject var vm: CountingViewModel
    @State private var showProfiles = false
    @State private var confirmReset = false
    @State private var showVideoSheet = false
    /// Güncellemeyle gelen kişi sayımı bir kez tanıtılır
    @AppStorage("bs.peopleTipSeen") private var peopleTipSeen = false
    // Görünüm yakınlaştırma (yalnızca ekran; sayım tam kare üzerinden sürer)
    @State private var zoom: CGFloat = 1
    @State private var pan: CGSize = .zero
    @GestureState private var pinch: CGFloat = 1
    @GestureState private var drag: CGSize = .zero

    var body: some View {
        GeometryReader { geo in
            mainStack(height: geo.size.height)
        }
        .background(Color.black.ignoresSafeArea())
        .preferredColorScheme(.dark)
        .sheet(isPresented: $showProfiles) {
            ProfilesView(vm: vm, store: vm.store)
        }
        .sheet(isPresented: $showVideoSheet) {
            VideoPickerSheet(vm: vm)
                .presentationDetents([.medium, .large])
        }
    }

    private func mainStack(height: CGFloat) -> some View {
        VStack(spacing: 0) {
            topBar
            cameraArea
            if vm.isCalibrating {
                if vm.isVideoMode {                     // video oynarken kalibrasyon: oynatıcı görünür kalsın
                    VideoTransportBar(vm: vm)
                        .padding(.horizontal)
                        .padding(.top, 8)
                }
                // Panel ekranın en çok %36'sı (+ sabit Kaydet satırı); içinde kayar — görüntü (alan ve çizgi ayarı) büyük kalsın
                ScrollView {
                    CalibrationPanel(vm: vm)
                }
                .frame(maxHeight: height * 0.36)
                .background(Color(white: 0.08))
                CalibrationActions(vm: vm)
            } else if vm.isVideoMode {
                VideoPanel(vm: vm, onPickVideo: { showVideoSheet = true })
            } else {
                controlPanel
            }
        }
    }

    private var topBar: some View {
        HStack(spacing: 10) {
            Button { showProfiles = true } label: {
                Label(vm.profile.name, systemImage: profileIcon)
                    .font(.headline)
                    .lineLimit(1)
            }
            .disabled(vm.isCalibrating)

            if vm.profile.expectedArea == 0 && vm.profile.mode == .blob {
                Text("Kalibre edilmedi")
                    .font(.caption2.bold())
                    .padding(.horizontal, 6).padding(.vertical, 3)
                    .background(Color.orange.opacity(0.85))
                    .clipShape(Capsule())
            }
            if vm.profile.mode == .safety {
                // Güvenlik alarmı bu cihazda çalışmaz: 0 sayacı "izleniyor" sanılmasın
                Text("Bu cihazda desteklenmiyor")
                    .font(.caption2.bold())
                    .lineLimit(1)
                    .padding(.horizontal, 6).padding(.vertical, 3)
                    .background(Color.orange.opacity(0.85))
                    .clipShape(Capsule())
                    .layoutPriority(1)
            }
            Spacer()
            if vm.thermalState == .serious || vm.thermalState == .critical {
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.red)
            }
            Text(String(format: "%.0f fps", vm.snapshot.fps))
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
            Button { showVideoSheet = true } label: {
                Image(systemName: "film").font(.title3)
            }
            .accessibilityLabel("Video ile test")
            .disabled(vm.isCalibrating)
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
    }

    /// Üst çubuktaki profil simgesi: sayım türüne göre
    private var profileIcon: String {
        switch vm.profile.mode {
        case .detect: return "person.2"
        case .safety: return "exclamationmark.shield"
        case .blob, .linescan: return "shippingbox"
        }
    }

    private var cameraArea: some View {
        GeometryReader { geo in
            let bounds = CGRect(origin: .zero, size: geo.size)
            let fit = (geo.size.width > 0 && geo.size.height > 0)
                ? AVMakeRect(aspectRatio: vm.snapshot.frameSize, insideRect: bounds)
                : bounds
            let scale = min(6, max(1, zoom * pinch))
            ZStack(alignment: .topLeading) {
                // Görüntü + maske + ROI/çizgi/izler birlikte yakınlaşır (hizalar korunur)
                ZStack(alignment: .topLeading) {
                    if vm.showsFrameImages {
                        Color.black
                        if let frame = vm.frameImage {
                            Image(decorative: frame, scale: 1)
                                .resizable()
                                .frame(width: fit.width, height: fit.height)
                                .position(x: fit.midX, y: fit.midY)
                        }
                    } else {
                        CameraPreview(session: vm.camera.session)
                            .frame(width: geo.size.width, height: geo.size.height)
                    }

                    if let mask = vm.snapshot.mask {
                        Image(decorative: mask, scale: 1)
                            .resizable()
                            .interpolation(.none)
                            .frame(width: fit.width, height: fit.height)
                            .position(x: fit.midX, y: fit.midY)
                            .opacity(0.5)
                            .allowsHitTesting(false)
                    }

                    OverlayView(profile: $vm.profile, snapshot: vm.snapshot,
                                fitRect: fit, editable: vm.isCalibrating, verdicts: vm.trackVerdicts)
                        .frame(width: geo.size.width, height: geo.size.height)

                    if vm.teachingStaff {
                        Color.clear
                            .contentShape(Rectangle())
                            .frame(width: geo.size.width, height: geo.size.height)
                            .onTapGesture(coordinateSpace: .local) { loc in
                                let x = (loc.x - fit.minX) / fit.width, y = (loc.y - fit.minY) / fit.height
                                guard (0...1).contains(x), (0...1).contains(y) else { return }
                                vm.teachStaffColor(at: CGPoint(x: x, y: y))
                            }
                            .accessibilityIdentifier("staffTeachLayer")
                    }
                }
                .frame(width: geo.size.width, height: geo.size.height)
                .scaleEffect(scale)
                .offset(Self.clamped(CGSize(width: pan.width + drag.width, height: pan.height + drag.height),
                                     scale: scale, size: geo.size))

                if vm.sourceKind == .network, !vm.isVideoMode, let state = vm.networkState {
                    Label(state.text, systemImage: state.isPlaying ? "dot.radiowaves.left.and.right" : "wifi.exclamationmark")
                        .font(.caption)
                        .padding(.horizontal, 10).padding(.vertical, 6)
                        .background(.ultraThinMaterial)
                        .clipShape(Capsule())
                        .padding(8)
                        .accessibilityElement(children: .combine)
                        .accessibilityIdentifier("networkState")
                }

                if scale > 1.01 {
                    Button {
                        withAnimation(.easeOut(duration: 0.2)) { zoom = 1; pan = .zero }
                    } label: {
                        Label(String(format: "%.1f×", scale), systemImage: "arrow.down.right.and.arrow.up.left")
                            .font(.caption.monospacedDigit())
                            .padding(.horizontal, 10).padding(.vertical, 6)
                            .background(.ultraThinMaterial)
                            .clipShape(Capsule())
                    }
                    .padding(8)
                    .frame(maxWidth: .infinity, alignment: .trailing)
                    .accessibilityLabel("Yakınlaştırmayı sıfırla")
                }

                if let err = vm.cameraError, vm.sourceKind == .phone {
                    Text(err)
                        .padding()
                        .background(.ultraThinMaterial)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                        .position(x: geo.size.width / 2, y: geo.size.height / 2)
                }
            }
            .frame(width: geo.size.width, height: geo.size.height)
            .clipped()
            .contentShape(Rectangle())
            // İki parmak: yakınlaştır (1×–6×)
            .simultaneousGesture(
                MagnifyGesture()
                    .updating($pinch) { value, state, _ in state = value.magnification }
                    .onEnded { value in
                        let z = min(6, max(1, zoom * value.magnification))
                        zoom = z < 1.05 ? 1 : z
                        pan = zoom == 1 ? .zero : Self.clamped(pan, scale: zoom, size: geo.size)
                    }
            )
            // Tek parmak: yakınken kaydır. Kalibrasyonda tek parmak ROI/çizgiyi sürükler, kaydırma kapalı.
            .simultaneousGesture(
                DragGesture(minimumDistance: 10)
                    .updating($drag) { value, state, _ in state = value.translation }
                    .onEnded { value in
                        pan = Self.clamped(CGSize(width: pan.width + value.translation.width,
                                                  height: pan.height + value.translation.height),
                                           scale: zoom, size: geo.size)
                    },
                including: zoom > 1 && !vm.isCalibrating ? .all : .subviews
            )
            // Çift dokunuş: sıfırla
            .simultaneousGesture(
                TapGesture(count: 2).onEnded {
                    withAnimation(.easeOut(duration: 0.2)) { zoom = 1; pan = .zero }
                },
                including: vm.isCalibrating ? .subviews : .all
            )
        }
        .background(Color.black)
    }

    /// Kaydırmayı, büyütülmüş görüntü kenarları alanın dışına taşmayacak şekilde sınırlar.
    private static func clamped(_ offset: CGSize, scale: CGFloat, size: CGSize) -> CGSize {
        let maxX = (scale - 1) * size.width / 2
        let maxY = (scale - 1) * size.height / 2
        return CGSize(width: min(maxX, max(-maxX, offset.width)), height: min(maxY, max(-maxY, offset.height)))
    }

    private var controlPanel: some View {
        VStack(spacing: 10) {
            if !peopleTipSeen && !vm.profile.isTwoWay {
                peopleTip
            }
            if vm.profile.isTwoWay {
                PeopleCounters(vm: vm)
                EntryDirectionButton(vm: vm)
            } else {
                beltCounters
            }
            runButtons
        }
        .padding()
        .confirmationDialog("Sayaç sıfırlansın mı?", isPresented: $confirmReset, titleVisibility: .visible) {
            Button("Sıfırla", role: .destructive) { vm.reset() }
        }
    }

    /// "Yeni: Kişi sayımı" kartı: dokununca profiller açılır (Kişi sayımı → Mağaza girişi)
    private var peopleTip: some View {
        HStack(spacing: 12) {
            Image(systemName: "person.2.fill")
                .font(.title3)
                .foregroundStyle(.green)
            VStack(alignment: .leading, spacing: 2) {
                Text("Yeni: Kişi sayımı").font(.subheadline.weight(.semibold))
                Text("Mağaza girişinde giren ve çıkanları sayar. Profillerden \"Mağaza girişi\"ni seç.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 4)
            Button {
                peopleTipSeen = true
            } label: {
                Image(systemName: "xmark").font(.caption.weight(.bold)).padding(6)
            }
            .accessibilityLabel("Tanıtımı kapat")
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 14).fill(Color.green.opacity(0.12)))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Color.green.opacity(0.35), lineWidth: 1))
        .contentShape(Rectangle())
        .onTapGesture {
            peopleTipSeen = true
            showProfiles = true
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("peopleTip")
        .accessibilityHint("Profilleri açar")
    }

    private var beltCounters: some View {
        VStack(spacing: 10) {
            HStack(alignment: .lastTextBaseline, spacing: 16) {
                Text("\(vm.total)")
                    .accessibilityIdentifier("liveCount")
                    .font(.system(size: 56, weight: .bold, design: .rounded))
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.5)
                Text("adet").foregroundStyle(.secondary)
                Spacer()
                VStack(alignment: .trailing, spacing: 0) {
                    Text(vm.inspectionStats.failRate.map { String(format: "%%%.1f", $0 * 100) } ?? "—")
                        .font(.title2.bold())
                        .monospacedDigit()
                        .foregroundStyle(.orange)
                    Text("kusur").font(.caption).foregroundStyle(.secondary)
                }
                RateView(logger: vm.logger)
            }
            RecentInspectionStrip(vm: vm)
        }
    }

    private var runButtons: some View {
        HStack(spacing: 10) {
            Button { vm.toggleRunning() } label: {
                Label(vm.isRunning ? "Durdur" : "Başlat",
                      systemImage: vm.isRunning ? "pause.fill" : "play.fill")
                    .lineLimit(1).minimumScaleFactor(0.7)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .tint(vm.isRunning ? .orange : .green)

            Button { confirmReset = true } label: {
                Label("Sıfırla", systemImage: "arrow.counterclockwise")
                    .lineLimit(1).minimumScaleFactor(0.7)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)

            Button { vm.beginCalibration() } label: {
                Label(vm.profile.isTwoWay ? "Ayarla" : "Kalibre", systemImage: "scope")
                    .lineLimit(1).minimumScaleFactor(0.7)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
        }
        .controlSize(.large)
    }
}

struct RateView: View {
    @ObservedObject var logger: CountLogger

    var body: some View {
        VStack(alignment: .trailing, spacing: 0) {
            Text("\(logger.ratePerMinute)")
                .font(.title2.bold())
                .monospacedDigit()
            Text("adet/dk")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}
