import SwiftUI
import UIKit

/// Sekmeler: Canlı · Genel bakış · Öğret · Ayarlar. Kamera ve sayım sekme değişse de sürer.
/// Açılışta logo animasyonu; ilk açılışta kurulum sihirbazı (kamera ancak sihirbaz bitince açılır).
struct RootView: View {
    @StateObject private var vm = CountingViewModel()
    @AppStorage("bs.onboarded") private var onboarded = false
    @State private var showSplash = !RootView.isUITest

    /// UI testleri animasyonu beklemez
    private nonisolated static var isUITest: Bool {
        #if DEBUG || UITEST
        return ProcessInfo.processInfo.environment.keys.contains { $0.hasPrefix("BS_TEST_") }
        #else
        return false
        #endif
    }

    var body: some View {
        ZStack {
            tabs
            if showSplash {
                SplashView { showSplash = false }
                    .zIndex(1)
            }
        }
        .fullScreenCover(isPresented: onboardingShown) {
            OnboardingView(vm: vm) { calibrate in
                onboarded = true
                // Video modunda canlı kaynak açılmaz (kareler videoyla karışırdı); video kapanınca kaynak açılır
                guard !vm.isVideoMode else { return }
                vm.startCamera()
                if calibrate { vm.beginCalibration() }
            }
        }
    }

    /// Sihirbaz animasyondan sonra açılır; yalnızca "bitir" ya da "atla" ile kapanır.
    private var onboardingShown: Binding<Bool> {
        Binding(get: { !onboarded && !showSplash }, set: { if !$0 { onboarded = true } })
    }

    private var tabs: some View {
        TabView {
            ContentView(vm: vm)
                .tabItem { Label("Canlı", systemImage: "viewfinder") }
            OverviewView(vm: vm, teach: vm.teach)
                .tabItem { Label("Genel bakış", systemImage: "chart.bar.fill") }
            TeachView(vm: vm, teach: vm.teach)
                .tabItem { Label("Öğret", systemImage: "plus.viewfinder") }
            SettingsView(vm: vm, settings: vm.settings, logger: vm.logger, showsDone: false)
                .onDisappear { vm.applySettings() }
                .tabItem { Label("Ayarlar", systemImage: "slider.horizontal.3") }
        }
        .preferredColorScheme(.dark)
        #if DEBUG || UITEST
        .overlay(alignment: .top) {
            VStack(spacing: 2) {
                if let message = vm.testHookError {
                    Text(message).font(.caption).padding(6).background(.red).accessibilityIdentifier("testHookError")
                }
                if ProcessInfo.processInfo.environment["BS_TEST_VIDEO"] != nil
                    || ProcessInfo.processInfo.environment["BS_TEST_RTSP_URL"] != nil {
                    Text(vm.snapshot.perf).font(.caption2).accessibilityIdentifier("perfStats")
                    TimelineView(.periodic(from: .now, by: 1)) { _ in
                        Text(vm.networkDebugText).font(.caption2).accessibilityIdentifier("networkStats")
                    }
                }
            }
        }
        #endif
        .onAppear {
            UIApplication.shared.isIdleTimerDisabled = true
            // Önceki sürümden güncelleyen (zaten kullanılan, belki bantta gözetimsiz çalışan) uygulamada sihirbaz
            // kendiliğinden açılmaz; Ayarlar → Kurulum'dan açılabilir.
            let defaults = UserDefaults.standard
            if defaults.object(forKey: "bs.onboarded") == nil,
               ["bs.profiles", "bs.selectedProfile", "bs.source", "bs.netcam"].contains(where: { defaults.object(forKey: $0) != nil }) {
                onboarded = true
            }
            #if DEBUG || UITEST
            let env = ProcessInfo.processInfo.environment
            if env["BS_TEST_ONBOARDING"] != nil {
                vm.prepareUITestForms()                  // sihirbaz testi: temiz ayarlar, sihirbaz açık
                onboarded = false
                return
            }
            if Self.isUITest { onboarded = true }        // diğer testler sihirbazı görmez
            if let path = env["BS_TEST_VIDEO"] {
                vm.runUITestVideo(path: path, expectedArea: env["BS_TEST_EXPECTED_AREA"].flatMap(Double.init))
                return
            }
            if env["BS_TEST_FORMS"] != nil {
                vm.prepareUITestForms()                  // ayar ekranı testleri: kamera açılmaz, ayarlar temiz
                return
            }
            if let url = env["BS_TEST_RTSP_URL"] {
                vm.runUITestNetwork(url: url, username: env["BS_TEST_RTSP_USER"] ?? "",
                                    password: env["BS_TEST_RTSP_PASS"] ?? "",
                                    expectedArea: env["BS_TEST_EXPECTED_AREA"].flatMap(Double.init))
                return
            }
            #endif
            // İlk açılışta kamera, sihirbaz bitince (izin gerekçesi anlatıldıktan sonra) açılır
            if onboarded { vm.startCamera() }
        }
    }
}
