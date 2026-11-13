"""Kayıttan izleme testlerinin ortak sahteleri (`test_archive_player.py`, `test_archive_api.py`).

Ağ yok: sahte yakalama (`FakeCap`), sahte arşiv (`FakeArchive`, `stream_url`/`stop`/`keep_alive` çağrılarını kaydeder),
sahte kaynak deposu/istemci ve hepsini bir `ArchiveManager`'a bağlayan `Rig` (sahte saatle).
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import cv2
import numpy as np

from bantvision.live.archive import ArchiveClient, ExportStream
from bantvision.live.archive_player import ArchiveManager
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
                 stall: bool = False, delay: float = 0.0, fail_after: int | None = None,
                 on_end: Callable[[], None] | None = None) -> None:
        self.left, self.fps, self.w, self.h, self.opened = frames, fps, w, h, opened
        self.on_end = on_end                # akış sonunda (False dönmeden önce): ör. sahte saati ilerletir
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
            if self.on_end is not None:
                self.on_end()
                self.on_end = None
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
        self.export_error: BaseException | None = None
        self.keep_gate: threading.Event | None = None

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
        if self.keep_gate is not None:
            self.keep_gate.wait(5)

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
        if self.export_error is not None:
            raise self.export_error
        chunks = list(self.export_chunks)

        def rest() -> Iterator[bytes]:
            yield from chunks[1:]

        return ExportStream(chunks[0], rest())  # type: ignore[arg-type]

    # yardımcılar
    def urls(self) -> list[tuple[Any, ...]]:
        return [c for c in self.calls if c[0] == "url"]

    def stops(self) -> list[str]:
        return [c[1] for c in self.calls if c[0] == "stop"]


class FakeStore:
    def __init__(self, sources: dict[str, dict[str, Any]]) -> None:
        self._sources = sources

        self.calls: list[str] = []          # hangi okuma yapıldı (görünüm dosya okumamalı)

    def source(self, source_id: str) -> dict[str, Any] | None:
        self.calls.append("source")
        return self._sources.get(source_id)

    def source_records(self) -> list[dict[str, Any]]:
        self.calls.append("source_records")
        return list(self._sources.values())

    def password(self, source_id: str) -> str:
        self.calls.append("password")
        return "s3cr3t"


class FakeClient:
    def __init__(self) -> None:
        self.channel_calls = 0
        self.gate: threading.Event | None = None        # verilirse `channels` açılana kadar bekler (yarış testleri)
        self.entered = threading.Event()

    def channels(self) -> list[RecorderChannel]:
        self.channel_calls += 1
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(5)
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

        self.hosts: list[str] = []

        def recorder_factory(src: dict[str, Any]) -> FakeClient:
            self.hosts.append(str(src.get("host")))
            return self.client

        self.sources = {k: dict(v) for k, v in (sources or SOURCES).items()}
        self.manager = ArchiveManager(FakeStore(self.sources), recorder_factory, open_capture,
                                      clock=self.clock, archive_factory=archive_factory)
