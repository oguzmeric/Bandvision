import SwiftUI
import AVFoundation

struct ContentView: View {
    @StateObject private var vm = CountingViewModel()
    @State private var showProfiles = false
    @State private var showSettings = false
    @State private var confirmReset = false

    var body: some View {
        VStack(spacing: 0) {
            topBar
            cameraArea
            if vm.isCalibrating {
                CalibrationPanel(vm: vm)
            } else {
                controlPanel
            }
        }
        .background(Color.black.ignoresSafeArea())
        .preferredColorScheme(.dark)
        .onAppear {
            UIApplication.shared.isIdleTimerDisabled = true
            vm.startCamera()
        }
        .sheet(isPresented: $showProfiles) {
            ProfilesView(vm: vm, store: vm.store)
        }
        .sheet(isPresented: $showSettings, onDismiss: { vm.applySettings() }) {
            SettingsView(settings: vm.settings, logger: vm.logger)
        }
    }

    private var topBar: some View {
        HStack(spacing: 10) {
            Button { showProfiles = true } label: {
                Label(vm.profile.name, systemImage: "shippingbox")
                    .font(.headline)
                    .lineLimit(1)
            }
            .disabled(vm.isCalibrating)

            if vm.profile.expectedArea == 0 {
                Text("Kalibre edilmedi")
                    .font(.caption2.bold())
                    .padding(.horizontal, 6).padding(.vertical, 3)
                    .background(Color.orange.opacity(0.85))
                    .clipShape(Capsule())
            }
            Spacer()
            if vm.thermalState == .serious || vm.thermalState == .critical {
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.red)
            }
            Text(String(format: "%.0f fps", vm.snapshot.fps))
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
            Button { showSettings = true } label: {
                Image(systemName: "gearshape").font(.title3)
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
    }

    private var cameraArea: some View {
        GeometryReader { geo in
            let bounds = CGRect(origin: .zero, size: geo.size)
            let fit = (geo.size.width > 0 && geo.size.height > 0)
                ? AVMakeRect(aspectRatio: vm.snapshot.frameSize, insideRect: bounds)
                : bounds
            ZStack(alignment: .topLeading) {
                CameraPreview(session: vm.camera.session)
                    .frame(width: geo.size.width, height: geo.size.height)

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
                            fitRect: fit, editable: vm.isCalibrating)
                    .frame(width: geo.size.width, height: geo.size.height)

                if let err = vm.cameraError {
                    Text(err)
                        .padding()
                        .background(.ultraThinMaterial)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                        .position(x: geo.size.width / 2, y: geo.size.height / 2)
                }
            }
        }
        .background(Color.black)
    }

    private var controlPanel: some View {
        VStack(spacing: 12) {
            HStack(alignment: .lastTextBaseline) {
                Text("\(vm.total)")
                    .font(.system(size: 76, weight: .bold, design: .rounded))
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.5)
                Text("adet").foregroundStyle(.secondary)
                Spacer()
                RateView(logger: vm.logger)
            }
            HStack(spacing: 10) {
                Button { vm.toggleRunning() } label: {
                    Label(vm.isRunning ? "Durdur" : "Başlat",
                          systemImage: vm.isRunning ? "pause.fill" : "play.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .tint(vm.isRunning ? .orange : .green)

                Button { confirmReset = true } label: {
                    Label("Sıfırla", systemImage: "arrow.counterclockwise")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)

                Button { vm.beginCalibration() } label: {
                    Label("Kalibre", systemImage: "scope")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
            }
            .controlSize(.large)
        }
        .padding()
        .confirmationDialog("Sayaç sıfırlansın mı?", isPresented: $confirmReset, titleVisibility: .visible) {
            Button("Sıfırla", role: .destructive) { vm.reset() }
        }
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
