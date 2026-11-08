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


# --- Arşiv (kayıttan izleme) sabit verileri: hepsi 2026-03-04 günü; testler birleştirmeyi doğrular ---
ARCHIVE_DAY = "2026-03-04"
TRASSIR_CALENDAR = ["2026-02-27", "2026-03-04", "2026-03-05"]
# Gece yarısından saniye; 1. ve 2. aralık 1 sn boşlukla dokunur (bağdaştırıcı birleştirir)
TRASSIR_TIMELINE = [{"begin": 32400, "end": 34200}, {"begin": 34201, "end": 36000}, {"begin": 50400, "end": 51000}]
EXPORT_BYTES = b"\x00\x00\x00\x0cftypisom" + bytes(range(256)) * 8     # 12 baytlık geçerli `ftyp` kutusu + gövde

HIKVISION_TRACK = "101"          # kanal 1 ana akış
HIKVISION_SEARCH_PAGES = {
    0: ("MORE", [("2026-03-04T12:00:00Z", "2026-03-04T12:30:00Z"), ("2026-03-04T12:30:00Z", "2026-03-04T13:00:00Z")]),
    400: ("OK", [("2026-03-04T14:00:00Z", "2026-03-04T14:10:00Z")]),
}
HIKVISION_DAILY = (3, 4, 6)      # kayıtlı günler (ayın geri kalanı kayıtsız)

DAHUA_PAGE = 100
# Sayfa 1: 08:00'dan başlayan 100 dokunan dakikalık dosya; sayfa 2: 12:00-12:10 ve 1 sn boşluklu 12:10:01-12:20
DAHUA_SECOND_PAGE = [(43200, 43800), (43801, 44400)]      # gece yarısından saniye


def clock(seconds: int) -> str:
    return f"{ARCHIVE_DAY} {seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


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
    dahua_lock: ClassVar[threading.Lock] = threading.Lock()
    dahua_next_id: ClassVar[int] = 0
    dahua_pages: ClassVar[dict[str, int]] = {}

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

    def do_POST(self) -> None:
        # keep-alive: gövde okunmadan yanıtlanırsa sonraki istek bozulur
        text = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8", errors="replace")
        if not self.authorized():
            self.challenge()
            return
        path = urllib.parse.urlsplit(self.path).path
        track = re.search(r"<trackID>(\d+)</trackID>", text)
        daily = re.fullmatch(r"/ISAPI/ContentMgmt/record/tracks/(\d+)/dailyDistribution", path)
        if path == "/ISAPI/ContentMgmt/search":
            position = re.search(r"<searchResultPostion>(\d+)</searchResultPostion>", text)
            status, spans = HIKVISION_SEARCH_PAGES.get(int(position.group(1)) if position else -1, ("NO MATCHES", []))
            if track is None or track.group(1) != HIKVISION_TRACK:
                status, spans = "NO MATCHES", []
            items = "".join(f"<searchMatchItem><timeSpan><startTime>{a}</startTime><endTime>{b}</endTime></timeSpan>"
                            "</searchMatchItem>" for a, b in spans)
            xml = ('<?xml version="1.0" encoding="UTF-8"?><CMSearchResult version="2.0" '
                   'xmlns="http://www.hikvision.com/ver20/XMLSchema"><responseStatus>true</responseStatus>'
                   f"<responseStatusStrg>{status}</responseStatusStrg><numOfMatches>{len(spans)}</numOfMatches>"
                   f"<matchList>{items}</matchList></CMSearchResult>")
            self.send(200, xml.encode(), "application/xml")
        elif daily is not None and daily.group(1) == HIKVISION_TRACK:
            days = "".join(f"<day><dayOfMonth>{d}</dayOfMonth><record>{'true' if d in HIKVISION_DAILY else 'false'}"
                           "</record></day>" for d in range(1, 8))
            xml = ('<?xml version="1.0" encoding="UTF-8"?><trackDailyDistribution version="2.0" '
                   f'xmlns="http://www.hikvision.com/ver20/XMLSchema"><dayList>{days}</dayList>'
                   "</trackDailyDistribution>")
            self.send(200, xml.encode(), "application/xml")
        else:
            self.send(404, b"Not Found", "text/plain")

    def dahua_find(self, q: dict[str, str]) -> str | None:
        """`mediaFileFind.cgi` beş eylemi; arama durumu nesne kimliğine bağlıdır (sayfa sayacı)."""
        action, obj = q.get("action"), q.get("object", "")
        with self.dahua_lock:
            if action == "factory.create":
                DigestHandler.dahua_next_id += 1
                DigestHandler.dahua_pages[str(DigestHandler.dahua_next_id)] = 0
                return f"result={DigestHandler.dahua_next_id}\r\n"
            if obj not in self.dahua_pages:
                return None
            if action == "findFile":
                DigestHandler.dahua_pages[obj] = 0
                ok = q.get("condition.Channel") == "1" and q.get("condition.Types[0]") == "dav"
                return "OK\r\n" if ok else None
            if action == "findNextFile":
                page = DigestHandler.dahua_pages[obj]
                DigestHandler.dahua_pages[obj] = page + 1
                if page == 0:
                    spans = [(clock(28800 + 60 * i), clock(28860 + 60 * i)) for i in range(DAHUA_PAGE)]
                elif page == 1:
                    spans = [(clock(a), clock(b)) for a, b in DAHUA_SECOND_PAGE]
                else:
                    spans = []
                lines = [f"found={len(spans)}"]
                for i, (a, b) in enumerate(spans):
                    lines += [f"items[{i}].StartTime={a}", f"items[{i}].EndTime={b}"]
                return "\r\n".join(lines) + "\r\n"
            if action in ("close", "destroy"):
                if action == "destroy":
                    DigestHandler.dahua_pages.pop(obj, None)
                return "OK\r\n"
        return None

    def do_GET(self) -> None:
        if not self.authorized():
            self.challenge()
            return
        url = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        if url.path == "/cgi-bin/mediaFileFind.cgi":
            reply = self.dahua_find(q)
            if reply is None:
                self.send(400, b"Error\r\n", "text/plain")
            else:
                self.send(200, reply.encode(), "text/plain")
        elif url.path == "/ISAPI/ContentMgmt/InputProxy/channels":
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
    lock: ClassVar[threading.Lock] = threading.Lock()
    archive_log: ClassVar[list[dict[str, str]]] = []      # `archive_command` çağrıları (testler /_mock/archive-log ile okur)
    last_play_day = ARCHIVE_DAY
    export_tasks: ClassVar[dict[str, int]] = {}            # görev → indirme sayısı

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
        if url.path == "/_mock/archive-log":
            with self.lock:
                body = json.dumps(self.archive_log).encode()
            self.send(200, body, "application/json")
            return
        if q.get("sid") != SID:
            self.json({"success": 0, "error_code": "no session"})
            return
        if url.path == "/channels":
            self.json(TRASSIR_CHANNELS)
        elif url.path == "/get_video":
            guids = {c["guid"] for c in TRASSIR_CHANNELS["channels"]}
            if q.get("channel") not in guids or q.get("stream") not in {"main", "sub", "archive_main", "archive_sub"}:
                self.json({"success": 0, "error_code": "bad channel or stream"})
                return
            TrassirHandler.get_video_calls += 1
            prefix = {"rtsp": "tok", "jpeg": "jpg"}.get(q.get("container", ""))
            if prefix is None:
                self.json({"success": 0, "error_code": "bad container"})
                return
            self.json({"success": 1, "token": f"{prefix}{q['channel']}{q['stream']}"})
        elif url.path == "/archive_command":
            self.archive_command(q)
        elif url.path == "/archive_status":
            self.archive_status(q)
        elif url.path == "/jit-export-download":
            self.export_download(q)
        else:
            self.send(404, b"Not Found", "text/plain")

    def archive_command(self, q: dict[str, str]) -> None:
        entry = {k: q[k] for k in ("command", "token", "start", "stop", "speed") if k in q}
        with self.lock:
            self.archive_log.append(entry)
            day = re.match(r"(\d{4})(\d{2})(\d{2})T", q.get("start", "")) if q.get("command") == "play" else None
            if day:
                TrassirHandler.last_play_day = "-".join(day.groups())
        self.json({"success": 1})

    def archive_status(self, q: dict[str, str]) -> None:
        if q.get("type") == "calendar":
            self.json({"success": 1, "calendar": TRASSIR_CALENDAR})
        elif q.get("type") == "timeline":
            self.json({"success": 1, "day_start": self.last_play_day, "timeline": TRASSIR_TIMELINE})
        else:
            self.json({"success": 0, "error_code": "bad type"})

    def do_POST(self) -> None:
        url = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if q.get("sid") != SID:
            self.json({"success": 0, "error_code": "no session"})
        elif url.path == "/jit-export-create-task":
            try:
                request = json.loads(body)
            except ValueError:
                request = None
            guids = {c["guid"] for c in TRASSIR_CHANNELS["channels"]}
            if not isinstance(request, dict) or request.get("resource_guid") not in guids:
                self.json({"success": 0, "error_code": "bad request"})
                return
            with self.lock:
                task = f"task{len(self.export_tasks) + 1}"
                self.export_tasks[task] = 0
            self.json({"success": 1, "task_id": task})
        else:
            self.send(404, b"Not Found", "text/plain")

    def export_download(self, q: dict[str, str]) -> None:
        task = q.get("task_id", "")
        with self.lock:
            calls = 0
            if task in self.export_tasks:
                self.export_tasks[task] += 1
                calls = self.export_tasks[task]
        if calls == 0:
            self.json({"success": 0, "error_code": "unknown task"})
        elif calls == 1:                     # dosya hazırlanıyor: bağdaştırıcının yeniden denemesi sınanır
            self.json({"success": 0, "error_code": "not ready"})
        else:
            self.send(200, EXPORT_BYTES, "video/mp4")


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
