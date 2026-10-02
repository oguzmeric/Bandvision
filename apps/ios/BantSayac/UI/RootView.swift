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
            SettingsView(settings: vm.settings, logger: vm.logger, showsDone: false)
                .onDisappear { vm.applySettings() }
                .tabItem { Label("Ayarlar", systemImage: "slider.horizontal.3") }
        }
        .preferredColorScheme(.dark)
        #if DEBUG
        .overlay(alignment: .top) {
            if let message = vm.testHookError {
                Text(message).font(.caption).padding(6).background(.red).accessibilityIdentifier("testHookError")
            }
        }
        #endif
        .onAppear {
            UIApplication.shared.isIdleTimerDisabled = true
            #if DEBUG
            let env = ProcessInfo.processInfo.environment
            if let path = env["BS_TEST_VIDEO"] {
                vm.runUITestVideo(path: path, expectedArea: env["BS_TEST_EXPECTED_AREA"].flatMap(Double.init))
                return
            }
            #endif
            vm.startCamera()
        }
    }
}
