import SwiftUI

struct SettingsView: View {
    /// Görüntü kaynağı bölümü için (nil: bölüm gösterilmez)
    var vm: CountingViewModel?
    @ObservedObject var settings: AppSettings
    @ObservedObject var logger: CountLogger
    /// Sayfa olarak açıldığında "Tamam"; sekmede gizli.
    var showsDone = true
    @Environment(\.dismiss) private var dismiss
    @State private var csvURL: URL?
    @AppStorage("bs.onboarded") private var onboarded = true

    /// "1.0.0 (23)": TestFlight'taki derleme numarasıyla aynı
    static var versionText: String {
        let info = Bundle.main.infoDictionary
        let version = info?["CFBundleShortVersionString"] as? String ?? "?"
        let build = info?["CFBundleVersion"] as? String ?? "?"
        return "\(version) (derleme \(build))"
    }

    var body: some View {
        NavigationStack {
            Form {
                if let vm { VideoSourceSection(vm: vm) }
                Section {
                    VStack(alignment: .leading) {
                        Text(verbatim: settings.torchLevel == 0 ? "Fener: kapalı" : "Fener: %\(Int(settings.torchLevel * 100))")
                        Slider(value: $settings.torchLevel, in: 0...1, step: 0.1)
                    }
                } header: {
                    Text("Işık")
                } footer: {
                    Text("Telefon feneri uzun süre açık kalınca ısınır; sürekli kullanımda harici LED/halka ışık önerilir.")
                }

                Section {
                    Picker("Pozlama süresi", selection: $settings.shutterDenominator) {
                        Text("Otomatik").tag(0)
                        Text("1/250 s").tag(250)
                        Text("1/500 s").tag(500)
                        Text("1/1000 s").tag(1000)
                        Text("1/2000 s").tag(2000)
                    }
                    Toggle("Odağı kilitle", isOn: $settings.focusLocked)
                    Toggle("Algılama maskesini göster", isOn: $settings.showMask)
                } header: {
                    Text("Kamera")
                } footer: {
                    Text("Hızlı bantta bulanıklığı önlemek için 1/1000 s veya daha kısa pozlama ve güçlü ışık kullanın.")
                }

                Section {
                    TextField("Hat adı", text: $settings.lineName)
                    TextField("https://…", text: $settings.webhookURL)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                } header: {
                    Text("Entegrasyon")
                } footer: {
                    Text("Sayım olayları 5 sn'de bir JSON olarak bu adrese POST edilir (n8n, Supabase Edge Function vb.). Boş bırakılırsa gönderilmez.")
                }

                Section("Hakkında") {
                    LabeledContent("Sürüm", value: Self.versionText)
                        .accessibilityIdentifier("appVersion")
                }
                if vm != nil {
                    Section {
                        Button("Kurulum sihirbazını yeniden aç") { onboarded = false }
                            .accessibilityIdentifier("reopenOnboarding")
                    } header: {
                        Text("Kurulum")
                    } footer: {
                        Text("Görüntü kaynağı, ürün, montaj kontrolü ve kalibrasyon adım adım.")
                    }
                }

                Section("Rapor") {
                    Button("Dakikalık CSV hazırla") { csvURL = logger.makeCSV() }
                    if let u = csvURL {
                        ShareLink(item: u) {
                            Label("CSV'yi paylaş", systemImage: "square.and.arrow.up")
                        }
                    }
                }
            }
            .navigationTitle("Ayarlar")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                if showsDone {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Tamam") { dismiss() }
                    }
                }
            }
        }
    }
}
