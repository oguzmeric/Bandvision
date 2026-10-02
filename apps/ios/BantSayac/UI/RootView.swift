import SwiftUI
import UIKit

/// Sekmeler: Canlı · Genel bakış · Öğret · Ayarlar. Kamera ve sayım sekme değişse de sürer.
struct RootView: View {
    @StateObject private var vm = CountingViewModel()

    var body: some View {
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
            #if DEBUG || UITEST
            let env = ProcessInfo.processInfo.environment
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
            vm.startCamera()
        }
    }
}
