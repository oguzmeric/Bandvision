"""Anahtarsız kipte başka siteden gelen tarayıcı istekleri (docs/13-web-platform.md "Güvenlik").

`Host` denetimi yalnızca DNS yeniden bağlamayı durdurur: herhangi bir site `http://127.0.0.1:8090`'a geçerli `Host` ile
doğrudan istek atabilir. Çok parçalı `POST /api/v1/jobs` CORS ön uçuşu gerektirmez, yani istek işleyiciye ulaşırdı.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest
from conftest import local_client
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from test_hostcheck import _drive, _http_scope

from bantvision.analyzer import Settings, create_app
from bantvision.analyzer.hostcheck import CROSS_SITE_REFUSED, HOST_REFUSED, is_loopback_origin

CROSS_SITE_TEXT = ("Bu istek başka bir siteden geldiği için kabul edilmedi: erişim anahtarı (ANALYZER_TOKEN) tanımlı "
                   "değilken analiz sunucusu yalnızca bu bilgisayarın sayfalarından gelen istekleri kabul eder.")
FOREIGN = "https://evil.example"
BAD_VIDEO = {"file": ("a.mp4", b"\x00" * 16, "video/mp4")}   # işleyiciye ulaşırsa 400 "okunamadı" (iş kalmaz)

# Panelin `isLoopbackOrigin`/`crossSiteRefused` (apps/dashboard/src/lib/hostCheck.mjs) ile ORTAK tablo: iki test takımı da aynı
# dosyayı okur, aynı girdi → aynı sonuç (contracts/loopback-origins.json).
SHARED = json.loads((pathlib.Path(__file__).resolve().parents[3] / "contracts" / "loopback-origins.json").read_text(encoding="utf-8"))
LOOPBACK_ORIGINS: list[tuple[Any, bool]] = [(r["origin"], r["loopback"]) for r in SHARED["loopbackOrigins"]]
SEC_FETCH_SITE: list[tuple[list[str], bool]] = [(r["lines"], r["refused"]) for r in SHARED["secFetchSite"]]


def test_refusal_text_is_verbatim_and_separate_from_the_host_text() -> None:
    assert CROSS_SITE_REFUSED == CROSS_SITE_TEXT
    assert CROSS_SITE_REFUSED != HOST_REFUSED


@pytest.mark.parametrize(("origin", "want"), LOOPBACK_ORIGINS)
def test_is_loopback_origin(origin: Any, want: bool) -> None:
    assert is_loopback_origin(origin) is want


@pytest.fixture()
def client(tmp_path: pathlib.Path) -> Any:
    with local_client(create_app(Settings(data_dir=tmp_path))) as c:
        yield c


# ------------------------------------------------------------------ HTTP: Origin var

def test_multipart_job_with_foreign_origin_is_refused_and_creates_nothing(client: Any, tmp_path: pathlib.Path) -> None:
    r = client.post("/api/v1/jobs", files=BAD_VIDEO, headers={"origin": FOREIGN})
    assert r.status_code == 403 and r.json() == {"detail": CROSS_SITE_TEXT}
    assert client.get("/api/v1/jobs").json() == [] and not any((tmp_path / "jobs").iterdir())
    # Karşılaştırma: aynı istek Origin'siz işleyiciye ulaşır (panelin sunucu tarafı, curl)
    assert client.post("/api/v1/jobs", files=BAD_VIDEO).status_code == 400


@pytest.mark.parametrize("origin", ["null", FOREIGN, "http://evil.example", "https://localhost.evil.example",
                                    "http://127.0.0.1.evil.example", "file://", "chrome-extension://abc",
                                    "ftp://localhost", "http://localhost/", "http://[::1", ""])
@pytest.mark.parametrize("path", ["/healthz", "/api/v1/live/sources", "/openapi.json"])
def test_foreign_null_and_malformed_origins_are_refused(client: Any, path: str, origin: str) -> None:
    r = client.get(path, headers={"origin": origin})
    assert r.status_code == 403 and r.json() == {"detail": CROSS_SITE_TEXT}


@pytest.mark.parametrize("origins", [("http://localhost:3000", FOREIGN), (FOREIGN, "http://localhost:3000"),
                                     ("http://localhost:3000", "http://localhost:3000")],
                         ids=["iyi-kotu", "kotu-iyi", "iyi-iyi"])
def test_two_origin_headers_are_refused(client: Any, origins: tuple[str, str]) -> None:
    r = client.get("/healthz", headers=[("origin", o) for o in origins])
    assert r.status_code == 403 and r.json() == {"detail": CROSS_SITE_TEXT}


@pytest.mark.parametrize("origin", ["http://localhost:3000", "http://127.0.0.1:3000", "https://localhost",
                                    "http://[::1]:3000", "HTTP://LOCALHOST:3000"])
def test_loopback_origins_pass(client: Any, origin: str) -> None:
    assert client.get("/healthz", headers={"origin": origin}).status_code == 200
    assert client.post("/api/v1/jobs", files=BAD_VIDEO, headers={"origin": origin}).status_code == 400   # işleyici


def test_bad_host_is_refused_first_with_the_host_text(client: Any) -> None:
    r = client.get("/healthz", headers={"host": "evil.example", "origin": FOREIGN})
    assert r.status_code == 403 and r.json() == {"detail": HOST_REFUSED}


# ------------------------------------------------------------------ ANALYZER_CORS_ORIGINS: izin verilen yabancı siteler

def test_configured_cors_origin_passes_including_preflight(tmp_path: pathlib.Path) -> None:
    listed = "https://panel.example"
    preflight = {"access-control-request-method": "POST"}
    with local_client(create_app(Settings(data_dir=tmp_path, cors_origins=[listed]))) as c:
        r = c.get("/healthz", headers={"origin": listed})
        assert r.status_code == 200 and r.headers["access-control-allow-origin"] == listed
        r = c.options("/api/v1/live/sources", headers={**preflight, "origin": listed})
        assert r.status_code == 200 and r.headers["access-control-allow-origin"] == listed
        assert c.post("/api/v1/jobs", files=BAD_VIDEO, headers={"origin": listed}).status_code == 400   # işleyici
        r = c.options("/api/v1/live/sources", headers={**preflight, "origin": FOREIGN})     # listede olmayan ön uçuş
        assert r.status_code == 403 and r.json() == {"detail": CROSS_SITE_TEXT}
        assert c.get("/healthz", headers={"origin": "http://localhost:3000"}).status_code == 200   # bu bilgisayar da


@pytest.mark.parametrize("origin", ["https://panel.example/", "https://panel.example:8443", "http://panel.example",
                                    "HTTPS://PANEL.EXAMPLE", "https://panel.example.evil.example"])
def test_cors_origin_must_match_exactly(tmp_path: pathlib.Path, origin: str) -> None:
    with local_client(create_app(Settings(data_dir=tmp_path, cors_origins=["https://panel.example"]))) as c:
        assert c.get("/healthz", headers={"origin": origin}).status_code == 403


def test_cors_wildcard_is_not_a_listed_origin(tmp_path: pathlib.Path) -> None:
    """`*` bir site adı değildir: anahtarsız kipte bütün sitelere açmaz (siteler tek tek yazılır)."""
    with local_client(create_app(Settings(data_dir=tmp_path, cors_origins=["*"]))) as c:
        assert c.get("/healthz", headers={"origin": FOREIGN}).status_code == 403


@pytest.mark.parametrize("origin", ["null", "NULL", "Null"])
@pytest.mark.parametrize("beside", [(), ("https://panel.example",)], ids=["yalniz", "gercek-site-yaninda"])
def test_null_origin_is_refused_even_when_listed(tmp_path: pathlib.Path, origin: str, beside: tuple[str, ...]) -> None:
    """Her sitedeki korumalı iframe `null` gönderir: tek bir siteyi göstermez, listede yazılı olsa da reddedilir."""
    listed = [origin, *beside]
    preflight = {"origin": origin, "access-control-request-method": "POST"}
    with local_client(create_app(Settings(data_dir=tmp_path, cors_origins=listed))) as c:
        r = c.get("/healthz", headers={"origin": origin})
        assert r.status_code == 403 and r.json() == {"detail": CROSS_SITE_TEXT}
        assert c.post("/api/v1/jobs", files=BAD_VIDEO, headers={"origin": origin}).status_code == 403
        assert c.options("/api/v1/live/sources", headers=preflight).status_code == 403
        if beside:                                                      # listedeki gerçek site etkilenmez
            r = c.get("/healthz", headers={"origin": beside[0]})
            assert r.status_code == 200 and r.headers["access-control-allow-origin"] == beside[0]


@pytest.mark.parametrize("listed", [("null",), ("null", "https://panel.example")], ids=["yalniz", "gercek-site-yaninda"])
def test_middleware_refuses_listed_null_before_the_allow_list(listed: tuple[str, ...]) -> None:
    http = _http_scope([(b"host", b"127.0.0.1:8090"), (b"origin", b"null")])
    sent, reached = _drive(http, [{"type": "http.request", "body": b"", "more_body": False}], allowed_origins=listed)
    assert reached == [] and sent[0]["status"] == 403 and CROSS_SITE_TEXT.encode() in sent[1]["body"]
    # Başlık boşluklu gelse de (`ASGI` sunucusu kırpmadıysa) `null`dır
    padded = _http_scope([(b"host", b"127.0.0.1:8090"), (b"origin", b" null ")])
    sent, reached = _drive(padded, [{"type": "http.request", "body": b"", "more_body": False}],
                           allowed_origins=(*listed, " null "))
    assert reached == [] and sent[0]["status"] == 403
    if len(listed) > 1:
        real = _http_scope([(b"host", b"127.0.0.1:8090"), (b"origin", listed[1].encode())])
        sent, reached = _drive(real, [], allowed_origins=listed)
        assert reached == ["http"] and sent == []


def test_websocket_with_listed_null_origin_is_closed_1008(tmp_path: pathlib.Path) -> None:
    with local_client(_app_with_ws(tmp_path, cors_origins=["null"])) as c:
        with pytest.raises(WebSocketDisconnect) as e, c.websocket_connect("/ws-test", headers={"host": "localhost",
                                                                                                "origin": "null"}):
            pass
        assert e.value.code == 1008


# ------------------------------------------------------------------ HTTP: Origin yok, Sec-Fetch-Site

@pytest.mark.parametrize("site", ["cross-site", "CROSS-SITE"])
def test_no_origin_cross_site_fetch_is_refused(client: Any, site: str) -> None:
    r = client.get("/healthz", headers={"sec-fetch-site": site})
    assert r.status_code == 403 and r.json() == {"detail": CROSS_SITE_TEXT}


@pytest.mark.parametrize("lines", [
    (b"same-origin", b"cross-site"),                 # yalnızca ikinci satır
    (b"none", b"same-site", b"cross-site"),
    (b"cross-site", b"same-origin"),
    (b" cross-site ",),                              # sunucu kırpmadıysa boşluklu değer
    (b"\tcross-site\t",),
    (b"CROSS-SITE",),                                # büyük harf
    (b" Cross-Site ",),
], ids=["ikinci-satir", "ucuncu-satir", "ilk-satir", "bosluklu", "sekmeli", "buyuk-harf", "bosluklu-karisik"])
def test_any_sec_fetch_site_line_saying_cross_site_is_refused(lines: tuple[bytes, ...]) -> None:
    scope = _http_scope([(b"host", b"127.0.0.1:8090"), *((b"sec-fetch-site", v) for v in lines)])
    sent, reached = _drive(scope, [{"type": "http.request", "body": b"", "more_body": False}])
    assert reached == [] and sent[0]["status"] == 403 and CROSS_SITE_TEXT.encode() in sent[1]["body"]


def test_two_sec_fetch_site_lines_through_the_whole_app(client: Any) -> None:
    r = client.get("/healthz", headers=[("sec-fetch-site", "same-origin"), ("sec-fetch-site", "cross-site")])
    assert r.status_code == 403 and r.json() == {"detail": CROSS_SITE_TEXT}
    assert client.get("/healthz", headers=[("sec-fetch-site", "same-origin"), ("sec-fetch-site", "none")]).status_code == 200


@pytest.mark.parametrize(("lines", "refused"), SEC_FETCH_SITE, ids=[" | ".join(r[0]) or "yok" for r in SEC_FETCH_SITE])
def test_shared_sec_fetch_site_table(lines: list[str], refused: bool) -> None:
    """Panelle ortak tablo (virgüllü tek satır dahil: `same-origin, cross-site`, Headers.get iki satırı böyle birleştirir)."""
    scope = _http_scope([(b"host", b"127.0.0.1:8090"), *((b"sec-fetch-site", v.encode()) for v in lines)])
    sent, reached = _drive(scope, [{"type": "http.request", "body": b"", "more_body": False}])
    if refused:
        assert reached == [] and sent[0]["status"] == 403 and CROSS_SITE_TEXT.encode() in sent[1]["body"]
    else:
        assert reached == ["http"]


@pytest.mark.parametrize("site", ["same-site", "same-origin", "none"])
def test_no_origin_other_fetch_metadata_passes(client: Any, site: str) -> None:
    assert client.get("/healthz", headers={"sec-fetch-site": site}).status_code == 200


def test_no_origin_and_no_fetch_metadata_passes(client: Any) -> None:
    """Panelin sunucu tarafı, curl ve başlatıcı: Origin de Sec-Fetch-Site de göndermez."""
    assert client.get("/healthz").status_code == 200


def test_when_origin_is_present_it_decides_not_fetch_metadata(client: Any) -> None:
    both = {"origin": "http://localhost:3000", "sec-fetch-site": "cross-site"}     # bu bilgisayarda başka port
    assert client.get("/healthz", headers=both).status_code == 200
    assert client.get("/healthz", headers={"origin": FOREIGN, "sec-fetch-site": "same-origin"}).status_code == 403


# ------------------------------------------------------------------ WebSocket

def _app_with_ws(tmp_path: pathlib.Path, **settings: Any) -> Any:
    app = create_app(Settings(data_dir=tmp_path, **settings))

    async def handler(ws: WebSocket) -> None:
        await ws.accept()
        await ws.send_text("merhaba")
        await ws.close()

    app.add_api_websocket_route("/ws-test", handler)
    return app


@pytest.mark.parametrize("headers", [{"origin": FOREIGN}, {"origin": "null"},
                                     {"origin": "https://localhost.evil.example"},
                                     {"sec-fetch-site": "cross-site"}],
                         ids=["yabanci", "null", "benzer", "fetch-cross-site"])
def test_websocket_cross_site_is_closed_1008(tmp_path: pathlib.Path, headers: dict[str, str]) -> None:
    with local_client(_app_with_ws(tmp_path)) as c:
        with pytest.raises(WebSocketDisconnect) as e, c.websocket_connect("/ws-test", headers={"host": "localhost",
                                                                                                **headers}):
            pass
        assert e.value.code == 1008


@pytest.mark.parametrize("headers", [{}, {"origin": "http://localhost:3000"}, {"origin": "https://panel.example"}],
                         ids=["origin-yok", "bu-bilgisayar", "listede"])
def test_websocket_allowed_origins_connect(tmp_path: pathlib.Path, headers: dict[str, str]) -> None:
    with local_client(_app_with_ws(tmp_path, cors_origins=["https://panel.example"])) as c, \
            c.websocket_connect("/ws-test", headers={"host": "localhost", **headers}) as ws:
        assert ws.receive_text() == "merhaba"


def test_two_origin_headers_on_a_websocket_are_closed_1008() -> None:
    scope = {"type": "websocket", "path": "/ws", "raw_path": b"/ws", "query_string": b"", "root_path": "",
             "scheme": "ws", "subprotocols": [], "headers": [(b"host", b"127.0.0.1"),
                                                             (b"origin", b"http://localhost:3000"),
                                                             (b"origin", b"http://localhost:3000")]}
    sent, reached = _drive(scope, [{"type": "websocket.connect"}])
    assert reached == [] and sent == [{"type": "websocket.close", "code": 1008, "reason": ""}]


def test_middleware_alone_reports_the_cross_site_text() -> None:
    scope = _http_scope([(b"host", b"127.0.0.1:8090"), (b"origin", FOREIGN.encode())])
    sent, reached = _drive(scope, [{"type": "http.request", "body": b"", "more_body": False}])
    assert reached == [] and sent[0]["status"] == 403 and CROSS_SITE_TEXT.encode() in sent[1]["body"]


# ------------------------------------------------------------------ anahtar tanımlı: bu denetim yok

def test_token_mode_has_no_cross_site_check(tmp_path: pathlib.Path) -> None:
    foreign = {"origin": FOREIGN, "sec-fetch-site": "cross-site"}
    with local_client(create_app(Settings(data_dir=tmp_path, token="gizli"))) as c:
        r = c.get("/api/v1/system/status", headers=foreign)
        assert r.status_code == 401 and r.json()["detail"] == "Yetkisiz: geçerli bir erişim anahtarı gerekli."
        assert c.get("/api/v1/system/status", headers={**foreign, "authorization": "Bearer gizli"}).status_code == 200
        assert c.get("/healthz", headers=foreign).status_code == 200
