import Foundation

/// Personel rengi öğretme geri bildirimi (§4.10 eki): dokunuştan sonra süre içinde renk gelmezse (video duraklatılmış
/// ya da bitmiş, kare akmıyor) `onTimeout` çağrılır; karanlık/akmıyor uyarısı gösterilmeden önceki kalibrasyon iletisi
/// saklanır ve sonraki başarılı öğretmede, uyarı hâlâ ekrandaysa geri konur.
@MainActor
final class StaffTeachFeedback {
    static let darkMessage = "Burası çok karanlık; personelin üstüne dokunun."
    static let noFrameMessage = "Görüntü akmıyor: videoyu oynatıp tekrar dokunun."

    var onTimeout: (@MainActor () -> Void)?
    private let timeout: Duration
    private var pending: Task<Void, Never>?
    private var messageBefore: String?

    init(timeout: Duration = .milliseconds(1500)) {
        self.timeout = timeout
    }

    /// Bir öğretme dokunuşu işlemciye gönderildi: sonuç beklenir
    var isWaiting: Bool { pending != nil }

    func tapped() {
        pending?.cancel()
        let delay = timeout
        pending = Task { [weak self] in
            try? await Task.sleep(for: delay)
            guard !Task.isCancelled, let self else { return }
            self.pending = nil
            self.onTimeout?()
        }
    }

    /// İşlemciden sonuç geldi (renk ya da karanlık): bekleme biter
    func resolved() {
        pending?.cancel()
        pending = nil
    }

    /// Uyarı gösterilecek: ilk uyarıdan önceki ileti saklanır. Gösterilecek metni döndürür.
    func notice(_ text: String, current: String) -> String {
        if messageBefore == nil { messageBefore = current }
        return text
    }

    /// Başarılı öğretme: uyarı hâlâ ekrandaysa önceki ileti, araya başka ileti girdiyse o kalır
    func cleared(current: String) -> String {
        guard let before = messageBefore else { return current }
        messageBefore = nil
        return current == Self.darkMessage || current == Self.noFrameMessage ? before : current
    }

    /// Kalibrasyon kapandı
    func reset() {
        resolved()
        messageBefore = nil
    }
}
