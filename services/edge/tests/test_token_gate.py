"""Anahtar kipinde `/api/` isteği gövdesi okunmadan reddedilir (docs/13-web-platform.md "Güvenlik").

FastAPI bağımlılığı (`auth`) çok parçalı gövde ayrıştırıldıktan sonra çalışır: anahtarsız bir istemci analiz sunucusuna bütün
bir yüklemeyi okutabilirdi. Ham soket denetimleri gerçek sunucuda yapılır: TestClient gövdeyi baştan bütün gönderir.
"""
from __future__ import annotations

import json
import pathlib
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import uvicorn
from conftest import local_client

from bantvision.analyzer import Settings, create_app
from bantvision.analyzer.jobs import token_from_env

ROOT = pathlib.Path(__file__).resolve().parents[3]
CLIP = ROOT / "apps" / "ios" / "BantSayacUITests" / "ui_test_clip.mp4"
TOKEN = "gizli"
GOOD = {"Authorization": f"Bearer {TOKEN}"}
DETAIL = {"detail": "Yetkisiz: geçerli bir erişim anahtarı gerekli."}
TOTAL = 8 * 1024 * 1024
SENT = 1024 * 1024
BOUNDARY = "sinir"


@pytest.fixture()
def live_server(tmp_path: pathlib.Path) -> Iterator[tuple[int, pathlib.Path]]:
    """Gerçek uvicorn, boş bir portta (çekirdek uygulama; işçi süreci yalnızca iş kuyruğa girince çalışır)."""
    server = uvicorn.Server(uvicorn.Config(create_app(Settings(data_dir=tmp_path, token=TOKEN)), host="127.0.0.1", port=0,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        assert time.monotonic() < deadline, "sunucu açılmadı"
        time.sleep(0.02)
    yield server.servers[0].sockets[0].getsockname()[1], tmp_path
    server.should_exit = True
    thread.join(timeout=30)


def _partial_upload(port: int, extra: str = "", path: str = "/api/v1/jobs") -> bytes:
    """Başlıklar ve gövdenin 1/8'i gönderilir, kalanı HİÇ gönderilmez: yanıt ancak gövde beklenmeden gelirse okunur."""
    part = (f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.mp4\"\r\n"
            "Content-Type: video/mp4\r\n\r\n").encode()
    head = (f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Length: {TOTAL}\r\n"
            f"Content-Type: multipart/form-data; boundary={BOUNDARY}\r\n{extra}\r\n").encode()
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(head + part + b"\x00" * (SENT - len(part)))
        s.settimeout(3)
        got = b""
        try:
            while b"\r\n\r\n" not in got or not got.rstrip().endswith(b"}"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                got += chunk
        except TimeoutError:
            pytest.fail(f"yanıt gövde bitmeden gelmedi: {got!r}")
    return got


def _status_and_json(raw: bytes) -> tuple[int, Any]:
    head, _, body = raw.partition(b"\r\n\r\n")
    return int(head.split(b" ", 2)[1]), json.loads(body)


@pytest.mark.parametrize("extra", ["", "Authorization: Bearer yanlis\r\n"], ids=["anahtarsiz", "yanlis"])
def test_refused_upload_gets_401_before_the_body_and_writes_nothing(live_server: tuple[int, pathlib.Path], extra: str) -> None:
    port, data_dir = live_server
    status, body = _status_and_json(_partial_upload(port, extra))
    assert (status, body) == (401, DETAIL)
    jobs = data_dir / "jobs"
    assert not jobs.exists() or not any(jobs.iterdir())
    assert httpx.get(f"http://127.0.0.1:{port}/api/v1/jobs", headers=GOOD).json() == []


def test_right_token_still_uploads_through_a_real_server(live_server: tuple[int, pathlib.Path]) -> None:
    port, data_dir = live_server
    url = f"http://127.0.0.1:{port}/api/v1/jobs"
    with CLIP.open("rb") as fh:
        r = httpx.post(url, headers=GOOD, files={"file": ("bant.mp4", fh, "video/mp4")}, timeout=60)
    assert r.status_code == 202, r.text
    job = r.json()
    assert (data_dir / "jobs" / job["id"]).is_dir()
    assert httpx.delete(f"{url}/{job['id']}", headers=GOOD, timeout=30).status_code == 204


def test_refused_request_never_reaches_the_app(tmp_path: pathlib.Path) -> None:
    """Yöntem ve bilinmeyen yol da anahtarı önce sorar: 405 ve 404 de anahtarsız 401 olur, anahtarlı aynı kalır."""
    with local_client(create_app(Settings(data_dir=tmp_path, token=TOKEN))) as c:
        for method, path in [("GET", "/api/v1/jobs"), ("PUT", "/api/v1/jobs"), ("GET", "/api/v1/yok"), ("GET", "/api/yok"),
                             ("POST", "/api/v1/live/views"), ("DELETE", "/api/v1/system/status")]:
            r = c.request(method, path)
            assert (r.status_code, r.json()) == (401, DETAIL), (method, path)
        assert c.get("/api/v1/yok", headers=GOOD).status_code == 404
        assert c.put("/api/v1/jobs", headers=GOOD).status_code == 405


def test_non_api_paths_are_unchanged(tmp_path: pathlib.Path) -> None:
    with local_client(create_app(Settings(data_dir=tmp_path, token=TOKEN))) as c:
        assert c.get("/healthz").status_code == 200
        for path in ("/docs", "/redoc", "/openapi.json", "/", "/api", "/apix/v1/jobs"):
            assert c.get(path).status_code == 404, path


def test_cors_preflight_needs_no_token_and_the_refusal_is_readable(tmp_path: pathlib.Path) -> None:
    """Listedeki site: ön uçuş anahtar göndermez, CORS yanıtlar; 401 de CORS başlığı taşır ki site nedenini okuyabilsin."""
    origin = "https://panel.example"
    with local_client(create_app(Settings(data_dir=tmp_path, token=TOKEN, cors_origins=[origin]))) as c:
        pre = c.options("/api/v1/jobs", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
        assert pre.status_code == 200 and pre.headers["access-control-allow-origin"] == origin
        r = c.get("/api/v1/jobs", headers={"Origin": origin})
        assert r.status_code == 401 and r.headers["access-control-allow-origin"] == origin


def test_no_token_mode_has_no_token_check(tmp_path: pathlib.Path) -> None:
    with local_client(create_app(Settings(data_dir=tmp_path))) as c:
        assert c.get("/api/v1/jobs").status_code == 200


@pytest.mark.parametrize(("token", "header", "want"), [
    ("gizli", "Bearer gizli", True),
    ("gizli", "Bearer yanlis", False),
    ("gizli", "gizli", False),
    ("gizli", "", False),
    ("gizli", None, False),
    ("gizlişifre", "Bearer gizlişifre".encode().decode("latin-1"), True),      # panel UTF-8 baytlarını gönderir
    ("gizlişifre", "Bearer gizlişifre".encode("latin-1", "replace").decode("latin-1"), False),
    ("\ud800", "Bearer x", False),                                             # kodlanamayan anahtar hata vermez
])
def test_token_matches_is_the_one_comparison(token: str, header: str | None, want: bool) -> None:
    from bantvision.analyzer.app import token_matches

    assert token_matches(header, token) is want


# Aynı değer iki tarafta (panel: analyzerRefusal.mjs `bearerHeader`, testi aynı biçimleri sınar) aynı anahtara iner. JS `trim`
# BOM'u atar, U+0085'i atmaz; Python `str.strip` tersini yapıyordu.
@pytest.mark.parametrize(("raw", "want"), [
    ("abc", "abc"),
    (" abc\t\r\n", "abc"),
    ("﻿abc", "abc"),
    ("abc﻿", "abc"),
    ("abc\u0085", "abc\u0085"),
    ("\u0085abc", "\u0085abc"),
    ("abc\x1c", "abc\x1c"),
    (" abc　", "abc"),
    ("a b", "a b"),
    ("", None),
    (" \t\r\n 　﻿", None),
])
def test_token_from_env_strips_the_js_trim_set(monkeypatch: pytest.MonkeyPatch, raw: str, want: str | None) -> None:
    monkeypatch.setenv("ANALYZER_TOKEN", raw)
    assert token_from_env() == want
