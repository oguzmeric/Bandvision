"""Kayıt cihazı istemcileri (bantvision.live.recorders).

Ayrıştırıcı testleri apps/ios/BantSayacTests/RecorderTests.swift ile aynı girdi ve beklentileri kullanır.
Tümleşik testler tools/mock_nvr.py'yi (Hikvision/Dahua Digest + TRASSIR HTTPS) ayrı süreçte çalıştırır;
sertifika üretilemez ya da sahte cihaz açılamazsa atlanır.
"""
from __future__ import annotations

import http.server
import logging
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import ClassVar

import cv2
import numpy as np
import pytest

from bantvision.live import recorders as rec
from bantvision.live.recorders import (
    CameraBrand,
    RecorderBrand,
    RecorderChannel,
    RecorderError,
    camera_rtsp_url,
    clean_host,
    dahua_channels,
    flag,
    hikvision_channels,
    make_recorder,
    parse_trassir_json,
    trassir_channels,
    trassir_value,
    with_credentials,
)

ROOT = pathlib.Path(__file__).resolve().parents[3]
MOCK_NVR = ROOT / "tools" / "mock_nvr.py"
USER = "admin"
PASSWORD = "test123"


# MARK: - TRASSIR ayrıştırıcıları


def test_trassir_json_with_trailing_comment() -> None:
    body = '{\n    "success": 1,\n    "sid": "e03qD0eg"\n}\n/* Don\'t forget to logout */'
    assert trassir_value(parse_trassir_json(body.encode()), "sid") == "e03qD0eg"


def test_trassir_json_with_unclosed_comment() -> None:
    obj = parse_trassir_json('{"success":"1","token":"c4Z0qkuu"} /* yarım'.encode())
    assert trassir_value(obj, "token") == "c4Z0qkuu"


def test_trassir_error_is_explained() -> None:
    obj = parse_trassir_json(b'{"success":0,"error_code":"invalid password"}')
    with pytest.raises(RecorderError) as e:
        trassir_value(obj, "sid")
    assert e.value == RecorderError.unauthorized()
    assert e.value.kind == "unauthorized"

    other = parse_trassir_json(b'{"success":0,"error_code":"no such channel"}')
    with pytest.raises(RecorderError) as e:
        trassir_value(other, "token")
    assert e.value == RecorderError.trassir("no such channel")
    assert str(e.value) == "TRASSIR: no such channel"


def test_trassir_error_mapping() -> None:
    assert rec.trassir_error("SDK disabled").kind == "trassir"
    assert "SDK kapalı" in str(rec.trassir_error("SDK disabled"))
    assert rec.trassir_error("Login failed").kind == "unauthorized"
    assert trassir_value_error({"success": 0}) == RecorderError.trassir("bilinmeyen hata")
    assert trassir_value_error({"success": 1, "sid": ""}) == RecorderError.trassir("bilinmeyen hata")


def trassir_value_error(obj: dict[str, object]) -> RecorderError:
    with pytest.raises(RecorderError) as e:
        trassir_value(obj, "sid")  # type: ignore[arg-type]
    return e.value


def test_trassir_not_json() -> None:
    with pytest.raises(RecorderError) as e:
        parse_trassir_json(b"<html>")
    assert e.value.kind == "unexpected"
    with pytest.raises(RecorderError):
        parse_trassir_json(b"\xff\xfe")
    with pytest.raises(RecorderError):
        parse_trassir_json(b"[1, 2]")


def test_trassir_channels_skip_zombies_and_duplicates() -> None:
    body = """
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
    channels = trassir_channels(parse_trassir_json(body.encode()))
    assert [c.id for c in channels] == ["aBc123", "dEf456", "gHi789"]
    assert [c.name for c in channels] == ["Bant 1", "Kapı", "Depo"]
    assert [c.has_substream for c in channels] == [True, False, True]
    assert all(c.number is None for c in channels)


def test_trassir_channel_without_substream_field_defaults_true() -> None:
    channels = trassir_channels({"channels": [{"guid": "x"}]})
    assert channels == [RecorderChannel(id="x", name="", number=None, has_substream=True)]
    assert channels[0].title == "x"
    assert channels[0].subtitle is None


# MARK: - Dahua


def test_dahua_channel_titles() -> None:
    text = (
        "table.ChannelTitle[0].Name=Bant 1\r\n"
        "table.ChannelTitle[1].Name=Kapı = giriş\r\n"
        "table.ChannelTitle[3].Name=\r\n"
        "table.ChannelTitle[2].Name=Depo\n"
        "table.ChannelTitle[2].Other=yok sayılır\n"
        "table.Encode[0].Name=yok sayılır"
    )
    channels = dahua_channels(text)
    assert [c.number for c in channels] == [1, 2, 3, 4]
    assert [c.id for c in channels] == ["1", "2", "3", "4"]
    assert [c.name for c in channels] == ["Bant 1", "Kapı = giriş", "Depo", ""]
    assert channels[3].title == "Kanal 4"  # adı boş kanal
    assert channels[0].subtitle == "Kanal 1"


def test_dahua_garbage() -> None:
    assert dahua_channels("Error\r\nBad Request!\r\n") == []


# MARK: - Hikvision


def test_hikvision_input_proxy_channels() -> None:
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
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
    channels = hikvision_channels(xml)
    assert [c.number for c in channels] == [1, 2]
    assert [c.name for c in channels] == ["Bant 1", ""]
    assert channels[1].title == "Kanal 2"


def test_hikvision_analog_channels() -> None:
    xml = b"""<VideoInputChannelList><VideoInputChannel><id>3</id><inputPort>3</inputPort>
<name>Paketleme</name><videoFormat>PAL</videoFormat></VideoInputChannel></VideoInputChannelList>"""
    channels = hikvision_channels(xml)
    assert [c.number for c in channels] == [3]
    assert channels[0].name == "Paketleme"


def test_hikvision_only_direct_children_are_read() -> None:
    xml = """<InputProxyChannelList><InputProxyChannel>
<sourceInputPortDescriptor><id>9</id><name>iç</name></sourceInputPortDescriptor>
<id>4</id><name>Dış</name></InputProxyChannel>
<InputProxyChannel><id>0</id></InputProxyChannel></InputProxyChannelList>"""
    channels = hikvision_channels(xml.encode())
    assert [(c.id, c.name) for c in channels] == [("4", "Dış")]


def test_hikvision_not_xml() -> None:
    assert hikvision_channels(b"not xml") == []


# MARK: - Ortak


def test_flags() -> None:
    assert flag("1")
    assert flag(1)
    assert flag(True)
    assert flag("TRUE")
    assert not flag("0")
    assert not flag(None)
    assert not flag(0)


def test_query_encoding_keeps_password_intact() -> None:
    assert rec._encode("a+b&c=d e/ş") == "a%2Bb%26c%3Dd%20e%2F%C5%9F"


def test_stream_urls() -> None:
    ch = RecorderChannel(id="3", name="x", number=3, has_substream=True)
    with make_recorder(RecorderBrand.HIKVISION, "10.0.0.5", 80, 554, "u", "p") as hik:
        assert hik.stream_url(ch, substream=True) == "rtsp://10.0.0.5:554/Streaming/Channels/302"
        assert hik.stream_url(ch, substream=False) == "rtsp://10.0.0.5:554/Streaming/Channels/301"
    with make_recorder(RecorderBrand.DAHUA, "10.0.0.5", 80, 554, "u", "p") as dahua:
        assert dahua.stream_url(ch, substream=True) == "rtsp://10.0.0.5:554/cam/realmonitor?channel=3&subtype=1"
        with pytest.raises(RecorderError) as e:
            dahua.stream_url(RecorderChannel(id="g", name="", number=None, has_substream=True), substream=True)
        assert e.value.kind == "unexpected"


def test_recorder_brand_defaults() -> None:
    assert RecorderBrand.TRASSIR.default_http_port == 8080
    assert RecorderBrand.TRASSIR.default_rtsp_port == 555
    assert RecorderBrand.TRASSIR.uses_https
    assert RecorderBrand.TRASSIR.title == "TRASSIR"
    for brand in (RecorderBrand.HIKVISION, RecorderBrand.DAHUA):
        assert brand.default_http_port == 80
        assert brand.default_rtsp_port == 554
        assert not brand.uses_https
    assert RecorderBrand("dahua") is RecorderBrand.DAHUA


def test_error_messages_are_turkish_and_typed() -> None:
    assert str(RecorderError.unauthorized()) == "Kullanıcı adı ya da şifre hatalı."
    assert str(RecorderError.unreachable("x yanıt vermedi")) == "Kayıt cihazına bağlanılamadı (x yanıt vermedi)."
    assert str(RecorderError.http(403)) == "Kayıt cihazı isteği reddetti (HTTP 403)."
    assert str(RecorderError.unexpected("JSON değil")) == "Kayıt cihazının yanıtı anlaşılamadı (JSON değil)."
    assert str(RecorderError.no_channels()) == "Kayıt cihazında kamera bulunamadı."
    assert RecorderError.http(403).status == 403
    assert RecorderError.http(403) != RecorderError.http(404)


# MARK: - Doğrudan kamera adresleri (NetworkCamera.swift)


def test_clean_host() -> None:
    assert clean_host(" https://192.168.1.10:8080/ ") == "192.168.1.10"
    assert clean_host("http://admin:pa@ss@192.168.1.64/doc") == "192.168.1.64"
    assert clean_host("nvr.local") == "nvr.local"
    assert clean_host("  ") == ""


def test_camera_rtsp_urls() -> None:
    # Derleme 12 kaydı: Dahua kanal 2 ana akış
    assert camera_rtsp_url(CameraBrand.DAHUA, "192.168.1.108", 554, 2, False) == \
        "rtsp://192.168.1.108:554/cam/realmonitor?channel=2&subtype=0"
    assert camera_rtsp_url(CameraBrand.HIKVISION, "rtsp://u:p@10.0.0.2:554/x", 554, 1, True) == \
        "rtsp://10.0.0.2:554/Streaming/Channels/102"
    assert camera_rtsp_url(CameraBrand.AXIS, "10.0.0.3", 554, 1, True) == \
        "rtsp://10.0.0.3:554/axis-media/media.amp?resolution=640x360&fps=25"
    assert camera_rtsp_url(CameraBrand.AXIS, "10.0.0.3", 554, 1, False) == "rtsp://10.0.0.3:554/axis-media/media.amp"
    assert camera_rtsp_url(CameraBrand.VIVOTEK, "10.0.0.4", 554, 1, False) == "rtsp://10.0.0.4:554/live1s1.sdp"
    assert camera_rtsp_url(CameraBrand.MILESIGHT, "10.0.0.5", 8554, 1, True) == "rtsp://10.0.0.5:8554/sub"
    assert camera_rtsp_url(CameraBrand.HIKVISION, "", 554, 1, True) is None
    assert camera_rtsp_url(CameraBrand.HIKVISION, "10.0.0.2", 0, 1, True) is None
    assert camera_rtsp_url(CameraBrand.HIKVISION, "10.0 .0.2", 554, 1, True) is None
    assert camera_rtsp_url(CameraBrand.CUSTOM, "", 554, 1, True, " rtsp://cam.local:8554/live ") == \
        "rtsp://cam.local:8554/live"
    assert camera_rtsp_url(CameraBrand.CUSTOM, "", 554, 1, True, "http://cam.local/live") is None
    assert camera_rtsp_url(CameraBrand.CUSTOM, "", 554, 1, True, "rtsp://") is None
    assert CameraBrand.CUSTOM.title == "Diğer (tam RTSP adresi)"


def test_with_credentials() -> None:
    url = "rtsp://10.0.0.5:554/cam/realmonitor?channel=3&subtype=1"
    assert with_credentials(url, "admin", "p@ss:w/rd") == \
        "rtsp://admin:p%40ss%3Aw%2Frd@10.0.0.5:554/cam/realmonitor?channel=3&subtype=1"
    assert with_credentials("rtsp://old:x@h:554/a", "yeni", "") == "rtsp://yeni@h:554/a"
    assert with_credentials(url, "", "") == url


def test_make_recorder_rejects_bad_host() -> None:
    with pytest.raises(RecorderError) as e:
        make_recorder(RecorderBrand.HIKVISION, "  ", 80, 554, "u", "p")
    assert e.value.kind == "unexpected"


def test_httpx_log_hides_query() -> None:
    import httpx

    record = logging.LogRecord("httpx", logging.INFO, __file__, 1, "HTTP Request: %s %s", (
        "GET", httpx.URL("https://10.0.0.1:8080/login?username=admin&password=gizli")), None)
    rec._RedactQueryFilter().filter(record)
    assert "gizli" not in record.getMessage()
    assert "/login" in record.getMessage()


# MARK: - Tümleşik: tools/mock_nvr.py


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_port(port: int, proc: subprocess.Popen[bytes], timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _jpeg() -> bytes:
    img = np.zeros((48, 64, 3), np.uint8)
    img[:, 32:] = (0, 128, 255)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


class _TrassirVideoHandler(http.server.BaseHTTPRequestHandler):
    """TRASSIR görüntü portu (555) yerine: `jpg…` jetonuna JPEG verir, `tok…?ping` isteklerini kaydeder."""

    jpeg: ClassVar[bytes] = b""
    pings: ClassVar[list[str]] = []

    def log_message(self, fmt: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        path, _, query = self.path.partition("?")
        if path.startswith("/jpg"):
            body, ctype = self.jpeg, "image/jpeg"
        elif path.startswith("/tok") and query == "ping":
            _TrassirVideoHandler.pings.append(path)
            body, ctype = b"", "text/plain"
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@dataclass
class MockNVR:
    http_port: int
    https_port: int
    video_port: int
    jpeg: bytes


@pytest.fixture(scope="module")
def mock_nvr(tmp_path_factory: pytest.TempPathFactory) -> Iterator[MockNVR]:
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl bulunamadı: sahte TRASSIR için kendinden imzalı sertifika üretilemiyor")
    work = tmp_path_factory.mktemp("mock_nvr")
    cert, key, snap = work / "nvr.crt", work / "nvr.key", work / "nvr.jpg"
    try:
        subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
                        "-out", str(cert), "-days", "2", "-subj", "/CN=127.0.0.1"],
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"sertifika üretilemedi: {exc}")
    jpeg = _jpeg()
    snap.write_bytes(jpeg)

    http_port, https_port = _free_port(), _free_port()
    log = (work / "mock_nvr.log").open("wb")
    proc = subprocess.Popen([sys.executable, "-u", str(MOCK_NVR), "--http-port", str(http_port),
                             "--https-port", str(https_port), "--cert", str(cert), "--key", str(key),
                             "--snapshot", str(snap)], stdin=subprocess.DEVNULL, stdout=log,
                            stderr=subprocess.STDOUT, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    _TrassirVideoHandler.jpeg = jpeg
    video = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _TrassirVideoHandler)
    threading.Thread(target=video.serve_forever, daemon=True).start()
    try:
        if not (_wait_port(http_port, proc) and _wait_port(https_port, proc)):
            log.flush()
            tail = (work / "mock_nvr.log").read_text(encoding="utf-8", errors="replace")[-600:]
            pytest.skip(f"sahte kayıt cihazı açılmadı: {tail}")
        yield MockNVR(http_port, https_port, int(video.server_address[1]), jpeg)
    finally:
        video.shutdown()
        video.server_close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


RTSP_PORT = 8554


def test_hikvision_against_mock(mock_nvr: MockNVR) -> None:
    with make_recorder(RecorderBrand.HIKVISION, "127.0.0.1", mock_nvr.http_port, RTSP_PORT, USER, PASSWORD) as c:
        channels = c.channels()
        assert [(ch.id, ch.name, ch.number) for ch in channels] == [("1", "Bant 1", 1), ("2", "", 2)]
        assert [ch.title for ch in channels] == ["Bant 1", "Kanal 2"]
        assert c.snapshot(channels[0]) == mock_nvr.jpeg
        with pytest.raises(RecorderError) as e:
            c.snapshot(channels[1])  # sahte cihazda yok → 404
        assert (e.value.kind, e.value.status) == ("http", 404)
        assert c.stream_url(channels[0], substream=True) == f"rtsp://127.0.0.1:{RTSP_PORT}/Streaming/Channels/102"
        c.keep_alive(c.stream_url(channels[0], substream=True))  # Hikvision: işlem yok


def test_dahua_against_mock(mock_nvr: MockNVR) -> None:
    with make_recorder(RecorderBrand.DAHUA, "http://127.0.0.1/", mock_nvr.http_port, RTSP_PORT,
                       USER, PASSWORD) as c:
        channels = c.channels()
        assert [ch.name for ch in channels] == ["Bant 1", "Kapı", "Depo", ""]
        assert [ch.number for ch in channels] == [1, 2, 3, 4]
        assert c.snapshot(channels[0])[:2] == b"\xff\xd8"
        assert c.stream_url(channels[2], substream=False) == \
            f"rtsp://127.0.0.1:{RTSP_PORT}/cam/realmonitor?channel=3&subtype=0"


@pytest.mark.parametrize("brand", [RecorderBrand.HIKVISION, RecorderBrand.DAHUA, RecorderBrand.TRASSIR])
def test_wrong_password_is_unauthorized(mock_nvr: MockNVR, brand: RecorderBrand) -> None:
    port = mock_nvr.https_port if brand is RecorderBrand.TRASSIR else mock_nvr.http_port
    with (make_recorder(brand, "127.0.0.1", port, mock_nvr.video_port, USER, "yanlis+&=") as c,
          pytest.raises(RecorderError) as e):
        c.channels()
    assert e.value.kind == "unauthorized"
    assert "yanlis" not in str(e.value)


def test_trassir_against_mock(mock_nvr: MockNVR) -> None:
    _TrassirVideoHandler.pings.clear()
    with make_recorder(RecorderBrand.TRASSIR, "127.0.0.1", mock_nvr.https_port, mock_nvr.video_port,
                       USER, PASSWORD) as c:
        channels = c.channels()
        assert [(ch.id, ch.name, ch.has_substream) for ch in channels] == [("bant1", "Bant 1", True),
                                                                           ("kapi", "Kapı", False)]
        bant, kapi = channels
        url = c.stream_url(bant, substream=True)
        assert url == f"rtsp://127.0.0.1:{mock_nvr.video_port}/tokbant1sub"
        assert c.stream_url(kapi, substream=True) == f"rtsp://127.0.0.1:{mock_nvr.video_port}/tokkapimain"
        assert c.stream_url(bant, substream=False) == f"rtsp://127.0.0.1:{mock_nvr.video_port}/tokbant1main"
        assert c.snapshot(bant) == mock_nvr.jpeg
        c.keep_alive(url)
        assert _TrassirVideoHandler.pings == ["/tokbant1sub"]

        # Oturum düşmüş: bir kez yeniden giriş yapılıp istek tekrarlanır
        assert isinstance(c, rec.TrassirClient)
        c._sid = "eski"
        assert [ch.id for ch in c.channels()] == ["bant1", "kapi"]
        assert c._sid == "S3ssi0n"

        with pytest.raises(RecorderError) as e:
            c.stream_url(RecorderChannel(id="yok", name="", number=None, has_substream=True), substream=True)
        assert e.value == RecorderError.trassir("bad channel or stream")


def test_unreachable_device() -> None:
    port = _free_port()  # dinleyen yok
    with (make_recorder(RecorderBrand.DAHUA, "127.0.0.1", port, 554, USER, PASSWORD) as c,
          pytest.raises(RecorderError) as e):
        c.channels()
    assert e.value.kind == "unreachable"
    assert PASSWORD not in str(e.value)
