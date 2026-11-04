"""Ekran kartı yükü (core/gpu_load.py): saf toplama işlevi, sahte PDH ile örnekleme ve gerçek donanım denemesi."""
from __future__ import annotations

import logging
import sys

import pytest

from bantvision.core import devices, gpu_load
from bantvision.core.gpu_load import GpuLoad, aggregate

LUID = "0x00000000_0x000132d5"
OTHER = "0x00000000_0x000132d6"


def name(pid: int, luid: str, eng: int, engtype: str = "3d", phys: int = 0) -> str:
    high, low = luid.split("_")
    return f"pid_{pid}_luid_{high}_{low}_phys_{phys}_eng_{eng}_engtype_{engtype}"


def test_aggregate_sums_pids_on_same_engine() -> None:
    s = [(name(1, LUID, 0), 10.0), (name(2, LUID, 0), 15.5)]
    assert aggregate(s, LUID) == 25.5


def test_aggregate_takes_max_over_engines() -> None:
    s = [(name(1, LUID, 0), 10.0), (name(2, LUID, 0), 5.0), (name(1, LUID, 3, "copy"), 40.0),
         (name(3, LUID, 7, "videodecode"), 20.0)]
    assert aggregate(s, LUID) == 40.0


def test_aggregate_ignores_other_luid() -> None:
    s = [(name(1, OTHER, 0), 90.0), (name(1, LUID, 0), 3.0)]
    assert aggregate(s, LUID) == 3.0
    assert aggregate([(name(1, OTHER, 0), 90.0)], LUID) is None


def test_aggregate_caps_at_100() -> None:
    assert aggregate([(name(1, LUID, 0), 80.0), (name(2, LUID, 0), 70.0)], LUID) == 100.0


def test_aggregate_no_matching_instance_is_none() -> None:
    assert aggregate([], LUID) is None
    assert aggregate([("garip_ad", 5.0)], LUID) is None


def test_aggregate_zero_load_is_zero_not_none() -> None:
    assert aggregate([(name(1, LUID, 0), 0.0)], LUID) == 0.0


def test_aggregate_matches_uppercase_luid_in_instance_names() -> None:
    """PDH örnek adları LUID'i BÜYÜK harfle yazar (luid_0x00000000_0x000132D5); eşleşme harf duyarsızdır."""
    upper = "pid_11064_luid_0x00000000_0x000132D5_phys_0_eng_0_engtype_3D"
    assert aggregate([(upper, 12.0)], LUID) == 12.0
    assert aggregate([(upper, 12.0)], LUID.upper().replace("0X", "0x")) == 12.0
    assert aggregate([(upper, 12.0)], OTHER) is None


class FakePdh:
    def __init__(self, reads: list[list[tuple[str, float]]]) -> None:
        self.reads = reads
        self.collects = 0
        self.closed = False

    def collect(self) -> None:
        self.collects += 1

    def read(self) -> list[tuple[str, float]]:
        return self.reads[min(self.collects, len(self.reads)) - 1]

    def close(self) -> None:
        self.closed = True


class Clock:
    def __init__(self) -> None:
        self.t = 100.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


def make(fake: FakePdh, clock: Clock) -> GpuLoad:
    return GpuLoad(_backend_factory=lambda: fake, _clock=clock, _sleep=clock.sleep)


def test_first_call_collects_twice_100ms_apart_then_once_per_call() -> None:
    fake = FakePdh([[(name(1, LUID, 0), 1.0)], [(name(1, LUID, 0), 7.0)], [(name(1, LUID, 0), 9.0)]])
    clock = Clock()
    g = make(fake, clock)
    assert g.percent(LUID) == 7.0
    assert fake.collects == 2 and clock.slept == [0.1]
    clock.t += 5.0
    assert g.percent(LUID) == 9.0
    assert fake.collects == 3 and clock.slept == [0.1]


def test_close_calls_reuse_the_last_sample() -> None:
    fake = FakePdh([[(name(1, LUID, 0), 4.0)]] * 5)
    clock = Clock()
    g = make(fake, clock)
    assert g.percent(LUID) == 4.0
    n = fake.collects
    assert g.percent(LUID) == 4.0
    assert fake.collects == n


def test_pdh_failure_gives_none_with_a_single_warning(caplog: pytest.LogCaptureFixture) -> None:
    clock = Clock()

    def boom() -> FakePdh:
        raise OSError("PdhOpenQueryW başarısız")

    g = GpuLoad(_backend_factory=boom, _clock=clock, _sleep=clock.sleep)
    with caplog.at_level(logging.WARNING, logger="bantvision.gpu_load"):
        assert g.percent(LUID) is None
        clock.t += 60.0                                      # yeniden deneme süresi geçti, yine hata
        assert g.percent(LUID) is None
    assert sum("okunamadı" in m for m in caplog.messages) == 1


def test_read_failure_recovers_after_retry_window() -> None:
    clock = Clock()

    class Flaky(FakePdh):
        def read(self) -> list[tuple[str, float]]:
            if self.collects == 2:
                raise OSError("okuma")
            return super().read()

    flaky = Flaky([[(name(1, LUID, 0), 6.0)]] * 5)
    g = make(flaky, clock)
    assert g.percent(LUID) is None and flaky.closed          # hata: sorgu kapatıldı, None
    clock.t += 1.0
    assert g.percent(LUID) is None                           # bekleme süresinde denenmez
    clock.t += 60.0
    g2 = GpuLoad(_backend_factory=lambda: FakePdh([[(name(1, LUID, 0), 6.0)]]), _clock=clock, _sleep=clock.sleep)
    assert g2.percent(LUID) == 6.0


def test_non_windows_is_always_none_and_imports_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gpu_load.sys, "platform", "linux")
    before = set(sys.modules)
    assert GpuLoad().percent(LUID) is None
    assert GpuLoad().percent(LUID) is None
    assert not [m for m in set(sys.modules) - before if m.startswith("ctypes")]


@pytest.mark.skipif(sys.platform != "win32", reason="PDH yalnız Windows'ta")
def test_real_hardware_percent_is_a_float_or_none() -> None:
    gpus = devices.list_gpus(refresh=True)
    if not gpus:
        pytest.skip("ekran kartı yok")
    g = GpuLoad()
    try:
        results = [g.percent(gpus[0].luid), g.percent(gpus[0].luid)]
    finally:
        g.close()
    print("gerçek ekran kartı yükü:", gpus[0].name, results)
    for r in results:
        assert r is None or (isinstance(r, float) and 0.0 <= r <= 100.0)
