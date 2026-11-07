"""Kayıttan izleme oynatıcısı ve yöneticisi (bantvision.live.archive_player).

Ağ yok: sahte yakalama (`FakeCap`) ve sahte arşiv (`FakeArchive`, `stream_url`/`stop`/`keep_alive` çağrılarını kaydeder).
Zaman ölçen kurallar (20 sn karesiz, 60 sn boşta, 60 sn önbellek, 5 sn canlı tutma) sahte saatle sınanır.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import cv2
import numpy as np
import pytest

from bantvision.live import archive_player as ap
from bantvision.live.archive import ArchiveClient, ExportStream, FileArchive
from bantvision.live.archive_player import (
    ArchiveManager,
    ArchivePlayer,
    ExportBusy,
    SourceMissing,
    TooManyPlayers,
)
from bantvision.live.recorders import RecorderChannel, RecorderError

CH = RecorderChannel("guid-1", "Kapı", None, True)
START = 1_000.0


class Clock:
    def __init__(self) -> None:
        self.t = 5_000.0

    def __call__(self) -> float:
        return self.t


class FakeCap:
    """Sahte yakalama. `frames` kare sonra akış biter (`read` False); `fps` CAP_PROP_FPS; `stall`: hiç kare vermez
    (`unblock` ya da 5 sn'ye dek bekler, sonra False); `fail_after`: o kadar kareden sonra `read` hata atar."""

    def __init__(self, frames: int = 10_000, fps: float = 25.0, w: int = 40, h: int = 20, opened: bool = True,
                 stall: bool = False, delay: float = 0.0, fail_after: int | None = None) -> None:
        self.left, self.fps, self.w, self.h, self.opened = frames, fps, w, h, opened
        self.stall, self.delay, self.fail_after = stall, delay, fail_after
        self.unblock = threading.Event()
        self.released = False
        self.sets: list[tuple[int, float]] = []
        self.read_count = 0

    def isOpened(self) -> bool:
        return self.opened

    def get(self, prop: int) -> float:
        return self.fps if prop == cv2.CAP_PROP_FPS else 0.0

    def set(self, prop: int, value: float) -> bool:
        self.sets.append((prop, value))
        return True

    def read(self) -> tuple[bool, Any]:
        if self.stall:
            self.unblock.wait(5)
            return False, None
        if self.fail_after is not None and self.read_count >= self.fail_after:
            raise cv2.error("okuma hatası")
        if self.left <= 0:
            return False, None
        self.left -= 1
        self.read_count += 1
        if self.delay:
            time.sleep(self.delay)
        return True, np.full((self.h, self.w, 3), self.read_count % 250, np.uint8)

    def release(self) -> None:
        self.released = True
        self.unblock.set()


class FakeArchive(ArchiveClient):
    def __init__(self, speeds: tuple[int, ...] = (1, 2, 4), can_export: bool = False) -> None:
        self.speeds = speeds
        self.can_export = can_export
        self.calls: list[tuple[Any, ...]] = []
        self.n = 0
        self.cal_calls = 0
        self.tl_calls = 0
        self.fail_next: list[BaseException] = []
        self.slow = 0.0
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()
        self.export_chunks = [b"\x00\x00\x00\x18ftypmp42", b"rest"]

    def stream_url(self, channel: RecorderChannel, start: float, end: float | None, substream: bool,
                   speed: int) -> str:
        self._check_speed(speed)
        if self.fail_next:
            raise self.fail_next.pop(0)
        with self._lock:
            self.n += 1
            url = f"rtsp://nvr:554/tok{self.n}"
            self.calls.append(("url", start, end, substream, speed, url))
        return url

    def stop(self, stream_url: str) -> None:
        with self._lock:
            self.calls.append(("stop", stream_url))

    def keep_alive(self, stream_url: str) -> None:
        with self._lock:
            self.calls.append(("keep", stream_url))

    def _busy(self) -> None:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(self.slow)
        with self._lock:
            self.active -= 1
        if self.fail_next:
            raise self.fail_next.pop(0)

    def calendar(self, channel: RecorderChannel, year: int, month: int) -> set[int]:
        self.cal_calls += 1
        self._busy()
        return {1, month}

    def timeline(self, channel: RecorderChannel, day: float) -> list[tuple[float, float]]:
        self.tl_calls += 1
        self._busy()
        return [(day, day + 60.0)]

    def export(self, channel: RecorderChannel, start: float, end: float) -> ExportStream:
        if not self.can_export:
            raise RecorderError.unsupported()
        chunks = list(self.export_chunks)

        def rest() -> Iterator[bytes]:
            yield from chunks[1:]

        return ExportStream(chunks[0], rest())  # type: ignore[arg-type]

    # yardımcılar
    def urls(self) -> list[tuple[Any, ...]]:
        return [c for c in self.calls if c[0] == "url"]

    def stops(self) -> list[str]:
        return [c[1] for c in self.calls if c[0] == "stop"]


def wait_for(pred: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(0.005)
    raise AssertionError("koşul gerçekleşmedi")


def make_player(archive: FakeArchive, caps: list[FakeCap], start: float = START, speed: int = 1,
                clock: Callable[[], float] = time.monotonic,
                url_fn_factory: Callable[[float, int, bool], Callable[[], str]] | None = None) -> ArchivePlayer:
    def factory(s: float, sp: int, sub: bool) -> Callable[[], str]:
        return lambda: archive.stream_url(CH, s, None, sub, sp)

    def open_capture(url: str) -> FakeCap:
        return caps.pop(0)

    return ArchivePlayer("p1", archive, CH.id, url_fn_factory or factory, open_capture, "NVR · Kapı", start, speed,
                         True, clock=clock, source_id="src1")


@pytest.fixture
def players() -> Iterator[list[ArchivePlayer]]:
    made: list[ArchivePlayer] = []
    yield made
    for p in made:
        p.close()


# MARK: - Oynatıcı: konum ve hız


def test_at_uses_25_fps_when_capture_reports_zero(players: list[ArchivePlayer]) -> None:
    arch = FakeArchive()
    p = make_player(arch, [FakeCap(frames=50, fps=0.0)])
    players.append(p)
    wait_for(lambda: p.view().state == "ended")
    v = p.view()
    assert v.at == pytest.approx(START + 2.0)
    assert v.fps == 25.0
    assert p.frame()[0] == 50


def test_at_uses_25_fps_when_capture_reports_absurd_fps(players: list[ArchivePlayer]) -> None:
    arch = FakeArchive()
    p = make_player(arch, [FakeCap(frames=25, fps=1000.0)])
    players.append(p)
    wait_for(lambda: p.view().state == "ended")
    assert p.view().at == pytest.approx(START + 1.0)


@pytest.mark.parametrize("speed,published", [(2, 50), (4, 25)])
def test_client_side_speed_skips_frames(players: list[ArchivePlayer], speed: int, published: int) -> None:
    """Hikvision/Dahua/dosya: her kare çözülür, `hız`. karede bir yayımlanır; konum = yayımlanan / fps × hız."""
    arch = FakeArchive(speeds=(1, 2, 4))
    p = make_player(arch, [FakeCap(frames=100, fps=25.0)], speed=speed)
    players.append(p)
    assert p.device_paced is False
    wait_for(lambda: p.view().state == "ended")
    assert p.frame()[0] == published
    assert p.view().at == pytest.approx(START + published / 25.0 * speed)
    assert arch.urls()[0][4] == speed                        # hız adres üreticisine de verilir


def test_device_paced_speed_does_not_skip(players: list[ArchivePlayer]) -> None:
    """TRASSIR: hız cihazda; her kare yayımlanır, konum = okunan / fps × hız."""
    arch = FakeArchive(speeds=(1, 2, 4, 8, 16))
    p = make_player(arch, [FakeCap(frames=50, fps=25.0)], speed=4)
    players.append(p)
    assert p.device_paced is True
    wait_for(lambda: p.view().state == "ended")
    assert p.frame()[0] == 50
    assert p.view().at == pytest.approx(START + 8.0)
    assert arch.urls()[0][4] == 4


def test_view_fields(players: list[ArchivePlayer]) -> None:
    arch = FakeArchive(speeds=(1, 2, 4, 8, 16), can_export=True)
    p = make_player(arch, [FakeCap(frames=5)])
    players.append(p)
    wait_for(lambda: p.view().state == "ended")
    v = p.view()
    assert (v.id, v.source_id, v.channel_id, v.name) == ("p1", "src1", "guid-1", "NVR · Kapı")
    assert v.speed == 1 and v.speeds == (1, 2, 4, 8, 16) and v.can_export is True
    assert v.message == ""


def test_frames_downscaled_and_readonly(players: list[ArchivePlayer]) -> None:
    arch = FakeArchive()
    p = make_player(arch, [FakeCap(frames=3, w=1920, h=1080)])
    players.append(p)
    wait_for(lambda: p.view().state == "ended")
    _, frame = p.frame()
    assert frame is not None and frame.shape[1] == 960
    assert not frame.flags.writeable


# MARK: - Oynatıcı: kumanda (tek yol: kapat + yeniden aç)


def test_pause_keeps_last_frame_and_at_then_resume_reopens(players: list[ArchivePlayer]) -> None:
    arch = FakeArchive()
    first, second = FakeCap(delay=0.002), FakeCap(delay=0.002)
    p = make_player(arch, [first, second])
    players.append(p)
    wait_for(lambda: p.frame()[0] >= 5)
    p.pause()
    v1, (seq1, f1) = p.view(), p.frame()
    assert v1.state == "paused"
    wait_for(lambda: first.released)
    time.sleep(0.05)
    v2, (seq2, f2) = p.view(), p.frame()
    assert v2.state == "paused" and v2.at == v1.at and seq2 == seq1 and f2 is f1
    old = arch.urls()[0][5]
    wait_for(lambda: old in arch.stops())                  # TRASSIR: eski jetonun oynatması durdurulur
    assert len(arch.urls()) == 1                           # duraklamada yeni adres alınmaz

    p.resume()
    wait_for(lambda: p.view().state == "playing")
    urls = arch.urls()
    assert len(urls) == 2
    assert urls[1][1] == pytest.approx(v1.at)              # sürdürme duraklanan konumdan, yeni adresle
    assert urls[1][5] != old
    assert arch.calls.index(("stop", old)) < arch.calls.index(urls[1])


def test_seek_reopens_at_new_start(players: list[ArchivePlayer]) -> None:
    arch = FakeArchive()
    p = make_player(arch, [FakeCap(delay=0.002), FakeCap(frames=25, fps=25.0)])
    players.append(p)
    wait_for(lambda: p.view().state == "playing")
    p.seek(9_000.0)
    v = p.view()
    assert v.state in ("connecting", "playing", "ended") and v.at >= 9_000.0
    wait_for(lambda: p.view().state == "ended")
    assert arch.urls()[1][1] == 9_000.0
    assert arch.stops()[0] == arch.urls()[0][5]
    assert p.view().at == pytest.approx(9_001.0)


def test_seek_while_paused_plays_from_new_position(players: list[ArchivePlayer]) -> None:
    arch = FakeArchive()
    p = make_player(arch, [FakeCap(delay=0.002), FakeCap(delay=0.002)])
    players.append(p)
    wait_for(lambda: p.frame()[0] >= 2)
    p.pause()
    p.seek(2_000.0)
    wait_for(lambda: len(arch.urls()) == 2)
    assert arch.urls()[1][1] == 2_000.0


def test_set_speed_reopens_with_new_speed(players: list[ArchivePlayer]) -> None:
    arch = FakeArchive()
    p = make_player(arch, [FakeCap(delay=0.002), FakeCap(delay=0.002)])
    players.append(p)
    wait_for(lambda: p.frame()[0] >= 5)
    p.set_speed(4)
    assert p.view().speed == 4
    wait_for(lambda: len(arch.urls()) == 2)
    url = arch.urls()[1]
    assert url[4] == 4 and url[1] >= START
    with pytest.raises(ValueError):
        p.set_speed(16)                                    # bu cihazın hızlarında yok


def test_set_speed_while_paused_stays_paused(players: list[ArchivePlayer]) -> None:
    arch = FakeArchive()
    p = make_player(arch, [FakeCap(delay=0.002), FakeCap(delay=0.002)])
    players.append(p)
    wait_for(lambda: p.frame()[0] >= 2)
    p.pause()
    p.set_speed(2)
    time.sleep(0.05)
    assert p.view().state == "paused" and p.view().speed == 2
    assert len(arch.urls()) == 1
    p.resume()
    wait_for(lambda: len(arch.urls()) == 2)
    assert arch.urls()[1][4] == 2


# MARK: - Oynatıcı: hata ve bitiş


def test_no_frames_for_20s_is_error_and_resume_retries(players: list[ArchivePlayer]) -> None:
    clock = Clock()
    arch = FakeArchive()
    stalled = FakeCap(stall=True)
    p = make_player(arch, [stalled, FakeCap(delay=0.002)], clock=clock)
    players.append(p)
    wait_for(lambda: len(arch.urls()) == 1)
    clock.t += ap.NO_FRAME_S - 1
    assert p.view().state == "connecting"
    clock.t += 2
    v = p.view()
    assert v.state == "error" and v.message == "Kayıt cihazından görüntü gelmedi."
    stalled.unblock.set()                                  # gerçek akışta okuma zaman aşımı
    wait_for(lambda: stalled.released)
    assert p.view().state == "error"                       # geç dönen okuma durumu ezmez
    p.resume()
    wait_for(lambda: p.view().state == "playing")


def test_stream_end_is_ended_and_keeps_last_frame(players: list[ArchivePlayer]) -> None:
    arch = FakeArchive()
    cap = FakeCap(frames=10)
    p = make_player(arch, [cap])
    players.append(p)
    wait_for(lambda: p.view().state == "ended")
    seq, frame = p.frame()
    assert seq == 10 and frame is not None
    wait_for(lambda: cap.released and arch.urls()[0][5] in arch.stops())


def test_open_error_is_turkish_error_and_thread_survives(players: list[ArchivePlayer]) -> None:
    arch = FakeArchive()
    arch.fail_next.append(RecorderError.unreachable("zaman aşımı"))
    p = make_player(arch, [FakeCap(delay=0.002)])
    players.append(p)
    wait_for(lambda: p.view().state == "error")
    msg = p.view().message
    assert msg.startswith("Kayıt cihazına ulaşılamadı") and str(RecorderError.unreachable("zaman aşımı")) in msg
    p.resume()                                             # "Sürdür" yeniden dener
    wait_for(lambda: p.view().state == "playing")


def test_capture_not_opened_is_error(players: list[ArchivePlayer]) -> None:
    arch = FakeArchive()
    cap = FakeCap(opened=False)
    p = make_player(arch, [cap])
    players.append(p)
    wait_for(lambda: p.view().state == "error")
    assert p.view().message == "Kayıt açılamadı."
    wait_for(lambda: cap.released and arch.urls()[0][5] in arch.stops())


def test_read_exception_is_error_and_thread_survives(players: list[ArchivePlayer]) -> None:
    arch = FakeArchive()
    p = make_player(arch, [FakeCap(fail_after=3), FakeCap(delay=0.002)])
    players.append(p)
    wait_for(lambda: p.view().state == "error")
    assert p.view().message == "Kayıt okunamadı."
    assert p.frame()[0] == 3
    p.resume()
    wait_for(lambda: p.view().state == "playing")


def test_close_releases_capture_and_stops_url() -> None:
    arch = FakeArchive()
    cap = FakeCap(delay=0.002)
    p = make_player(arch, [cap])
    wait_for(lambda: p.view().state == "playing")
    p.close()
    assert cap.released
    assert arch.urls()[0][5] in arch.stops()
    assert p.view().state == "ended" or p.closed


def test_keep_alive_every_5s(players: list[ArchivePlayer]) -> None:
    clock = Clock()
    arch = FakeArchive(speeds=(1, 2, 4, 8, 16))
    p = make_player(arch, [FakeCap(delay=0.002)], clock=clock)
    players.append(p)
    wait_for(lambda: p.view().state == "playing")
    time.sleep(0.02)
    assert not [c for c in arch.calls if c[0] == "keep"]
    clock.t += 5.5
    url = arch.urls()[0][5]
    wait_for(lambda: ("keep", url) in arch.calls)


def test_file_source_seeks_and_paces_in_real_time(players: list[ArchivePlayer]) -> None:
    """Dosya kaynağı (R9): açılışta konuma sarılır, gerçek zamanlı oynar, zaman ekseni dosya saniyesi."""
    arch = FakeArchive()
    cap = FakeCap(frames=10, fps=100.0)

    def factory(s: float, sp: int, sub: bool) -> Callable[[], str]:
        return lambda: "C:/videolar/test.mp4"

    t0 = time.monotonic()
    p = make_player(arch, [cap], start=12.5, url_fn_factory=factory)
    players.append(p)
    wait_for(lambda: p.view().state == "ended")
    assert time.monotonic() - t0 >= 0.08
    assert (cv2.CAP_PROP_POS_MSEC, 12_500.0) in cap.sets
    assert p.view().at == pytest.approx(12.6)


# MARK: - Yönetici


class FakeStore:
    def __init__(self, sources: dict[str, dict[str, Any]]) -> None:
        self._sources = sources

    def source(self, source_id: str) -> dict[str, Any] | None:
        return self._sources.get(source_id)

    def password(self, source_id: str) -> str:
        return "s3cr3t"


class FakeClient:
    def __init__(self) -> None:
        self.channel_calls = 0

    def channels(self) -> list[RecorderChannel]:
        self.channel_calls += 1
        return [CH, RecorderChannel("2", "", 2, True)]


SOURCES = {
    "nvr": {"id": "nvr", "kind": "recorder", "name": "NVR", "recorderBrand": "trassir", "host": "10.0.0.1",
            "username": "admin"},
    "hik": {"id": "hik", "kind": "recorder", "name": "Hik", "recorderBrand": "hikvision", "host": "10.0.0.2",
            "username": "admin"},
    "cam": {"id": "cam", "kind": "camera", "name": "Tek kamera", "brand": "hikvision", "host": "10.0.0.3"},
}


class Rig:
    def __init__(self, archive: FakeArchive | None = None, sources: dict[str, dict[str, Any]] | None = None,
                 caps: Callable[[], FakeCap] | None = None) -> None:
        self.clock = Clock()
        self.archive = archive or FakeArchive(speeds=(1, 2, 4, 8, 16), can_export=True)
        self.client = FakeClient()
        self.opened: list[str] = []
        self._caps = caps or (lambda: FakeCap(delay=0.002))
        self.brands: list[str] = []

        def open_capture(url: str) -> FakeCap:
            self.opened.append(url)
            return self._caps()

        def archive_factory(client: Any, brand: str) -> ArchiveClient:
            self.brands.append(str(brand))
            return self.archive

        self.manager = ArchiveManager(FakeStore(sources or dict(SOURCES)), lambda src: self.client, open_capture,
                                      clock=self.clock, archive_factory=archive_factory)


@pytest.fixture
def rig() -> Iterator[Rig]:
    r = Rig()
    yield r
    r.manager.stop()


def test_open_returns_view_and_plays(rig: Rig) -> None:
    v = rig.manager.open("nvr", "guid-1", START, 2, True)
    assert v.source_id == "nvr" and v.channel_id == "guid-1"
    assert v.name == "NVR · guid-1"                          # açılış ağa çıkmaz: kanal adı henüz bilinmiyor
    assert v.speed == 2 and v.can_export is True and v.state == "connecting"
    p = rig.manager.get(v.id)
    assert p is not None
    wait_for(lambda: p.view().state == "playing")
    assert p.view().name == "NVR · Kapı"                    # kanal listesi ilk bağlanışta alındı
    assert rig.archive.urls()[0][1:5] == (START, None, True, 2)
    assert rig.brands == ["trassir"]


def test_trassir_url_has_no_credentials_hikvision_does_but_stop_gets_bare_url() -> None:
    r = Rig(archive=FakeArchive(speeds=(1, 2, 4)))
    try:
        v1 = r.manager.open("nvr", "guid-1", START, 1, True)
        wait_for(lambda: len(r.opened) == 1)
        assert "@" not in r.opened[0]
        r.manager.close(v1.id)
        r.manager.open("hik", "guid-1", START, 1, True)
        wait_for(lambda: len(r.opened) == 2)
        assert r.opened[1].startswith("rtsp://admin:s3cr3t@")
        r.manager.stop()
        assert r.archive.stops() and all("s3cr3t" not in s for s in r.archive.stops())
    finally:
        r.manager.stop()


def test_third_player_rejected_and_closed_player_frees_slot(rig: Rig) -> None:
    a = rig.manager.open("nvr", "guid-1", START, 1, True)
    rig.manager.open("nvr", "guid-1", START, 1, True)        # iki sekme aynı kamera
    with pytest.raises(TooManyPlayers) as e:
        rig.manager.open("nvr", "2", START, 1, True)
    assert str(e.value) == "En çok 2 kayıt aynı anda izlenebilir."
    assert rig.manager.close(a.id) is True
    assert rig.manager.close(a.id) is False
    rig.manager.open("nvr", "2", START, 1, True)


def test_open_validation(rig: Rig) -> None:
    with pytest.raises(SourceMissing):
        rig.manager.open("yok", "guid-1", START, 1, True)
    with pytest.raises(ValueError):
        rig.manager.open("nvr", None, START, 1, True)        # kanal seçilmemiş
    with pytest.raises(ValueError):
        rig.manager.open("cam", None, START, 1, True)        # kayıt cihazı değil
    with pytest.raises(ValueError):
        rig.manager.open("nvr", "guid-1", START, 3, True)    # hız yok
    assert rig.manager.sweep() == 0


def test_idle_player_closed_by_sweep(rig: Rig) -> None:
    a = rig.manager.open("nvr", "guid-1", START, 1, True)
    b = rig.manager.open("nvr", "2", START, 1, True)
    pa, pb = rig.manager.get(a.id), rig.manager.get(b.id)
    assert pa is not None and pb is not None
    wait_for(lambda: pa.view().state == "playing")
    rig.clock.t += 40
    pb.touch()
    rig.clock.t += 21
    assert rig.manager.sweep() == 1
    assert rig.manager.get(a.id) is None and rig.manager.get(b.id) is not None
    assert pa.closed
    wait_for(lambda: len(rig.archive.stops()) == 1)          # yalnız kapanan oynatıcının adresi durur


def test_reaper_starts_lazily(rig: Rig) -> None:
    assert rig.manager._reaper is None
    rig.manager.open("nvr", "guid-1", START, 1, True)
    assert rig.manager._reaper is not None and rig.manager._reaper.is_alive()


def test_calendar_and_timeline_cached_60s_errors_not_cached(rig: Rig) -> None:
    m, arch = rig.manager, rig.archive
    assert m.calendar("nvr", "guid-1", 2026, 11) == {1, 11}
    assert m.calendar("nvr", "guid-1", 2026, 11) == {1, 11}
    assert arch.cal_calls == 1
    m.calendar("nvr", "guid-1", 2026, 10)                    # başka ay başka anahtar
    assert arch.cal_calls == 2
    rig.clock.t += ap.CACHE_S + 1
    m.calendar("nvr", "guid-1", 2026, 11)
    assert arch.cal_calls == 3

    arch.fail_next.append(RecorderError.unreachable("zaman aşımı"))
    with pytest.raises(RecorderError):
        m.timeline("nvr", "guid-1", 86_400.0)
    assert m.timeline("nvr", "guid-1", 86_400.0) == [(86_400.0, 86_460.0)]
    assert m.timeline("nvr", "guid-1", 86_400.0) == [(86_400.0, 86_460.0)]
    assert arch.tl_calls == 2


def test_calendar_unknown_channel_and_source(rig: Rig) -> None:
    with pytest.raises(SourceMissing):
        rig.manager.calendar("yok", "guid-1", 2026, 11)
    with pytest.raises(LookupError):
        rig.manager.timeline("nvr", "yok", 0.0)


def test_calendar_calls_serialized_per_source(rig: Rig) -> None:
    rig.archive.slow = 0.03
    threads = [threading.Thread(target=rig.manager.calendar, args=("nvr", "guid-1", 2026, m)) for m in range(1, 7)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert rig.archive.cal_calls == 6
    assert rig.archive.max_active == 1


def test_export_lock_and_filename(rig: Rig) -> None:
    rig.archive.tz = UTC                                     # dosya adındaki saat cihazın saat diliminde
    start = datetime(2026, 11, 7, 14, 30, tzinfo=UTC).timestamp()
    name, stream = rig.manager.export("nvr", "guid-1", start, start + 60)
    assert name == "NVR-Kapi-20261107-1430.mp4"
    with pytest.raises(ExportBusy) as e:
        rig.manager.export("nvr", "guid-1", start, start + 60)
    assert str(e.value) == "Bir dışa aktarma sürüyor."
    assert b"".join(stream) == b"\x00\x00\x00\x18ftypmp42rest"   # sonuna dek okununca kilit kalkar
    _, again = rig.manager.export("nvr", "guid-1", start, start + 60)
    next(again)
    again.close()                                            # yarıda kapatma da kilidi bırakır
    _, third = rig.manager.export("nvr", "guid-1", start, start + 60)
    third.close()


def test_export_unsupported_propagates_and_releases_lock() -> None:
    r = Rig(archive=FakeArchive(can_export=False))
    try:
        with pytest.raises(RecorderError) as e:
            r.manager.export("nvr", "guid-1", 0.0, 60.0)
        assert e.value.kind == "unsupported"
        r.archive.can_export = True
        _, s = r.manager.export("nvr", "guid-1", 0.0, 60.0)
        s.close()
    finally:
        r.manager.stop()


def test_name_without_network(rig: Rig) -> None:
    assert rig.manager.name("nvr", "guid-1") == "NVR · guid-1"
    assert rig.client.channel_calls == 0
    rig.manager.calendar("nvr", "guid-1", 2026, 11)          # kanal listesi önbelleğe girer
    assert rig.manager.name("nvr", "guid-1") == "NVR · Kapı"
    assert rig.manager.name("nvr", "2") == "NVR · Kanal 2"
    assert rig.manager.name("yok", "x") == "Silinmiş kamera"


def test_stop_closes_all_players(rig: Rig) -> None:
    v = rig.manager.open("nvr", "guid-1", START, 1, True)
    p = rig.manager.get(v.id)
    assert p is not None
    rig.manager.stop()
    assert p.closed and rig.manager.get(v.id) is None
    with pytest.raises(RuntimeError):
        rig.manager.open("nvr", "guid-1", START, 1, True)


def test_file_source_uses_file_archive(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "test.mp4"
    video.write_bytes(b"x")
    monkeypatch.setenv("ANALYZER_ALLOW_FILE_SOURCES", "1")
    caps: list[FakeCap] = []

    def make_cap() -> FakeCap:
        caps.append(FakeCap(frames=5, fps=100.0))
        return caps[-1]

    src = {"id": "f", "kind": "camera", "name": "Dosya", "brand": "custom", "customUrl": str(video)}
    r = Rig(sources={"f": src}, caps=make_cap)
    try:
        assert r.manager.calendar("f", None, 1970, 1) == {1}
        v = r.manager.open("f", None, 3.0, 1, True)
        assert v.can_export is False and v.speeds == FileArchive.speeds and v.name == "Dosya"
        p = r.manager.get(v.id)
        assert p is not None
        wait_for(lambda: p.view().state == "ended")
        assert r.opened == [str(video)]
        assert (cv2.CAP_PROP_POS_MSEC, 3_000.0) in caps[0].sets
        with pytest.raises(RecorderError):
            r.manager.export("f", None, 0.0, 1.0)
        assert r.brands == []
    finally:
        r.manager.stop()

    monkeypatch.delenv("ANALYZER_ALLOW_FILE_SOURCES")
    r2 = Rig(sources={"f": src})
    try:
        with pytest.raises(ValueError):
            r2.manager.open("f", None, 0.0, 1, True)
    finally:
        r2.manager.stop()
