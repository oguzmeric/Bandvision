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
            let base = url.deletingPathExtension().lastPathComponent
            let target = url.deletingLastPathComponent()
                .appendingPathComponent("\(base).corrupt-\(Int(Date().timeIntervalSince1970)).json")
            do {
                try FileManager.default.moveItem(at: url, to: target)
                return .corrupt(movedTo: target.lastPathComponent)
            } catch {
                return .corrupt(movedTo: nil)
            }
        }
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
