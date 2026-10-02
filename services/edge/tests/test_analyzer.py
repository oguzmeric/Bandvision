"""Video analiz sunucusu (docs/13-web-platform.md): uçtan uca API, sözleşme, güvenlik, saklama süresi."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from bantvision.analyzer import JobStore, Settings, Worker, create_app

ROOT = pathlib.Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "contracts"
CLIP = ROOT / "apps" / "ios" / "BantSayacUITests" / "ui_test_clip.mp4"
CLIP_META = json.loads((ROOT / "apps" / "ios" / "BantSayacUITests" / "ui_test_clip.json").read_text(encoding="utf-8"))


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
    with TestClient(create_app(Settings(data_dir=tmp_path))) as c:
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
    for bad in ('{"preset": "box"}', '{"sahibi": "x"}', '{"roiPolygon": [{"x": 0.1, "y": 0.1}]}', "{bozuk"):
        with CLIP.open("rb") as fh:
            r = client.post("/api/v1/jobs", files={"file": ("a.mp4", fh, "video/mp4")}, data={"options": bad})
        assert r.status_code == 422, bad
    assert client.get("/api/v1/jobs").json() == []            # reddedilen yüklemelerden iz kalmaz
    assert not any((tmp_path / "jobs").iterdir())


def test_upload_size_limit(tmp_path: pathlib.Path) -> None:
    with TestClient(create_app(Settings(data_dir=tmp_path, max_upload_mb=0))) as c, CLIP.open("rb") as fh:
        r = c.post("/api/v1/jobs", files={"file": ("a.mp4", fh, "video/mp4")})
    assert r.status_code == 413
    assert not any((tmp_path / "jobs").iterdir())


def test_token_required_when_configured(tmp_path: pathlib.Path) -> None:
    with TestClient(create_app(Settings(data_dir=tmp_path, token="gizli"))) as c:
        assert c.get("/api/v1/jobs").status_code == 401
        assert c.get("/api/v1/jobs", headers={"Authorization": "Bearer yanlis"}).status_code == 401
        assert c.get("/api/v1/jobs", headers={"Authorization": "Bearer gizli"}).status_code == 200
        assert c.get("/healthz").status_code == 200


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
