"""Çalışan iş silinince: alt süreç durur, klasör diskte kalmaz; kalırsa yeniden denenir, açılışta temizlenir."""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from conftest import local_client
from fastapi.testclient import TestClient

from bantvision.analyzer import JobStore, Settings, create_app, jobs

ROOT = pathlib.Path(__file__).resolve().parents[3]
CLIP = ROOT / "apps" / "ios" / "BantSayacUITests" / "ui_test_clip.mp4"
CLIP_META = json.loads((ROOT / "apps" / "ios" / "BantSayacUITests" / "ui_test_clip.json").read_text(encoding="utf-8"))
OPTIONS = {"preset": "egg", "truth": CLIP_META["count"], "bgRange": [0, CLIP_META["emptySeconds"] - 0.3]}

# Sahte analiz: videoyu ve işaretli çıktıyı açık tutar (Windows'ta açık dosya silinemez), öldürülene dek sürer
HOLDING_ANALYSIS = """
import pathlib, sys, time
raw = pathlib.Path(sys.argv[2]); raw.mkdir(exist_ok=True)
held = [open(sys.argv[1], "rb"), open(raw / "isaretli.mp4", "wb")]
held[1].write(b"x" * 1024); held[1].flush()
print('{"stage": "counting"}', flush=True)
time.sleep(120)
"""
# Sahte analiz: hemen başarıyla biter, sıra kodlamaya gelir
FINISHED_ANALYSIS = """
import json, pathlib, sys
raw = pathlib.Path(sys.argv[2]); raw.mkdir(exist_ok=True)
(raw / "isaretli.mp4").write_bytes(b"x" * 1024)
(raw / "ozet.json").write_text(json.dumps({"count": 1}), encoding="utf-8")
"""
# Sahte ffmpeg: çıktıyı açık tutar, öldürülene dek sürer
HOLDING_ENCODER = """
import sys, time
held = open(sys.argv[1], "wb")
held.write(b"x" * 1024); held.flush()
time.sleep(120)
"""
SLEEPING_CHILD = "import time; time.sleep(120)"


class FakeChildren:
    """`subprocess.Popen` yerine geçer: analiz ve ffmpeg komutları sahte betiklerle çalışır, süreçler toplanır."""

    def __init__(self, tmp: pathlib.Path) -> None:
        self.tmp = tmp
        self.started: list[subprocess.Popen[Any]] = []
        self.analysis = HOLDING_ANALYSIS
        self.encoder = HOLDING_ENCODER
        self.before_return: Callable[[], None] = lambda: None
        self._popen = subprocess.Popen

    def _script(self, body: str) -> str:
        path = self.tmp / f"child_{uuid.uuid4().hex}.py"
        path.write_text(body, encoding="utf-8")
        return str(path)

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.Popen[Any]:
        if "bantvision.video" in cmd:                        # python -m bantvision.video <girdi> --out <çıktı> ...
            real = [sys.executable, self._script(self.analysis), cmd[3], cmd[5]]
        else:                                                # ffmpeg ... <çıktı>
            real = [sys.executable, self._script(self.encoder), cmd[-1]]
        proc = self._popen(real, **kwargs)
        self.started.append(proc)
        self.before_return()
        return proc


def wait_until(condition: Callable[[], Any], what: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError(f"zamanında olmadı: {what}")


def upload(client: TestClient) -> str:
    with CLIP.open("rb") as fh:
        r = client.post("/api/v1/jobs", files={"file": ("bant.mp4", fh, "video/mp4")},
                        data={"options": json.dumps(OPTIONS)})
    assert r.status_code == 202, r.text
    return r.json()["id"]


def stage_of(client: TestClient, job_id: str) -> str | None:
    return client.get(f"/api/v1/jobs/{job_id}").json().get("stage")


@pytest.fixture()
def data_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "data"


@pytest.fixture()
def client(data_dir: pathlib.Path) -> Iterator[TestClient]:
    with local_client(create_app(Settings(data_dir=data_dir, ffmpeg="sahte-ffmpeg"))) as c:
        yield c


@pytest.fixture()
def children(tmp_path: pathlib.Path, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeChildren]:
    fake = FakeChildren(tmp_path)
    monkeypatch.setattr(subprocess, "Popen", fake)
    yield fake
    for proc in fake.started:
        proc.kill()
        proc.wait()


def test_delete_during_analysis_stops_child_and_leaves_nothing(
        client: TestClient, children: FakeChildren, data_dir: pathlib.Path) -> None:
    job_id = upload(client)
    wait_until(lambda: stage_of(client, job_id) == "counting", "analiz başlasın")

    assert client.delete(f"/api/v1/jobs/{job_id}").status_code == 204

    assert children.started[0].poll() is not None            # yanıt dönmeden süreç bitmiş
    assert list((data_dir / "jobs").iterdir()) == []
    assert client.get(f"/api/v1/jobs/{job_id}").status_code == 404


def test_delete_during_encoding_stops_encoder_and_worker_moves_on(
        client: TestClient, children: FakeChildren, data_dir: pathlib.Path) -> None:
    children.analysis = FINISHED_ANALYSIS
    job_id = upload(client)
    annotated = data_dir / "jobs" / job_id / "out" / "annotated.mp4"
    wait_until(lambda: len(children.started) == 2 and annotated.exists(), "kodlama başlasın")

    assert client.delete(f"/api/v1/jobs/{job_id}").status_code == 204

    assert children.started[1].poll() is not None
    assert list((data_dir / "jobs").iterdir()) == []

    # silinen iş işçiyi tutmaz: sıradaki iş başlar, eskisinin klasörü geri gelmez
    children.analysis = HOLDING_ANALYSIS
    next_id = upload(client)
    wait_until(lambda: stage_of(client, next_id) == "counting", "sıradaki iş başlasın")
    assert [p.name for p in (data_dir / "jobs").iterdir()] == [next_id]


def test_delete_before_child_is_registered_still_stops_it(
        client: TestClient, children: FakeChildren, data_dir: pathlib.Path) -> None:
    """İşçi süreci başlattı ama henüz kaydetmedi: silme onu göremez, işçi kendisi durdurmalı."""
    children.analysis = SLEEPING_CHILD
    started, release = threading.Event(), threading.Event()

    def hold() -> None:
        started.set()
        release.wait(30)

    children.before_return = hold
    job_id = upload(client)
    assert started.wait(30)

    assert client.delete(f"/api/v1/jobs/{job_id}").status_code == 204
    release.set()

    wait_until(lambda: children.started[0].poll() is not None, "süreç dursun", timeout=10)
    wait_until(lambda: list((data_dir / "jobs").iterdir()) == [], "klasör gitsin", timeout=10)


def test_delete_with_real_analysis_leaves_nothing(client: TestClient, data_dir: pathlib.Path) -> None:
    job_id = upload(client)
    wait_until(lambda: stage_of(client, job_id) == "counting", "analiz başlasın", timeout=120)

    assert client.delete(f"/api/v1/jobs/{job_id}").status_code == 204

    assert list((data_dir / "jobs").iterdir()) == []


def _store_with_job(data_dir: pathlib.Path) -> tuple[JobStore, str, pathlib.Path]:
    store = JobStore(Settings(data_dir=data_dir))
    job, input_path = store.create("bant.mp4", 4, {}, ".mp4")
    input_path.write_bytes(b"data")
    return store, job["id"], store.dir(job["id"])


def test_store_delete_retries_until_folder_is_gone(data_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, job_id, folder = _store_with_job(data_dir)
    real = shutil.rmtree
    calls: list[int] = []

    def locked_twice(path: pathlib.Path, ignore_errors: bool = False) -> None:
        calls.append(1)
        if len(calls) > 2:
            real(path, ignore_errors=ignore_errors)

    monkeypatch.setattr(jobs.shutil, "rmtree", locked_twice)
    monkeypatch.setattr(jobs, "REMOVE_WAIT_S", 0, raising=False)

    assert store.delete(job_id) is True

    assert len(calls) == 3
    assert not folder.exists()


def test_store_delete_gives_up_without_error_and_retries_later(
        data_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, job_id, folder = _store_with_job(data_dir)
    job = store.get(job_id)
    assert job is not None
    monkeypatch.setattr(jobs, "REMOVE_WAIT_S", 0, raising=False)
    with monkeypatch.context() as m:
        m.setattr(jobs.shutil, "rmtree", lambda *_a, **_k: None)

        assert store.delete(job_id) is True

        # kullanıcı için iş silinmiştir: listede yok, geç gelen bir yazma kaydı geri getirmez
        assert store.get(job_id) is None and store.list() == []
        store.save(job)
        assert store.get(job_id) is None
        assert folder.exists()
        store.retry_removals()
        assert folder.exists()

    store.retry_removals()
    assert not folder.exists()


def test_startup_removes_folders_without_a_record(data_dir: pathlib.Path) -> None:
    store, job_id, folder = _store_with_job(data_dir)
    store.update(job_id, status="done", progress=1.0)
    orphan = store.root / str(uuid.uuid4())
    (orphan / "work").mkdir(parents=True)
    (orphan / "input.mp4").write_bytes(b"data")
    other = store.root / "elle-konmus"
    other.mkdir()

    with local_client(create_app(Settings(data_dir=data_dir))):
        pass

    assert not orphan.exists()
    assert folder.exists()                                   # kaydı olan iş durur
    assert other.exists()                                    # iş klasörü adı taşımayana dokunulmaz
