"""İzleme okuyucuları: paylaşım, boşta kapanma, oturum karesi, sınırlar, hata ve yeniden deneme (ağsız, sahte açıcı)."""
from __future__ import annotations

import threading
import time
from typing import Any

import numpy as np

from bantvision.live.viewer import IDLE_S, MAX_SUB, SourceGone, ViewHub


class FakeCap:
    """Okundukça kare veren sahte akış; `fail=True` hiç açılmaz; `frames` sonra akış biter."""

    def __init__(self, opened: bool = True, frames: int = 10_000, w: int = 1920, h: int = 1080) -> None:
        self._opened, self._left, self.w, self.h = opened, frames, w, h

    def isOpened(self) -> bool:
        return self._opened

    def read(self) -> tuple[bool, Any]:
        if self._left <= 0:
            return False, None
        self._left -= 1
        time.sleep(0.005)
        return True, np.full((self.h, self.w, 3), 100, np.uint8)

    def release(self) -> None:
        pass


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def make_hub(caps: Any = None, sessions: dict[tuple[str, str | None], Any] | None = None,
             gone: set[str] | None = None, clock: Any = time.monotonic) -> tuple[ViewHub, list[str]]:
    opened: list[str] = []

    def opener(source_id: str, channel_id: str | None, sub: bool) -> tuple[Any, Any]:
        if gone and source_id in gone:
            raise SourceGone("Kamera silinmiş.")
        return (lambda: f"rtsp://{source_id}/{channel_id}/{'sub' if sub else 'main'}"), None

    def capture(url: str) -> Any:
        opened.append(url)
        return caps(url) if caps else FakeCap()

    hub = ViewHub(opener, lambda s, c: (sessions or {}).get((s, c)), capture=capture, clock=clock, reaper=False)
    return hub, opened


def wait(fn: Any, timeout: float = 5.0) -> Any:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.02)
    raise AssertionError("zaman aşımı")


def test_one_reader_per_camera_shared_and_downscaled() -> None:
    hub, opened = make_hub()
    try:
        t = wait(lambda: (x := hub.tile("a", "1")).frame is not None and x)
        assert t.state == "live" and t.frame.shape[1] == 960                    # alt akış 960 px'e küçültülür
        hub.tile("a", "1")
        hub.tile("a", "1")
        assert opened == ["rtsp://a/1/sub"]                                      # aynı kamera tek bağlantı
    finally:
        hub.stop()


def test_idle_reader_closes_after_30s() -> None:
    clock = Clock()
    hub, _ = make_hub(clock=clock)
    try:
        hub.tile("a", None)
        assert hub.open_count("sub") == 1
        clock.t += IDLE_S - 1
        assert hub.sweep() == 0
        clock.t += 2
        assert hub.sweep() == 1 and hub.open_count("sub") == 0
    finally:
        hub.stop()


def test_running_session_frame_is_reused_without_second_connection() -> None:
    class Sess:
        status = type("St", (), {"state": "live", "message": "", "fps": 12.0})()

        def latest_frame(self) -> tuple[int, np.ndarray]:
            return 7, np.zeros((480, 640, 3), np.uint8)

    sessions: dict[tuple[str, str | None], Any] = {("a", "1"): Sess()}
    hub, opened = make_hub(sessions=sessions)
    try:
        t = hub.tile("a", "1")
        assert t.seq == 7 and t.frame is not None and t.state == "live" and opened == []
        sessions.clear()                                                         # oturum kapandı: kendi okuyucusu açılır
        wait(lambda: hub.tile("a", "1").frame is not None)
        assert opened == ["rtsp://a/1/sub"]
    finally:
        hub.stop()


def test_limit_16_sub_readers() -> None:
    hub, _ = make_hub()
    try:
        for i in range(MAX_SUB):
            assert hub.tile(f"s{i}", None).message == ""
        t = hub.tile("fazla", None)
        assert t.state == "error" and "Sınır aşıldı" in t.message
        assert hub.open_count("sub") == MAX_SUB
    finally:
        hub.stop()


def test_deleted_source_and_unopenable_stream_are_turkish_errors_with_backoff() -> None:
    hub, opened = make_hub(caps=lambda url: FakeCap(opened=False), gone={"silindi"})
    try:
        assert hub.tile("silindi", None).message == "Kamera silinmiş."
        t = wait(lambda: (x := hub.tile("kapali", None)).state == "error" and x)
        assert "açılamadı" in t.message
        time.sleep(1.5)
        assert len([u for u in opened if "kapali" in u]) <= 2                    # sıkı döngü yok: 1 sn, 2 sn bekleme
    finally:
        hub.stop()


def test_peek_does_not_open_a_reader() -> None:
    hub, opened = make_hub()
    try:
        t = hub.peek("a", None)
        assert t.state == "connecting" and opened == [] and hub.open_count("sub") == 0
    finally:
        hub.stop()


def test_stop_joins_reader_threads() -> None:
    hub, _ = make_hub()
    hub.tile("a", None)
    before = threading.active_count()
    hub.stop()
    wait(lambda: threading.active_count() < before)
