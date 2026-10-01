import Foundation

@MainActor
final class AppSettings: ObservableObject {
    /// 0 = kapalı, 0.1...1 = fener seviyesi.
    @Published var torchLevel: Double { didSet { UserDefaults.standard.set(torchLevel, forKey: "bs.torch") } }
    /// 0 = otomatik pozlama, aksi halde 1/N saniye.
    @Published var shutterDenominator: Int { didSet { UserDefaults.standard.set(shutterDenominator, forKey: "bs.shutter") } }
    @Published var focusLocked: Bool { didSet { UserDefaults.standard.set(focusLocked, forKey: "bs.focusLocked") } }
    @Published var showMask: Bool { didSet { UserDefaults.standard.set(showMask, forKey: "bs.showMask") } }
    @Published var lineName: String { didSet { UserDefaults.standard.set(lineName, forKey: "bs.line") } }
    @Published var webhookURL: String { didSet { UserDefaults.standard.set(webhookURL, forKey: "bs.webhook") } }

    init() {
        let d = UserDefaults.standard
        torchLevel = d.object(forKey: "bs.torch") as? Double ?? 0
        shutterDenominator = d.object(forKey: "bs.shutter") as? Int ?? 0
        focusLocked = d.bool(forKey: "bs.focusLocked")
        showMask = d.bool(forKey: "bs.showMask")
        lineName = d.string(forKey: "bs.line") ?? "Hat-1"
        webhookURL = d.string(forKey: "bs.webhook") ?? ""
    }
}
