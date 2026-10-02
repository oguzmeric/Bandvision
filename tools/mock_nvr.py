"""CI için sahte kayıt cihazları (iOS UI testi, .github/workflows/ios-uitest.yml).

- Hikvision ISAPI + Dahua CGI: tek HTTP sunucusu, HTTP Digest (MD5, qop=auth) kimlik doğrulama.
- TRASSIR SDK: HTTPS (kendinden imzalı sertifika), /login → sid, /channels, /get_video → jeton.
  Yanıtların sonuna gerçek SDK'daki gibi /* … */ açıklaması eklenir.
Görüntü akışlarını MediaMTX verir (Hikvision/Dahua yolları ana sunucuda, TRASSIR jetonları 555'teki ikinci sunucuda).

Yalnızca standart kütüphane. Kullanım:
  python tools/mock_nvr.py --http-port 8081 --https-port 8080 --cert cert.pem --key key.pem --snapshot kare.jpg
"""
from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import re
import secrets
import socketserver
import ssl
import sys
import threading
import urllib.parse
from typing import ClassVar

USER = "admin"
PASSWORD = "test123"
REALM = "mock-nvr"
SID = "S3ssi0n"

TRASSIR_CHANNELS = {
    "channels": [
        {"guid": "bant1", "name": "Bant 1", "rights": "1", "codec": "h264",
         "have_mainstream": "1", "have_substream": "1"},
        {"guid": "kapi", "name": "Kapı", "rights": "1", "codec": "h264",
         "have_mainstream": "1", "have_substream": "0"},
    ],
    "remote_channels": [],
    "zombies": [{"guid": "kayip", "name": "Kayıp kamera"}],
    "templates": [],
}

HIKVISION_PROXY = """<?xml version="1.0" encoding="UTF-8"?>
<InputProxyChannelList version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
<InputProxyChannel version="2.0"><id>1</id><name>Bant 1</name>
<sourceInputPortDescriptor><proxyProtocol>HIKVISION</proxyProtocol><ipAddress>10.0.0.64</ipAddress>
<srcInputPort>1</srcInputPort></sourceInputPortDescriptor></InputProxyChannel>
<InputProxyChannel version="2.0"><id>2</id><name></name></InputProxyChannel>
</InputProxyChannelList>
"""

DAHUA_TITLES = (
    "table.ChannelTitle[0].Name=Bant 1\r\n"
    "table.ChannelTitle[1].Name=Kapı\r\n"
    "table.ChannelTitle[2].Name=Depo\r\n"
    "table.ChannelTitle[3].Name=\r\n"
)


def md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()   # Digest MD5 (RFC 2617), yalnızca test sunucusu


class Base(http.server.BaseHTTPRequestHandler):
    snapshot: bytes = b""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        status = args[1] if len(args) > 1 else ""
        sys.stdout.write(f"[{self.server.server_port}] {self.command} {self.path.split('?')[0]} → {status}\n")
        sys.stdout.flush()

    def send(self, code: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


class DigestHandler(Base):
    """Hikvision + Dahua. Kimlik doğrulama gerçek cihazlar gibi Digest."""
    nonces: ClassVar[set[str]] = set()

    def authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Digest "):
            return False
        p = {m[0]: m[2] or m[3] for m in re.findall(r'(\w+)=("([^"]*)"|([^,\s]*))', header[7:])}
        if p.get("username") != USER or p.get("nonce") not in self.nonces:
            return False
        ha1 = md5(f"{USER}:{REALM}:{PASSWORD}")
        ha2 = md5(f"{self.command}:{p.get('uri', '')}")
        if p.get("qop"):
            expected = md5(f"{ha1}:{p['nonce']}:{p.get('nc', '')}:{p.get('cnonce', '')}:{p['qop']}:{ha2}")
        else:
            expected = md5(f"{ha1}:{p['nonce']}:{ha2}")
        return secrets.compare_digest(expected, p.get("response", ""))

    def challenge(self) -> None:
        nonce = secrets.token_hex(16)
        self.nonces.add(nonce)
        self.send(401, b"Unauthorized", "text/plain",
                  {"WWW-Authenticate": f'Digest realm="{REALM}", qop="auth", nonce="{nonce}", algorithm=MD5'})

    def do_GET(self) -> None:
        if not self.authorized():
            self.challenge()
            return
        url = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        if url.path == "/ISAPI/ContentMgmt/InputProxy/channels":
            self.send(200, HIKVISION_PROXY.encode(), "application/xml")
        elif url.path == "/ISAPI/Streaming/channels/101/picture":
            self.send(200, self.snapshot, "image/jpeg")
        elif url.path == "/cgi-bin/configManager.cgi" and q == {"action": "getConfig", "name": "ChannelTitle"}:
            self.send(200, DAHUA_TITLES.encode(), "text/plain")
        elif url.path == "/cgi-bin/snapshot.cgi" and q.get("channel") == "1":
            self.send(200, self.snapshot, "image/jpeg")
        else:                       # analog kanal listesi, diğer anlık görüntüler: yok → uygulama RTSP'ye düşer
            self.send(404, b"Not Found", "text/plain")


class TrassirHandler(Base):
    """TRASSIR SDK: oturum (sid) ve jeton. Görüntü portu 555'teki MediaMTX'te `tok…` yolları."""
    get_video_calls = 0

    def json(self, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False, indent=1) + "\n/* Don't forget to logout */\n"
        self.send(200, body.encode(), "application/json")

    def do_GET(self) -> None:
        url = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        if url.path == "/login":
            if q.get("username") == USER and q.get("password") == PASSWORD:
                self.json({"success": 1, "sid": SID})
            else:
                self.json({"success": 0, "error_code": "invalid password"})
            return
        if q.get("sid") != SID:
            self.json({"success": 0, "error_code": "no session"})
            return
        if url.path == "/channels":
            self.json(TRASSIR_CHANNELS)
        elif url.path == "/get_video":
            guids = {c["guid"] for c in TRASSIR_CHANNELS["channels"]}
            if q.get("channel") not in guids or q.get("stream") not in {"main", "sub"}:
                self.json({"success": 0, "error_code": "bad channel or stream"})
                return
            TrassirHandler.get_video_calls += 1
            prefix = {"rtsp": "tok", "jpeg": "jpg"}.get(q.get("container", ""))
            if prefix is None:
                self.json({"success": 0, "error_code": "bad container"})
                return
            self.json({"success": 1, "token": f"{prefix}{q['channel']}{q['stream']}"})
        else:
            self.send(404, b"Not Found", "text/plain")


class Server(http.server.ThreadingHTTPServer):
    """`HTTPServer.server_bind` dinlemeden önce `socket.getfqdn()` ile ters DNS sorgular; macOS CI makinesinde
    bu takılıyordu (port bağlı ama dinlenmiyor). Sorgu atlanır."""

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = port


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http-port", type=int, required=True)
    ap.add_argument("--https-port", type=int, required=True)
    ap.add_argument("--cert", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--snapshot", required=True)
    a = ap.parse_args()
    print(f"başlıyor: python {sys.version.split()[0]}", flush=True)
    with open(a.snapshot, "rb") as f:
        Base.snapshot = f.read()

    plain = Server(("127.0.0.1", a.http_port), DigestHandler)
    secure = Server(("127.0.0.1", a.https_port), TrassirHandler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(a.cert, a.key)
    secure.socket = ctx.wrap_socket(secure.socket, server_side=True)

    threading.Thread(target=plain.serve_forever, daemon=True).start()
    print(f"sahte kayıt cihazları: Hikvision/Dahua http://127.0.0.1:{a.http_port}, "
          f"TRASSIR https://127.0.0.1:{a.https_port}", flush=True)
    secure.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
