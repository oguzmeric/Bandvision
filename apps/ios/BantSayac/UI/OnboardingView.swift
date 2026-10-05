import SwiftUI

/// İlk açılışta kurulum sihirbazı: karşılama → görüntü kaynağı → ürün → montaj → hazır.
/// Kamera izni ancak son adımdan sonra (gerekçesi anlatılmış olarak) istenir. Ayarlar → Kurulum'dan yeniden açılır.
struct OnboardingView: View {
    @ObservedObject var vm: CountingViewModel
    /// true: kalibrasyonla başla
    let onFinish: (_ calibrate: Bool) -> Void

    private enum Step: Int, CaseIterable { case welcome, source, product, mounting, ready }
    enum SourceChoice: String, CaseIterable, Identifiable {
        case phone, camera, recorder
        var id: String { rawValue }
    }

    @State private var step: Step = .welcome
    @State private var source: SourceChoice = .phone
    @State private var networkFormKind: NetworkDeviceKind?
    @State private var productID: UUID?
    @State private var checks: Set<Int> = []

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                header
                ScrollView {
                    content
                        .padding(.horizontal, 20)
                        .padding(.vertical, 12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                footer
            }
            .background(Color("LaunchBackground").ignoresSafeArea())
            .sheet(item: $networkFormKind) { kind in
                NavigationStack {
                    NetworkCameraForm(vm: vm, initialKind: kind)
                        .toolbar {
                            ToolbarItem(placement: .cancellationAction) {
                                Button("Kapat") { networkFormKind = nil }
                            }
                        }
                }
                .preferredColorScheme(.dark)
            }
        }
        .preferredColorScheme(.dark)
        .onAppear {
            productID = productID ?? vm.profile.id
            if vm.sourceKind == .network {
                source = vm.networkConfig.kind == .recorder ? .recorder : .camera
            }
        }
    }

    // MARK: - Üst ve alt çubuk

    private var header: some View {
        HStack {
            if step != .welcome {
                Button {
                    withAnimation { step = Step(rawValue: step.rawValue - 1) ?? .welcome }
                } label: {
                    Image(systemName: "chevron.left")
                }
                .accessibilityLabel("Geri")
            }
            Spacer()
            HStack(spacing: 6) {
                ForEach(Step.allCases, id: \.self) { s in
                    Capsule()
                        .fill(s.rawValue <= step.rawValue ? Color.accentColor : Color.secondary.opacity(0.4))
                        .frame(width: s == step ? 18 : 7, height: 7)
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Adım \(step.rawValue + 1) / \(Step.allCases.count)")
            Spacer()
            Button("Atla") { finish(calibrate: false) }
                .font(.callout)
                .accessibilityIdentifier("onboardingSkip")
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
    }

    private var footer: some View {
        Button {
            advance()
        } label: {
            Text(primaryTitle)
                .font(.headline)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 6)
        }
        .buttonStyle(.borderedProminent)
        .disabled(!canAdvance)
        .padding(20)
        .accessibilityIdentifier("onboardingNext")
    }

    private var primaryTitle: String {
        switch step {
        case .welcome: return "Başla"
        case .ready: return "Kalibrasyonla başla"
        default: return "Devam"
        }
    }

    /// Ağ kaynağı seçildiyse bağlantı ayarlanmış olmalı
    private var canAdvance: Bool {
        step != .source || source == .phone || networkReady
    }

    private var networkReady: Bool {
        vm.networkConfig.isComplete && vm.networkConfig.kind == (source == .recorder ? .recorder : .camera)
    }

    private func advance() {
        if step == .ready {
            finish(calibrate: true)
        } else {
            withAnimation { step = Step(rawValue: step.rawValue + 1) ?? .ready }
        }
    }

    private func finish(calibrate: Bool) {
        if let productID, productID != vm.profile.id { vm.selectProfile(productID) }
        if source == .phone || !networkReady {
            vm.setSource(.phone)
        } else {
            vm.setSource(.network)
        }
        onFinish(calibrate)
    }

    // MARK: - Adımlar

    @ViewBuilder private var content: some View {
        switch step {
        case .welcome: welcome
        case .source: sourceStep
        case .product: productStep
        case .mounting: mountingStep
        case .ready: readyStep
        }
    }

    private var welcome: some View {
        VStack(alignment: .leading, spacing: 18) {
            Image("LaunchLogo")
                .resizable()
                .scaledToFit()
                .frame(maxWidth: 260)
                .frame(maxWidth: .infinity)
                .accessibilityLabel("BandVision")
            Text("Banttan geçen ürünleri sayar, kalitesini kontrol eder.")
                .font(.title3.weight(.semibold))
            feature("number", "Sayım", "Ürünler sayım çizgisinden geçerken sayılır; bitişik ürünler ayrılır.")
            feature("checkmark.seal", "Kalite kontrol", "İyi ve kusurlu örnekleri göstererek uygulamaya öğretirsin.")
            feature("video", "Her kaynak", "iPhone kamerası, IP kamera ya da kayıt cihazı (TRASSIR, Dahua, Hikvision).")
            feature("lock.shield", "Cihazda işlenir", "Görüntüler telefondan çıkmaz; yalnızca sonuçlar paylaşılabilir.")
        }
    }

    private func feature(_ icon: String, _ title: String, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: icon)
                .font(.title3)
                .frame(width: 30)
                .foregroundStyle(Color.accentColor)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline)
                Text(text).font(.callout).foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .combine)
    }

    private var sourceStep: some View {
        VStack(alignment: .leading, spacing: 14) {
            stepTitle("Görüntü nereden gelecek?")
            sourceCard(.phone, icon: "iphone.rear.camera", title: "iPhone kamerası",
                       text: "Telefon bandın tam tepesine sabitlenir.")
            sourceCard(.camera, icon: "web.camera", title: "IP kamera",
                       text: "Ağa doğrudan bağlı bir kamera (RTSP).")
            sourceCard(.recorder, icon: "externaldrive.connected.to.line.below", title: "Kayıt cihazı (NVR/XVR)",
                       text: "Kameralar TRASSIR, Dahua ya da Hikvision kayıt cihazına bağlı.")
            if source != .phone {
                Button {
                    networkFormKind = source == .recorder ? .recorder : .camera
                } label: {
                    Label(networkReady ? "Ayarlandı: \(vm.networkConfig.summary)" : "Bağlantıyı ayarla",
                          systemImage: networkReady ? "checkmark.circle.fill" : "gearshape")
                }
                .buttonStyle(.bordered)
                .tint(networkReady ? .green : .accentColor)
                .accessibilityIdentifier("onboardingConnect")
                Text("Telefon kamerayla ya da kayıt cihazıyla aynı ağda olmalı (misafir Wi-Fi çoğu zaman erişemez).")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func sourceCard(_ choice: SourceChoice, icon: String, title: String, text: String) -> some View {
        Button {
            source = choice
        } label: {
            HStack(spacing: 14) {
                Image(systemName: icon).font(.title2).frame(width: 36)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.headline).foregroundStyle(.primary)
                    Text(text).font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.leading)
                }
                Spacer()
                Image(systemName: source == choice ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(source == choice ? Color.accentColor : .secondary)
            }
            .padding(14)
            .background(RoundedRectangle(cornerRadius: 12).fill(Color.white.opacity(source == choice ? 0.12 : 0.05)))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(source == choice ? .isSelected : [])
        .accessibilityIdentifier("source.\(choice.rawValue)")
    }

    private var productStep: some View {
        VStack(alignment: .leading, spacing: 12) {
            stepTitle("Ne sayacaksın?")
            ForEach(ProductCatalog.categories) { cat in
                if cat.available {
                    Label(cat.title, systemImage: cat.icon)
                        .font(.headline)
                        .padding(.top, 4)
                    products(of: cat)
                } else {
                    comingSoon(cat)
                }
            }
            Text("Listede yoksa \"Genel ürün\"ü seç; kalibrasyonla senin ürününe göre ayarlanır.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    /// Henüz çalışmayan sayım türü: görünür ama seçilemez
    private func comingSoon(_ cat: CountCategory) -> some View {
        HStack(spacing: 12) {
            Image(systemName: cat.icon).frame(width: 24).foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 2) {
                Text(cat.title).foregroundStyle(.secondary)
                Text(cat.subtitle).font(.caption).foregroundStyle(.tertiary)
            }
            Spacer()
            Text("Yakında")
                .font(.caption2.bold())
                .padding(.horizontal, 8).padding(.vertical, 3)
                .background(Capsule().fill(Color.white.opacity(0.08)))
                .foregroundStyle(.secondary)
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 12).stroke(Color.white.opacity(0.08)))
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("category.\(cat.id)")
    }

    /// Türün kayıtlı profilleri; hiç yoksa hazır profil (seçilince eklenir)
    private func products(of cat: CountCategory) -> some View {
        let saved = vm.store.profiles.filter(cat.contains)
        return VStack(alignment: .leading, spacing: 12) {
            if saved.isEmpty {
                ForEach(cat.presets) { preset in
                    Button {
                        let p = preset.make()
                        vm.store.add(p)
                        productID = p.id
                    } label: {
                        HStack {
                            Text(preset.name).foregroundStyle(.primary)
                            Spacer()
                            Image(systemName: "plus.circle").foregroundStyle(Color.accentColor)
                        }
                        .padding(14)
                        .background(RoundedRectangle(cornerRadius: 12).fill(Color.white.opacity(0.05)))
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("preset.\(preset.name)")
                }
            }
            productRows(saved)
        }
    }

    private func productRows(_ list: [ProductProfile]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(list) { p in
                Button {
                    productID = p.id
                } label: {
                    HStack {
                        Text(p.name).foregroundStyle(.primary)
                        Spacer()
                        Image(systemName: productID == p.id ? "checkmark.circle.fill" : "circle")
                            .foregroundStyle(productID == p.id ? Color.accentColor : .secondary)
                    }
                    .padding(14)
                    .background(RoundedRectangle(cornerRadius: 12).fill(Color.white.opacity(productID == p.id ? 0.12 : 0.05)))
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("product.\(p.name)")
            }
        }
    }

    /// Kişi sayımı (mağaza girişi) için montaj maddeleri
    private static let peopleMountingItems = [
        "Kamera girişi yukarıdan ya da yandan görüyor; kişiler kadrajdan tam geçiyor",
        "Sayım çizgisinin iki yanında yürüme alanı görünüyor (yalnızca kapı eşiği değil)",
        "Kamera sabit, titreşmiyor",
        "Işık yeterli; kapıdan gelen ters ışık ya da parlama yok",
        "Girişte görüntülü sayım bilgilendirmesi asılı (görüntü kaydedilmez, yalnızca sayı)"
    ]

    /// Seçilen profile göre montaj maddeleri
    private var mountingItems: [String] {
        let selected = vm.store.profiles.first { $0.id == (productID ?? vm.profile.id) }
        return selected?.isTwoWay == true ? Self.peopleMountingItems : Self.mountingItems
    }

    private static let mountingItems = [
        "Kamera bandın tam tepesinde ve banda dik bakıyor",
        "Kamera sabit, titreşmiyor",
        "Işık yeterli ve düzgün (gölge, parlama yok)",
        "Bant görüntüde boydan boya görünüyor",
        "Telefon şarjda ve uygulama açık kalacak"
    ]

    private var mountingStep: some View {
        VStack(alignment: .leading, spacing: 12) {
            stepTitle("Montajı kontrol et")
            ForEach(mountingItems.indices, id: \.self) { i in
                Button {
                    if checks.contains(i) { checks.remove(i) } else { checks.insert(i) }
                } label: {
                    HStack(alignment: .top, spacing: 12) {
                        Image(systemName: checks.contains(i) ? "checkmark.square.fill" : "square")
                            .foregroundStyle(checks.contains(i) ? Color.accentColor : .secondary)
                        Text(mountingItems[i]).foregroundStyle(.primary).multilineTextAlignment(.leading)
                        Spacer(minLength: 0)
                    }
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(checks.contains(i) ? .isSelected : [])
            }
            Text("İşaretlemek zorunlu değil; ama sayım doğruluğu bu koşullara bağlı.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var readyStep: some View {
        VStack(alignment: .leading, spacing: 14) {
            stepTitle("Hazır")
            Text("Son adım kalibrasyon. Canlı ekranda:")
            numbered(1, "Alanı ayarla: dikdörtgen ya da banda göre çokgen; sayım çizgisini yerleştir.")
            numbered(2, "Bant boşken \"Boş bandı öğren\".")
            numbered(3, "\"Örnek geçir\" ile banttan 8 ürün geçir; tek ürünün boyu öğrenilir.")
            if source == .phone || !networkReady {
                Label("Devam edince iPhone kamerası için izin istenecek; görüntü yalnızca bu telefonda işlenir.",
                      systemImage: "camera")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func numbered(_ n: Int, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text("\(n)")
                .font(.headline)
                .frame(width: 28, height: 28)
                .background(Circle().fill(Color.accentColor.opacity(0.25)))
            Text(text)
        }
        .accessibilityElement(children: .combine)
    }

    private func stepTitle(_ text: String) -> some View {
        Text(text).font(.title2.bold()).padding(.bottom, 4)
    }
}
