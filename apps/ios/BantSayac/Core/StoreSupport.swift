import Foundation

/// Uygulamanın kendi veri klasörü: Application Support/BantSayac (kullanıcı dosyalarında görünmez).
enum AppFiles {
    static var directory: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("BantSayac", isDirectory: true)
    }
}

/// Atomik yazılan JSON dosyası. Okunamayan (bozuk) dosya kenara alınır; üzerine yazılıp veri sessizce kaybolmaz.
struct JSONFile: Sendable {
    let url: URL

    enum LoadResult<T> {
        case missing
        case loaded(T)
        /// Bozuk dosya kenara alındı (yeni adı); nil: kenara alınamadı, dosyaya yazılmamalı
        case corrupt(movedTo: String?)
    }

    func load<T: Decodable>(_ type: T.Type) -> LoadResult<T> {
        guard FileManager.default.fileExists(atPath: url.path) else { return .missing }
        do {
            return .loaded(try JSONDecoder().decode(T.self, from: Data(contentsOf: url)))
        } catch {
            let target = sideURL()
            do {
                try FileManager.default.moveItem(at: url, to: target)
                return .corrupt(movedTo: target.lastPathComponent)
            } catch {
                return .corrupt(movedTo: nil)
            }
        }
    }

    /// Dosyanın kopyasını yanına `<ad>.corrupt-<unix saniye>.json` olarak alır; özgün dosya yerinde kalır.
    /// Kısmen okunabilen dosyada (bazı kayıtlar geçersiz) kayıtlar üzerine yazılmadan önce çağrılır.
    /// Dönen değer kopyanın dosya adı; kopya alınamadıysa nil (dosyaya yazılmamalı).
    func backupCopy() -> String? {
        let target = sideURL()
        do {
            try FileManager.default.copyItem(at: url, to: target)
            return target.lastPathComponent
        } catch {
            return nil
        }
    }

    /// Kenara alınan dosyanın adı; aynı saniyede ikinci kez alınırsa "-2", "-3" … eklenir (var olan kopyanın üzerine yazılmaz).
    private func sideURL() -> URL {
        let base = url.deletingPathExtension().lastPathComponent
        let stamp = Int(Date().timeIntervalSince1970)
        let dir = url.deletingLastPathComponent()
        var target = dir.appendingPathComponent("\(base).corrupt-\(stamp).json")
        var n = 2
        while FileManager.default.fileExists(atPath: target.path) {
            target = dir.appendingPathComponent("\(base).corrupt-\(stamp)-\(n).json")
            n += 1
        }
        return target
    }

    func save<T: Encodable>(_ value: T) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        try encoder.encode(value).write(to: url, options: .atomic)
    }
}

/// Benzersiz ad: `base` (en çok `limit` karakter) başka kayıtta varsa " (2)", " (3)" … eklenir; toplam `limit`i aşmaz.
enum UniqueName {
    static func make(_ base: String, limit: Int, taken: Set<String>) -> String {
        let trimmed = String(base.prefix(limit))
        guard taken.contains(trimmed) else { return trimmed }
        var n = 2
        while true {
            let suffix = " (\(n))"
            let candidate = String(trimmed.prefix(max(0, limit - suffix.count))) + suffix
            if !taken.contains(candidate) { return candidate }
            n += 1
        }
    }
}
