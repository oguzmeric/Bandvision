"""Cihaz ayarları: `<data>/devices.json` (DeviceSettings), ortak canlı modellerin boşluksuz cihaz değişimi
(SharedModel.set_choice / status) ve `/api/v1/live/devices` uçları (GET, PUT, hız testi)."""
from __future__ import annotations

import json
import logging
import pathlib
import threading
import time
from collections.abc import Iterator
from typing import Any

import numpy as np
import pytest
from conftest import local_client
from fastapi.testclient import TestClient

from bantvision.analyzer import Settings, create_app
from bantvision.core import devices
from bantvision.core.devices import Gpu, Used
from bantvision.live import api, jsonfile
from bantvision.live.api import SharedDetector, SharedPose
from bantvision.live.devices_store import DeviceSettings

DEFAULTS = {"detector": "auto", "pose": "auto", "video": "auto", "fire": "auto"}
NVIDIA = Gpu("gpu-10de-28a1", "NVIDIA Laptop GPU", 5920, 0, "0x00000000_0x0000a1b2")
INTEL = Gpu("gpu-8086-a7a0", "Intel Graphics", 128, 1, "0x00000000_0x0000c3d4")
N4 = "Ekran kartı çalışırken hata verdi (DEVICE_REMOVED); işlemci kullanılıyor."
SWAP_FAILED = ("Seçilen cihaza geçilemedi: Kişi tanıma modeli yüklenemedi: Model indirilemedi (bağlantı hatası); "
               "önceki cihazda çalışmaya devam ediyor.")


def wait_for(fn: Any, timeout: float = 10.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        v = fn()
        if v:
            return v
        time.sleep(0.02)
    raise AssertionError("koşul zamanında sağlanmadı")


def used_for(choice: str) -> Used:
    if choice.startswith("gpu-"):
        return Used("gpu", choice, f"Kart {choice}", None)
    return devices.cpu_used()


class Model:
    """Sahte iç model: `detect`/`estimate` hangi seçimle kurulduğunu döndürür."""

    def __init__(self, choice: str) -> None:
        self.choice = choice
        self.used = used_for(choice)

    def detect(self, *_a: Any, **_k: Any) -> list[str]:
        return [self.choice]

    def estimate(self, *_a: Any, **_k: Any) -> str:
        return self.choice


# ---------------------------------------------------------------- DeviceSettings

def test_store_missing_file_gives_defaults(tmp_path: pathlib.Path) -> None:
    s = DeviceSettings(tmp_path)
    assert s.choices() == DEFAULTS
    assert not (tmp_path / "devices.json").exists()                     # okumak dosya yazmaz


def test_store_round_trip(tmp_path: pathlib.Path) -> None:
    saved = DeviceSettings(tmp_path).save({"detector": "gpu-10de-28a1", "pose": "cpu", "video": "auto", "fire": "cpu"})
    assert saved == {"detector": "gpu-10de-28a1", "pose": "cpu", "video": "auto", "fire": "cpu"}
    assert json.loads((tmp_path / "devices.json").read_text(encoding="utf-8")) == {"choices": saved}
    assert DeviceSettings(tmp_path).choices() == saved
    assert not list(tmp_path.glob("*.tmp"))                             # atomik yazma: geçici dosya kalmaz


def test_store_choices_returns_a_copy(tmp_path: pathlib.Path) -> None:
    s = DeviceSettings(tmp_path)
    s.choices()["detector"] = "cpu"
    assert s.choices() == DEFAULTS


def test_store_save_rejects_bad_values_and_keeps_old(tmp_path: pathlib.Path) -> None:
    s = DeviceSettings(tmp_path)
    for bad in ({"detector": "cuda", "pose": "cpu", "video": "cpu"}, {"detector": "cpu", "pose": "cpu"}):
        with pytest.raises(ValueError):
            s.save(bad)
    assert s.choices() == DEFAULTS and not (tmp_path / "devices.json").exists()


@pytest.mark.parametrize("text", ["{bozuk", "[1, 2]", '{"choices": ["cpu"]}', "\udcff"])
def test_store_corrupt_file_is_moved_aside(tmp_path: pathlib.Path, text: str,
                                           caplog: pytest.LogCaptureFixture) -> None:
    f = tmp_path / "devices.json"
    raw = text.encode("utf-8", "surrogateescape")
    f.write_bytes(raw)
    with caplog.at_level(logging.ERROR):
        s = DeviceSettings(tmp_path)
    assert s.choices() == DEFAULTS
    assert not f.exists() and (tmp_path / "devices.json.corrupt").read_bytes() == raw
    assert any(r.levelno == logging.ERROR and "bozuk" in r.getMessage() for r in caplog.records)


def test_store_unknown_key_ignored_and_bad_value_defaults(tmp_path: pathlib.Path,
                                                          caplog: pytest.LogCaptureFixture) -> None:
    (tmp_path / "devices.json").write_text(json.dumps(
        {"choices": {"detector": "cpu", "pose": "cuda:0", "kamera": "cpu"}, "eski": 1}), encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        s = DeviceSettings(tmp_path)
    assert s.choices() == {"detector": "cpu", "pose": "auto", "video": "auto", "fire": "auto"}
    assert (tmp_path / "devices.json").exists()                         # bozuk sayılmaz, kenara alınmaz
    assert any("pose" in r.getMessage() for r in caplog.records)


def test_store_locked_read_gives_defaults_and_leaves_file(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                                         caplog: pytest.LogCaptureFixture) -> None:
    f = tmp_path / "devices.json"
    original = json.dumps({"choices": {"detector": "cpu", "pose": "cpu", "video": "cpu"}})
    f.write_text(original, encoding="utf-8")
    real_read = pathlib.Path.read_text

    def locked(self: pathlib.Path, *a: Any, **k: Any) -> str:
        if self.name == "devices.json":
            raise PermissionError(13, "kilitli")
        return real_read(self, *a, **k)

    monkeypatch.setattr(jsonfile, "READ_RETRY_DELAYS_S", ())
    monkeypatch.setattr(pathlib.Path, "read_text", locked)
    with caplog.at_level(logging.ERROR):
        s = DeviceSettings(tmp_path)
    assert s.choices() == DEFAULTS
    assert real_read(f, encoding="utf-8") == original and not (tmp_path / "devices.json.corrupt").exists()
    assert any(r.levelno == logging.ERROR and "okunamadı" in r.getMessage() for r in caplog.records)
    new = {"detector": "gpu-10de-28a1", "pose": "auto", "video": "cpu", "fire": "gpu-10de-28a1"}
    assert s.save(new) == new                                           # kullanıcı az önce seçti: yazılır
    assert json.loads(real_read(f, encoding="utf-8")) == {"choices": new}


def test_store_write_failure_raises_and_keeps_memory(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bantvision.live import devices_store

    def fail(*_a: Any, **_k: Any) -> None:
        raise PermissionError(13, "kilitli")

    s = DeviceSettings(tmp_path)
    monkeypatch.setattr(devices_store, "write_json_atomic", fail)
    with pytest.raises(devices_store.DeviceSettingsBusy):
        s.save({"detector": "cpu", "pose": "cpu", "video": "cpu"})
    assert s.choices() == DEFAULTS


SAVED = {"detector": "gpu-8086-a7a0", "pose": "cpu", "video": "gpu-10de-28a1", "fire": "cpu"}


def lock_first_reads(monkeypatch: pytest.MonkeyPatch, n: int) -> list[tuple[float, ...] | None]:
    """devices.json'un ilk `n` okuması "unreadable" (kilitli) döner; sonrakiler gerçek okumadır."""
    from bantvision.live import devices_store

    real = devices_store.read_json
    seen: list[tuple[float, ...] | None] = []

    def fake(path: pathlib.Path, delays: tuple[float, ...] | None = None) -> jsonfile.JsonRead:
        seen.append(delays)
        if len(seen) <= n:
            return jsonfile.JsonRead(None, "unreadable")
        return real(path, delays)

    monkeypatch.setattr(devices_store, "read_json", fake)
    return seen


def test_store_refresh_rereads_a_file_locked_at_start(tmp_path: pathlib.Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "devices.json").write_text(json.dumps({"choices": SAVED}), encoding="utf-8")
    seen = lock_first_reads(monkeypatch, 2)
    s = DeviceSettings(tmp_path)
    assert s.unread and s.choices() == DEFAULTS
    assert s.refresh() is None and s.unread                             # hâlâ kilitli
    assert s.refresh() == SAVED and not s.unread and s.choices() == SAVED
    assert s.refresh() is None                                          # bir kez okunduysa yeniden okunmaz
    assert seen[1:] == [(), ()]                                         # yeniden denemeler beklemesiz


def test_store_refresh_is_a_no_op_after_a_normal_read(tmp_path: pathlib.Path) -> None:
    s = DeviceSettings(tmp_path)
    assert not s.unread and s.refresh() is None


# ---------------------------------------------------------------- SharedModel: cihaz değişimi

def test_never_loaded_set_choice_only_stores() -> None:
    calls: list[str] = []
    det = SharedDetector(loader=lambda c: calls.append(c) or Model(c))
    assert det.status() == {"state": "idle", "device": None, "note": None}
    det.set_choice("gpu-10de-28a1")
    time.sleep(0.1)
    assert calls == [] and det.choice == "gpu-10de-28a1" and not det.ever_started
    assert det.status() == {"state": "idle", "device": None, "note": None}
    det.warm()
    wait_for(lambda: det.status()["state"] == "ready")
    assert calls == ["gpu-10de-28a1"] and det.ever_started
    assert det.status() == {"state": "ready", "device": {"id": "gpu-10de-28a1", "kind": "gpu",
                                                        "name": "Kart gpu-10de-28a1"}, "note": None}


def test_slow_swap_keeps_old_model_serving_until_new_is_ready() -> None:
    gate, started = threading.Event(), threading.Event()
    calls: list[str] = []

    def loader(choice: str) -> Model:
        calls.append(choice)
        if choice != "cpu":
            started.set()
            assert gate.wait(30)
        return Model(choice)

    det = SharedDetector(loader=loader)
    det.set_choice("cpu")
    det.warm()
    wait_for(lambda: det.state == "ready")
    assert det.detect("bgr", ["person"]) == ["cpu"]
    try:
        det.set_choice("gpu-8086-a7a0")                                 # ör. Intel: ilk açılış ~15 sn
        assert started.wait(5)
        for _ in range(5):                                              # değişim sürerken eski model hizmette
            assert det.detect("bgr", ["person"]) == ["cpu"]
        assert det.state == "ready"                                     # güvenlik izlemesi sağlıklı kalır
        assert det.status() == {"state": "loading", "device": {"id": "cpu", "kind": "cpu", "name": "İşlemci"},
                                "note": None}                           # eski cihaz hizmette, yenisi yükleniyor
    finally:
        gate.set()
    wait_for(lambda: det.status()["state"] == "ready")
    assert det.detect("bgr", ["person"]) == ["gpu-8086-a7a0"]
    assert det.status()["device"] == {"id": "gpu-8086-a7a0", "kind": "gpu", "name": "Kart gpu-8086-a7a0"}
    assert calls == ["cpu", "gpu-8086-a7a0"]


def test_choice_changed_during_swap_ends_with_last_choice() -> None:
    gate, started = threading.Event(), threading.Event()
    calls: list[str] = []

    def loader(choice: str) -> Model:
        calls.append(choice)
        if choice == "gpu-8086-a7a0":
            started.set()
            assert gate.wait(30)
        return Model(choice)

    pose = SharedPose(loader=loader)
    pose.set_choice("cpu")
    pose.warm()
    wait_for(lambda: pose.state == "ready")
    det_calls_before = list(calls)
    pose.set_choice("gpu-8086-a7a0")
    assert started.wait(5)
    pose.set_choice("gpu-10de-28a1")                                    # yükleme sürerken bir daha değişti
    assert pose.estimate("bgr", (0, 0, 1, 1)) == "cpu"
    gate.set()
    wait_for(lambda: pose.estimate("bgr", (0, 0, 1, 1)) == "gpu-10de-28a1")
    wait_for(lambda: pose.status()["state"] == "ready")
    assert calls == det_calls_before + ["gpu-8086-a7a0", "gpu-10de-28a1"]   # aradaki sonuç atıldı, sonuncusu yüklendi
    assert pose.status()["device"]["id"] == "gpu-10de-28a1"             # type: ignore[index]


def test_choice_switched_back_during_swap_keeps_current_model() -> None:
    gate, started = threading.Event(), threading.Event()
    calls: list[str] = []

    def loader(choice: str) -> Model:
        calls.append(choice)
        if choice != "cpu":
            started.set()
            assert gate.wait(30)
        return Model(choice)

    det = SharedDetector(loader=loader)
    det.set_choice("cpu")
    det.warm()
    wait_for(lambda: det.state == "ready")
    det.set_choice("gpu-10de-28a1")
    assert started.wait(5)
    det.set_choice("cpu")                                               # vazgeçti: çalışan modele geri dönüş
    gate.set()
    wait_for(lambda: det.status()["state"] == "ready")
    time.sleep(0.1)
    assert calls == ["cpu", "gpu-10de-28a1"] and det.detect("bgr", ["person"]) == ["cpu"]
    assert det.status()["device"]["id"] == "cpu"                        # type: ignore[index]


def test_failed_swap_keeps_old_model_and_reports_error_then_retries_new_choice() -> None:
    now = [1000.0]
    calls: list[str] = []
    fail = [True]

    def loader(choice: str) -> Model:
        calls.append(choice)
        if choice != "cpu" and fail[0]:
            raise OSError("ağ yok")
        return Model(choice)

    det = SharedDetector(loader=loader, clock=lambda: now[0])
    det.set_choice("cpu")
    det.warm()
    wait_for(lambda: det.state == "ready")
    det.set_choice("gpu-10de-28a1")
    wait_for(lambda: len(calls) == 2 and det.status()["state"] == "ready")
    assert det.state == "ready" and det.error == ""                     # hizmet sağlığı: eski model çalışıyor
    assert det.status() == {"state": "ready", "device": {"id": "cpu", "kind": "cpu", "name": "İşlemci"},
                            "note": SWAP_FAILED}
    assert det.detect("bgr", ["person"]) == ["cpu"]                     # eski model hizmette
    assert det.choice == "gpu-10de-28a1"                                # kayıtlı seçim korunur
    for _ in range(5):                                                  # bekleme süresi dolmadan yeniden denenmez
        det.warm()
        det.detect("bgr", ["person"])
    time.sleep(0.1)
    assert calls == ["cpu", "gpu-10de-28a1"] and det.state == "ready"
    fail[0] = False
    now[0] += 61.0
    det.detect("bgr", ["person"])                                       # bekleme dolunca yeni seçimle yeniden denenir
    wait_for(lambda: det.detect("bgr", ["person"]) == ["gpu-10de-28a1"])
    assert calls == ["cpu", "gpu-10de-28a1", "gpu-10de-28a1"] and det.error == ""
    assert det.status() == {"state": "ready", "device": {"id": "gpu-10de-28a1", "kind": "gpu",
                                                        "name": "Kart gpu-10de-28a1"}, "note": None}


def test_failed_swap_then_reverting_to_serving_choice_clears_the_failure() -> None:
    """NVIDIA hizmette → Intel seçildi, yüklenemedi → yeniden NVIDIA: durum temiz, yükleyici çağrılmaz."""
    calls: list[str] = []

    def loader(choice: str) -> Model:
        calls.append(choice)
        if choice == "gpu-8086-a7a0":
            raise OSError("ağ yok")
        return Model(choice)

    det = SharedDetector(loader=loader)
    det.set_choice("gpu-10de-28a1")
    det.warm()
    wait_for(lambda: det.state == "ready")
    det.set_choice("gpu-8086-a7a0")
    wait_for(lambda: det.status()["note"] == SWAP_FAILED)
    det.set_choice("gpu-10de-28a1")
    assert det.state == "ready" and det.error == ""
    assert det.status() == {"state": "ready", "device": {"id": "gpu-10de-28a1", "kind": "gpu",
                                                        "name": "Kart gpu-10de-28a1"}, "note": None}
    time.sleep(0.1)
    assert calls == ["gpu-10de-28a1", "gpu-8086-a7a0"]


def test_failed_first_load_without_a_model_is_an_error() -> None:
    det = SharedDetector(loader=lambda _c: (_ for _ in ()).throw(OSError("ağ yok")))
    det.warm()
    wait_for(lambda: det.state == "error")
    assert det.error == "Kişi tanıma modeli yüklenemedi: Model indirilemedi (bağlantı hatası)"
    assert det.status() == {"state": "error", "device": None, "note": det.error}


def test_base_exception_in_loader_does_not_leave_loading_stuck(caplog: pytest.LogCaptureFixture) -> None:
    class Boom(BaseException):
        pass

    now, calls = [1000.0], []

    def loader(choice: str) -> Model:
        calls.append(choice)
        if len(calls) == 1:
            raise Boom("dur")
        return Model(choice)

    det = SharedDetector(loader=loader, clock=lambda: now[0])
    with caplog.at_level(logging.ERROR):
        det.warm()
        wait_for(lambda: det.state == "error")
    assert det.status()["state"] == "error" and det.error.startswith("Kişi tanıma modeli yüklenemedi")
    assert any("Boom" in r.getMessage() for r in caplog.records)
    now[0] += 61.0
    det.warm()                                                          # `_loading` takılı kalmadı: yeniden denenir
    wait_for(lambda: det.state == "ready")
    assert calls == ["cpu", "cpu"]


def test_discarded_model_is_released_before_the_last_choice_loads() -> None:
    import gc
    import weakref

    gate, started = threading.Event(), threading.Event()
    made: list[weakref.ref[Model]] = []
    alive_when_last_loaded: list[bool] = []

    def loader(choice: str) -> Model:
        if choice == "gpu-10de-28a1":
            gc.collect()
            alive_when_last_loaded.append(made[-1]() is not None)
        m = Model(choice)
        made.append(weakref.ref(m))
        if choice == "gpu-8086-a7a0":
            started.set()
            assert gate.wait(30)
        return m

    det = SharedDetector(loader=loader)
    det.set_choice("cpu")
    det.warm()
    wait_for(lambda: det.state == "ready")
    det.set_choice("gpu-8086-a7a0")
    assert started.wait(5)
    det.set_choice("gpu-10de-28a1")
    gate.set()
    wait_for(lambda: det.detect("bgr", ["person"]) == ["gpu-10de-28a1"])
    assert alive_when_last_loaded == [False]                            # atılan Intel modeli bırakılmıştı


def test_swap_waits_for_an_inflight_detect() -> None:
    entered, release = threading.Event(), threading.Event()

    class Slow(Model):
        def detect(self, *_a: Any, **_k: Any) -> list[str]:
            entered.set()
            assert release.wait(30)
            return [self.choice]

    loaded = threading.Event()

    def loader(choice: str) -> Model:
        if choice == "cpu":
            return Slow(choice)
        loaded.set()
        return Model(choice)

    det = SharedDetector(loader=loader)
    det.set_choice("cpu")
    det.warm()
    wait_for(lambda: det.state == "ready")
    out: list[Any] = []
    t = threading.Thread(target=lambda: out.append(det.detect("bgr", ["person"])))
    t.start()
    try:
        assert entered.wait(5)
        det.set_choice("gpu-10de-28a1")
        assert loaded.wait(5)
        time.sleep(0.2)                                                 # yeni model hazır ama çıkarım sürüyor
        # değişim çıkarım bitene dek bekler; hizmette eski (işlemci) model
        assert det.status() == {"state": "loading", "device": {"id": "cpu", "kind": "cpu", "name": "İşlemci"},
                                "note": None}
    finally:
        release.set()
        t.join(10)
    assert out == [["cpu"]]
    wait_for(lambda: det.status()["state"] == "ready")
    assert det.detect("bgr", ["person"]) == ["gpu-10de-28a1"]


def test_same_choice_is_a_no_op() -> None:
    calls: list[str] = []
    det = SharedDetector(loader=lambda c: calls.append(c) or Model(c))
    det.set_choice("gpu-10de-28a1")
    det.warm()
    wait_for(lambda: det.state == "ready")
    det.set_choice("gpu-10de-28a1")
    time.sleep(0.1)
    assert calls == ["gpu-10de-28a1"] and det.status()["state"] == "ready"


def test_runtime_fallback_note_is_read_live() -> None:
    class Falling(Model):
        def detect(self, *_a: Any, **_k: Any) -> list[str]:
            self.used = devices.cpu_used(N4)                            # GuardedSession N4 düşüşü gibi
            return []

    det = SharedDetector(loader=lambda c: Falling(c))
    det.set_choice("gpu-10de-28a1")
    det.warm()
    wait_for(lambda: det.state == "ready")
    assert det.status()["device"]["kind"] == "gpu"                      # type: ignore[index]
    det.detect("bgr", ["person"])
    assert det.status() == {"state": "ready", "device": {"id": "cpu", "kind": "cpu", "name": "İşlemci"}, "note": N4}


def test_broken_inner_session_is_reported_as_error() -> None:
    text = "Model kullanılamıyor: ekran kartı hata verdi ve işlemci oturumu kurulamadı (bellek yok)"

    class Broken(Model):
        broken: str | None = None

    m = Broken("gpu-10de-28a1")
    pose = SharedPose(loader=lambda _c: m)
    pose.set_choice("gpu-10de-28a1")
    pose.warm()
    wait_for(lambda: pose.status()["state"] == "ready")
    m.broken = text
    assert pose.status() == {"state": "error", "device": None, "note": text}


def test_default_loaders_pass_the_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    from bantvision.core import detector, pose

    seen: list[tuple[str, str | None]] = []
    monkeypatch.setattr(detector, "ObjectDetector", lambda device=None: seen.append(("det", device)) or "d")
    monkeypatch.setattr(pose, "PoseEstimator", lambda device=None: seen.append(("pose", device)) or "p")
    assert api._load_detector("gpu-10de-28a1") == "d" and api._load_pose_estimator("auto") == "p"
    assert seen == [("det", "gpu-10de-28a1"), ("pose", "auto")]


# ---------------------------------------------------------------- API

class FakeBenchDetector:
    def __init__(self, choice: str, gate: threading.Event | None = None,
                 started: threading.Event | None = None) -> None:
        self.used = used_for(choice) if choice != "gpu-ffff-0000" else devices.cpu_used(
            "Seçilen ekran kartı bulunamadı; işlemci kullanılıyor.")
        self.calls: list[tuple[tuple[int, ...], str, list[str]]] = []
        self._gate, self._started = gate, started

    def detect(self, bgr: np.ndarray, classes: list[str]) -> list[Any]:
        if self._started is not None:
            self._started.set()
        if self._gate is not None:
            assert self._gate.wait(30)
        self.calls.append((bgr.shape, str(bgr.dtype), classes))
        return []


@pytest.fixture()
def windows_gpus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(devices, "_is_windows", lambda: True)
    monkeypatch.setattr(devices, "list_gpus", lambda *a, **k: [NVIDIA, INTEL])
    monkeypatch.setattr(devices, "dml_available", lambda *a, **k: True)


@pytest.fixture()
def loads(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(api, "_load_detector", lambda c: calls.append(("detector", c)) or Model(c))
    monkeypatch.setattr(api, "_load_pose_estimator", lambda c: calls.append(("pose", c)) or Model(c))
    return calls


@pytest.fixture()
def client(tmp_path: pathlib.Path, windows_gpus: None, loads: list[tuple[str, str]]) -> Iterator[TestClient]:
    with local_client(create_app(Settings(data_dir=tmp_path))) as c:
        yield c


def test_get_devices_shape(client: TestClient) -> None:
    live = client.app.state.live                                        # type: ignore[attr-defined]
    live.detector.warm()
    wait_for(lambda: live.detector.status()["state"] == "ready")
    r = client.get("/api/v1/live/devices")
    assert r.status_code == 200
    assert r.json() == {
        "gpuSupport": {"available": True, "reason": None},
        "devices": [{"id": "cpu", "kind": "cpu", "name": "İşlemci"},
                    {"id": "gpu-10de-28a1", "kind": "gpu", "name": "NVIDIA Laptop GPU", "memoryMb": 5920},
                    {"id": "gpu-8086-a7a0", "kind": "gpu", "name": "Intel Graphics", "memoryMb": 128}],
        "auto": "gpu-10de-28a1",
        "choices": DEFAULTS,
        "inUse": {"detector": {"state": "ready", "device": {"id": "cpu", "kind": "cpu", "name": "İşlemci"},
                               "note": None},                           # sahte model "auto"yu işlemcide kurar
                  "pose": {"state": "idle", "device": None, "note": None}},
    }


def test_manager_applies_saved_choices_at_start(tmp_path: pathlib.Path, windows_gpus: None,
                                                loads: list[tuple[str, str]]) -> None:
    (tmp_path / "devices.json").write_text(json.dumps(
        {"choices": {"detector": "gpu-8086-a7a0", "pose": "cpu", "video": "gpu-10de-28a1", "fire": "cpu"}}), encoding="utf-8")
    with local_client(create_app(Settings(data_dir=tmp_path))) as c:
        live = c.app.state.live                                         # type: ignore[attr-defined]
        assert live.detector.choice == "gpu-8086-a7a0" and live.pose.choice == "cpu"
        assert loads == []                                              # açılışta hiçbir model ısınmadı
        assert c.app.state.worker._device_arg() == "gpu-10de-28a1"     # type: ignore[attr-defined]
        live.pose.warm()
        wait_for(lambda: live.pose.status()["state"] == "ready")
        assert loads == [("pose", "cpu")]


def test_put_devices_saves_and_switches_live_models(client: TestClient, tmp_path: pathlib.Path,
                                                    loads: list[tuple[str, str]]) -> None:
    live = client.app.state.live                                        # type: ignore[attr-defined]
    live.detector.warm()
    wait_for(lambda: live.detector.status()["state"] == "ready")
    assert loads == [("detector", "auto")]
    body = {"choices": {"detector": "gpu-8086-a7a0", "pose": "cpu", "video": "gpu-10de-28a1", "fire": "cpu"}}
    r = client.put("/api/v1/live/devices", json=body)
    assert r.status_code == 200
    assert r.json()["choices"] == body["choices"]
    assert set(r.json()) == {"gpuSupport", "devices", "auto", "choices", "inUse"}
    assert json.loads((tmp_path / "devices.json").read_text(encoding="utf-8")) == body
    assert live.detector.choice == "gpu-8086-a7a0" and live.pose.choice == "cpu"
    wait_for(lambda: live.detector.status()["state"] == "ready" and ("detector", "gpu-8086-a7a0") in loads)
    assert live.detector.detect("bgr", ["person"]) == ["gpu-8086-a7a0"]
    assert ("pose", "cpu") not in loads                                 # hiç yüklenmemiş poz modeli yalnız seçimi tutar
    assert client.app.state.worker._device_arg() == "gpu-10de-28a1"    # type: ignore[attr-defined]
    auto = {"choices": {"detector": "auto", "pose": "auto", "video": "auto", "fire": "auto"}}
    assert client.put("/api/v1/live/devices", json=auto).status_code == 200
    assert live.detector.choice == "auto"                               # çözülmeden saklanır: donanımı izler


@pytest.mark.parametrize("body", [
    {"choices": {"detector": "cuda", "pose": "cpu", "video": "cpu"}},
    {"choices": {"detector": "gpu-10DE-28a1", "pose": "cpu", "video": "cpu"}},
    {"choices": {"detector": "cpu", "pose": "cpu"}},
    {"choices": {"detector": "cpu", "pose": "cpu", "video": "cpu", "urun": "cpu"}},
    {"choices": {"detector": "cpu", "pose": "cpu", "video": 1}},
    {"choices": {"detector": "cpu", "pose": "cpu", "video": "cpu"}, "fazla": True},
    {},
])
def test_put_devices_rejects_bad_bodies(client: TestClient, tmp_path: pathlib.Path, body: dict[str, Any]) -> None:
    r = client.put("/api/v1/live/devices", json=body)
    assert r.status_code == 422
    assert not (tmp_path / "devices.json").exists()
    assert client.app.state.live.detector.choice == "auto"             # type: ignore[attr-defined]


def test_put_devices_write_failure_is_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from bantvision.live import devices_store

    def fail(*_a: Any, **_k: Any) -> None:
        raise PermissionError(13, "kilitli")

    monkeypatch.setattr(devices_store, "write_json_atomic", fail)
    r = client.put("/api/v1/live/devices", json={"choices": {"detector": "cpu", "pose": "cpu", "video": "cpu"}})
    assert r.status_code == 503 and "kaydedilemedi" in r.json()["detail"]
    assert client.app.state.live.detector.choice == "auto"             # type: ignore[attr-defined]


def test_get_devices_rereads_a_file_locked_at_start_and_applies_it(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, windows_gpus: None,
        loads: list[tuple[str, str]]) -> None:
    (tmp_path / "devices.json").write_text(json.dumps({"choices": SAVED}), encoding="utf-8")
    lock_first_reads(monkeypatch, 1)
    with local_client(create_app(Settings(data_dir=tmp_path))) as c:
        live = c.app.state.live                                         # type: ignore[attr-defined]
        assert live.detector.choice == "auto" and live.pose.choice == "auto"   # açılışta kilitli: varsayılanlar
        live.detector.warm()
        wait_for(lambda: live.detector.status()["state"] == "ready")
        r = c.get("/api/v1/live/devices")
        assert r.status_code == 200 and r.json()["choices"] == SAVED
        assert live.detector.choice == "gpu-8086-a7a0" and live.pose.choice == "cpu"
        wait_for(lambda: live.detector.detect("bgr", ["person"]) == ["gpu-8086-a7a0"])   # okunan seçime geçti
        assert c.app.state.worker._device_arg() == "gpu-10de-28a1"     # type: ignore[attr-defined]
        assert json.loads((tmp_path / "devices.json").read_text(encoding="utf-8")) == {"choices": SAVED}


def test_put_devices_body_wins_over_a_file_locked_at_start(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, windows_gpus: None,
        loads: list[tuple[str, str]]) -> None:
    (tmp_path / "devices.json").write_text(json.dumps({"choices": SAVED}), encoding="utf-8")
    lock_first_reads(monkeypatch, 1)
    body = {"detector": "cpu", "pose": "gpu-10de-28a1", "video": "auto", "fire": "gpu-8086-a7a0"}
    with local_client(create_app(Settings(data_dir=tmp_path))) as c:
        live = c.app.state.live                                         # type: ignore[attr-defined]
        r = c.put("/api/v1/live/devices", json={"choices": body})
        assert r.status_code == 200 and r.json()["choices"] == body
        assert live.detector.choice == "cpu" and live.pose.choice == "gpu-10de-28a1"
        assert c.get("/api/v1/live/devices").json()["choices"] == body  # sonra dosya yeniden okunup ezilmez
        assert live.detector.choice == "cpu"
    assert json.loads((tmp_path / "devices.json").read_text(encoding="utf-8")) == {"choices": body}


def test_overlapping_puts_leave_file_and_models_in_agreement(client: TestClient, tmp_path: pathlib.Path,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """İlk kayıt dosyayı yazdı, modellere uygularken takıldı: ikinci kayıt araya girip dosyayı ve modelleri kendi
    seçimine çekip sonra ilkinin uygulaması bitse dosya B, modeller A kalırdı. Kilit ikinciyi bekletir."""
    live = client.app.state.live                                        # type: ignore[attr-defined]
    real_set = live.detector.set_choice
    applying, release = threading.Event(), threading.Event()

    def slow_set(choice: str) -> None:
        if choice == "gpu-8086-a7a0":
            applying.set()
            assert release.wait(30)
        real_set(choice)

    monkeypatch.setattr(live.detector, "set_choice", slow_set)
    a = {"detector": "gpu-8086-a7a0", "pose": "gpu-8086-a7a0", "video": "gpu-8086-a7a0", "fire": "gpu-8086-a7a0"}
    b = {"detector": "cpu", "pose": "cpu", "video": "cpu", "fire": "cpu"}
    out: dict[str, int] = {}
    ta = threading.Thread(target=lambda: out.update(a=client.put("/api/v1/live/devices",
                                                                 json={"choices": a}).status_code))
    ta.start()
    tb: threading.Thread | None = None
    try:
        assert applying.wait(10)
        tb = threading.Thread(target=lambda: out.update(b=client.put("/api/v1/live/devices",
                                                                     json={"choices": b}).status_code))
        tb.start()
        time.sleep(0.3)
        on_disk = json.loads((tmp_path / "devices.json").read_text(encoding="utf-8"))["choices"]
        assert on_disk == a                                             # ikinci kayıt ilkinin bitmesini bekliyor
    finally:
        release.set()
        ta.join(30)
        if tb is not None:
            tb.join(30)
    assert out == {"a": 200, "b": 200}
    on_disk = json.loads((tmp_path / "devices.json").read_text(encoding="utf-8"))["choices"]
    assert on_disk == b and live.detector.choice == b["detector"] and live.pose.choice == b["pose"]


def test_benchmark_times_a_fresh_detector(client: TestClient) -> None:
    made: list[FakeBenchDetector] = []

    def factory(choice: str) -> FakeBenchDetector:
        made.append(FakeBenchDetector(choice))
        return made[-1]

    client.app.state.live.make_bench_detector = factory                 # type: ignore[attr-defined]
    r = client.post("/api/v1/live/devices/benchmark", json={"device": "gpu-10de-28a1"})
    assert r.status_code == 200
    j = r.json()
    assert j["device"] == {"id": "gpu-10de-28a1", "kind": "gpu", "name": "Kart gpu-10de-28a1", "note": None}
    assert isinstance(j["msPerFrame"], float) and j["msPerFrame"] >= 0
    assert isinstance(j["loadS"], float) and j["loadS"] >= 0
    assert len(made) == 1 and len(made[0].calls) == 23                  # 3 ısınma + 20 ölçüm
    assert all(c == ((720, 1280, 3), "uint8", ["person"]) for c in made[0].calls)


def test_benchmark_reports_fallback_note(client: TestClient) -> None:
    client.app.state.live.make_bench_detector = FakeBenchDetector       # type: ignore[attr-defined]
    r = client.post("/api/v1/live/devices/benchmark", json={"device": "gpu-ffff-0000"})
    assert r.status_code == 200
    assert r.json()["device"]["kind"] == "cpu"
    assert r.json()["device"]["note"] == "Seçilen ekran kartı bulunamadı; işlemci kullanılıyor."


def test_benchmark_uses_a_fixed_frame(client: TestClient) -> None:
    frames: list[np.ndarray] = []

    class Spy(FakeBenchDetector):
        def detect(self, bgr: np.ndarray, classes: list[str]) -> list[Any]:
            frames.append(bgr.copy())
            return []

    client.app.state.live.make_bench_detector = Spy                     # type: ignore[attr-defined]
    assert client.post("/api/v1/live/devices/benchmark", json={"device": "cpu"}).status_code == 200
    want = np.random.default_rng(0).integers(0, 256, (720, 1280, 3), dtype=np.uint8)
    assert all(np.array_equal(f, want) for f in frames)


@pytest.mark.parametrize("body", [{"device": "auto"}, {"device": "cuda"}, {}, {"device": "cpu", "fazla": 1}])
def test_benchmark_rejects_bad_device(client: TestClient, body: dict[str, Any]) -> None:
    client.app.state.live.make_bench_detector = lambda _c: pytest.fail("kurulmamalı")  # type: ignore[attr-defined]
    assert client.post("/api/v1/live/devices/benchmark", json=body).status_code == 422


def test_benchmark_one_at_a_time(client: TestClient) -> None:
    gate, started = threading.Event(), threading.Event()
    client.app.state.live.make_bench_detector = (                       # type: ignore[attr-defined]
        lambda c: FakeBenchDetector(c, gate=gate, started=started))
    first: dict[str, Any] = {}

    def run() -> None:
        first["r"] = client.post("/api/v1/live/devices/benchmark", json={"device": "cpu"})

    t = threading.Thread(target=run)
    t.start()
    try:
        assert started.wait(10)
        r = client.post("/api/v1/live/devices/benchmark", json={"device": "gpu-10de-28a1"})
        assert r.status_code == 409
        assert r.json()["detail"] == "Başka bir hız testi sürüyor; bitince yeniden deneyin."
    finally:
        gate.set()
        t.join(30)
    assert first["r"].status_code == 200
    client.app.state.live.make_bench_detector = FakeBenchDetector       # type: ignore[attr-defined]
    assert client.post("/api/v1/live/devices/benchmark", json={"device": "cpu"}).status_code == 200


def test_benchmark_model_download_failure_is_502_and_releases_lock(client: TestClient) -> None:
    def factory(_c: str) -> Any:
        raise OSError("ağ yok")

    client.app.state.live.make_bench_detector = factory                 # type: ignore[attr-defined]
    r = client.post("/api/v1/live/devices/benchmark", json={"device": "cpu"})
    assert r.status_code == 502
    assert r.json()["detail"] == "Kişi tanıma modeli yüklenemedi: Model indirilemedi (bağlantı hatası)"
    client.app.state.live.make_bench_detector = FakeBenchDetector       # type: ignore[attr-defined]
    assert client.post("/api/v1/live/devices/benchmark", json={"device": "cpu"}).status_code == 200


def test_benchmark_run_failure_is_502_and_releases_lock(client: TestClient) -> None:
    class Failing(FakeBenchDetector):
        def detect(self, bgr: np.ndarray, classes: list[str]) -> list[Any]:
            raise RuntimeError("Model kullanılamıyor: ekran kartı hata verdi ve işlemci oturumu kurulamadı (x)")

    client.app.state.live.make_bench_detector = Failing                 # type: ignore[attr-defined]
    r = client.post("/api/v1/live/devices/benchmark", json={"device": "cpu"})
    assert r.status_code == 502 and r.json()["detail"].startswith("Hız testi tamamlanamadı")
    client.app.state.live.make_bench_detector = FakeBenchDetector       # type: ignore[attr-defined]
    assert client.post("/api/v1/live/devices/benchmark", json={"device": "cpu"}).status_code == 200


def test_default_bench_factory_builds_object_detector(monkeypatch: pytest.MonkeyPatch) -> None:
    from bantvision.core import detector

    seen: list[str | None] = []
    monkeypatch.setattr(detector, "ObjectDetector", lambda device=None: seen.append(device) or "d")
    assert api._bench_detector("gpu-10de-28a1") == "d" and seen == ["gpu-10de-28a1"]


def test_non_windows_has_one_cpu_device(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                        loads: list[tuple[str, str]]) -> None:
    monkeypatch.setattr(devices, "_is_windows", lambda: False)
    monkeypatch.setattr(devices, "_cache", None)
    with local_client(create_app(Settings(data_dir=tmp_path))) as c:
        r = c.get("/api/v1/live/devices")
    assert r.status_code == 200
    j = r.json()
    assert j["gpuSupport"] == {"available": False, "reason": "Ekran kartı desteği yalnız Windows'ta var"}
    assert j["devices"] == [{"id": "cpu", "kind": "cpu", "name": "İşlemci"}]
    assert j["auto"] == "cpu" and j["choices"] == DEFAULTS
    assert j["inUse"] == {"detector": {"state": "idle", "device": None, "note": None},
                          "pose": {"state": "idle", "device": None, "note": None}}


def test_devices_routes_require_the_access_key(tmp_path: pathlib.Path, windows_gpus: None,
                                               loads: list[tuple[str, str]]) -> None:
    with local_client(create_app(Settings(data_dir=tmp_path, token="gizli"))) as c:
        assert c.get("/api/v1/live/devices").status_code == 401
        assert c.put("/api/v1/live/devices", json={"choices": DEFAULTS}).status_code == 401
        assert c.post("/api/v1/live/devices/benchmark", json={"device": "cpu"}).status_code == 401
        ok = c.get("/api/v1/live/devices", headers={"Authorization": "Bearer gizli"})
        assert ok.status_code == 200


def test_store_fire_choice_is_optional_on_save_and_kept(tmp_path: pathlib.Path) -> None:
    s = DeviceSettings(tmp_path)
    s.save({"detector": "cpu", "pose": "cpu", "video": "cpu", "fire": "cpu"})
    old_client = s.save({"detector": "auto", "pose": "auto", "video": "auto"})       # eski istemci: fire yok
    assert old_client == {"detector": "auto", "pose": "auto", "video": "auto", "fire": "cpu"}
    assert DeviceSettings(tmp_path).choices()["fire"] == "cpu"
    with pytest.raises(ValueError):
        s.save({"detector": "cpu", "pose": "cpu", "video": "cpu", "fire": "cuda"})


def test_put_devices_fire_is_saved_kept_and_validated(client: TestClient) -> None:
    base = {"detector": "cpu", "pose": "cpu", "video": "cpu"}
    r = client.put("/api/v1/live/devices", json={"choices": {**base, "fire": "cpu"}})
    assert r.status_code == 200 and r.json()["choices"]["fire"] == "cpu"
    r = client.put("/api/v1/live/devices", json={"choices": base})
    assert r.status_code == 200 and r.json()["choices"]["fire"] == "cpu"
    assert client.put("/api/v1/live/devices", json={"choices": {**base, "fire": "cuda"}}).status_code == 422
    assert client.put("/api/v1/live/devices", json={"choices": {**base, "fire": None}}).status_code == 200
