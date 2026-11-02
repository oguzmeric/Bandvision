"""Analiz sunucusunun sertleştirmesi (docs/13-web-platform.md "Güvenlik"):

- Erişim anahtarı (ANALYZER_TOKEN) yokken her HTTP ve WebSocket isteği yalnızca bu bilgisayarın adlarıyla (`localhost`,
  `127.0.0.1`, `[::1]`) kabul edilir; başka ad `403` (DNS yeniden bağlama savunması). Anahtar varken denetim yok.
- Anahtarsız sunucu ağa açılmaz (`--host` geri döngü dışı + anahtar yok → çıkış kodu 2).
- Kayıt cihazının şifre reddi `502` (analiz sunucusunun tek `401`'i kendi anahtar denetimi).

Başka siteden gelen tarayıcı istekleri: tests/test_crosssite.py.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
from typing import Any

import anyio
import pytest
import uvicorn
from conftest import local_client
from fastapi import WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from bantvision.analyzer import Settings, create_app
from bantvision.analyzer import __main__ as analyzer_main
from bantvision.analyzer.hostcheck import (
    HOST_REFUSED,
    LOOPBACK_NAMES,
    LocalOnlyMiddleware,
    host_name,
    is_loopback_host,
)

# Kararlardaki metinler (birebir; sabitler de bunlara eşit olmalı)
HOST_REFUSED_TEXT = ("Bu adres kabul edilmiyor: erişim anahtarı (ANALYZER_TOKEN) tanımlı değilken analiz sunucusuna "
                     "yalnızca bu bilgisayardan (localhost, 127.0.0.1) bağlanılabilir.")
LAUNCH_REFUSED_TEXT = ("Erişim anahtarı (ANALYZER_TOKEN) olmadan analiz sunucusu yalnızca bu bilgisayarda (127.0.0.1) "
                       "açılabilir; ağa açmak için ANALYZER_TOKEN tanımlayın.")
RECORDER_UNAUTHORIZED_TEXT = "Kullanıcı adı ya da şifre hatalı."

ACCEPTED = ["localhost", "localhost:8090", "127.0.0.1:8090", "[::1]:8090", "LOCALHOST"]
REFUSED = ["testserver", "evil.example", "127.0.0.1.evil.example", "localhost.", "[::1", "::1", "a:b:c",
           "localhost:99999x"]
GUARDED_PATHS = ["/healthz", "/api/v1/system/status", "/openapi.json", "/docs", "/redoc"]


def test_texts_and_names_are_verbatim() -> None:
    assert HOST_REFUSED == HOST_REFUSED_TEXT
    assert analyzer_main.LAUNCH_REFUSED == LAUNCH_REFUSED_TEXT
    assert LOOPBACK_NAMES == frozenset({"localhost", "127.0.0.1", "::1"})


# ------------------------------------------------------------------ (a) ayrıştırıcı: panelin hostCheck.mjs'i ile birebir

def test_host_name_mirrors_panel_cases() -> None:
    """apps/dashboard/src/lib/hostCheck.test.mjs `hostName` vakaları."""
    assert host_name("LOCALHOST:3000") == "localhost"
    assert host_name(" 127.0.0.1 ") == "127.0.0.1"
    assert host_name("[::1]:3000") == "::1"
    assert host_name("ofis.example.com") == "ofis.example.com"
    bad: list[Any] = ["", ":3000", "[::1", "[::1]x", "::1", "127.0.0.1:abc", "127.0.0.1:3000:1", "127.0.0.1:123456",
                      None, 42]
    for h in bad:
        assert host_name(h) is None, repr(h)


def test_is_loopback_host_mirrors_panel_cases() -> None:
    """apps/dashboard/src/lib/hostCheck.test.mjs `isLoopbackHost` vakaları."""
    for h in ["127.0.0.1", "127.0.0.1:3000", "localhost", "localhost:3000", "LocalHost:3000", "[::1]", "[::1]:3000"]:
        assert is_loopback_host(h) is True, h
    for h in ["evil.example.com", "evil.example.com:3000", "localhost.evil.com:3000", "127.0.0.1.nip.io:3000",
              "127.0.0.2:3000", "0.0.0.0:3000", "192.168.1.20:3000", "10.0.0.5", "[::2]:3000", "::1",
              "attacker@127.0.0.1", "127.0.0.1/", "", None]:
        assert is_loopback_host(h) is False, repr(h)


def test_ipv6_and_port_forms() -> None:
    """IPv6 ve port biçimleri (gözden geçirme odağı 3) ve kararlardaki reddedilen adlar."""
    for h in ["[::1]:8090", "LOCALHOST", "127.0.0.1:65535", *ACCEPTED]:
        assert is_loopback_host(h) is True, h
    for h in ["[::1", "::1", "localhost:99999x", "a:b:c", *REFUSED]:
        assert is_loopback_host(h) is False, h
    assert host_name("[::1") is None and host_name("::1") is None and host_name("a:b:c") is None
    assert host_name("localhost:99999x") is None
    assert host_name("localhost.") == "localhost." and host_name("127.0.0.1.evil.example") == "127.0.0.1.evil.example"


@pytest.mark.parametrize(("header", "want"), [
    # node ile hostCheck.mjs'te ölçülen sonuçlar: aynı girdi → aynı çıktı
    ("localhost:", "localhost"),                  # boş port geçerli
    ("[::1]:", "::1"),
    ("[LOCALHOST]", "localhost"),
    ("[127.0.0.1]:80", "127.0.0.1"),
    ("[]", None),
    ("[]:80", None),
    ("localhost:99999", "localhost"),             # 5 haneye kadar her port (aralık denetlenmez)
    ("localhost:+80", None),
    ("localhost: 80", None),
    ("localhost:\u0663", None),                   # yalnızca ASCII rakam (Python'un \d'si Unicode rakamını da tutar)
    ("localhost:1\n2", None),
    ("localhost:80\n", "localhost"),              # sondaki satır sonu kırpılır (JS trim)
    ("\ufefflocalhost", "localhost"),             # JS trim BOM'u atar (Python strip atmaz)
    ("\x85localhost", "\x85localhost"),           # JS trim NEL'i atmaz (Python strip atar)
    ("\x1clocalhost", "\x1clocalhost"),
    ("local host", "local host"),
])
def test_host_name_matches_js_trim_digits_and_brackets(header: str, want: str | None) -> None:
    assert host_name(header) == want


# ------------------------------------------------------------------ (b) anahtarsız uygulama: yalnızca geri döngü adları

@pytest.fixture(scope="module")
def no_token_client(tmp_path_factory: pytest.TempPathFactory) -> Any:
    with local_client(create_app(Settings(data_dir=tmp_path_factory.mktemp("anahtarsiz")))) as c:
        yield c


@pytest.mark.parametrize("path", GUARDED_PATHS)
def test_no_token_accepts_only_loopback_names(no_token_client: TestClient, path: str) -> None:
    for host in ACCEPTED:
        r = no_token_client.get(path, headers={"host": host})
        assert r.status_code == 200, (path, host, r.text)
    for host in REFUSED:
        r = no_token_client.get(path, headers={"host": host})
        assert r.status_code == 403, (path, host)
        assert r.json() == {"detail": HOST_REFUSED_TEXT}, (path, host)


def test_local_client_default_host_is_accepted(no_token_client: TestClient) -> None:
    assert no_token_client.get("/healthz").json()["ok"] is True                   # Host: 127.0.0.1


def test_default_testclient_host_is_refused(tmp_path: pathlib.Path) -> None:
    """R9: TestClient'ın varsayılan adı (`testserver`) anahtarsız kipte 403 alır; üretim kodunda ayrıcalık yok."""
    with TestClient(create_app(Settings(data_dir=tmp_path))) as c:
        for path in ("/healthz", "/api/v1/system/status", "/api/v1/live/sources"):
            r = c.get(path)
            assert r.status_code == 403 and r.json()["detail"] == HOST_REFUSED_TEXT, path


# ------------------------------------------------------------------ (c) Host başlığı yok / birden çok: ara katman doğrudan

def _drive(scope: dict[str, Any], incoming: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Ara katmanı ağsız sürer: içteki uygulama çağrılırsa türü kaydedilir; gönderilen iletiler döner."""
    sent: list[dict[str, Any]] = []
    reached: list[str] = []

    async def inner(scope: Any, _receive: Any, _send: Any) -> None:
        reached.append(scope["type"])

    async def receive() -> dict[str, Any]:
        return incoming.pop(0) if incoming else {"type": "http.disconnect"}

    async def send(msg: Any) -> None:
        sent.append(msg)

    anyio.run(LocalOnlyMiddleware(inner), scope, receive, send)
    return sent, reached


def _http_scope(headers: list[tuple[bytes, bytes]]) -> dict[str, Any]:
    return {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
            "path": "/healthz", "raw_path": b"/healthz", "query_string": b"", "root_path": "", "headers": headers,
            "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8090)}


@pytest.mark.parametrize("headers", [
    [],                                                          # Host yok
    [(b"accept", b"*/*")],
    [(b"host", b"localhost"), (b"host", b"evil.example")],      # birden çok Host (RFC 9112: geçersiz istek)
    [(b"host", b"localhost"), (b"host", b"localhost")],
], ids=["bos", "host-yok", "iki-farkli-host", "iki-ayni-host"])
def test_missing_or_repeated_host_is_403(headers: list[tuple[bytes, bytes]]) -> None:
    sent, reached = _drive(_http_scope(headers), [{"type": "http.request", "body": b"", "more_body": False}])
    assert reached == []                                         # uygulamaya hiç ulaşmaz
    assert sent[0]["type"] == "http.response.start" and sent[0]["status"] == 403
    assert json.loads(b"".join(m.get("body", b"") for m in sent[1:])) == {"detail": HOST_REFUSED_TEXT}


def test_single_loopback_host_reaches_the_app() -> None:
    sent, reached = _drive(_http_scope([(b"host", b"127.0.0.1:8090")]), [])
    assert reached == ["http"] and sent == []


def test_websocket_without_host_is_closed_1008_before_accept() -> None:
    scope = {"type": "websocket", "path": "/ws", "raw_path": b"/ws", "query_string": b"", "root_path": "",
             "headers": [], "scheme": "ws", "subprotocols": []}
    sent, reached = _drive(scope, [{"type": "websocket.connect"}])
    assert reached == [] and sent == [{"type": "websocket.close", "code": 1008, "reason": ""}]


def test_lifespan_passes_through_untouched() -> None:
    sent, reached = _drive({"type": "lifespan", "asgi": {"version": "3.0"}}, [])
    assert reached == ["lifespan"] and sent == []


# ------------------------------------------------------------------ (d) CORS ön uçuşu: Host denetimi en dışta

def test_cors_preflight_with_bad_host_is_403_not_cors_200(tmp_path: pathlib.Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, cors_origins=["http://localhost:3000"]))
    preflight = {"origin": "http://localhost:3000", "access-control-request-method": "GET"}
    with local_client(app) as c:
        r = c.options("/api/v1/live/sources", headers={**preflight, "host": "evil.example"})
        assert r.status_code == 403 and r.json() == {"detail": HOST_REFUSED_TEXT}
        assert "access-control-allow-origin" not in r.headers
        ok = c.options("/api/v1/live/sources", headers={**preflight, "host": "localhost:8090"})   # karşılaştırma
        assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == "http://localhost:3000"


# ------------------------------------------------------------------ (e) WebSocket: kabul etmeden 1008

def _app_with_ws(tmp_path: pathlib.Path) -> Any:
    app = create_app(Settings(data_dir=tmp_path))

    async def handler(ws: WebSocket) -> None:
        await ws.accept()
        await ws.send_text("merhaba")
        await ws.close()

    app.add_api_websocket_route("/ws-test", handler)
    return app


def test_websocket_with_bad_host_is_closed_1008(tmp_path: pathlib.Path) -> None:
    with local_client(_app_with_ws(tmp_path)) as c:
        with pytest.raises(WebSocketDisconnect) as e, c.websocket_connect("/ws-test", headers={"host": "evil.example"}):
            pass
        assert e.value.code == 1008
        with c.websocket_connect("/ws-test", headers={"host": "localhost"}) as ws:
            assert ws.receive_text() == "merhaba"


def test_websocket_default_testclient_host_is_closed_1008(tmp_path: pathlib.Path) -> None:
    """R9 (WebSocket): Starlette'in test istemcisi WebSocket'i hep `testserver` adıyla açar."""
    with TestClient(_app_with_ws(tmp_path)) as c:
        with pytest.raises(WebSocketDisconnect) as e, c.websocket_connect("/ws-test"):
            pass
        assert e.value.code == 1008


# ------------------------------------------------------------------ (f) anahtar tanımlı: Host denetimi yok (bugünkü gibi)

def test_token_mode_has_no_host_check(tmp_path: pathlib.Path) -> None:
    with local_client(create_app(Settings(data_dir=tmp_path, token="gizli"))) as c:
        evil = {"host": "evil.example"}
        assert c.get("/healthz", headers=evil).status_code == 200
        r = c.get("/api/v1/system/status", headers=evil)
        assert r.status_code == 401 and r.json()["detail"] == "Yetkisiz: geçerli bir erişim anahtarı gerekli."
        assert c.get("/api/v1/system/status", headers={**evil, "Authorization": "Bearer gizli"}).status_code == 200
        assert c.get("/openapi.json", headers=evil).status_code == 404                 # belge sayfaları kapalı


# ------------------------------------------------------------------ (g) akış ara katmandan tamponlanmadan geçer

def test_mjpeg_stream_flows_through_host_check(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """test_live.py `test_view_stream_and_status_with_file_sources`'ın `Host: localhost:8090` çeşidi: dosya kaynağı
    (kamera gibi oynar), birleşik izleme akışı (MJPEG)."""
    from test_live import CLIP, _asgi_stream_until_disconnect, camera

    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    host = {"host": "localhost:8090"}
    with local_client(create_app(Settings(data_dir=tmp_path))) as c:
        a = c.post("/api/v1/live/sources", headers=host,
                   json=camera(brand="custom", customUrl=str(CLIP), password="", name="Kapı")).json()["id"]
        v = c.post("/api/v1/live/views", headers=host,
                   json={"name": "Bir", "layout": "1", "tiles": [{"sourceId": a, "channelId": None}]}).json()
        path = f"/api/v1/live/views/{v['id']}/stream"
        r = c.get(f"{path}?w=320&h=180&limit=1", headers=host)
        assert r.status_code == 200 and r.headers["content-type"].startswith("multipart/x-mixed-replace")
        assert r.content.count(b"Content-Type: image/jpeg") == 1 and b"\xff\xd8" in r.content
        # Sınırsız akış: ilk parçalar gelir gelmez istemciye ulaşır (403 tek gövde parçasıdır; akış en az iki)
        assert _asgi_stream_until_disconnect(c, path, b"w=320&h=180", 2, host=b"localhost:8090") >= 2
        assert c.get(f"{path}?limit=1", headers={"host": "evil.example"}).status_code == 403


# ------------------------------------------------------------------ (h) anahtarsız sunucu ağa açılmaz

class Launch:
    """`python -m bantvision.analyzer ARGS`: uvicorn.run yalnızca kaydedilir (sunucu açılmaz, port dinlenmez)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.mp = monkeypatch
        self.calls: list[dict[str, Any]] = []
        monkeypatch.setattr(uvicorn, "run", lambda app, **kw: self.calls.append({"app": app, **kw}))

    def __call__(self, *args: str) -> list[dict[str, Any]]:
        self.mp.setattr(sys, "argv", ["python -m bantvision.analyzer", *args])
        analyzer_main.main()
        return self.calls


@pytest.fixture()
def launch(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> Launch:
    monkeypatch.setenv("ANALYZER_DATA_DIR", str(tmp_path))                 # create_app depoyu burada açar
    monkeypatch.delenv("ANALYZER_TOKEN", raising=False)
    return Launch(monkeypatch)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.20", "ofis-pc", ""])
@pytest.mark.parametrize("token", [None, "", "   "])
def test_launch_on_network_without_token_is_refused(launch: Launch, monkeypatch: pytest.MonkeyPatch,
                                                    capsys: pytest.CaptureFixture[str], host: str,
                                                    token: str | None) -> None:
    if token is not None:
        monkeypatch.setenv("ANALYZER_TOKEN", token)                       # boş ya da yalnızca boşluk = anahtar yok
    with pytest.raises(SystemExit) as e:
        launch("--host", host)
    assert e.value.code == 2
    assert capsys.readouterr().err.strip() == LAUNCH_REFUSED_TEXT
    assert launch.calls == []                                               # uvicorn.run hiç çağrılmadı


def _refused_cli(tmp_path: pathlib.Path, log: pathlib.Path) -> subprocess.CompletedProcess[str]:
    """Gerçek komut satırı (`--log` çıktıyı süreç düzeyinde yönlendirir: pytest'in içinde sınanmaz)."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "ANALYZER_DATA_DIR": str(tmp_path / "veri")}
    env.pop("ANALYZER_TOKEN", None)
    return subprocess.run([sys.executable, "-m", "bantvision.analyzer", "--host", "0.0.0.0", "--port", "8098",
                           "--log", str(log)], capture_output=True, text=True, encoding="utf-8", env=env, timeout=120,
                          cwd=pathlib.Path(__file__).resolve().parents[1], check=False)


def test_refused_launch_with_log_prints_on_console_and_in_the_log(tmp_path: pathlib.Path) -> None:
    """Reddedilen açılış sessiz kalmaz: ileti hem gerçek hata çıktısına hem günlük dosyasına yazılır (R13)."""
    log = tmp_path / "logs" / "analyzer.log"
    r = _refused_cli(tmp_path, log)
    assert r.returncode == 2
    assert r.stderr.strip() == LAUNCH_REFUSED_TEXT and r.stdout == ""
    assert log.read_text(encoding="utf-8").strip() == LAUNCH_REFUSED_TEXT


def test_refused_launch_with_unwritable_log_still_exits_2_with_the_message(tmp_path: pathlib.Path) -> None:
    (tmp_path / "dosya").write_text("klasör değil", encoding="utf-8")
    r = _refused_cli(tmp_path, tmp_path / "dosya" / "analyzer.log")         # günlük klasörü açılamaz
    assert r.returncode == 2
    assert r.stderr.strip() == LAUNCH_REFUSED_TEXT


@pytest.mark.parametrize(("value", "want"), [
    ("", None),
    ("   ", None),                                    # yalnızca boşluk: anahtar yok
    ("\t \n", None),
    ("gizli", "gizli"),
    ("  gizli ", "  gizli "),                         # başka karakter varsa olduğu gibi kalır (kırpılmaz)
    ("gizli şifre", "gizli şifre"),
])
def test_settings_from_env_whitespace_only_token_is_no_token(monkeypatch: pytest.MonkeyPatch, value: str,
                                                             want: str | None) -> None:
    monkeypatch.setenv("ANALYZER_TOKEN", value)
    assert Settings.from_env().token == want


def test_settings_from_env_without_token_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANALYZER_TOKEN", raising=False)
    assert Settings.from_env().token is None


def test_whitespace_only_token_leaves_the_host_check_on(launch: Launch, monkeypatch: pytest.MonkeyPatch) -> None:
    """Yalnızca boşluktan oluşan anahtar Host denetimini kapatmaz ve anahtar gibi kabul edilmez (R13)."""
    monkeypatch.setenv("ANALYZER_TOKEN", "   ")
    (call,) = launch()
    assert call["app"].state.settings.token is None
    c = local_client(call["app"])                                           # ömür başlamaz: istek ara katmanda biter
    assert c.get("/healthz", headers={"host": "evil.example"}).status_code == 403
    assert c.get("/healthz").status_code == 200


def test_launch_on_network_with_token_starts(launch: Launch, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANALYZER_TOKEN", "x")
    (call,) = launch("--host", "0.0.0.0", "--port", "8093")
    assert call["host"] == "0.0.0.0" and call["port"] == 8093
    assert call["app"].state.settings.token == "x"                          # create_app ile aynı kaynak


@pytest.mark.parametrize("args", [(), ("--host", "127.0.0.1"), ("--host", "localhost"), ("--host", "LOCALHOST"),
                                  ("--host", "::1")])
def test_launch_on_loopback_without_token_starts(launch: Launch, args: tuple[str, ...]) -> None:
    (call,) = launch(*args)
    assert call["host"] == (args[1] if args else "127.0.0.1")
    assert call["app"].state.settings.token is None


# ------------------------------------------------------------------ (i) kayıt cihazı şifre reddi 502 (401 değil)

def test_recorder_password_rejection_is_502_with_same_message(tmp_path: pathlib.Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """test_live.py'nin sahteli uygulaması; kayıt cihazı kanal listesinde ve küçük resimde şifreyi reddeder."""
    from test_live import _app_with_fakes

    from bantvision.live import recorders as rec

    def unauthorized(*_a: Any, **_k: Any) -> Any:
        raise rec.RecorderError.unauthorized()

    app = _app_with_fakes(tmp_path)
    monkeypatch.setattr(app.state.live, "channels", unauthorized)
    monkeypatch.setattr(app.state.live, "snapshot", unauthorized)
    with local_client(app) as c:
        r = c.post("/api/v1/live/sources", json={"kind": "recorder", "recorderBrand": "hikvision", "host": "nvr.example",
                                                 "username": "u", "password": "p", "name": "NVR"})
        assert r.status_code == 201, r.text
        sid = r.json()["id"]
        for resp in (c.get(f"/api/v1/live/sources/{sid}/channels"),
                     c.post("/api/v1/live/views/from-recorder", json={"sourceId": sid}),
                     c.get(f"/api/v1/live/sources/{sid}/snapshot?channel=1")):
            assert resp.status_code == 502, resp.request.url
            assert resp.json() == {"detail": RECORDER_UNAUTHORIZED_TEXT}, resp.request.url
