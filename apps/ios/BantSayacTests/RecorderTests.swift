import XCTest
@testable import BantSayac

/// Kayıt cihazı yanıt ayrıştırıcıları ve ayarların geriye uyumu (ağdan bağımsız).
final class RecorderParserTests: XCTestCase {

    // MARK: TRASSIR

    func testTrassirJSONWithTrailingComment() throws {
        let body = """
        {
            "success": 1,
            "sid": "e03qD0eg"
        }
        /* Don't forget to logout */
        """
        let json = try RecorderParsers.trassirJSON(Data(body.utf8))
        XCTAssertEqual(try RecorderParsers.trassirValue(json, key: "sid"), "e03qD0eg")
    }

    func testTrassirJSONWithUnclosedComment() throws {
        let json = try RecorderParsers.trassirJSON(Data(#"{"success":"1","token":"c4Z0qkuu"} /* yarım"#.utf8))
        XCTAssertEqual(try RecorderParsers.trassirValue(json, key: "token"), "c4Z0qkuu")
    }

    func testTrassirErrorIsExplained() throws {
        let json = try RecorderParsers.trassirJSON(Data(#"{"success":0,"error_code":"invalid password"}"#.utf8))
        XCTAssertThrowsError(try RecorderParsers.trassirValue(json, key: "sid")) { error in
            XCTAssertEqual(error as? RecorderError, .unauthorized)
        }
        let other = try RecorderParsers.trassirJSON(Data(#"{"success":0,"error_code":"no such channel"}"#.utf8))
        XCTAssertThrowsError(try RecorderParsers.trassirValue(other, key: "token")) { error in
            XCTAssertEqual(error as? RecorderError, .trassir("no such channel"))
        }
    }

    func testTrassirNotJSON() {
        XCTAssertThrowsError(try RecorderParsers.trassirJSON(Data("<html>".utf8)))
    }

    func testTrassirChannelsSkipZombiesAndDuplicates() throws {
        let body = """
        {
          "channels": [
            {"guid": "aBc123", "name": "Bant 1", "rights": "1", "codec": "h264",
             "have_mainstream": "1", "have_substream": "1"},
            {"guid": "dEf456", "name": "Kapı", "have_mainstream": "1", "have_substream": "0"},
            {"guid": "aBc123", "name": "Bant 1 (kopya)"}
          ],
          "remote_channels": [
            {"guid": "gHi789", "name": "Depo", "server_name": "Şube", "server_guid": "srv", "have_substream": 1}
          ],
          "zombies": [ {"guid": "zzz", "name": "Kayıp kamera"} ],
          "templates": []
        }
        /* comment */
        """
        let list = RecorderParsers.trassirChannels(try RecorderParsers.trassirJSON(Data(body.utf8)))
        XCTAssertEqual(list.map(\.id), ["aBc123", "dEf456", "gHi789"])
        XCTAssertEqual(list.map(\.name), ["Bant 1", "Kapı", "Depo"])
        XCTAssertEqual(list.map(\.hasSubstream), [true, false, true])
        XCTAssertTrue(list.allSatisfy { $0.number == nil })
    }

    // MARK: Dahua

    func testDahuaChannelTitles() {
        let text = """
        table.ChannelTitle[0].Name=Bant 1\r
        table.ChannelTitle[1].Name=Kapı = giriş\r
        table.ChannelTitle[3].Name=\r
        table.ChannelTitle[2].Name=Depo
        table.ChannelTitle[2].Other=yok sayılır
        table.Encode[0].Name=yok sayılır
        """
        let list = RecorderParsers.dahuaChannels(text)
        XCTAssertEqual(list.map(\.number), [1, 2, 3, 4])
        XCTAssertEqual(list.map(\.id), ["1", "2", "3", "4"])
        XCTAssertEqual(list.map(\.name), ["Bant 1", "Kapı = giriş", "Depo", ""])
        XCTAssertEqual(list[3].title, "Kanal 4")              // adı boş kanal
    }

    func testDahuaGarbage() {
        XCTAssertTrue(RecorderParsers.dahuaChannels("Error\r\nBad Request!\r\n").isEmpty)
    }

    // MARK: Hikvision

    func testHikvisionInputProxyChannels() {
        let xml = """
        <?xml version="1.0" encoding="UTF-8"?>
        <InputProxyChannelList version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
          <InputProxyChannel version="2.0">
            <id>1</id>
            <name>Bant 1</name>
            <sourceInputPortDescriptor>
              <proxyProtocol>HIKVISION</proxyProtocol>
              <ipAddress>192.168.1.64</ipAddress>
              <srcInputPort>1</srcInputPort>
              <userName>admin</userName>
            </sourceInputPortDescriptor>
          </InputProxyChannel>
          <InputProxyChannel version="2.0">
            <id>2</id>
            <name></name>
          </InputProxyChannel>
        </InputProxyChannelList>
        """
        let list = RecorderParsers.hikvisionChannels(Data(xml.utf8))
        XCTAssertEqual(list.map(\.number), [1, 2])
        XCTAssertEqual(list.map(\.name), ["Bant 1", ""])
        XCTAssertEqual(list[1].title, "Kanal 2")
    }

    func testHikvisionAnalogChannels() {
        let xml = """
        <VideoInputChannelList><VideoInputChannel><id>3</id><inputPort>3</inputPort>
        <name>Paketleme</name><videoFormat>PAL</videoFormat></VideoInputChannel></VideoInputChannelList>
        """
        let list = RecorderParsers.hikvisionChannels(Data(xml.utf8))
        XCTAssertEqual(list.map(\.number), [3])
        XCTAssertEqual(list.first?.name, "Paketleme")
    }

    func testHikvisionNotXML() {
        XCTAssertTrue(RecorderParsers.hikvisionChannels(Data("not xml".utf8)).isEmpty)
    }

    // MARK: Ortak

    func testFlags() {
        XCTAssertTrue(RecorderParsers.flag("1"))
        XCTAssertTrue(RecorderParsers.flag(1))
        XCTAssertTrue(RecorderParsers.flag(true))
        XCTAssertFalse(RecorderParsers.flag("0"))
        XCTAssertFalse(RecorderParsers.flag(nil))
    }

    func testQueryEncodingKeepsPasswordIntact() {
        XCTAssertEqual(DeviceHTTPClient.encode("a+b&c=d e/ş"), "a%2Bb%26c%3Dd%20e%2F%C5%9F")
    }

    func testStreamURLs() async throws {
        let http = DeviceHTTPClient(host: "10.0.0.5", port: 80, https: false, username: "u", password: "p")
        let ch = RecorderChannel(id: "3", name: "x", number: 3, hasSubstream: true)
        let hik = HikvisionClient(http: http, host: "10.0.0.5", rtspPort: 554)
        let sub = try await hik.streamURL(ch, substream: true).absoluteString
        let main = try await hik.streamURL(ch, substream: false).absoluteString
        XCTAssertEqual(sub, "rtsp://10.0.0.5:554/Streaming/Channels/302")
        XCTAssertEqual(main, "rtsp://10.0.0.5:554/Streaming/Channels/301")
        let dahua = DahuaClient(http: http, host: "10.0.0.5", rtspPort: 554)
        let dsub = try await dahua.streamURL(ch, substream: true).absoluteString
        XCTAssertEqual(dsub, "rtsp://10.0.0.5:554/cam/realmonitor?channel=3&subtype=1")
    }
}

final class NetworkCameraConfigTests: XCTestCase {
    /// Derleme 12'nin kaydettiği ayar (yeni alanlar yok) okunabilmeli: kullanıcının kamerası kaybolmasın.
    func testDecodesBuild12Config() throws {
        let old = #"{"brand":"dahua","host":"192.168.1.108","port":554,"channel":2,"substream":false,"username":"admin","customURL":""}"#
        let c = try JSONDecoder().decode(NetworkCameraConfig.self, from: Data(old.utf8))
        XCTAssertEqual(c.kind, .camera)
        XCTAssertEqual(c.brand, .dahua)
        XCTAssertEqual(c.host, "192.168.1.108")
        XCTAssertEqual(c.channel, 2)
        XCTAssertFalse(c.substream)
        XCTAssertEqual(c.recorderBrand, .trassir)
        XCTAssertNil(c.recorderChannel)
        XCTAssertEqual(c.rtspURL?.absoluteString, "rtsp://192.168.1.108:554/cam/realmonitor?channel=2&subtype=0")
    }

    func testRecorderRoundTripAndDefaults() throws {
        var c = NetworkCameraConfig()
        c.kind = .recorder
        c.recorderBrand = .trassir
        c.recorderHost = " https://192.168.1.10:8080/ "
        c.recorderChannel = RecorderChannel(id: "aBc123", name: "Bant 1", number: nil, hasSubstream: true)
        XCTAssertEqual(c.cleanRecorderHost, "192.168.1.10")
        XCTAssertEqual(c.effectiveHTTPPort, 8080)
        XCTAssertEqual(c.effectiveRTSPPort, 555)
        XCTAssertTrue(c.isComplete)
        XCTAssertEqual(c.summary, "TRASSIR · 192.168.1.10 · Bant 1")

        let back = try JSONDecoder().decode(NetworkCameraConfig.self, from: JSONEncoder().encode(c))
        XCTAssertEqual(back, c)

        c.recorderBrand = .hikvision
        c.recorderRTSPPort = 8554
        XCTAssertEqual(c.effectiveHTTPPort, 80)
        XCTAssertEqual(c.effectiveRTSPPort, 8554)
        c.recorderChannel = nil
        XCTAssertFalse(c.isComplete)
        XCTAssertEqual(c.summary, "Ayarlanmadı")
    }
}
