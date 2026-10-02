import SwiftUI

/// Ayarlar → Görüntü kaynağı bölümü.
struct VideoSourceSection: View {
    @ObservedObject var vm: CountingViewModel

    var body: some View {
        Section {
            Picker("Kaynak", selection: Binding(get: { vm.sourceKind }, set: { vm.setSource($0) })) {
                ForEach(VideoSourceKind.allCases) { Text($0.title).tag($0) }
            }
            NavigationLink {
                NetworkCameraForm(vm: vm)
            } label: {
                HStack {
                    Text("Ağ kamerası")
                    Spacer()
                    Text(vm.networkConfig.summary).foregroundStyle(.secondary).lineLimit(1)
                }
            }
            if vm.sourceKind == .network, let state = vm.networkState {
                Text(state.text).font(.caption).foregroundStyle(state.isPlaying ? .green : .orange)
            }
        } header: {
            Text("Görüntü kaynağı")
        } footer: {
            Text("Ağ kamerası: telefon, kameranın RTSP yayınını alır ve aynı sayım/kalite kontrolünü yapar. Telefon kameraya ağ üzerinden ulaşabilmeli (aynı yerel ağ ya da VPN). Uygulama açık ve telefon şarjda kalmalı.")
        }
    }
}

/// Ağ kamerası ayarları, bağlantı sınaması ve kaydetme.
struct NetworkCameraForm: View {
    @ObservedObject var vm: CountingViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var config = NetworkCameraConfig()
    @State private var password = ""
    @State private var portText = "554"
    @State private var testing = false
    @State private var result: NetworkCameraSource.ProbeResult?
    @State private var errorText: String?
    @State private var saveWarning: String?
    @FocusState private var focused: Bool

    var body: some View {
        Form {
            Section {
                Picker("Marka", selection: $config.brand) {
                    ForEach(CameraBrand.allCases) { Text($0.title).tag($0) }
                }
                if config.brand == .custom {
                    TextField("rtsp://192.168.1.64:554/…", text: $config.customURL)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .focused($focused)
                } else {
                    LabeledContent("IP adresi") {
                        TextField("192.168.1.64", text: $config.host)
                            .keyboardType(.numbersAndPunctuation)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .multilineTextAlignment(.trailing)
                            .focused($focused)
                    }
                    LabeledContent("Port") {
                        TextField("554", text: $portText)
                            .keyboardType(.numbersAndPunctuation)
                            .multilineTextAlignment(.trailing)
                            .focused($focused)
                    }
                    Stepper("Kanal: \(config.channel)", value: $config.channel, in: 1...64)
                    Toggle("Alt akış (önerilir)", isOn: $config.substream)
                }
            } header: {
                Text("Kamera")
            } footer: {
                if let url = config.rtspURL {
                    Text("Adres: \(url.absoluteString)").textSelection(.enabled)
                } else {
                    Text(config.brand == .custom ? "rtsp:// ile başlayan tam adresi girin."
                                                 : "Kameranın IP adresini girin (ör. 192.168.1.64).")
                }
            }

            Section {
                TextField("Kullanıcı adı", text: $config.username)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .focused($focused)
                SecureField("Şifre", text: $password)
                    .focused($focused)
            } header: {
                Text("Giriş")
            } footer: {
                Text("Şifre yalnızca bu iPhone'un güvenli anahtar deposunda (Keychain) saklanır.")
            }

            Section {
                Button {
                    test()
                } label: {
                    HStack {
                        Label("Bağlantıyı test et", systemImage: "antenna.radiowaves.left.and.right")
                        if testing { Spacer(); ProgressView() }
                    }
                }
                .disabled(testing || config.rtspURL == nil)
                if let result {
                    if let thumb = result.thumbnail {
                        Image(decorative: thumb, scale: 1).resizable().scaledToFit()
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                    }
                    Label("Bağlandı · \(result.width)×\(result.height) · \(result.codec)",
                          systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                    if result.width > 1280 {
                        Text("Sayım için alt akış (ör. 640×360) yeterli ve daha az pil/ısı demek.")
                            .font(.caption).foregroundStyle(.orange)
                    }
                }
                if let errorText {
                    Label(errorText, systemImage: "xmark.octagon.fill").foregroundStyle(.red)
                    Text("Kontrol et: IP adresi doğru mu · telefon kamerayla aynı ağda mı (misafir Wi-Fi çoğu zaman kameralara erişemez) · kamerada RTSP açık mı, port 554 mü · kullanıcı adı/şifre · marka/kanal doğru mu (olmazsa \"Diğer\" ile tam adres). iPhone \"Yerel ağ\" izni istediyse izin ver.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Section {
                Button {
                    save()
                } label: {
                    Label("Kaydet ve bu kamerayı kullan", systemImage: "checkmark")
                }
                .disabled(config.rtspURL == nil)
            }
        }
        .alert("Şifre", isPresented: Binding(get: { saveWarning != nil }, set: { if !$0 { saveWarning = nil } })) {
            Button("Tamam") { saveWarning = nil; dismiss() }
        } message: {
            Text(saveWarning ?? "")
        }
        .navigationTitle("Ağ kamerası")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button("Tamam") { focused = false }
            }
        }
        .onAppear {
            config = vm.networkConfig
            portText = String(config.port)
            password = CameraCredentialStore.password()
        }
        .onChange(of: portText) { _, text in
            config.port = Int(text.filter(\.isNumber)) ?? 0
        }
        .onChange(of: config) { _, _ in
            result = nil
            errorText = nil
        }
    }

    private func test() {
        guard let url = config.rtspURL else { return }
        focused = false
        testing = true
        result = nil
        errorText = nil
        let user = config.username.isEmpty ? (url.user ?? "") : config.username
        let pass = password.isEmpty ? (url.password ?? "") : password
        Task { @MainActor in
            switch await NetworkCameraSource.probe(url: url, username: user, password: pass) {
            case .success(let r): result = r
            case .failure(let e): errorText = e.localizedDescription
            }
            testing = false
        }
    }

    private func save() {
        focused = false
        let warning = vm.saveNetworkConfig(config, password: password)
        vm.setSource(.network)
        if let warning {
            saveWarning = warning                    // sessizce geçme: kullanıcıya göster, sonra kapat
        } else {
            dismiss()
        }
    }
}
