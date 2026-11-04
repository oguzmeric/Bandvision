"""core/devices.py: DXGI satırlarından kart kimlikleri, seçim çözümü, korumalı ONNX oturumu (sahte onnxruntime ile)."""
from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable

import numpy as np
import pytest

from bantvision.core import devices
from bantvision.core.devices import CHOICE_RE, Gpu

DML = "DmlExecutionProvider"
CPU = "CPUExecutionProvider"

# ham DXGI satırı: (dizin, açıklama, satıcı, aygıt, ayrılmış bayt, bayraklar, luid_high, luid_low)
INTEL = (0, "Intel(R) Iris(R) Xe Graphics ", 0x8086, 0x9A49, 128 * 2**20, 0, 0, 0x1234)
NVIDIA = (1, "NVIDIA Laptop GPU", 0x10DE, 0x28A1, 5920 * 2**20, 0, 0, 0xABCD)
BASIC = (2, "Microsoft Basic Render Driver", 0x1414, 0x008C, 0, 2, 0, 0x9999)
NVIDIA2 = (3, "NVIDIA Laptop GPU", 0x10DE, 0x28A1, 5920 * 2**20, 0, 0, 0xBEEF)


class FakeSO:
    def __init__(self) -> None:
        self.entries: dict[str, str] = {}

    def add_session_config_entry(self, k: str, v: str) -> None:
        self.entries[k] = v


class FakeSession:
    def __init__(self, ort: FakeOrt, path: str, so: FakeSO, providers: list) -> None:
        self.ort, self.path, self.so, self.providers = ort, path, so, providers
        self.runs: list[tuple] = []
        names = [p[0] if isinstance(p, tuple) else p for p in providers]
        self.is_gpu = DML in names
        self.reported = [CPU] if ort.report_cpu else [n for n in names if n in ort.available]

    def get_providers(self) -> list[str]:
        return self.reported

    def get_inputs(self) -> list[str]:
        return ["input"]

    def get_outputs(self) -> list[str]:
        return ["output"]

    def run(self, output_names, feeds):
        self.runs.append((output_names, feeds))
        if self.is_gpu and self.ort.gpu_run_hook is not None:
            self.ort.gpu_run_hook()
        if self.is_gpu and self.ort.run_error is not None:
            raise self.ort.run_error
        if not self.is_gpu and self.ort.cpu_run_error is not None:
            raise self.ort.cpu_run_error
        return [np.full((1,), 7.0 if self.is_gpu else 3.0)]


class FakeOrt:
    """onnxruntime yerine: DirectML var/yok, sessiz işlemci düşüşü, kurucu ve run hataları ayarlanabilir."""

    class ExecutionMode:
        ORT_SEQUENTIAL = "seq"
        ORT_PARALLEL = "par"

    SessionOptions = FakeSO

    def __init__(self, *, dml: bool = True, report_cpu: bool = False, ctor_error: Exception | None = None,
                 run_error: Exception | None = None, cpu_run_error: Exception | None = None) -> None:
        self.available = [DML, CPU] if dml else [CPU]
        self.report_cpu, self.ctor_error = report_cpu, ctor_error
        self.run_error, self.cpu_run_error = run_error, cpu_run_error
        self.gpu_run_hook: Callable[[], None] | None = None     # GPU run içinde çağrılır (engelleme için)
        self.cpu_ctor_error: Exception | None = None            # işlemci (DirectML'siz) kurucu hatası
        self.sessions: list[FakeSession] = []

    def get_available_providers(self) -> list[str]:
        return list(self.available)

    def InferenceSession(self, path, so=None, providers=None) -> FakeSession:
        is_gpu = any((p[0] if isinstance(p, tuple) else p) == DML for p in providers)
        if self.ctor_error is not None and is_gpu:
            raise self.ctor_error
        if self.cpu_ctor_error is not None and not is_gpu:
            raise self.cpu_ctor_error
        s = FakeSession(self, str(path), so, list(providers))
        self.sessions.append(s)
        return s


class Configure:
    """configure(so) yerine: kaç kez ve hangi seçeneklere uygulandığını tutar."""

    def __init__(self) -> None:
        self.options: list[FakeSO] = []

    def __call__(self, so: FakeSO) -> None:
        so.intra_op_num_threads = 2
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.options.append(so)


@pytest.fixture(autouse=True)
def _temiz(monkeypatch):
    monkeypatch.setattr(devices, "_cache", None)
    monkeypatch.setattr(devices, "_dxgi_warned", False)
    monkeypatch.setattr(devices, "_dml_warned", False)
    before = devices.default_choice()
    yield
    devices.set_default_choice(before)


def gpus2() -> list[Gpu]:
    return devices.list_gpus(_enum=lambda: [INTEL, NVIDIA, BASIC])


# --------------------------------------------------------------- 1. kimlikler

def test_ids_drop_software_and_number_duplicates():
    gpus = devices.list_gpus(_enum=lambda: [INTEL, NVIDIA, BASIC, NVIDIA2])
    assert [g.id for g in gpus] == ["gpu-8086-9a49", "gpu-10de-28a1", "gpu-10de-28a1-2"]
    assert all("Microsoft" not in g.name for g in gpus)
    intel, nv, nv2 = gpus
    assert intel.name == "Intel(R) Iris(R) Xe Graphics"                  # baştaki/sondaki boşluk atılır
    assert (intel.memory_mb, nv.memory_mb) == (128, 5920)
    assert (intel.index, nv.index, nv2.index) == (0, 1, 3)
    assert intel.luid == "0x00000000_0x00001234"
    assert nv.luid == "0x00000000_0x0000abcd"


def test_microsoft_vendor_dropped_even_without_software_flag():
    row = (0, "Microsoft Remote Display", 0x1414, 0x00A0, 0, 0, 0, 1)
    assert devices.list_gpus(_enum=lambda: [row]) == []


def test_luid_negative_high_part_is_unsigned():
    row = (0, "X", 0x10DE, 0x0001, 2**20, 0, -1, 5)
    assert devices.list_gpus(_enum=lambda: [row])[0].luid == "0xffffffff_0x00000005"


def test_non_windows_gives_empty_list(monkeypatch):
    monkeypatch.setattr(devices, "_is_windows", lambda: False)
    monkeypatch.setattr(devices, "_dxgi_rows", lambda: pytest.fail("DXGI çağrılmamalı"))
    assert devices.list_gpus(refresh=True) == []


def test_list_gpus_cached_30s_and_refresh(monkeypatch):
    monkeypatch.setattr(devices, "_is_windows", lambda: True)
    calls = []
    monkeypatch.setattr(devices, "_dxgi_rows", lambda: calls.append(1) or [NVIDIA])
    now = [100.0]
    monkeypatch.setattr(devices.time, "monotonic", lambda: now[0])
    assert [g.id for g in devices.list_gpus()] == ["gpu-10de-28a1"]
    now[0] += 29
    devices.list_gpus()
    assert len(calls) == 1
    devices.list_gpus(refresh=True)
    assert len(calls) == 2
    now[0] += 31
    devices.list_gpus()
    assert len(calls) == 3


def test_dxgi_failure_gives_empty_and_warns_once(monkeypatch, caplog):
    monkeypatch.setattr(devices, "_is_windows", lambda: True)

    def boom():
        raise OSError("dxgi yok")

    monkeypatch.setattr(devices, "_dxgi_rows", boom)
    with caplog.at_level(logging.WARNING, logger="bantvision.devices"):
        assert devices.list_gpus(refresh=True) == []
        assert devices.list_gpus(refresh=True) == []
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


# --------------------------------------------------------------- 2. auto

def test_auto_choice_largest_memory_lowest_index_on_ties():
    ort = FakeOrt()
    assert devices.auto_choice(gpus2(), _ort=ort) == "gpu-10de-28a1"
    tie = [Gpu("gpu-aaaa-0001", "A", 100, 2, "l"), Gpu("gpu-bbbb-0002", "B", 100, 1, "l")]
    assert devices.auto_choice(tie, _ort=ort) == "gpu-bbbb-0002"


def test_auto_choice_cpu_without_gpus_or_dml():
    assert devices.auto_choice([], _ort=FakeOrt()) == "cpu"
    assert devices.auto_choice(gpus2(), _ort=FakeOrt(dml=False)) == "cpu"


# --------------------------------------------------------------- 3. resolve

def test_resolve_cpu_auto_present_missing():
    ort, gpus = FakeOrt(), gpus2()
    assert devices.resolve("cpu", gpus, _ort=ort) == (None, None)
    g, note = devices.resolve("auto", gpus, _ort=ort)
    assert g is not None and g.id == "gpu-10de-28a1" and note is None
    g, note = devices.resolve("gpu-8086-9a49", gpus, _ort=ort)
    assert g is not None and g.index == 0 and note is None
    assert devices.resolve("gpu-1002-73bf", gpus, _ort=ort) == (
        None, "Seçilen ekran kartı bulunamadı; işlemci kullanılıyor.")


def test_resolve_auto_without_gpu_has_no_note():
    assert devices.resolve("auto", [], _ort=FakeOrt()) == (None, None)
    assert devices.resolve("auto", gpus2(), _ort=FakeOrt(dml=False)) == (None, None)


def test_resolve_gpu_id_without_directml_is_n1(monkeypatch):
    monkeypatch.setattr(devices, "_is_windows", lambda: True)
    assert devices.resolve("gpu-10de-28a1", gpus2(), _ort=FakeOrt(dml=False)) == (
        None, "Ekran kartı desteği kurulu değil (onnxruntime-directml); işlemci kullanılıyor.")
    monkeypatch.setattr(devices, "_is_windows", lambda: False)
    assert devices.resolve("gpu-10de-28a1", [], _ort=FakeOrt(dml=False)) == (
        None, "Ekran kartı desteği yalnız Windows'ta var; işlemci kullanılıyor.")


def test_gpu_support(monkeypatch):
    monkeypatch.setattr(devices, "_is_windows", lambda: False)
    assert devices.gpu_support(_ort=FakeOrt()) == (False, "Ekran kartı desteği yalnız Windows'ta var")
    monkeypatch.setattr(devices, "_is_windows", lambda: True)
    assert devices.gpu_support(_ort=FakeOrt(dml=False)) == (
        False, "Ekran kartı desteği kurulu değil (onnxruntime-directml)")
    assert devices.gpu_support(_ort=FakeOrt()) == (True, None)


def test_dml_available_follows_provider_list():
    assert devices.dml_available(_ort=FakeOrt()) is True
    assert devices.dml_available(_ort=FakeOrt(dml=False)) is False


# --------------------------------------------------------------- 4-5. oturum açma

def test_cpu_session_options_untouched():
    ort, conf = FakeOrt(), Configure()
    s = devices.open_session("m.onnx", conf, "cpu", _ort=ort, _gpus=gpus2())
    (sess,) = ort.sessions
    assert sess.providers == [CPU]
    assert not hasattr(sess.so, "enable_mem_pattern") and not hasattr(sess.so, "execution_mode")
    assert sess.so.intra_op_num_threads == 2
    assert s.used == devices.cpu_used()
    assert s.used.to_json() == {"id": "cpu", "kind": "cpu", "name": "İşlemci", "note": None}


def test_gpu_session_uses_dml_with_required_options():
    ort, conf = FakeOrt(), Configure()
    s = devices.open_session("m.onnx", conf, "gpu-8086-9a49", _ort=ort, _gpus=gpus2())
    (sess,) = ort.sessions
    assert sess.providers == [(DML, {"device_id": 0}), CPU]
    assert sess.so.enable_mem_pattern is False and sess.so.execution_mode == "seq"
    assert sess.so.intra_op_num_threads == 2 and len(conf.options) == 1
    assert s.used.kind == "gpu" and s.used.id == "gpu-8086-9a49" and s.used.note is None
    assert s.used.name == "Intel(R) Iris(R) Xe Graphics"


def test_auto_opens_largest_gpu():
    ort = FakeOrt()
    s = devices.open_session("m.onnx", Configure(), "auto", _ort=ort, _gpus=gpus2())
    assert ort.sessions[0].providers[0] == (DML, {"device_id": 1})
    assert s.used.id == "gpu-10de-28a1"


def test_open_session_missing_gpu_and_no_directml_fall_back_with_notes(monkeypatch):
    monkeypatch.setattr(devices, "_is_windows", lambda: True)
    s = devices.open_session("m.onnx", Configure(), "gpu-1002-73bf", _ort=FakeOrt(), _gpus=gpus2())
    assert s.used == devices.cpu_used("Seçilen ekran kartı bulunamadı; işlemci kullanılıyor.")
    s = devices.open_session("m.onnx", Configure(), "gpu-10de-28a1", _ort=FakeOrt(dml=False), _gpus=gpus2())
    assert s.used.kind == "cpu" and "onnxruntime-directml" in (s.used.note or "")


def test_get_inputs_delegates():
    s = devices.open_session("m.onnx", Configure(), "cpu", _ort=FakeOrt(), _gpus=[])
    assert s.get_inputs() == ["input"]
    assert s.get_outputs() == ["output"]                                 # model üstverisi (gerçek model testi)


# --------------------------------------------------------------- 6-7. açılış düşüşleri

def test_silent_cpu_fallback_is_not_reported_as_gpu():
    ort, conf = FakeOrt(report_cpu=True), Configure()
    s = devices.open_session("m.onnx", conf, "gpu-10de-28a1", _ort=ort, _gpus=gpus2())
    assert s.used == devices.cpu_used("Ekran kartında açılamadı (DirectML etkinleşmedi); işlemci kullanılıyor.")
    gpu_try, cpu_final = ort.sessions
    assert gpu_try.is_gpu and cpu_final.providers == [CPU]
    assert not hasattr(cpu_final.so, "enable_mem_pattern") and cpu_final.so is not gpu_try.so
    assert len(conf.options) == 2


def test_constructor_error_falls_back_with_first_line_reason(caplog):
    ort = FakeOrt(ctor_error=RuntimeError("D3D12 device removed\nstack…"))
    with caplog.at_level(logging.ERROR, logger="bantvision.devices"):
        s = devices.open_session("m.onnx", Configure(), "gpu-10de-28a1", _ort=ort, _gpus=gpus2())
    assert s.used == devices.cpu_used("Ekran kartında açılamadı (D3D12 device removed); işlemci kullanılıyor.")
    assert [x.providers for x in ort.sessions] == [[CPU]]
    assert any(r.levelno == logging.ERROR and r.exc_info for r in caplog.records)


def test_reason_is_truncated_to_160_chars():
    ort = FakeOrt(ctor_error=RuntimeError("x" * 500))
    s = devices.open_session("m.onnx", Configure(), "gpu-10de-28a1", _ort=ort, _gpus=gpus2())
    assert s.used.note == f"Ekran kartında açılamadı ({'x' * 160}); işlemci kullanılıyor."


# --------------------------------------------------------------- 8-9. çalışma hatası

def test_run_error_on_gpu_rebuilds_on_cpu_and_retries():
    ort = FakeOrt(run_error=RuntimeError("DXGI_ERROR_DEVICE_REMOVED\nayrıntı"))
    conf = Configure()
    s = devices.open_session("m.onnx", conf, "gpu-10de-28a1", _ort=ort, _gpus=gpus2())
    feeds = {"input": np.zeros((1,))}
    out = s.run(None, feeds)
    assert float(out[0][0]) == 3.0                                       # işlemci sonucu
    assert s.used == devices.cpu_used(
        "Ekran kartı çalışırken hata verdi (DXGI_ERROR_DEVICE_REMOVED); işlemci kullanılıyor.")
    gpu_s, cpu_s = ort.sessions
    assert cpu_s.providers == [CPU] and cpu_s.runs == [(None, feeds)]    # aynı çağrı yeniden denendi
    assert not hasattr(cpu_s.so, "enable_mem_pattern") and len(conf.options) == 2
    out2 = s.run(None, feeds)                                            # düştükten sonra doğrudan işlemci
    assert float(out2[0][0]) == 3.0
    assert len(gpu_s.runs) == 1 and len(cpu_s.runs) == 2 and len(ort.sessions) == 2
    assert s.get_inputs() == ["input"]


def test_run_error_on_cpu_propagates():
    ort = FakeOrt(cpu_run_error=ValueError("bozuk girdi"))
    s = devices.open_session("m.onnx", Configure(), "cpu", _ort=ort, _gpus=[])
    with pytest.raises(ValueError, match="bozuk girdi"):
        s.run(None, {})
    assert s.used.kind == "cpu" and s.used.note is None and len(ort.sessions) == 1


def test_run_error_after_fallback_on_cpu_propagates():
    ort = FakeOrt(run_error=RuntimeError("gpu gitti"), cpu_run_error=ValueError("cpu de hata"))
    s = devices.open_session("m.onnx", Configure(), "gpu-10de-28a1", _ort=ort, _gpus=gpus2())
    with pytest.raises(ValueError, match="cpu de hata"):
        s.run(None, {})
    assert s.used.note is not None and s.used.note.startswith("Ekran kartı çalışırken hata verdi")


def test_concurrent_gpu_failures_build_one_cpu_session():
    ort = FakeOrt(run_error=RuntimeError("DEVICE_REMOVED"))
    barrier = threading.Barrier(2, timeout=10)
    ort.gpu_run_hook = barrier.wait                                      # iki çağrı da GPU'da hata alsın
    s = devices.open_session("m.onnx", Configure(), "gpu-10de-28a1", _ort=ort, _gpus=gpus2())
    results: list[float] = []

    def call() -> None:
        results.append(float(s.run(None, {})[0][0]))

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)
    assert results == [3.0, 3.0]                                         # ikisi de işlemci sonucunu aldı
    assert len(ort.sessions) == 2 and [x.is_gpu for x in ort.sessions] == [True, False]
    assert s.used.kind == "cpu" and (s.used.note or "").startswith("Ekran kartı çalışırken hata verdi")


def test_failing_cpu_rebuild_is_terminal_and_quiet(caplog):
    ort = FakeOrt(run_error=RuntimeError("DEVICE_REMOVED"))
    s = devices.open_session("m.onnx", Configure(), "gpu-10de-28a1", _ort=ort, _gpus=gpus2())
    ort.cpu_ctor_error = MemoryError("bellek yok")
    assert s.broken is None
    with caplog.at_level(logging.ERROR, logger="bantvision.devices"):
        with pytest.raises(MemoryError):                                 # o çağrı için asıl hata
            s.run(None, {})
        n_logs = len(caplog.records)
        for _ in range(3):                                               # sonrası: net hata, yeni günlük yok
            with pytest.raises(RuntimeError, match="Model kullanılamıyor.*bellek yok"):
                s.run(None, {})
    assert len(caplog.records) == n_logs
    assert sum(1 for r in caplog.records if r.exc_info and "İşlemci oturumu kurulamadı" in r.getMessage()) == 1
    assert len(ort.sessions) == 1 and len(ort.sessions[0].runs) == 1     # GPU yeniden denenmedi
    assert s.broken is not None and s.broken.startswith("Model kullanılamıyor") and "bellek yok" in s.broken


def test_cpu_choice_does_not_enumerate_dxgi(monkeypatch):
    monkeypatch.setattr(devices, "list_gpus", lambda *a, **k: pytest.fail("DXGI sorgulanmamalı"))
    monkeypatch.setattr(devices, "_dxgi_rows", lambda: pytest.fail("DXGI sorgulanmamalı"))
    s = devices.open_session("m.onnx", Configure(), "cpu", _ort=FakeOrt())
    assert s.used == devices.cpu_used()


def test_silent_fallback_log_lists_reported_providers(caplog):
    with caplog.at_level(logging.ERROR, logger="bantvision.devices"):
        s = devices.open_session("m.onnx", Configure(), "gpu-10de-28a1", _ort=FakeOrt(report_cpu=True),
                                 _gpus=gpus2())
    msg = next(r.getMessage() for r in caplog.records if r.levelno == logging.ERROR)
    assert "CPUExecutionProvider" in msg
    assert s.used.note == "Ekran kartında açılamadı (DirectML etkinleşmedi); işlemci kullanılıyor."


def test_dml_available_failures_return_false_and_warn_once(monkeypatch, caplog):
    class Boom:
        def get_available_providers(self):
            raise OSError("sağlayıcı sorgusu bozuk")

    with caplog.at_level(logging.WARNING, logger="bantvision.devices"):
        assert devices.dml_available(_ort=Boom()) is False
        assert devices.dml_available(_ort=Boom()) is False
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 1 and "OSError" in warns[0].getMessage() and "bozuk" in warns[0].getMessage()

    def no_import():
        raise ImportError("onnxruntime yok")

    monkeypatch.setattr(devices, "_dml_warned", False)
    monkeypatch.setattr(devices, "_import_ort", no_import)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="bantvision.devices"):
        assert devices.dml_available() is False
    assert "ImportError" in caplog.records[0].getMessage()


# --------------------------------------------------------------- 10-11. varsayılan ve regex

def test_default_choice():
    assert devices.default_choice() == "cpu"
    devices.set_default_choice("auto")
    assert devices.default_choice() == "auto"
    with pytest.raises(ValueError):
        devices.set_default_choice("GPU-1")
    assert devices.default_choice() == "auto"


@pytest.mark.parametrize("ok", ["auto", "cpu", "gpu-10de-28a1", "gpu-10de-28a1-2"])
def test_choice_re_accepts(ok):
    assert CHOICE_RE.fullmatch(ok)


@pytest.mark.parametrize("bad", ["GPU-10DE-28A1", "gpu-1-2", "gpu-10de-28a1-x", "gpu-10de-28a1\n", "", "Auto"])
def test_choice_re_rejects(bad):
    assert not CHOICE_RE.fullmatch(bad)
    assert not devices.valid_choice(bad)


# --------------------------------------------------------------- 12. gerçek donanım

@pytest.mark.skipif(sys.platform != "win32", reason="DXGI yalnız Windows'ta")
def test_real_dxgi_enumeration():
    gpus = devices.list_gpus(refresh=True)
    assert isinstance(gpus, list)
    for g in gpus:
        assert CHOICE_RE.fullmatch(g.id) and not g.id.startswith("gpu-1414-")
        assert "microsoft" not in g.name.lower() and g.name == g.name.strip() and g.name
        assert g.memory_mb >= 0 and g.index >= 0 and g.luid.startswith("0x")
    assert len({g.id for g in gpus}) == len(gpus)
