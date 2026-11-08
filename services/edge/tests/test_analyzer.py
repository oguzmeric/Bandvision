"""Video analiz sunucusu (docs/13-web-platform.md): uçtan uca API, sözleşme, güvenlik, saklama süresi."""
from __future__ import annotations

import datetime as dt
import importlib.metadata
import json
import logging
import os
import pathlib
import subprocess
import sys
import textwrap
import time
import tomllib
import warnings
from typing import Any, ClassVar

import anyio
import pytest
from conftest import local_client
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from bantvision.analyzer import JobStore, Settings, Worker, create_app

ROOT = pathlib.Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "contracts"
CLIP = ROOT / "apps" / "ios" / "BantSayacUITests" / "ui_test_clip.mp4"
CLIP_META = json.loads((ROOT / "apps" / "ios" / "BantSayacUITests" / "ui_test_clip.json").read_text(encoding="utf-8"))
PYPROJECT = ROOT / "services" / "edge" / "pyproject.toml"


@pytest.fixture(scope="module")
def job_validator() -> Draft202012Validator:
    schemas = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in CONTRACTS.glob("*.schema.json")}
    registry = Registry().with_resources([(n, Resource.from_contents(s)) for n, s in schemas.items()])
    for s in schemas.values():
        registry = registry.with_resource(s["$id"], Resource.from_contents(s))
    return Draft202012Validator(schemas["analysis-job.schema.json"], registry=registry,
                                format_checker=Draft202012Validator.FORMAT_CHECKER)


def assert_contract(v: Draft202012Validator, job: dict[str, Any]) -> None:
    errs = ["/".join(map(str, e.absolute_path)) + ": " + e.message for e in v.iter_errors(job)]
    assert errs == [], errs


def wait_done(client: TestClient, job_id: str, timeout: float = 240) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.5)
    raise AssertionError("iş zamanında bitmedi")


@pytest.fixture()
def client(tmp_path: pathlib.Path) -> TestClient:
    with local_client(create_app(Settings(data_dir=tmp_path))) as c:
        yield c


def test_upload_analyze_and_download(client: TestClient, job_validator: Draft202012Validator) -> None:
    """Test klibi: sayım Python referansıyla aynı, işaretli video H.264, sonuç sözleşmeye uygun."""
    options = {"preset": "egg", "truth": CLIP_META["count"], "bgRange": [0, CLIP_META["emptySeconds"] - 0.3]}
    with CLIP.open("rb") as fh:
        r = client.post("/api/v1/jobs", files={"file": ("bant.mp4", fh, "video/mp4")},
                        data={"options": json.dumps(options)})
    assert r.status_code == 202, r.text
    job = r.json()
    assert_contract(job_validator, job)
    assert job["status"] == "queued" and job["video"]["sizeBytes"] == CLIP.stat().st_size

    job = wait_done(client, job["id"])
    assert job["status"] == "done", job.get("error")
    assert_contract(job_validator, job)
    res = job["result"]
    assert res["count"] == CLIP_META["count"] and res["errorPct"] == 0
    assert set(res["files"]) == {"annotated.mp4", "counts.csv", "profile.json", "background.png"}
    assert job["video"]["width"] == 720 and job["video"]["height"] == 1280 and job["progress"] == 1.0

    csv = client.get(f"/api/v1/jobs/{job['id']}/files/counts.csv")
    assert csv.status_code == 200 and "attachment" in csv.headers["content-disposition"]
    assert len(csv.text.strip().splitlines()) >= 2

    video = client.get(f"/api/v1/jobs/{job['id']}/files/annotated.mp4")
    assert video.status_code == 200 and video.headers["content-type"] == "video/mp4"
    path = pathlib.Path(client.app.state.settings.data_dir) / "probe.mp4"
    path.write_bytes(video.content)
    info = subprocess.run([client.app.state.settings.ffmpeg_exe(), "-hide_banner", "-i", str(path)],
                          capture_output=True, text=True, check=False).stderr
    assert "Video: h264" in info and "yuv420p" in info, info      # tarayıcıda oynar

    part = client.get(f"/api/v1/jobs/{job['id']}/files/annotated.mp4", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100   # oynatıcıda ileri/geri sarma

    assert [j["id"] for j in client.get("/api/v1/jobs").json()] == [job["id"]]
    assert client.delete(f"/api/v1/jobs/{job['id']}").status_code == 204
    assert client.get(f"/api/v1/jobs/{job['id']}").status_code == 404


def test_rejects_bad_uploads(client: TestClient, tmp_path: pathlib.Path) -> None:
    r = client.post("/api/v1/jobs", files={"file": ("not.txt", b"hello", "text/plain")})
    assert r.status_code == 415
    r = client.post("/api/v1/jobs", files={"file": ("bozuk.mp4", b"\x00" * 4096, "video/mp4")})
    assert r.status_code == 400 and "okunamadı" in r.json()["detail"]
    r = client.post("/api/v1/jobs", files={"file": ("bos.mp4", b"", "video/mp4")})
    assert r.status_code == 400
    for bad in ('{"preset": "palet"}', '{"countMode": "ai"}', '{"sahibi": "x"}',
                '{"roiPolygon": [{"x": 0.1, "y": 0.1}]}', "{bozuk"):
        with CLIP.open("rb") as fh:
            r = client.post("/api/v1/jobs", files={"file": ("a.mp4", fh, "video/mp4")}, data={"options": bad})
        assert r.status_code == 422, bad
    assert client.get("/api/v1/jobs").json() == []            # reddedilen yüklemelerden iz kalmaz
    assert not any((tmp_path / "jobs").iterdir())


def test_upload_size_limit(tmp_path: pathlib.Path) -> None:
    with local_client(create_app(Settings(data_dir=tmp_path, max_upload_mb=0))) as c, CLIP.open("rb") as fh:
        r = c.post("/api/v1/jobs", files={"file": ("a.mp4", fh, "video/mp4")})
    assert r.status_code == 413
    assert not any((tmp_path / "jobs").iterdir())


def test_token_required_when_configured(tmp_path: pathlib.Path) -> None:
    with local_client(create_app(Settings(data_dir=tmp_path, token="gizli"))) as c:
        assert c.get("/api/v1/jobs").status_code == 401
        assert c.get("/api/v1/jobs", headers={"Authorization": "Bearer yanlis"}).status_code == 401
        assert c.get("/api/v1/jobs", headers={"Authorization": "Bearer gizli"}).status_code == 200
        assert c.get("/healthz").status_code == 200


def test_non_ascii_token_is_compared_as_utf8_bytes(tmp_path: pathlib.Path) -> None:
    """Türkçe karakterli anahtar çalışır: başlığın baytları anahtarın UTF-8 baytlarıyla karşılaştırılır (500 yok)."""
    app = create_app(Settings(data_dir=tmp_path, token="gizlişifre"))
    with local_client(app, raise_server_exceptions=False) as c:
        assert c.get("/api/v1/jobs", headers={"Authorization": "Bearer gizlişifre".encode()}).status_code == 200
        for wrong in (b"Bearer yanlis", "Bearer gizlişifrex".encode(), b"Bearer gizlisifre", b"gizli"):
            assert c.get("/api/v1/jobs", headers={"Authorization": wrong}).status_code == 401, wrong
        assert c.get("/api/v1/jobs").status_code == 401


def test_non_ascii_header_under_ascii_token_is_401(tmp_path: pathlib.Path) -> None:
    with local_client(create_app(Settings(data_dir=tmp_path, token="gizli")), raise_server_exceptions=False) as c:
        r = c.get("/api/v1/jobs", headers={"Authorization": "Bearer gizlişifre".encode()})
        assert r.status_code == 401 and r.json()["detail"] == "Yetkisiz: geçerli bir erişim anahtarı gerekli."
        assert c.get("/api/v1/jobs", headers={"Authorization": b"Bearer gizli"}).status_code == 200


def _asgi_status(app: Any, headers: list[tuple[bytes, bytes]]) -> int:
    """`GET /api/v1/jobs` doğrudan ASGI ile: TestClient başlığı hep UTF-8'e çevirir, UTF-8 olmayan ham bayt gönderemez."""
    statuses: list[int] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg: Any) -> None:
        if msg["type"] == "http.response.start":
            statuses.append(msg["status"])

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
             "path": "/api/v1/jobs", "raw_path": b"/api/v1/jobs", "query_string": b"", "root_path": "",
             "headers": headers, "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8090)}
    anyio.run(app, scope, receive, send)
    return statuses[0]


@pytest.mark.parametrize("surrogate", [0xD800, 0xDBFF, 0xDC00, 0xDFFF])
def test_token_with_lone_surrogate_is_401_not_500(tmp_path: pathlib.Path, surrogate: int) -> None:
    """Kodlanamayan anahtar 500 vermez. Başka değer de eşleşmez: `ignore` `Bearer gizli`yi, `replace` `Bearer gizli?`yi,
    `backslashreplace` kaçış metnini kabul ederdi."""
    app = create_app(Settings(data_dir=tmp_path, token="gizli" + chr(surrogate)))
    with local_client(app, raise_server_exceptions=False) as c:
        assert c.get("/api/v1/jobs").status_code == 401
        for wrong in (b"Bearer gizli", b"Bearer gizli?", f"Bearer gizli{chr(92)}u{surrogate:04x}".encode()):
            assert c.get("/api/v1/jobs", headers={"Authorization": wrong}).status_code == 401, wrong
        assert c.get("/healthz").status_code == 200


def test_surrogateescape_token_matches_its_original_bytes(tmp_path: pathlib.Path) -> None:
    """POSIX'te UTF-8 olmayan ortam değeri bu biçimde gelir: süreç hangi baytlarla başladıysa, istemci onları gönderince
    eşleşir."""
    original = b"gizli\xff\xfe"
    app = create_app(Settings(data_dir=tmp_path, token=original.decode("utf-8", "surrogateescape")))
    assert _asgi_status(app, [(b"authorization", b"Bearer " + original)]) == 200
    for wrong in (b"Bearer gizli", b"Bearer gizli??", b"Bearer gizli\xff"):
        assert _asgi_status(app, [(b"authorization", wrong)]) == 401, wrong
    assert _asgi_status(app, []) == 401


def test_token_mixing_escape_and_lone_surrogates_does_not_raise(tmp_path: pathlib.Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, token="gizli" + chr(0xDCFF) + chr(0xD800)))
    assert _asgi_status(app, []) == 401
    assert _asgi_status(app, [(b"authorization", b"Bearer gizli\xff")]) == 401


def test_unknown_ids_and_files_are_404(client: TestClient) -> None:
    assert client.get("/api/v1/jobs/../../etc/passwd").status_code == 404
    assert client.get("/api/v1/jobs/not-a-uuid").status_code == 404
    assert client.get("/api/v1/jobs/8b0f3c2e-61a4-4d0e-9a7f-2c5d1e9b4a10/files/annotated.mp4").status_code == 404


def test_retention_expires_files_but_keeps_summary(tmp_path: pathlib.Path,
                                                   job_validator: Draft202012Validator) -> None:
    store = JobStore(Settings(data_dir=tmp_path, retention_days=7))
    job, _ = store.create("a.mp4", 10, {}, ".mp4")
    out = store.dir(job["id"]) / "out"
    (out / "annotated.mp4").write_bytes(b"x")
    (out / "counts.csv").write_text("a;b\n", encoding="utf-8")
    store.update(job["id"], status="done", progress=1.0,
                 result={"count": 5, "truth": None, "errorPct": None, "processingFps": None,
                         "files": ["annotated.mp4", "counts.csv"]})
    assert store.expire(dt.datetime.now(dt.UTC) + dt.timedelta(days=6)) == []      # süre dolmadı
    assert store.expire(dt.datetime.now(dt.UTC) + dt.timedelta(days=8)) == [job["id"]]
    after = store.get(job["id"])
    assert after is not None and after["status"] == "expired" and after["result"]["count"] == 5
    assert after["result"]["files"] == [] and store.file(job["id"], "annotated.mp4") is None
    assert [p.name for p in store.dir(job["id"]).iterdir()] == ["job.json"]
    assert_contract(job_validator, after)


def test_restart_recovery(tmp_path: pathlib.Path) -> None:
    store = JobStore(Settings(data_dir=tmp_path))
    running, _ = store.create("r.mp4", 10, {}, ".mp4")
    store.update(running["id"], status="running", stage="counting", progress=0.4)
    queued, _ = store.create("q.mp4", 10, {}, ".mp4")
    worker = Worker(store)
    worker.recover()
    failed = store.get(running["id"])
    assert failed is not None and failed["status"] == "failed" and "yeniden başladı" in failed["error"]
    assert worker.queue.get_nowait() == queued["id"]


def test_failed_analysis_is_reported(client: TestClient, job_validator: Draft202012Validator) -> None:
    """Kalibrasyon yapılamazsa (boş bant aralığı videodan sonra) iş anlaşılır hatayla biter."""
    with CLIP.open("rb") as fh:
        r = client.post("/api/v1/jobs", files={"file": ("a.mp4", fh, "video/mp4")},
                        data={"options": json.dumps({"bgRange": [500, 501]})})
    job = wait_done(client, r.json()["id"])
    assert job["status"] == "failed" and "Kalibrasyon" in job["error"], job
    assert_contract(job_validator, job)


def test_linescan_options_reach_video_tool() -> None:
    """Şerit tarama seçenekleri (§4.9) komut satırına geçer."""
    from bantvision.analyzer.jobs import options_to_args
    args = options_to_args({"preset": "box", "countMode": "linescan", "productLength": 0.3})
    assert args == ["--preset", "box", "--mode", "linescan", "--product-length", "0.3"]


def test_people_options_reach_video_tool() -> None:
    """Kişi sayımı seçenekleri (§4.10): hazır profil, kamera konumu, giriş yönü ve çizgi komut satırına geçer."""
    from bantvision.analyzer.jobs import options_to_args
    args = options_to_args({"preset": "people", "countAnchor": "bottom", "direction": "up", "line": 0.6})
    assert args == ["--preset", "people", "--anchor", "bottom", "--direction", "up", "--line", "0.6"]


def test_people_options_validate_against_contract() -> None:
    from bantvision.analyzer.app import OptionsIn
    o = OptionsIn.model_validate({"preset": "people", "countMode": "detect", "countAnchor": "center"})
    assert o.countAnchor == "center"
    with pytest.raises(ValueError):
        OptionsIn.model_validate({"preset": "people", "countAnchor": "ayak"})


def test_system_status_shape(tmp_path: pathlib.Path) -> None:
    with local_client(create_app(Settings(data_dir=tmp_path, token="gizli"))) as c:
        assert c.get("/api/v1/system/status").status_code == 401
        r = c.get("/api/v1/system/status", headers={"Authorization": "Bearer gizli"})
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {"cpuPercent", "uptimeS", "version", "commit", "gpu"}
        assert isinstance(body["cpuPercent"], float) and 0.0 <= body["cpuPercent"] <= 100.0
        assert isinstance(body["uptimeS"], int) and body["uptimeS"] >= 0
        assert isinstance(body["version"], str) and body["version"]
        assert isinstance(body["commit"], str) and body["commit"]


class _FakeGpuLoad:
    """Sahte PDH örnekleyici: kaç örnek oluşturulduğunu ve hangi LUID'lerin sorulduğunu kaydeder."""
    instances = 0
    asked: ClassVar[list[str]] = []
    value: float | None = 37.5
    closed = 0

    def __init__(self) -> None:
        type(self).instances += 1

    def percent(self, luid: str) -> float | None:
        type(self).asked.append(luid)
        return type(self).value

    def close(self) -> None:
        type(self).closed += 1


def _fake_gpus(monkeypatch: pytest.MonkeyPatch, gpus: list[Any], auto: str = "cpu") -> type[_FakeGpuLoad]:
    from bantvision.core import devices, gpu_load
    _FakeGpuLoad.instances, _FakeGpuLoad.asked, _FakeGpuLoad.value, _FakeGpuLoad.closed = 0, [], 37.5, 0
    monkeypatch.setattr(devices, "list_gpus", lambda *a, **k: list(gpus))
    monkeypatch.setattr(devices, "auto_choice", lambda *a, **k: auto)
    monkeypatch.setattr(gpu_load, "GpuLoad", _FakeGpuLoad)
    return _FakeGpuLoad


def _gpu(gid: str, name: str, luid: str, index: int = 0) -> Any:
    from bantvision.core.devices import Gpu
    return Gpu(gid, name, 4096, index, luid)


def test_system_status_gpu_is_null_without_any_gpu(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_gpus(monkeypatch, [])
    with local_client(create_app(Settings(data_dir=tmp_path))) as c:
        assert c.get("/api/v1/system/status").json()["gpu"] is None
    assert fake.instances == 0 and fake.asked == []


def test_system_status_gpu_follows_detector_then_pose_then_auto(tmp_path: pathlib.Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """R12: canlı algılayıcının kartı; yoksa poz modelinin kartı; yoksa `auto` kartı. Sorgulanan LUID o kartınkidir."""
    fake = _fake_gpus(monkeypatch, [_gpu("gpu-8086-a7a8", "Intel kart", "0x00000000_0x000132d5", 0),
                                    _gpu("gpu-10de-28a1", "NVIDIA kart", "0x00000000_0x000153a6", 1)],
                      auto="gpu-10de-28a1")
    app = create_app(Settings(data_dir=tmp_path))
    live = app.state.live
    gpu_dev = lambda gid: {"state": "ready", "device": {"id": gid, "kind": "gpu", "name": "x"}, "note": None}
    cpu_dev = {"state": "ready", "device": {"id": "cpu", "kind": "cpu", "name": "İşlemci"}, "note": None}
    idle = {"state": "idle", "device": None, "note": None}
    with local_client(app) as c:
        monkeypatch.setattr(live.detector, "status", lambda: gpu_dev("gpu-8086-a7a8"))
        monkeypatch.setattr(live.pose, "status", lambda: gpu_dev("gpu-10de-28a1"))
        assert c.get("/api/v1/system/status").json()["gpu"] == {"name": "Intel kart", "percent": 37.5}
        assert fake.asked[-1] == "0x00000000_0x000132d5"
        monkeypatch.setattr(live.detector, "status", lambda: cpu_dev)             # algılayıcı işlemcide: poz kartı
        assert c.get("/api/v1/system/status").json()["gpu"] == {"name": "NVIDIA kart", "percent": 37.5}
        assert fake.asked[-1] == "0x00000000_0x000153a6"
        monkeypatch.setattr(live.pose, "status", lambda: idle)                    # ikisi de kart değil: auto
        assert c.get("/api/v1/system/status").json()["gpu"] == {"name": "NVIDIA kart", "percent": 37.5}
        monkeypatch.setattr(live.detector, "status", lambda: idle)
        fake.value = None                                                         # yük bilinmiyor: ad yine var
        assert c.get("/api/v1/system/status").json()["gpu"] == {"name": "NVIDIA kart", "percent": None}
    assert fake.instances == 1                                                    # uygulama başına tek örnekleyici


def test_lifespan_shutdown_closes_gpu_sampler_even_if_stop_raises(tmp_path: pathlib.Path,
                                                                  monkeypatch: pytest.MonkeyPatch,
                                                                  caplog: pytest.LogCaptureFixture) -> None:
    """Kapanışta bir stop() hata verse de sonraki adımlar çalışır (hata günlüğe yazılır) ve PDH sorgusu kapanır;
    yeniden girilen lifespan taze örnekleyici kurar."""
    fake = _fake_gpus(monkeypatch, [_gpu("gpu-10de-28a1", "NVIDIA kart", "0x00000000_0x000153a6")],
                      auto="gpu-10de-28a1")
    app = create_app(Settings(data_dir=tmp_path))
    live = app.state.live
    ran: list[str] = []

    def boom() -> None:
        ran.append("worker")
        raise RuntimeError("worker durmadı")

    def boom_viewers() -> None:
        ran.append("viewers")
        raise RuntimeError("okuyucular durmadı")

    monkeypatch.setattr(live.viewers, "stop", boom_viewers)
    monkeypatch.setattr(app.state.worker, "stop", boom)
    for name, obj in (("clips", live.clips), ("notifier", live.notifier)):
        real = obj.stop
        monkeypatch.setattr(obj, "stop", lambda real=real, name=name: (ran.append(name), real())[1])
    with caplog.at_level(logging.ERROR), local_client(app) as c:                # kapanış hatası dışarı taşmaz
        assert c.get("/api/v1/system/status").json()["gpu"]["percent"] == 37.5
    assert ran == ["viewers", "worker", "clips", "notifier"]                      # hatadan sonraki adımlar da çalıştı
    failed = [r for r in caplog.records if "Kapanışta adım başarısız" in r.getMessage()]
    assert [r.getMessage() for r in failed] == ["Kapanışta adım başarısız: izleme okuyucuları",
                                                "Kapanışta adım başarısız: video işçisi"]
    assert all(r.exc_info for r in failed)
    assert fake.instances == 1 and fake.closed == 1
    monkeypatch.undo()
    _fake_gpus(monkeypatch, [_gpu("gpu-10de-28a1", "NVIDIA kart", "0x00000000_0x000153a6")], auto="gpu-10de-28a1")
    with local_client(app) as c2:                                                 # aynı uygulama, yeni lifespan
        assert c2.get("/api/v1/system/status").json()["gpu"]["percent"] == 37.5
    assert _FakeGpuLoad.instances == 1 and _FakeGpuLoad.closed == 1


def test_system_status_gpu_id_not_listed_is_null(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_gpus(monkeypatch, [_gpu("gpu-8086-a7a8", "Intel kart", "0x00000000_0x000132d5")], auto="gpu-10de-28a1")
    with local_client(create_app(Settings(data_dir=tmp_path))) as c:
        assert c.get("/api/v1/system/status").json()["gpu"] is None


def test_system_status_survives_gpu_lookup_failure(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                                   caplog: pytest.LogCaptureFixture) -> None:
    from bantvision.core import devices

    def boom(*a: object, **k: object) -> list[Any]:
        raise RuntimeError("dxgi")

    monkeypatch.setattr(devices, "list_gpus", boom)
    with caplog.at_level(logging.WARNING), local_client(create_app(Settings(data_dir=tmp_path))) as c:
        for _ in range(2):
            r = c.get("/api/v1/system/status")
            assert r.status_code == 200 and r.json()["gpu"] is None and r.json()["uptimeS"] >= 0
    assert sum("Ekran kartı yükü" in m for m in caplog.messages) == 1


def test_system_status_without_psutil_reports_cpu_null(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                                        caplog: pytest.LogCaptureFixture) -> None:
    """Eski kurulumda psutil yoksa durum ucu yine 200 döner: işlemci yükü bilinmiyor (`null`), uyarı günlüğe bir kez."""
    monkeypatch.setitem(sys.modules, "psutil", None)                  # `import psutil` ImportError verir
    with caplog.at_level(logging.WARNING), local_client(create_app(Settings(data_dir=tmp_path))) as c:
        for _ in range(2):
            r = c.get("/api/v1/system/status")
            assert r.status_code == 200
            body = r.json()
            assert body["cpuPercent"] is None and isinstance(body["uptimeS"], int) and body["commit"]
    assert sum("psutil" in m for m in caplog.messages) == 1


def test_analyzer_starts_and_serves_status_without_psutil(tmp_path: pathlib.Path) -> None:
    """Güncellemeden önceki kurulum: psutil hiç kurulu değilken analiz sunucusu modülü içe aktarılır ve durum ucu çalışır
    (ayrı süreçte; psutil hiç yüklenmeden)."""
    code = textwrap.dedent("""
        import json, pathlib, sys, warnings
        sys.modules["psutil"] = None
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient
        from bantvision.analyzer.app import create_app
        from bantvision.analyzer.jobs import Settings
        # conftest.local_client ile aynı (ayrı süreçte conftest yok): anahtarsız kipte Host bu bilgisayarın adı olmalı
        app = create_app(Settings(data_dir=pathlib.Path(sys.argv[1])))
        with TestClient(app, base_url="http://127.0.0.1") as c:
            r = c.get("/api/v1/system/status")
            print(json.dumps({"status": r.status_code, "body": r.json()}))
    """)
    out = subprocess.run([sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True, encoding="utf-8",
                         timeout=120, cwd=pathlib.Path(__file__).resolve().parents[1], check=False,
                         env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert out.returncode == 0, out.stderr[-2000:]
    res = json.loads(out.stdout.strip().splitlines()[-1])
    assert res["status"] == 200 and res["body"]["cpuPercent"] is None


def test_system_status_version_reads_distribution_named_in_pyproject(tmp_path: pathlib.Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """Sürüm, pyproject.toml'daki `name` adlı dağıtımdan okunur ("bantvision" adında bir dağıtım yok). Paket kurulu olsun
    olmasın (yalnızca PYTHONPATH ile çalıştırma) aynı sonuç: yalnızca bu dağıtımın bilgisi sahtelenir (ad ve sürüm
    pyproject'ten); öteki paketler gerçek bilgiyi okur."""
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    real = importlib.metadata.version

    def installed(name: str) -> str:
        return str(project["version"]) if name == project["name"] else real(name)

    monkeypatch.setattr(importlib.metadata, "version", installed)
    assert importlib.metadata.version("pytest") == real("pytest")             # başka paketler etkilenmez
    with local_client(create_app(Settings(data_dir=tmp_path))) as c:
        assert c.get("/api/v1/system/status").json()["version"] == project["version"]


def test_system_status_version_unknown_without_package(tmp_path: pathlib.Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    real = importlib.metadata.version

    def missing(name: str) -> str:
        if name == project["name"]:
            raise importlib.metadata.PackageNotFoundError(name)
        return real(name)

    monkeypatch.setattr(importlib.metadata, "version", missing)
    assert importlib.metadata.version("pytest") == real("pytest")
    with local_client(create_app(Settings(data_dir=tmp_path))) as c:
        assert c.get("/api/v1/system/status").json()["version"] == "?"


def test_system_status_commit_from_env(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BV_COMMIT", "abc1234")
    with local_client(create_app(Settings(data_dir=tmp_path))) as c:
        assert c.get("/api/v1/system/status").json()["commit"] == "abc1234"


API_DOCS = ("/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json")


def test_api_docs_not_served_with_token(tmp_path: pathlib.Path) -> None:
    """Erişim anahtarı tanımlıyken anahtarsız açık tek uç /healthz'dir: API belge sayfaları ve şema sunulmaz."""
    with local_client(create_app(Settings(data_dir=tmp_path, token="gizli"))) as c:
        for path in API_DOCS:
            assert c.get(path).status_code == 404, path
            assert c.get(path, headers={"Authorization": "Bearer gizli"}).status_code == 404, path
        assert c.get("/healthz").status_code == 200
        assert c.get("/api/v1/system/status").status_code == 401


def test_api_docs_served_without_token(tmp_path: pathlib.Path) -> None:
    """Anahtarsız (yerel geliştirme) belge sayfaları eskisi gibi açık."""
    with local_client(create_app(Settings(data_dir=tmp_path))) as c:
        for path in API_DOCS:
            assert c.get(path).status_code == 200, path
        assert "/api/v1/system/status" in c.get("/openapi.json").json()["paths"]


def test_openapi_schema_has_no_warnings_and_unique_operation_ids(tmp_path: pathlib.Path) -> None:
    """Şema üretimi uyarısızdır: GET ve HEAD aynı işlem kimliğini paylaşmaz (alarm kaydı ve olay resmi)."""
    app = create_app(Settings(data_dir=tmp_path))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        schema = app.openapi()
    ops = [op["operationId"] for item in schema["paths"].values() for op in item.values()]
    assert len(ops) == len(set(ops))
    for path in ("/api/v1/live/alarms/{alarm_id}/clip.webm", "/api/v1/live/alarms/{alarm_id}/image.jpg"):
        assert set(schema["paths"][path]) == {"get", "head"}, path


class _FakeProc:
    def __init__(self) -> None:
        self.stdout: list[str] = []

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        pass


def _run_fake_job(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, summary: dict[str, Any],
                  worker_kwargs: dict[str, Any], options: dict[str, Any] | None = None,
                  extra_files: dict[str, bytes] | None = None) -> tuple[list[str], dict[str, Any]]:
    """Gerçek video süreci yerine sahte Popen: komut satırını yakalar, `ozet.json`'u verilen özetle ve `extra_files`'ı
    (alarmlar.csv, alarm-N.jpg…) ham çıktı klasörüne yazar."""
    from bantvision.analyzer import jobs
    store = JobStore(Settings(data_dir=tmp_path))
    job, path = store.create("a.mp4", 10, options or {}, ".mp4")
    path.write_bytes(b"x")
    cmds: list[list[str]] = []

    def fake_popen(cmd: list[str], **kw: Any) -> _FakeProc:
        cmds.append(cmd)
        raw = pathlib.Path(cmd[cmd.index("--out") + 1])
        (raw / "ozet.json").write_text(json.dumps(summary), encoding="utf-8")
        for name, data in (extra_files or {}).items():
            (raw / name).write_bytes(data)
        return _FakeProc()

    monkeypatch.setattr(jobs.subprocess, "Popen", fake_popen)
    worker = Worker(store, **worker_kwargs)
    worker.process(job["id"])
    done = store.get(job["id"])
    assert done is not None
    return cmds[0], done


SUMMARY = {"video": "a.mp4", "fps": 30.0, "seconds": 3.0, "size": [64, 48], "count": 4, "truth": None,
           "errorPct": None, "calibration": {}, "processingFps": 50.0}


def test_worker_passes_device_choice_to_video_tool(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cmd, done = _run_fake_job(tmp_path, monkeypatch, SUMMARY, {"device_choice": lambda: "auto"})
    assert cmd[cmd.index("--device") + 1] == "auto"
    assert done["status"] == "done" and "device" not in done["result"]


def test_worker_device_choice_defaults_to_cpu(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cmd, _ = _run_fake_job(tmp_path, monkeypatch, SUMMARY, {})
    assert cmd[cmd.index("--device") + 1] == "cpu"


def test_worker_copies_summary_device_to_result(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                                job_validator: Draft202012Validator) -> None:
    dev = {"kind": "gpu", "name": "NVIDIA Laptop GPU", "note": None}
    _, done = _run_fake_job(tmp_path, monkeypatch, {**SUMMARY, "device": dev}, {"device_choice": lambda: "auto"})
    assert done["result"]["device"] == dev
    assert_contract(job_validator, done)


@pytest.mark.parametrize("bad", [None, "gpu", {"kind": "tpu", "name": "x"}, {"kind": "gpu", "name": 3},
                                 {"kind": "gpu"}, {"kind": "cpu", "name": "İşlemci", "note": 5}],
                         ids=str)
def test_worker_omits_malformed_summary_device(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                               job_validator: Draft202012Validator, bad: Any) -> None:
    _, done = _run_fake_job(tmp_path, monkeypatch, {**SUMMARY, "device": bad}, {})
    assert done["status"] == "done" and "device" not in done["result"]
    assert_contract(job_validator, done)


# --- güvenlik alarmı, araç ve hayvan (Video ile test genişlemesi) ---------------------------------------------------------

JPEG = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"fake-jpeg-bytes" + bytes([0xFF, 0xD9])
ALARMS = [
    {"kind": "handsUp", "trackId": 3, "startS": 12.4, "atS": 15.4, "endS": 19.0, "image": "alarm-1.jpg"},
    {"kind": "lying", "trackId": 5, "startS": 61.0, "atS": 71.0, "endS": 95.0, "image": "alarm-2.jpg"},
]
SAFETY_SUMMARY = {**SUMMARY, "count": 2, "alarms": ALARMS, "seconds": 95.0,
                  "device": {"kind": "cpu", "name": "İşlemci", "note": None}}
SAFETY_FILES = {"alarmlar.csv": b"baslangic_sn;alarm_sn\n", "profil.json": b"{}",
                "alarm-1.jpg": JPEG, "alarm-2.jpg": JPEG}
SAFETY_OPTIONS = {"preset": "safety", "safety": {"handsUp": {"seconds": 3}, "lying": {"enabled": False}}}


def _post(client: TestClient, options: dict[str, Any]) -> Any:
    return client.post("/api/v1/jobs", files={"file": ("a.mp4", b"x", "video/mp4")},
                       data={"options": json.dumps(options)})


def _accept_without_analysis(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Yükleme kabul sınaması: sahte bayt "okunabilir video" sayılır ve iş çalıştırılmaz (model/süreç yok)."""
    from bantvision.analyzer import app as app_module
    monkeypatch.setattr(app_module, "_is_readable_video", lambda _path: True)
    monkeypatch.setattr(client.app.state.worker, "submit", lambda _job_id: None)


@pytest.mark.parametrize("preset", ["vehicle", "animal", "safety"])
def test_options_accept_new_presets(preset: str) -> None:
    from bantvision.analyzer.app import OptionsIn
    assert OptionsIn.model_validate({"preset": preset}).preset == preset


def test_options_accept_vehicle_and_animal_with_counting_fields() -> None:
    from bantvision.analyzer.app import OptionsIn
    for preset in ("vehicle", "animal"):
        o = OptionsIn.model_validate({"preset": preset, "countMode": "detect", "countAnchor": "bottom",
                                      "direction": "left", "line": 0.4, "truth": 7})
        assert (o.preset, o.countAnchor, o.truth) == (preset, "bottom", 7)


def test_options_accept_safety_rules_and_keep_only_given_values() -> None:
    from bantvision.analyzer.app import OptionsIn
    o = OptionsIn.model_validate({"preset": "safety", "safety": {"handsUp": {"enabled": True, "seconds": 5},
                                                                 "lying": {"enabled": False}}})
    assert o.model_dump(exclude_none=True) == {
        "preset": "safety", "safety": {"handsUp": {"enabled": True, "seconds": 5.0}, "lying": {"enabled": False}}}
    assert OptionsIn.model_validate({"preset": "safety", "safety": {}}).model_dump(exclude_none=True) == {
        "preset": "safety", "safety": {}}


@pytest.mark.parametrize("rules", [
    {"handsUp": {"seconds": 2.9}}, {"handsUp": {"seconds": 5.1}}, {"lying": {"seconds": 4.9}},
    {"lying": {"seconds": 30.1}}, {"lying": {"seconds": "10"}}, {"handsUp": {"seconds": True}}, {"lying": {"enabled": "false"}},
    {"fire": {"enabled": True}}, {"handsUp": {"seconds": 3, "kind": "x"}}, {"handsUp": {"seconds": float("nan")}},
], ids=str)
def test_options_reject_bad_safety_rules(rules: dict[str, Any]) -> None:
    from bantvision.analyzer.app import OptionsIn
    with pytest.raises(ValueError):
        OptionsIn.model_validate({"preset": "safety", "safety": rules})


def test_safety_rule_range_error_is_turkish_and_422(client: TestClient) -> None:
    r = _post(client, {"preset": "safety", "safety": {"handsUp": {"seconds": 9}}})
    assert r.status_code == 422
    assert "Eller yukarı süresi 3–5 sn arasında bir sayı olmalı." in r.json()["detail"]
    r = _post(client, {"preset": "safety", "safety": {"lying": {"seconds": 1}}})
    assert r.status_code == 422 and "Yerde yatma süresi 5–30 sn arasında bir sayı olmalı." in r.json()["detail"]
    assert client.get("/api/v1/jobs").json() == []


@pytest.mark.parametrize("extra", [
    {"countMode": "detect"}, {"truth": 3}, {"direction": "down"}, {"line": 0.5},
    {"countLine": {"a": {"x": 0.1, "y": 0.1}, "b": {"x": 0.9, "y": 0.9}}},
    {"roi": {"x": 0, "y": 0, "width": 1, "height": 1}},
    {"roiPolygon": [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.5, "y": 0.9}]}, {"bgRange": [0, 1]},
    {"productLength": 0.3}, {"countAnchor": "bottom"},
], ids=lambda e: next(iter(e)))
def test_counting_option_on_safety_is_422_and_creates_no_job(client: TestClient, extra: dict[str, Any]) -> None:
    r = _post(client, {"preset": "safety", **extra})
    assert r.status_code == 422
    assert r.json()["detail"] == "Güvenlik alarmı videosunda sayım ayarları kullanılmaz."
    assert client.get("/api/v1/jobs").json() == []


@pytest.mark.parametrize("preset", ["generic", "egg", "flour", "box", "people", "vehicle", "animal", None])
def test_safety_option_on_counting_preset_is_422_and_creates_no_job(client: TestClient, preset: str | None) -> None:
    options: dict[str, Any] = {"safety": {"lying": {"seconds": 10}}}
    if preset:
        options["preset"] = preset
    r = _post(client, options)
    assert r.status_code == 422
    assert r.json()["detail"] == "Kural ayarları yalnızca güvenlik alarmı videosunda kullanılır."
    assert client.get("/api/v1/jobs").json() == []


def test_both_safety_rules_off_is_422(client: TestClient) -> None:
    r = _post(client, {"preset": "safety", "safety": {"handsUp": {"enabled": False}, "lying": {"enabled": False}}})
    assert r.status_code == 422 and r.json()["detail"] == "En az bir kural açık olmalı."
    assert client.get("/api/v1/jobs").json() == []


def test_safety_job_without_rules_is_accepted(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Kural verilmezse canlıdaki varsayılanlar (eller yukarı 3 sn, yerde yatma 10 sn); tek kural kapalı olabilir."""
    _accept_without_analysis(client, monkeypatch)
    for options in ({"preset": "safety"}, {"preset": "safety", "safety": {"lying": {"enabled": False}}}):
        r = _post(client, options)
        assert r.status_code == 202, r.text
        assert r.json()["options"] == options


@pytest.mark.parametrize("preset", ["vehicle", "animal"])
def test_vehicle_and_animal_jobs_are_accepted_with_counting_options(client: TestClient, monkeypatch: pytest.MonkeyPatch,
                                                                    preset: str) -> None:
    _accept_without_analysis(client, monkeypatch)
    options = {"preset": preset, "countMode": "detect", "countAnchor": "bottom", "direction": "left", "line": 0.4,
               "truth": 7}
    r = _post(client, options)
    assert r.status_code == 202, r.text
    assert r.json()["options"] == options


def test_invalid_options_give_one_short_message_not_a_pydantic_dump(client: TestClient) -> None:
    r = _post(client, {"preset": "bilinmeyen"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail.startswith("Seçenekler geçersiz: preset: ")
    assert "pydantic" not in detail and "validation error" not in detail and len(detail.splitlines()) == 1
    r = _post(client, {"safety": {"handsUp": {"seconds": 9}}, "preset": "safety"})
    assert r.status_code == 422
    assert r.json()["detail"].startswith("Seçenekler geçersiz: safety.handsUp.seconds: ")
    assert "Eller yukarı süresi 3–5 sn arasında bir sayı olmalı." in r.json()["detail"]


def test_safety_options_reach_video_tool() -> None:
    from bantvision.analyzer.jobs import options_to_args
    assert options_to_args({"preset": "safety", "safety": {"handsUp": {"enabled": True, "seconds": 3},
                                                           "lying": {"enabled": False}}}) == [
        "--preset", "safety", "--hands-up", "3", "--no-lying"]
    assert options_to_args({"preset": "safety", "safety": {"handsUp": {"enabled": False},
                                                           "lying": {"seconds": 12.5}}}) == [
        "--preset", "safety", "--no-hands-up", "--lying", "12.5"]
    assert options_to_args({"preset": "safety"}) == ["--preset", "safety"]
    assert options_to_args({"preset": "safety", "safety": {"handsUp": {"enabled": True}}}) == ["--preset", "safety"]


@pytest.mark.parametrize("preset", ["vehicle", "animal"])
def test_vehicle_and_animal_options_reach_video_tool(preset: str) -> None:
    from bantvision.analyzer.jobs import options_to_args
    assert options_to_args({"preset": preset, "countAnchor": "bottom", "direction": "up", "line": 0.6, "truth": 5}) == [
        "--preset", preset, "--truth", "5", "--anchor", "bottom", "--direction", "up", "--line", "0.6"]


def test_worker_safety_result_has_alarms_and_images(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                                    client: TestClient, job_validator: Draft202012Validator) -> None:
    cmd, done = _run_fake_job(tmp_path, monkeypatch, SAFETY_SUMMARY, {}, SAFETY_OPTIONS, SAFETY_FILES)
    assert cmd[cmd.index("--preset") + 1] == "safety" and "--no-lying" in cmd and "--hands-up" in cmd
    assert done["status"] == "done", done.get("error")
    res = done["result"]
    assert res["count"] == 2 and res["alarms"] == ALARMS
    assert res["files"] == ["alarms.csv", "profile.json", "alarm-1.jpg", "alarm-2.jpg"]
    assert res["device"] == {"kind": "cpu", "name": "İşlemci", "note": None}
    assert_contract(job_validator, done)
    assert not (tmp_path / "jobs" / done["id"] / "work").exists()
    for name in ("alarm-1.jpg", "alarm-2.jpg"):
        r = client.get(f"/api/v1/jobs/{done['id']}/files/{name}")
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content == JPEG
        assert r.headers["content-disposition"].startswith("inline")
    r = client.get(f"/api/v1/jobs/{done['id']}/files/alarms.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"].startswith("attachment")


def test_worker_safety_result_without_images_lists_only_moved_files(tmp_path: pathlib.Path,
                                                                    monkeypatch: pytest.MonkeyPatch,
                                                                    job_validator: Draft202012Validator) -> None:
    alarms = [{**ALARMS[0], "image": None}]
    _, done = _run_fake_job(tmp_path, monkeypatch, {**SAFETY_SUMMARY, "count": 1, "alarms": alarms}, {},
                            SAFETY_OPTIONS, {"alarmlar.csv": b"x"})
    assert done["status"] == "done"
    assert done["result"]["alarms"] == alarms and done["result"]["files"] == ["alarms.csv"]
    assert_contract(job_validator, done)


def test_worker_safety_count_is_true_total_beyond_listed_alarms(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                                                job_validator: Draft202012Validator) -> None:
    alarms = [{**ALARMS[0], "image": f"alarm-{i}.jpg" if i <= 50 else None} for i in range(1, 501)]
    images = {f"alarm-{i}.jpg": JPEG for i in range(1, 51)}
    _, done = _run_fake_job(tmp_path, monkeypatch, {**SAFETY_SUMMARY, "count": 730, "alarms": alarms}, {},
                            SAFETY_OPTIONS, images)
    assert done["status"] == "done"
    assert done["result"]["count"] == 730 and len(done["result"]["alarms"]) == 500
    assert done["result"]["files"] == [f"alarm-{i}.jpg" for i in range(1, 51)]
    assert_contract(job_validator, done)


@pytest.mark.parametrize("bad", [
    {"kind": "fire"}, {"trackId": "3"}, {"trackId": True}, {"trackId": 1.5}, {"startS": -1}, {"startS": "1"},
    {"atS": None}, {"endS": "x"}, {"endS": -2}, {"image": "../x.jpg"}, {"image": "alarm-100.jpg"},
    {"image": "alarm-1.jpg.exe"}, {"image": 3}, {"extra": 1},
], ids=lambda d: next(iter(d)) + "=" + repr(next(iter(d.values()))))
def test_worker_fails_job_on_broken_alarm_item(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                               bad: dict[str, Any]) -> None:
    alarms = [ALARMS[0], {**ALARMS[1], **bad}]
    _, done = _run_fake_job(tmp_path, monkeypatch, {**SAFETY_SUMMARY, "alarms": alarms}, {}, SAFETY_OPTIONS,
                            SAFETY_FILES)
    assert done["status"] == "failed" and done["error"] == "Sonuç hazırlanamadı: alarm listesi bozuk"
    assert "result" not in done


def test_worker_fails_job_on_alarm_missing_a_field(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    alarms = [{k: v for k, v in ALARMS[0].items() if k != "endS"}]
    _, done = _run_fake_job(tmp_path, monkeypatch, {**SAFETY_SUMMARY, "alarms": alarms}, {}, SAFETY_OPTIONS,
                            SAFETY_FILES)
    assert done["status"] == "failed" and done["error"] == "Sonuç hazırlanamadı: alarm listesi bozuk"


@pytest.mark.parametrize("alarms", ["x", {"kind": "lying"}, [None], ["alarm"], [ALARMS[0]] * 501],
                         ids=["metin", "nesne", "boş öğe", "metin öğe", "501 alarm"])
def test_worker_fails_job_on_broken_alarm_list(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                               alarms: Any) -> None:
    _, done = _run_fake_job(tmp_path, monkeypatch, {**SAFETY_SUMMARY, "alarms": alarms}, {}, SAFETY_OPTIONS,
                            SAFETY_FILES)
    assert done["status"] == "failed" and done["error"] == "Sonuç hazırlanamadı: alarm listesi bozuk"


def test_worker_accepts_alarm_without_end(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                          job_validator: Draft202012Validator) -> None:
    """Sözleşme `endS: null`'a izin verir (bu araç hiç üretmez, ama başka bir üretici verebilir)."""
    summary = {**SAFETY_SUMMARY, "count": 1, "alarms": [{**ALARMS[0], "endS": None}]}
    _, done = _run_fake_job(tmp_path, monkeypatch, summary, {}, SAFETY_OPTIONS, SAFETY_FILES)
    assert done["status"] == "done" and done["result"]["alarms"][0]["endS"] is None
    assert_contract(job_validator, done)


def test_counting_job_result_has_no_alarms(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, done = _run_fake_job(tmp_path, monkeypatch, SUMMARY, {})
    assert "alarms" not in done["result"]


@pytest.mark.parametrize("preset", ["vehicle", "animal"])
def test_worker_vehicle_and_animal_result_is_two_way(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                                     job_validator: Draft202012Validator, preset: str) -> None:
    summary = {**SUMMARY, "count": 5, "countOut": 3, "truth": 5, "errorPct": 0.0}
    _, done = _run_fake_job(tmp_path, monkeypatch, summary, {}, {"preset": preset, "truth": 5})
    assert done["result"]["count"] == 5 and done["result"]["countOut"] == 3
    assert "alarms" not in done["result"]
    assert_contract(job_validator, done)


@pytest.mark.parametrize("name", ["alarm-999.jpg", "alarm-1.jpg.exe", "alarm-.jpg", "alarm-a.jpg", "ALARM-1.jpg",
                                  "alarm-1.JPG", "alarm-100.jpg", "alarm-1.jpg%0a", "..%2fprofile.json", "x.jpg",
                                  "job.json", "input.mp4", "%2e%2e%2fjob.json", "alarm-1%2ejpg.exe",
                                  "alarmlar.csv", "ozet.json"])
def test_files_route_refuses_unknown_names(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, client: TestClient,
                                           name: str) -> None:
    _, done = _run_fake_job(tmp_path, monkeypatch, SAFETY_SUMMARY, {}, SAFETY_OPTIONS, SAFETY_FILES)
    assert client.get(f"/api/v1/jobs/{done['id']}/files/{name}").status_code == 404


def test_files_route_refuses_traversal_from_alarm_name(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                                       client: TestClient) -> None:
    _, done = _run_fake_job(tmp_path, monkeypatch, SAFETY_SUMMARY, {}, SAFETY_OPTIONS, SAFETY_FILES)
    (tmp_path / "jobs" / done["id"] / "x").write_bytes(b"secret")
    for url in (f"/api/v1/jobs/{done['id']}/files/../x", f"/api/v1/jobs/{done['id']}/files/..%2fx",
                f"/api/v1/jobs/{done['id']}/files/alarm-1.jpg/../../x"):
        assert client.get(url).status_code == 404, url


def test_is_public_file_accepts_fixed_names_and_alarm_images_only() -> None:
    from bantvision.analyzer.jobs import is_public_file
    for ok in ("annotated.mp4", "counts.csv", "alarms.csv", "profile.json", "background.png", "alarm-1.jpg",
               "alarm-50.jpg", "alarm-99.jpg"):
        assert is_public_file(ok), ok
    for bad in ("alarm-100.jpg", "alarm-1.jpg\n", "alarm-1.jpg.exe", "alarm-1.jpeg", "../alarm-1.jpg", "alarm-1.jpg ",
                "", "job.json", "alarmlar.csv", "sayimlar.csv", "ozet.json"):
        assert not is_public_file(bad), bad


def test_expiry_removes_alarm_images_and_empties_files(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                                       client: TestClient, job_validator: Draft202012Validator) -> None:
    _, done = _run_fake_job(tmp_path, monkeypatch, SAFETY_SUMMARY, {}, SAFETY_OPTIONS, SAFETY_FILES)
    store = JobStore(Settings(data_dir=tmp_path))
    from bantvision.analyzer.jobs import now
    later = now() + dt.timedelta(days=30)
    assert store.expire(later) == [done["id"]]
    assert store.file(done["id"], "alarm-1.jpg") is None
    expired = store.get(done["id"])
    assert expired is not None and expired["status"] == "expired"
    assert expired["result"]["files"] == []
    assert len(expired["result"]["alarms"]) == 2 and all(a["image"] is None for a in expired["result"]["alarms"])
    assert [a["atS"] for a in expired["result"]["alarms"]] == [15.4, 71.0]          # liste kalır, yalnız resimler gider
    assert_contract(job_validator, expired)
    assert client.get(f"/api/v1/jobs/{done['id']}/files/alarm-1.jpg").status_code == 404
    assert client.get(f"/api/v1/jobs/{done['id']}/files/alarms.csv").status_code == 404


def test_worker_fails_safety_job_whose_summary_has_no_alarm_list(tmp_path: pathlib.Path,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    summary = {k: v for k, v in SAFETY_SUMMARY.items() if k != "alarms"}
    _, done = _run_fake_job(tmp_path, monkeypatch, summary, {}, SAFETY_OPTIONS, SAFETY_FILES)
    assert done["status"] == "failed" and done["error"] == "Sonuç hazırlanamadı: alarm listesi bozuk"


@pytest.mark.parametrize("count", [1, 0, None, "2", True])
def test_worker_fails_job_when_count_is_below_listed_alarms_or_not_a_number(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, count: Any) -> None:
    _, done = _run_fake_job(tmp_path, monkeypatch, {**SAFETY_SUMMARY, "count": count}, {}, SAFETY_OPTIONS, SAFETY_FILES)
    assert done["status"] == "failed" and done["error"] == "Sonuç hazırlanamadı: alarm listesi bozuk"


def test_worker_fails_job_when_an_alarm_image_was_not_moved(tmp_path: pathlib.Path,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    files = {k: v for k, v in SAFETY_FILES.items() if k != "alarm-2.jpg"}
    _, done = _run_fake_job(tmp_path, monkeypatch, SAFETY_SUMMARY, {}, SAFETY_OPTIONS, files)
    assert done["status"] == "failed" and done["error"] == "Sonuç hazırlanamadı: alarm listesi bozuk"


def test_alarm_files_of_a_failed_job_are_not_served(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                                    client: TestClient) -> None:
    """Resimler `out/` a taşındıktan sonra liste bozuk çıkarsa iş başarısızdır; dosyalar diskte kalsa da sunulmaz."""
    _, done = _run_fake_job(tmp_path, monkeypatch, {**SAFETY_SUMMARY, "count": 1}, {}, SAFETY_OPTIONS, SAFETY_FILES)
    assert done["status"] == "failed"
    out = tmp_path / "jobs" / done["id"] / "out"
    assert (out / "alarm-1.jpg").is_file() and (out / "alarms.csv").is_file()
    for name in ("alarm-1.jpg", "alarm-2.jpg", "alarms.csv"):
        assert client.get(f"/api/v1/jobs/{done['id']}/files/{name}").status_code == 404, name


def test_alarm_image_outside_result_files_is_not_served(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                                        client: TestClient) -> None:
    _, done = _run_fake_job(tmp_path, monkeypatch, SAFETY_SUMMARY, {}, SAFETY_OPTIONS, SAFETY_FILES)
    (tmp_path / "jobs" / done["id"] / "out" / "alarm-7.jpg").write_bytes(JPEG)        # diskte var, sonuçta listelenmemiş
    assert client.get(f"/api/v1/jobs/{done['id']}/files/alarm-7.jpg").status_code == 404
    assert client.get(f"/api/v1/jobs/{done['id']}/files/alarm-1.jpg").status_code == 200



# ---------------------------------------------------------------- yangın / duman (preset fire)

FIRE_ALARMS = [
    {"kind": "fire", "trackId": 0, "startS": 12.4, "atS": 15.4, "endS": 19.0, "image": "alarm-1.jpg"},
    {"kind": "smoke", "trackId": 1, "startS": 30.0, "atS": 38.0, "endS": 52.0, "image": "alarm-2.jpg"},
]
FIRE_SUMMARY = {**SAFETY_SUMMARY, "alarms": FIRE_ALARMS}
FIRE_OPTIONS = {"preset": "fire", "fire": {"fire": {"seconds": 4}, "smoke": {"enabled": False}, "sensitivity": "high"}}


def test_options_accept_fire_preset_and_rules() -> None:
    from bantvision.analyzer.app import OptionsIn
    assert OptionsIn.model_validate({"preset": "fire"}).preset == "fire"
    o = OptionsIn.model_validate(FIRE_OPTIONS)
    assert o.model_dump(exclude_none=True) == {
        "preset": "fire", "fire": {"fire": {"seconds": 4.0}, "smoke": {"enabled": False}, "sensitivity": "high"}}
    assert OptionsIn.model_validate({"preset": "fire", "fire": {}}).model_dump(exclude_none=True) == {
        "preset": "fire", "fire": {}}


@pytest.mark.parametrize("rules", [
    {"fire": {"seconds": 1.9}}, {"fire": {"seconds": 10.1}}, {"smoke": {"seconds": 4.9}}, {"smoke": {"seconds": 30.1}},
    {"fire": {"seconds": "4"}}, {"fire": {"seconds": True}}, {"smoke": {"enabled": "false"}},
    {"sensitivity": "max"}, {"sensitivity": 1}, {"fire": {"seconds": 3, "kind": "x"}}, {"fire": {"seconds": float("nan")}},
    {"handsUp": {"seconds": 3}},
], ids=str)
def test_options_reject_bad_fire_rules(rules: dict[str, Any]) -> None:
    from bantvision.analyzer.app import OptionsIn
    with pytest.raises(ValueError):
        OptionsIn.model_validate({"preset": "fire", "fire": rules})


def test_fire_rule_range_error_is_turkish_and_422(client: TestClient) -> None:
    r = _post(client, {"preset": "fire", "fire": {"fire": {"seconds": 11}}})
    assert r.status_code == 422 and "Yangın süresi 2–10 sn arasında bir sayı olmalı." in r.json()["detail"]
    r = _post(client, {"preset": "fire", "fire": {"smoke": {"seconds": 4}}})
    assert r.status_code == 422 and "Duman süresi 5–30 sn arasında bir sayı olmalı." in r.json()["detail"]
    assert client.get("/api/v1/jobs").json() == []


@pytest.mark.parametrize("extra", [
    {"countMode": "detect"}, {"truth": 3}, {"direction": "down"}, {"line": 0.5},
    {"countLine": {"a": {"x": 0.1, "y": 0.1}, "b": {"x": 0.9, "y": 0.9}}},
    {"roi": {"x": 0, "y": 0, "width": 1, "height": 1}},
    {"roiPolygon": [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.5, "y": 0.9}]}, {"bgRange": [0, 1]},
    {"productLength": 0.3}, {"countAnchor": "bottom"},
], ids=lambda e: next(iter(e)))
def test_counting_option_on_fire_is_422_and_creates_no_job(client: TestClient, extra: dict[str, Any]) -> None:
    r = _post(client, {"preset": "fire", **extra})
    assert r.status_code == 422
    assert r.json()["detail"] == "Yangın/duman analizi sayım seçenekleriyle birlikte kullanılamaz."
    assert client.get("/api/v1/jobs").json() == []


@pytest.mark.parametrize("preset", ["generic", "egg", "flour", "box", "people", "vehicle", "animal", "safety", None])
def test_fire_option_on_other_preset_is_422_and_creates_no_job(client: TestClient, preset: str | None) -> None:
    options: dict[str, Any] = {"fire": {"sensitivity": "low"}}
    if preset:
        options["preset"] = preset
    r = _post(client, options)
    assert r.status_code == 422
    assert r.json()["detail"] == "Yangın/duman kuralları yalnız yangın/duman analizinde geçerlidir."
    assert client.get("/api/v1/jobs").json() == []


def test_safety_option_on_fire_preset_is_422(client: TestClient) -> None:
    r = _post(client, {"preset": "fire", "safety": {"lying": {"seconds": 10}}})
    assert r.status_code == 422
    assert r.json()["detail"] == "Kural ayarları yalnızca güvenlik alarmı videosunda kullanılır."


def test_both_fire_rules_off_is_422(client: TestClient) -> None:
    r = _post(client, {"preset": "fire", "fire": {"fire": {"enabled": False}, "smoke": {"enabled": False}}})
    assert r.status_code == 422 and r.json()["detail"] == "En az bir kural açık olmalı."
    assert client.get("/api/v1/jobs").json() == []


def test_fire_job_is_accepted_and_options_kept(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _accept_without_analysis(client, monkeypatch)
    for options in ({"preset": "fire"}, {"preset": "fire", "fire": {"smoke": {"enabled": False}}}, FIRE_OPTIONS):
        r = _post(client, options)
        assert r.status_code == 202, r.text
        assert r.json()["options"] == options


def test_fire_options_reach_video_tool() -> None:
    from bantvision.analyzer.jobs import options_to_args
    assert options_to_args(FIRE_OPTIONS) == [
        "--preset", "fire", "--fire", "4", "--no-smoke", "--sensitivity", "high"]
    assert options_to_args({"preset": "fire", "fire": {"fire": {"enabled": False}, "smoke": {"seconds": 12.5}}}) == [
        "--preset", "fire", "--no-fire", "--smoke", "12.5"]
    assert options_to_args({"preset": "fire"}) == ["--preset", "fire"]
    assert options_to_args({"preset": "fire", "fire": {"fire": {"enabled": True}}}) == ["--preset", "fire"]


def test_worker_fire_result_has_alarms_and_images(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                                  client: TestClient, job_validator: Draft202012Validator) -> None:
    files = {**SAFETY_FILES, "alarmlar.csv": b"baslangic_sn;alarm_sn;bitis_sn;tur;iz\n"}
    cmd, done = _run_fake_job(tmp_path, monkeypatch, FIRE_SUMMARY, {}, FIRE_OPTIONS, files)
    assert cmd[cmd.index("--preset") + 1] == "fire" and "--no-smoke" in cmd
    assert cmd[cmd.index("--sensitivity") + 1] == "high"
    assert done["status"] == "done", done.get("error")
    res = done["result"]
    assert res["count"] == 2 and res["alarms"] == FIRE_ALARMS
    assert res["files"] == ["alarms.csv", "profile.json", "alarm-1.jpg", "alarm-2.jpg"]
    assert_contract(job_validator, done)
    r = client.get(f"/api/v1/jobs/{done['id']}/files/alarm-1.jpg")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"


@pytest.mark.parametrize("options,alarms", [
    ({"preset": "fire"}, [ALARMS[0]]),                                           # yangın işinde güvenlik türü
    (SAFETY_OPTIONS, [FIRE_ALARMS[0]]),                                          # güvenlik işinde yangın türü
], ids=["handsUp-in-fire-job", "fire-in-safety-job"])
def test_worker_fails_job_whose_alarm_kind_does_not_match_the_preset(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, options: dict[str, Any], alarms: list[Any]) -> None:
    _, done = _run_fake_job(tmp_path, monkeypatch, {**SAFETY_SUMMARY, "count": 1, "alarms": alarms}, {}, options,
                            SAFETY_FILES)
    assert done["status"] == "failed" and done["error"] == "Sonuç hazırlanamadı: alarm listesi bozuk"


def test_worker_fails_fire_job_whose_summary_has_no_alarm_list(tmp_path: pathlib.Path,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    summary = {k: v for k, v in SAFETY_SUMMARY.items() if k != "alarms"}
    _, done = _run_fake_job(tmp_path, monkeypatch, summary, {}, FIRE_OPTIONS, SAFETY_FILES)
    assert done["status"] == "failed" and done["error"] == "Sonuç hazırlanamadı: alarm listesi bozuk"


def test_worker_fire_job_with_missing_model_fails_with_turkish_reason(tmp_path: pathlib.Path) -> None:
    """Gerçek video süreci, model dosyası yok: iş `failed`, ileti "Yangın/duman modeli kurulu değil."."""
    store = JobStore(Settings(data_dir=tmp_path))
    job, path = store.create("a.mp4", 10, {"preset": "fire"}, ".mp4")
    path.write_bytes(CLIP.read_bytes())
    Worker(store).process(job["id"])
    done = store.get(job["id"])
    assert done is not None
    assert done["status"] == "failed", done
    assert done["error"] == "Analiz başarısız: Yangın/duman modeli kurulu değil."
