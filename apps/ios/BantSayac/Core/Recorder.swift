import Foundation

/// Ağ görüntü kaynağının türü: doğrudan IP kamera ya da kameraların bağlı olduğu kayıt cihazı (NVR/XVR).
enum NetworkDeviceKind: String, Codable, CaseIterable, Identifiable {
    case camera
    case recorder

    var id: String { rawValue }
    var title: String { self == .camera ? "Kamera" : "Kayıt cihazı" }
}

/// Desteklenen kayıt cihazları (docs/10-field-setup.md §3c, docs/08-trassir-integration.md).
enum RecorderBrand: String, Codable, CaseIterable, Identifiable {
    case trassir, hikvision, dahua

    var id: String { rawValue }

    var title: String {
        switch self {
        case .trassir: return "TRASSIR"
        case .hikvision: return "Hikvision"
        case .dahua: return "Dahua"
        }
    }

    /// Kanal listesi ve küçük resim için HTTP(S) portu. TRASSIR: SDK web sunucusu (Ayarlar → Web sunucusu).
    var defaultHTTPPort: Int { self == .trassir ? 8080 : 80 }
    /// Görüntü portu. TRASSIR jetonlu akışı 555'ten verir.
    var defaultRTSPPort: Int { self == .trassir ? 555 : 554 }
    /// TRASSIR SDK yalnızca HTTPS (kendinden imzalı sertifika) konuşur.
    var usesHTTPS: Bool { self == .trassir }
}

/// Kayıt cihazındaki bir kamera. `id`: TRASSIR'da kanal GUID'i, Hikvision/Dahua'da kanal numarası.
struct RecorderChannel: Identifiable, Hashable, Codable, Sendable {
    let id: String
    let name: String
    /// Ekranda gösterilecek kanal numarası (TRASSIR'da yok)
    let number: Int?
    let hasSubstream: Bool

    var title: String {
        if let number { return name.isEmpty ? "Kanal \(number)" : name }
        return name.isEmpty ? id : name
    }

    var subtitle: String? { number.map { "Kanal \($0)" } }
}

enum RecorderError: LocalizedError, Equatable {
    case unauthorized
    case unreachable(String)
    case http(Int)
    case unexpected(String)
    case trassir(String)
    case noChannels

    var errorDescription: String? {
        switch self {
        case .unauthorized: return "Kullanıcı adı ya da şifre hatalı."
        case .unreachable(let why): return "Kayıt cihazına bağlanılamadı (\(why))."
        case .http(let code): return "Kayıt cihazı isteği reddetti (HTTP \(code))."
        case .unexpected(let why): return "Kayıt cihazının yanıtı anlaşılamadı (\(why))."
        case .trassir(let why): return "TRASSIR: \(why)"
        case .noChannels: return "Kayıt cihazında kamera bulunamadı."
        }
    }
}

// MARK: - Yanıt ayrıştırıcıları (ağdan bağımsız; BantSayacTests ile sınanır)

enum RecorderParsers {
    /// TRASSIR SDK yanıtları JSON'dur ama sonuna `/* … */` açıklaması ekleyebilir; JSONSerialization bunu kabul etmez.
    static func trassirJSON(_ data: Data) throws -> [String: Any] {
        guard var text = String(data: data, encoding: .utf8) else { throw RecorderError.unexpected("UTF-8 değil") }
        while let open = text.range(of: "/*") {
            guard let close = text.range(of: "*/", range: open.upperBound..<text.endIndex) else {
                text.removeSubrange(open.lowerBound..<text.endIndex)
                break
            }
            text.removeSubrange(open.lowerBound..<close.upperBound)
        }
        guard let json = try? JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any] else {
            throw RecorderError.unexpected("JSON değil")
        }
        return json
    }

    /// `/login` ve `/get_video` yanıtı: {"success":1,"sid"|"token":"…"} ya da {"success":0,"error_code":"…"}
    static func trassirValue(_ json: [String: Any], key: String) throws -> String {
        if flag(json["success"]), let value = json[key] as? String, !value.isEmpty { return value }
        let code = (json["error_code"] as? String) ?? (json["error"] as? String) ?? "bilinmeyen hata"
        throw trassirError(code)
    }

    /// TRASSIR hata kodlarını kullanıcının anlayacağı dile çevirir.
    static func trassirError(_ code: String) -> RecorderError {
        let c = code.lowercased()
        if c.contains("password") || c.contains("user") || c.contains("auth") || c.contains("login") {
            return .unauthorized
        }
        if c.contains("sdk") || c.contains("disabled") {
            return .trassir("SDK kapalı. TRASSIR'da Ayarlar → Web sunucusu (SDK) bölümünden açın.")
        }
        return .trassir(code)
    }

    /// `/channels`: yerel ve uzak kanallar; kayıp kanallar (zombies) listelenmez.
    static func trassirChannels(_ json: [String: Any]) -> [RecorderChannel] {
        var out: [RecorderChannel] = []
        var seen = Set<String>()
        for key in ["channels", "remote_channels"] {
            for item in (json[key] as? [[String: Any]]) ?? [] {
                guard let guid = item["guid"] as? String, !guid.isEmpty, seen.insert(guid).inserted else { continue }
                // Alan yoksa alt akış var sayılır; yoksa ana akışa düşülür
                let sub = item["have_substream"].map { flag($0) } ?? true
                out.append(RecorderChannel(id: guid, name: (item["name"] as? String) ?? "", number: nil, hasSubstream: sub))
            }
        }
        return out
    }

    /// Dahua `configManager.cgi?action=getConfig&name=ChannelTitle`:
    /// `table.ChannelTitle[0].Name=Bant 1` satırları (dizin 0'dan, kanal numarası 1'den).
    static func dahuaChannels(_ text: String) -> [RecorderChannel] {
        var names: [Int: String] = [:]
        for raw in text.split(whereSeparator: \.isNewline) {
            let line = raw.trimmingCharacters(in: .whitespaces)
            guard line.hasPrefix("table.ChannelTitle["), let close = line.firstIndex(of: "]"),
                  let eq = line.firstIndex(of: "="), close < eq else { continue }
            let indexText = line[line.index(line.startIndex, offsetBy: "table.ChannelTitle[".count)..<close]
            guard let index = Int(indexText), index >= 0,
                  line[line.index(after: close)..<eq] == ".Name" else { continue }
            names[index] = String(line[line.index(after: eq)...]).trimmingCharacters(in: .whitespaces)
        }
        return names.keys.sorted().map {
            RecorderChannel(id: String($0 + 1), name: names[$0] ?? "", number: $0 + 1, hasSubstream: true)
        }
    }

    /// Hikvision ISAPI: `InputProxyChannelList` (IP kanalları) ya da `VideoInputChannelList` (analog kanallar).
    /// Yalnızca kanal öğesinin doğrudan altındaki `<id>` ve `<name>` okunur (iç içe kaynak tanımları atlanır).
    static func hikvisionChannels(_ data: Data) -> [RecorderChannel] {
        let parser = XMLParser(data: data)
        let delegate = HikvisionChannelParser()
        parser.delegate = delegate
        parser.shouldProcessNamespaces = true
        guard parser.parse() else { return [] }
        return delegate.channels
    }

    /// "1", 1, true → true
    static func flag(_ value: Any?) -> Bool {
        switch value {
        case let b as Bool: return b
        case let n as NSNumber: return n.intValue != 0
        case let s as String: return s == "1" || s.lowercased() == "true"
        default: return false
        }
    }
}

private final class HikvisionChannelParser: NSObject, XMLParserDelegate {
    private static let channelElements: Set<String> = ["InputProxyChannel", "VideoInputChannel"]
    private(set) var channels: [RecorderChannel] = []
    private var depth = 0
    private var channelDepth: Int?
    private var field: String?
    private var text = ""
    private var id: String?
    private var name: String?

    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?,
                qualifiedName qName: String?, attributes attributeDict: [String: String] = [:]) {
        depth += 1
        if channelDepth == nil, Self.channelElements.contains(elementName) {
            channelDepth = depth
            id = nil
            name = nil
        } else if let cd = channelDepth, depth == cd + 1, elementName == "id" || elementName == "name" {
            field = elementName
            text = ""
        }
    }

    func parser(_ parser: XMLParser, foundCharacters string: String) {
        if field != nil { text += string }
    }

    func parser(_ parser: XMLParser, didEndElement elementName: String, namespaceURI: String?,
                qualifiedName qName: String?) {
        defer { depth -= 1 }
        if let f = field, elementName == f {
            let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
            if f == "id" { id = value } else { name = value }
            field = nil
        } else if let cd = channelDepth, depth == cd {
            if let id, let n = Int(id), n > 0 {
                channels.append(RecorderChannel(id: id, name: name ?? "", number: n, hasSubstream: true))
            }
            channelDepth = nil
        }
    }
}
