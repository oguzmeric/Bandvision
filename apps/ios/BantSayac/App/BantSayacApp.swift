import SwiftUI

@main
struct BantSayacApp: App {
    /// Yön kilidi (İzleme sekmesinde yatay serbest)
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup {
            RootView()
        }
    }
}
