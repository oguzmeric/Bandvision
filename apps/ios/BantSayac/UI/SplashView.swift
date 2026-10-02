import SwiftUI

/// Açılış animasyonu. İlk karesi sistem açılış ekranıyla (UILaunchScreen: LaunchLogo, LaunchBackground)
/// birebir aynıdır; geçiş kesintisiz olur. Logonun üzerinden ışık geçer, logo hafifçe büyür, ekran açılır.
/// Toplam ~1,3 sn; "Hareketi Azalt" açıksa yalnızca kısa bir solma. Bu sırada uygulama arka planda hazırlanır.
struct SplashView: View {
    let onFinished: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var sweep: CGFloat = -1          // ışık bandının konumu (-1 → 1, logo genişliği cinsinden)
    @State private var scale: CGFloat = 1
    @State private var glow: Double = 0
    @State private var opacity: Double = 1

    /// Sistem açılış ekranındaki boyut: görsel 1x'te 280 px → 280 pt
    private let logoSize: CGFloat = 280

    var body: some View {
        ZStack {
            Color("LaunchBackground").ignoresSafeArea()
            logo
                .scaleEffect(scale)
                .shadow(color: Color(red: 0.62, green: 0.3, blue: 1).opacity(glow), radius: 28)
        }
        .opacity(opacity)
        .accessibilityHidden(true)
        .allowsHitTesting(opacity > 0.5)
        .task { await run() }
    }

    private var logo: some View {
        Image("LaunchLogo")
            .resizable()
            .frame(width: logoSize, height: logoSize)
            .overlay {
                // Işık bandı yalnızca logonun parlak kısımlarında görünür (siyah zemin aydınlanmaz)
                GeometryReader { geo in
                    LinearGradient(colors: [.clear, .white.opacity(0.55), .clear],
                                   startPoint: .leading, endPoint: .trailing)
                        .frame(width: geo.size.width * 0.35)
                        .rotationEffect(.degrees(18))
                        .offset(x: sweep * geo.size.width)
                        .frame(width: geo.size.width, height: geo.size.height)
                }
                .blendMode(.screen)
                .mask(Image("LaunchLogo").resizable().luminanceToAlpha())
                .allowsHitTesting(false)
            }
    }

    @MainActor
    private func run() async {
        if reduceMotion {
            try? await Task.sleep(for: .milliseconds(250))
            withAnimation(.easeOut(duration: 0.25)) { opacity = 0 }
            try? await Task.sleep(for: .milliseconds(260))
            onFinished()
            return
        }
        withAnimation(.easeInOut(duration: 0.75)) { sweep = 1.2 }
        withAnimation(.easeOut(duration: 0.6).delay(0.15)) {
            scale = 1.04
            glow = 0.55
        }
        try? await Task.sleep(for: .milliseconds(850))
        withAnimation(.easeIn(duration: 0.35)) {
            opacity = 0
            scale = 1.1
        }
        try? await Task.sleep(for: .milliseconds(360))
        onFinished()
    }
}
